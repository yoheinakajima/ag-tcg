#!/usr/bin/env python3
"""Tournament health checker (Pass 38, Part F) — prod/local, fail-closed monitor.

A standalone, read-only monitor for the standing-tournament engine's persistent
state. It runs the SAME hard safety invariants the engine enforces at write time,
but as an independent after-the-fact audit, so an operator can answer "is the
deployment healthy and safe to leave running?" from one command.

Modes:
  --mode prod    read the live Replit Object Storage backend (read-only; never
                 writes, never pulls into the working dir).
  --mode local   read the local working dir (data/tournament/).

HARD failures (process exits non-zero — the deployment is NOT safe):
  * root main.py/deck.csv drifted from the frozen Kaggle baseline,
  * auto-submit enabled (config.auto_submit true or TOURNAMENT_AUTO_SUBMIT set),
  * a forbidden upload/submit event exists in the ledger,
  * any event missing no_upload=true,
  * a finished game_id appears more than once (un-deduped / divergent ledger),
  * a finished game has no durable sidecar,
  * a manifest-tracked file's bytes do not match its recorded sha256 (HARD in
    --mode prod, the authoritative snapshot; WARNING in --mode local, whose
    disposable working dir may be rebuilt ahead of the last push),
  * manifest event_count disagrees with the ledger,
  * a NEVER_SCHEDULE candidate appears in the scheduler queue,
  * a held_probe candidate is not schedulable (retention dropped).

WARNINGS (do not fail; surfaced for the operator):
  * candidates below the placement-games threshold (tiny sample),
  * candidates with zero games,
  * invalid/timeout games present,
  * very low total game count,
  * a currently-held (or stale) lease.

NO upload, NO submit, NO push, NO root mutation, NO candidate generation.
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    get_storage_backend, StorageError,
)

BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
TDIR = REPO / "data" / "tournament"
EXP = REPO / "data" / "experiments"
_FORBIDDEN = {"SubmissionUploaded", "KaggleScoreUpdated"}
_LOW_TOTAL_GAMES = 10


# --------------------------------------------------------------------------- #
# state sources (read-only)
# --------------------------------------------------------------------------- #
@dataclass
class StateBundle:
    source: str
    events: list[dict]
    manifest: dict
    game_keys: list[str]
    scheduler_queue: dict
    config_text: str | None
    _read: object  # callable: key -> bytes | None

    def read_bytes(self, key: str) -> bytes | None:
        return self._read(key)


def _local_bundle() -> StateBundle:
    def read(key: str):
        p = TDIR / key
        return p.read_bytes() if p.is_file() else None

    ev = (TDIR / "events.jsonl")
    events = sync.parse_events_text(ev.read_text(encoding="utf-8")) if ev.is_file() else []
    man = TDIR / "storage_manifest.json"
    manifest = json.loads(man.read_text(encoding="utf-8")) if man.is_file() else {}
    games = ([p.relative_to(TDIR).as_posix() for p in (TDIR / "games").glob("*.json.gz")]
             if (TDIR / "games").is_dir() else [])
    q = TDIR / "projections" / "scheduler_queue.json"
    queue = json.loads(q.read_text(encoding="utf-8")) if q.is_file() else {}
    cfg = TDIR / "config.yaml"
    return StateBundle("local", events, manifest, sorted(games), queue,
                       cfg.read_text(encoding="utf-8") if cfg.is_file() else None, read)


def _prod_bundle() -> StateBundle:
    backend = get_storage_backend(env="production", backend="replit_app_storage")

    def read(key: str):
        try:
            return backend.read_bytes(key) if backend.exists(key) else None
        except Exception:
            return None

    raw = read("events.jsonl")
    events = sync.parse_events_text(raw.decode("utf-8")) if raw else []
    mraw = read("storage_manifest.json")
    manifest = json.loads(mraw.decode("utf-8")) if mraw else {}
    games = [k for k in backend.list("games") if k.endswith(".json.gz")]
    qraw = read("projections/scheduler_queue.json")
    queue = json.loads(qraw.decode("utf-8")) if qraw else {}
    craw = read("config.yaml")
    return StateBundle("prod:" + backend.name, events, manifest, sorted(games),
                       queue, craw.decode("utf-8") if craw else None, read)


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
@dataclass
class Check:
    name: str
    severity: str          # "hard" | "warn"
    passed: bool
    detail: str = ""


@dataclass
class Result:
    checks: list[Check] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def add(self, name, severity, passed, detail=""):
        self.checks.append(Check(name, severity, bool(passed), detail))

    @property
    def hard_failures(self):
        return [c for c in self.checks if c.severity == "hard" and not c.passed]

    @property
    def warnings(self):
        return [c for c in self.checks if c.severity == "warn" and not c.passed]


def _cmp_root(name: str) -> bool:
    r, b = REPO / name, BASELINE / name
    return r.is_file() and b.is_file() and filecmp.cmp(r, b, shallow=False)


def run_checks(bundle: StateBundle, *, config_path_text: str | None) -> Result:
    res = Result()
    events = bundle.events

    # --- root immutability (always local; root lives in the repo) ----------
    res.add("root_main_py_unchanged", "hard", _cmp_root("main.py"),
            "root main.py must be byte-identical to the frozen baseline")
    res.add("root_deck_csv_unchanged", "hard", _cmp_root("deck.csv"),
            "root deck.csv must be byte-identical to the frozen baseline")

    # --- auto-submit must be off (config + env) ----------------------------
    # Load config from the bundle's config.yaml (write it to a temp path so the
    # existing loader parses it identically), falling back to defaults.
    cfg = load_config()
    if bundle.config_text is not None:
        tmp = EXP / ".health_config_probe.yaml"
        EXP.mkdir(parents=True, exist_ok=True)
        tmp.write_text(bundle.config_text, encoding="utf-8")
        try:
            cfg = load_config(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    env_auto = str(os.environ.get("TOURNAMENT_AUTO_SUBMIT", "")).strip().lower() in {
        "1", "true", "yes", "on"}
    res.add("auto_submit_off", "hard",
            (cfg.auto_submit is False) and not env_auto,
            f"config.auto_submit={cfg.auto_submit} env_auto_submit={env_auto}")

    # --- no forbidden upload/submit events ---------------------------------
    forbidden = sorted({e.get("event_type") for e in events} & _FORBIDDEN)
    res.add("no_forbidden_events", "hard", not forbidden,
            f"forbidden events present: {forbidden}")

    # --- every event no_upload=true ----------------------------------------
    missing_no_upload = sum(1 for e in events
                            if (e.get("payload") or {}).get("no_upload") is not True)
    res.add("all_events_no_upload", "hard", missing_no_upload == 0,
            f"{missing_no_upload} event(s) missing no_upload=true")

    # --- finished games: unique + sidecar present --------------------------
    finished_ids: list[str] = []
    finish_sha: dict[str, set] = {}
    for e in events:
        if e.get("event_type") != "GameFinished":
            continue
        gid = (e.get("payload") or {}).get("game_id")
        if not gid:
            continue
        finished_ids.append(str(gid))
        sha = (e.get("payload") or {}).get("artifact_sha256")
        finish_sha.setdefault(str(gid), set()).add(sha)
    dup_ids = sorted({g for g in finished_ids if finished_ids.count(g) > 1})
    res.add("no_duplicate_finished_game_ids", "hard", not dup_ids,
            f"duplicate finished game_ids: {dup_ids[:5]}")
    divergent = sorted(g for g, s in finish_sha.items()
                       if len({x for x in s if x is not None}) > 1)
    res.add("no_divergent_finish_sha", "hard", not divergent,
            f"game_ids with conflicting artifact_sha256: {divergent[:5]}")

    sidecar_names = set(bundle.game_keys)

    def _sidecar_key(gid: str) -> str:
        return f"games/{gid}.json.gz"

    missing_sidecars = sorted(g for g in set(finished_ids)
                              if _sidecar_key(g) not in sidecar_names)
    res.add("every_finished_game_has_sidecar", "hard", not missing_sidecars,
            f"finished games missing sidecar: {missing_sidecars[:5]}")

    # --- manifest sha integrity + event_count ------------------------------
    man = bundle.manifest
    mfiles = man.get("files", []) or []
    sha_mismatches = []
    checked = 0
    for f in mfiles:
        key, want = f.get("key"), f.get("sha256")
        data = bundle.read_bytes(key) if key else None
        if data is None:
            sha_mismatches.append(f"{key} (absent)")
            continue
        checked += 1
        if hashlib.sha256(data).hexdigest() != want:
            sha_mismatches.append(f"{key} (sha)")
    # Authoritative prod snapshot must be byte-consistent (hard). The local
    # working dir is explicitly disposable and may be rebuilt ahead of the last
    # push (projections carry a fresh generated_at), so there it is a warning.
    manifest_sev = "hard" if bundle.source.startswith("prod") else "warn"
    res.add("manifest_sha_integrity", manifest_sev, not sha_mismatches,
            f"checked={checked} mismatches={sha_mismatches[:5]}"
            + ("" if manifest_sev == "hard"
               else " (local working dir is disposable; may be rebuilt ahead of "
                    "last push — re-pull to reconcile)"))
    res.add("manifest_event_count_matches", "hard",
            man.get("event_count") == len(events),
            f"manifest={man.get('event_count')} ledger={len(events)}")
    res.add("manifest_no_upload_auto_submit", "hard",
            man.get("no_upload") is True and man.get("auto_submit") is False,
            f"manifest no_upload={man.get('no_upload')} "
            f"auto_submit={man.get('auto_submit')}")

    # --- pool / scheduler invariants (from events alone) -------------------
    pool = CandidatePool.from_events([_E(e) for e in events])
    status_map = {c.candidate_id: c.status for c in pool.candidates}
    queue = bundle.scheduler_queue.get("queue", []) or []
    never = set()
    for it in queue:
        for cid in (it.get("candidate_a"), it.get("candidate_b")):
            if status_map.get(cid) in poolmod.NEVER_SCHEDULE:
                never.add(cid)
    res.add("no_never_schedule_in_queue", "hard", not never,
            f"NEVER_SCHEDULE candidates queued: {sorted(never)}")

    held = [c for c in pool.candidates if c.status == poolmod.HELD_PROBE]
    held_dropped = [c.candidate_id for c in held if not c.schedulable]
    res.add("held_probe_retained", "hard",
            (poolmod.HELD_PROBE in poolmod.SCHEDULABLE_STATUSES) and not held_dropped,
            f"held_probe not schedulable: {held_dropped}")

    # --- soft / sample-size warnings ---------------------------------------
    games_per: dict[str, int] = {}
    totals = {"games": 0, "ok": 0, "invalid": 0, "timeout": 0, "draw": 0}
    for e in events:
        if e.get("event_type") != "GameFinished":
            continue
        p = e.get("payload") or {}
        a, b = p.get("candidate_a"), p.get("candidate_b")
        if not a or not b:
            continue
        totals["games"] += 1
        for c in (a, b):
            games_per[c] = games_per.get(c, 0) + 1
        r = p.get("result")
        if r in ("win", "loss", "draw"):
            totals["ok"] += 1
            if r == "draw":
                totals["draw"] += 1
        else:
            totals["invalid"] += 1
            if p.get("timeout"):
                totals["timeout"] += 1

    min_games = cfg.min_placement_games_per_candidate
    schedulable_ids = [c.candidate_id for c in pool.schedulable()]
    below = sorted(c for c in schedulable_ids if games_per.get(c, 0) < min_games)
    zero = sorted(c for c in schedulable_ids if games_per.get(c, 0) == 0)
    res.add("placement_sample_size", "warn", not below,
            f"{len(below)}/{len(schedulable_ids)} schedulable below "
            f"{min_games} games (tiny sample; rankings low-confidence)")
    res.add("no_zero_game_candidates", "warn", not zero,
            f"{len(zero)} schedulable candidate(s) with zero games: {zero[:8]}")
    res.add("no_invalid_or_timeout_games", "warn",
            totals["invalid"] == 0 and totals["timeout"] == 0,
            f"invalid={totals['invalid']} timeout={totals['timeout']}")
    res.add("sufficient_total_games", "warn", totals["games"] >= _LOW_TOTAL_GAMES,
            f"total games {totals['games']} (< {_LOW_TOTAL_GAMES} is low-confidence)")

    # --- lease status (informational warning) ------------------------------
    lease_info = None
    try:
        if bundle.source.startswith("prod"):
            be = get_storage_backend(env="production", backend="replit_app_storage")
            lease_info = lease_mod.read_lease(be)
    except Exception:
        lease_info = None
    now = time.time()
    lease_active = bool(lease_info and float(lease_info.get("expires_at", 0) or 0) > now)
    lease_stale = bool(lease_info and not lease_active)
    res.add("no_stale_lease", "warn", not lease_stale,
            f"stale lease present: {lease_info.get('tick_id') if lease_info else None}")

    res.info = {
        "source": bundle.source,
        "events": len(events),
        "finished_games": len(set(finished_ids)),
        "game_sidecars": len(bundle.game_keys),
        "totals": totals,
        "registered_candidates": len(pool.candidates),
        "schedulable_candidates": len(schedulable_ids),
        "status_counts": pool.stats(),
        "queue_size": len(queue),
        "held_probe_count": len(held),
        "lease_active": lease_active,
        "config_auto_submit": cfg.auto_submit,
        "manifest_status": man.get("status"),
        "manifest_tick_id": man.get("tick_id"),
    }
    return res


class _E:
    """Adapt a raw event dict to the attribute access CandidatePool expects."""
    def __init__(self, d: dict):
        self.event_type = d.get("event_type")
        self.payload = d.get("payload") or {}
        self.timestamp = d.get("timestamp")
        self.event_id = d.get("event_id")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def write_report(res: Result, out_json: Path, out_md: Path, *, mode: str,
                 elapsed: float) -> None:
    healthy = not res.hard_failures
    payload = {
        "schema": "pass38_tournament_health_v1",
        "generated_at": time.time(),
        "mode": mode,
        "no_upload": True, "auto_submit": False, "upload_performed": False,
        "candidate_generation": False, "github_push": False,
        "healthy": healthy,
        "hard_failures": [c.name for c in res.hard_failures],
        "warnings": [c.name for c in res.warnings],
        "checks": [{"name": c.name, "severity": c.severity, "passed": c.passed,
                    "detail": c.detail} for c in res.checks],
        "info": res.info,
        "elapsed_s": round(elapsed, 3),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def mark(c: Check) -> str:
        if c.passed:
            return "PASS"
        return "FAIL" if c.severity == "hard" else "WARN"

    info = res.info
    md = [
        "# Tournament health check", "",
        "> Independent read-only audit of the standing-tournament engine's "
        "persistent state. Internal diagnostics; NOT a Kaggle leaderboard. NO "
        "upload, NO submit, NO push, NO root mutation, NO candidate generation.",
        "",
        f"- mode: **{mode}**  source: `{info.get('source')}`",
        f"- **healthy (no hard failures): {'yes' if healthy else 'NO'}**",
        f"- hard failures: {len(res.hard_failures)}  warnings: {len(res.warnings)}",
        f"- events: {info.get('events')}  finished games: "
        f"{info.get('finished_games')}  sidecars: {info.get('game_sidecars')}",
        f"- totals: {info.get('totals')}",
        f"- candidates: {info.get('registered_candidates')} registered, "
        f"{info.get('schedulable_candidates')} schedulable; "
        f"status {info.get('status_counts')}",
        f"- scheduler queue size: {info.get('queue_size')}  held_probe: "
        f"{info.get('held_probe_count')}  lease_active: {info.get('lease_active')}",
        "",
        "## Hard safety invariants",
        "| check | result | detail |", "|---|---|---|",
        *[f"| {c.name} | {mark(c)} | {c.detail} |"
          for c in res.checks if c.severity == "hard"],
        "",
        "## Warnings (sample size / data quality)",
        "| check | result | detail |", "|---|---|---|",
        *[f"| {c.name} | {mark(c)} | {c.detail} |"
          for c in res.checks if c.severity == "warn"],
        "",
        f"_generated in {round(elapsed, 2)}s_",
    ]
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Tournament health checker (read-only).")
    ap.add_argument("--mode", choices=["prod", "local"], default="local")
    ap.add_argument("--out-json", default=str(EXP / "tournament_health.json"))
    ap.add_argument("--out-md", default=str(EXP / "tournament_health.md"))
    args = ap.parse_args()

    t0 = time.time()
    try:
        bundle = _prod_bundle() if args.mode == "prod" else _local_bundle()
    except (StorageError, Exception) as exc:  # fail closed on unreachable prod
        out_json = Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({
            "schema": "pass38_tournament_health_v1", "mode": args.mode,
            "healthy": False, "error": f"state source unavailable: {exc}",
            "hard_failures": ["state_source_unavailable"],
        }, indent=2), encoding="utf-8")
        print(f"health: UNHEALTHY — state source unavailable: {exc}")
        return 1

    res = run_checks(bundle, config_path_text=bundle.config_text)
    write_report(res, Path(args.out_json), Path(args.out_md),
                 mode=args.mode, elapsed=time.time() - t0)

    healthy = not res.hard_failures
    print(f"health[{args.mode}]: healthy={healthy} "
          f"hard_failures={[c.name for c in res.hard_failures]} "
          f"warnings={[c.name for c in res.warnings]}")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
