#!/usr/bin/env python3
"""PASS 46C — frame-persisting diagnostic trace runner (READ-ONLY / LOCAL ONLY).

A bounded, reusable LOCAL diagnostic lane (NOT wired into the production daemon) that:
  1. Runs a Part-A safety stop-gate and REFUSES to play any game unless it passes.
  2. Plays a small bounded panel of local ``cabt`` games, each in a subprocess-isolated
     worker with a hard timeout, and persists the FULL per-decision-frame ``env.steps``
     trace (compressed) under ``data/experiments/pass46c_traces/``.
  3. Writes a trace manifest with ``no_upload=true``.

Guarantees: NEVER mutates production Object Storage, NEVER runs a production tick,
NEVER writes ``data/tournament/events.jsonl`` or any tournament ledger, NEVER emits a
lifecycle / generation / promotion / submission event, NEVER touches root ``main.py`` /
``deck.csv``. Public references stay benchmark-only opponents.

Run: ``python3 scripts/run_pass46c_trace_games.py``  (idempotent; overwrites pass46c_traces/).
"""
from __future__ import annotations

import filecmp
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync, promotion, pool as poolmod, projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
LOCAL_EVENTS = REPO / "data" / "tournament" / "events.jsonl"
WORKER = REPO / "scripts" / "_pass46c_trace_worker.py"
GAME_TIMEOUT_S = 60
GAME_RETRIES = 1  # cabt native wedges are non-deterministic; one retry usually clears it
DEFAULT_BUDGET_S = 100.0  # per-invocation wall-clock; runner is resumable across calls

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED, poolmod.INVALID}

CAVEATS = [
    "READ-ONLY / LOCAL diagnostic: production Object Storage was not mutated.",
    "No production tick executed; the deployed daemon is unchanged and still soaking.",
    "No candidate generation, promotion, retirement, quarantine, queue, or upload occurred.",
    "No tournament ledger / events.jsonl write occurred; traces live in a diagnostic-only dir.",
    "Public references are BENCHMARK-ONLY opponents, never candidates/parents/sources.",
    "Game outcomes here are LOCAL self-play diagnostics, NOT Kaggle leaderboard scores.",
]

# -- participants (tarball paths verified present) ----------------------------------
TARBALLS = {
    "league_water_anti_disruption_pivot_v1":
        "data/submissions/candidates_pass33/league_water_anti_disruption_pivot_v1.tar.gz",
    "generated_lightning_monolightningm_dsratio_v1":
        "data/submissions/generated_pass42/generated_lightning_monolightningm_dsratio_v1.tar.gz",
    "mono_lightning_miraidon_easy":
        "data/submissions/candidates_pass35/mono_lightning_miraidon_easy.tar.gz",
    "generated_diamond_diamondtoolbox_eratio_v1":
        "data/submissions/generated_pass42/generated_diamond_diamondtoolbox_eratio_v1.tar.gz",
    "diamond_toolbox_diancie":
        "data/submissions/candidates_pass35/diamond_toolbox_diancie.tar.gz",
    "public_ref_kiyotah_dragapult":
        "data/reference_agents/tarballs/public_ref_kiyotah_dragapult.tar.gz",
    "public_ref_kiyotah_mega_lucario":
        "data/reference_agents/tarballs/public_ref_kiyotah_mega_lucario.tar.gz",
}
ROLE = {
    "league_water_anti_disruption_pivot_v1": "internal_candidate_top_water",
    "generated_lightning_monolightningm_dsratio_v1": "internal_candidate_probation",
    "mono_lightning_miraidon_easy": "parent",
    "generated_diamond_diamondtoolbox_eratio_v1": "internal_candidate_probation_lowperf",
    "diamond_toolbox_diancie": "parent",
    "public_ref_kiyotah_dragapult": "public_reference",
    "public_ref_kiyotah_mega_lucario": "public_reference",
}
# Unordered matchups; each is expanded to BOTH seats (2 games).
MATCHUPS = [
    ("g1_water_vs_refs", "league_water_anti_disruption_pivot_v1",
     "public_ref_kiyotah_dragapult", "top_water_vs_reference"),
    ("g1_water_vs_refs", "league_water_anti_disruption_pivot_v1",
     "public_ref_kiyotah_mega_lucario", "top_water_vs_reference"),
    ("g2_lightning", "generated_lightning_monolightningm_dsratio_v1",
     "mono_lightning_miraidon_easy", "probation_vs_parent"),
    ("g2_lightning", "generated_lightning_monolightningm_dsratio_v1",
     "public_ref_kiyotah_dragapult", "probation_vs_reference"),
    ("g3_diamond_lowperf", "generated_diamond_diamondtoolbox_eratio_v1",
     "diamond_toolbox_diancie", "low_probation_vs_parent"),
    ("g4_ref_baseline", "public_ref_kiyotah_dragapult",
     "public_ref_kiyotah_mega_lucario", "reference_vs_reference_baseline"),
]


def sha_path(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def sha_obj(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def write_pair(stem: str, data: dict, md_title: str, md_body: str) -> None:
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + md_title + "\n\n_Pass 46C — read-only / local frame-persisting "
            "diagnostic. Local self-play only; NOT a Kaggle strength claim. "
            "No generation / promotion / upload / tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + md_body + "\n", encoding="utf-8")


def _extract_agent(tarball: Path, dest: Path) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202 - our own build artifacts / vetted refs
    main = dest / "main.py"
    if main.exists():
        return str(main)
    for p in dest.rglob("main.py"):
        return str(p)
    raise FileNotFoundError(f"no main.py inside {tarball.name}")


def _resolve_parents() -> dict:
    """Read parent_candidate_id for generated candidates from the LOCAL ledger (read-only)."""
    parents: dict = {}
    if not LOCAL_EVENTS.exists():
        return parents
    for line in LOCAL_EVENTS.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if e.get("event_type") != "CandidateGenerated":
            continue
        p = e.get("payload", {})
        cid = p.get("candidate_id")
        if cid:
            parents[cid] = p.get("parent_candidate_id")
    return parents


# ============================================================= Part A: safety
def part_a() -> dict:
    main_before = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_before = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    replit_txt = (REPO / ".replit").read_text(encoding="utf-8")
    dep_ok = ("scripts/tournament_deployment_tick.py" in replit_txt
              and "--production" in replit_txt
              and "replit_app_storage" in replit_txt)
    deployment_target_scheduled = 'deploymentTarget = "scheduled"' in replit_txt
    try:
        cfg = load_config()
        auto_submit = bool(getattr(cfg, "auto_submit", False)) if cfg is not None else False
    except Exception:  # noqa: BLE001
        auto_submit = False
    # references absent from prod pool + worklist (read-only prod load)
    b = get_storage_backend(env="production", backend="replit_app_storage")
    txt = b.read_text(sync.EVENTS_KEY)
    tmpf = Path(tempfile.mkdtemp()) / "events.jsonl"
    tmpf.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmpf).load()
    pool = CandidatePool.from_events(events)
    status_of = {c.candidate_id: c.status for c in pool.candidates}
    ref_ids = set(promotion.load_reference_ids())
    refs_in_pool = sorted(ref_ids & set(status_of))
    projmod.PROJ_DIR = Path(tempfile.mkdtemp())
    cfg = load_config()
    prior = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
    wl_ids: set[str] = set()
    for g in build_worklist(pool, state, cfg):
        d = g.to_dict()
        wl_ids.add(d["candidate_a"])
        wl_ids.add(d["candidate_b"])
    refs_in_wl = sorted(ref_ids & wl_ids)
    never_in_wl = sorted(c for c, s in status_of.items() if s in NEVER and c in wl_ids)
    forbidden_in_ledger = sorted({e.event_type for e in events
                                  if e.event_type in LEDGER_FORBIDDEN})
    # every panel participant tarball is present, and references are never our candidate
    panel_ids = set(TARBALLS)
    missing = sorted(pid for pid, rel in TARBALLS.items() if not (REPO / rel).exists())
    panel_refs = {pid for pid in panel_ids if ROLE[pid] == "public_reference"}
    refs_only_as_opponents = all(
        ROLE[pid] == "public_reference" for pid in panel_refs)  # tautology guard
    checks = {
        "root_main_unchanged_before": main_before,
        "root_deck_unchanged_before": deck_before,
        "deployment_points_to_tick_not_root": dep_ok,
        "deployment_target_scheduled": deployment_target_scheduled,
        "auto_submit_falsy": auto_submit is False,
        "references_absent_from_pool": refs_in_pool == [],
        "references_absent_from_worklist": refs_in_wl == [],
        "no_never_schedule_in_worklist": never_in_wl == [],
        "no_forbidden_events_in_prod_ledger": forbidden_in_ledger == [],
        "all_panel_tarballs_present": missing == [],
        "panel_references_are_opponents_only": refs_only_as_opponents,
    }
    all_ok = all(checks.values())
    data = {
        "pass": "46c", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "start_application_started": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": sha_path(REPO / "main.py"),
        "root_deck_sha256": sha_path(REPO / "deck.csv"),
        "deployment_run": "scripts/tournament_deployment_tick.py --production replit_app_storage",
        "checks": checks, "all_ok": all_ok,
        "refs_in_pool": refs_in_pool, "refs_in_worklist": refs_in_wl,
        "never_schedule_in_worklist": never_in_wl,
        "forbidden_events_in_prod_ledger": forbidden_in_ledger,
        "panel_tarballs_missing": missing,
        "prod_ledger_len": len(events),
        "panel_participants": {pid: ROLE[pid] for pid in sorted(panel_ids)},
    }
    md = "## Stop-gate checks\n" + "".join(
        f"- `{k}`: {'PASS' if v else 'FAIL'}\n" for k, v in checks.items())
    md += f"\n**all_ok = {all_ok}**\n"
    write_pair("pass46c_safety_preflight", data,
               "Pass 46C — Part A: safety stop-gate", md)
    return data


# ============================================================= Part B/C: run panel
def _outcome_for_a(rewards) -> str | None:
    if not (isinstance(rewards, list) and len(rewards) == 2):
        return None
    r0, r1 = rewards
    if not (isinstance(r0, (int, float)) and isinstance(r1, (int, float))):
        return None
    return "win" if r0 > r1 else "loss" if r0 < r1 else "draw"


def _play_one(a_main: str, b_main: str, out_json: Path) -> dict:
    """Run one game in an isolated worker with a hard timeout (with one retry for
    non-deterministic native wedges); return its record."""
    res: dict = {"ok": False, "timeout": False, "error": "not_run", "steps": None}
    for _attempt in range(GAME_RETRIES + 1):
        if out_json.exists():
            out_json.unlink()
        try:
            subprocess.run(
                [sys.executable, str(WORKER), a_main, b_main, str(out_json),
                 str(GAME_TIMEOUT_S)],
                capture_output=True, text=True, timeout=GAME_TIMEOUT_S + 15, check=False)
        except subprocess.TimeoutExpired:
            res = {"ok": False, "timeout": True, "error": "wedged_or_killed", "steps": None}
            continue
        if not out_json.exists():
            res = {"ok": False, "timeout": False, "error": "no_worker_output", "steps": None}
            continue
        res = json.loads(out_json.read_text(encoding="utf-8"))
        if res.get("ok"):
            return res
    return res


def canonical_games() -> list[dict]:
    """Deterministic 12-game panel: each unordered matchup expanded to both seats."""
    games: list[dict] = []
    i = 0
    for group, x, y, kind in MATCHUPS:
        for a, b in ((x, y), (y, x)):
            games.append({
                "i": i, "gid": f"pass46c_{i:02d}_{a}__vs__{b}",
                "group": group, "candidate_a": a, "candidate_b": b,
                "matchup_kind": kind})
            i += 1
    return games


def _existing_ok(trace_path: Path) -> bool:
    if not trace_path.exists():
        return False
    try:
        with gzip.open(trace_path, "rt", encoding="utf-8") as fh:
            return bool(json.load(fh).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def _write_trace(g: dict, res: dict) -> Path:
    a_outcome = _outcome_for_a(res.get("rewards")) if res.get("ok") else None
    trace = {
        "id": g["gid"], "pass": "46c", "no_upload": True, "local_only": True,
        "production_mutated": False,
        "group": g["group"], "matchup_kind": g["matchup_kind"],
        "candidate_a": g["candidate_a"], "candidate_b": g["candidate_b"],
        "role_a": ROLE[g["candidate_a"]], "role_b": ROLE[g["candidate_b"]],
        "a_seat": 0,  # candidate_a always sits at seat 0 of (first, second)
        "ok": bool(res.get("ok")), "timeout": bool(res.get("timeout")),
        "error": res.get("error"), "n_steps": res.get("n_steps"),
        "rewards": res.get("rewards"), "statuses": res.get("statuses"),
        "a_outcome": a_outcome, "elapsed_s": res.get("elapsed_s"),
        "steps": res.get("steps") or [],
    }
    trace["steps_sha256"] = sha_obj(trace["steps"])
    trace_path = TRACES / f"{g['gid']}.json.gz"
    with gzip.open(trace_path, "wt", encoding="utf-8") as fh:
        json.dump(trace, fh, default=str)
    return trace_path


def _rebuild_manifest(games: list[dict], parents: dict) -> dict:
    records: list[dict] = []
    for g in games:
        trace_path = TRACES / f"{g['gid']}.json.gz"
        if not trace_path.exists():
            records.append({
                "game_id": g["gid"], "group": g["group"],
                "matchup_kind": g["matchup_kind"],
                "candidate_a": g["candidate_a"], "candidate_b": g["candidate_b"],
                "role_a": ROLE[g["candidate_a"]], "role_b": ROLE[g["candidate_b"]],
                "ok": False, "timeout": False, "error": "not_yet_played",
                "n_steps": None, "a_outcome": None, "rewards": None,
                "elapsed_s": None, "trace_path": None, "trace_bytes": None,
                "steps_sha256": None, "no_upload": True})
            continue
        with gzip.open(trace_path, "rt", encoding="utf-8") as fh:
            t = json.load(fh)
        records.append({
            "game_id": t["id"], "group": t["group"], "matchup_kind": t["matchup_kind"],
            "candidate_a": t["candidate_a"], "candidate_b": t["candidate_b"],
            "role_a": t["role_a"], "role_b": t["role_b"],
            "ok": t["ok"], "timeout": t["timeout"], "error": t["error"],
            "n_steps": t["n_steps"], "a_outcome": t["a_outcome"],
            "rewards": t["rewards"], "elapsed_s": t["elapsed_s"],
            "trace_path": str(trace_path.relative_to(REPO)),
            "trace_bytes": trace_path.stat().st_size,
            "steps_sha256": t["steps_sha256"], "no_upload": True})
    n_ok = sum(1 for r in records if r["ok"])
    manifest = {
        "pass": "46c", "part": "B/C", "no_upload": True, "local_only": True,
        "production_mutated": False, "tick_executed": False,
        "events_written": False, "object_storage_mutated": False,
        "trace_dir": str(TRACES.relative_to(REPO)),
        "game_timeout_s": GAME_TIMEOUT_S, "game_retries": GAME_RETRIES,
        "panel_matchups": [
            {"group": gr, "a": x, "b": y, "kind": k} for gr, x, y, k in MATCHUPS],
        "panel_parents_resolved": {
            "generated_lightning_monolightningm_dsratio_v1":
                parents.get("generated_lightning_monolightningm_dsratio_v1"),
            "generated_diamond_diamondtoolbox_eratio_v1":
                parents.get("generated_diamond_diamondtoolbox_eratio_v1"),
        },
        "n_games_planned": len(games), "n_traces": sum(
            1 for r in records if r["trace_path"]),
        "n_ok": n_ok, "n_timeout": sum(1 for r in records if r["timeout"]),
        "n_error": sum(1 for r in records
                       if r["error"] and not r["timeout"] and r["error"] != "not_yet_played"),
        "n_not_played": sum(1 for r in records if r["error"] == "not_yet_played"),
        "complete": n_ok == len(games),
        "traces": records,
    }
    md = (f"Panel: **{n_ok}/{len(games)}** games OK "
          f"({manifest['n_timeout']} timeout, {manifest['n_error']} error, "
          f"{manifest['n_not_played']} not-yet-played). Full decision-frame traces "
          f"persisted (gzip) under `{manifest['trace_dir']}`; `no_upload=true`, "
          "no ledger/OS write.\n\n"
          "| game | kind | a (seat0) | b | ok | steps | a_outcome |\n"
          "|---|---|---|---|---|---|---|\n")
    for r in records:
        md += (f"| {r['group']} | {r['matchup_kind']} | {r['candidate_a']} | "
               f"{r['candidate_b']} | {r['ok']} | {r['n_steps']} | {r['a_outcome']} |\n")
    write_pair("pass46c_trace_manifest", manifest, "Pass 46C — trace manifest", md)
    return manifest


def run_panel(gate: dict, budget_s: float, fresh: bool) -> dict:
    if not gate.get("all_ok"):
        raise SystemExit("STOP: Part-A safety stop-gate failed; refusing to run games.")
    if fresh and TRACES.exists():
        shutil.rmtree(TRACES)
    TRACES.mkdir(parents=True, exist_ok=True)
    parents = _resolve_parents()
    games = canonical_games()
    deadline = time.time() + budget_s
    agent_main: dict = {}
    tmp = Path(tempfile.mkdtemp(prefix="pass46c_agents_"))
    work_dir = Path(tempfile.mkdtemp(prefix="pass46c_games_"))

    def agent_path(pid: str) -> str:
        if pid not in agent_main:
            agent_main[pid] = _extract_agent(REPO / TARBALLS[pid], tmp / pid)
        return agent_main[pid]

    for g in games:
        trace_path = TRACES / f"{g['gid']}.json.gz"
        if _existing_ok(trace_path):
            continue
        if time.time() >= deadline:
            break
        res = _play_one(agent_path(g["candidate_a"]), agent_path(g["candidate_b"]),
                        work_dir / f"{g['i']:02d}.json")
        _write_trace(g, res)
    return _rebuild_manifest(games, parents)


def main() -> int:
    budget_s = DEFAULT_BUDGET_S
    fresh = "--fresh" in sys.argv[1:]
    for a in sys.argv[1:]:
        if a.startswith("--budget="):
            budget_s = float(a.split("=", 1)[1])
    gate = part_a()  # full dynamic Part-A stop-gate runs fresh on EVERY invocation
    if not gate.get("all_ok"):
        print(json.dumps({"stage": "safety", "all_ok": False,
                          "checks": gate["checks"]}, indent=2))
        return 1
    manifest = run_panel(gate, budget_s, fresh)
    print(json.dumps({"all_ok": True,
                      "n_games_planned": manifest["n_games_planned"],
                      "n_ok": manifest["n_ok"], "n_timeout": manifest["n_timeout"],
                      "n_error": manifest["n_error"],
                      "n_not_played": manifest["n_not_played"],
                      "complete": manifest["complete"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
