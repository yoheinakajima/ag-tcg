#!/usr/bin/env python3
"""Pass 38 (Part C) — pull + inspect the production Object Storage state.

OPS / read-only against the backend. Pulls the persistent tournament state into
the disposable local working dir (``data/tournament/``) via the engine's own
``pull_state`` (clears local managed state, then downloads — the backend is the
sole source of truth and is NEVER written here), then inspects:

  * events.jsonl — total, counts by type, finished game ids, no_upload on every
    event, and that NO forbidden upload/submit event exists,
  * storage_manifest.json — schema/no_upload/auto_submit/event_count/last_event_id,
  * remote events hash == sha256 of the pulled local events.jsonl,
  * projections present + tournament_state totals,
  * game sidecars and tick run records.

Writes data/experiments/pass38_remote_state_snapshot.{json,md}. NO upload, NO
submit, NO push, NO root mutation, NO candidate generation.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"
PROJ = TDIR / "projections"
_FORBIDDEN = {"SubmissionUploaded", "KaggleScoreUpdated"}
_EXPECTED_PROJECTIONS = [
    "tournament_state.json", "rankings.json", "rankings.md", "matchups.csv",
    "candidate_pool.json", "candidate_pool.md", "lineage.json", "lineage.md",
    "non_inertness.json", "non_inertness.md", "scheduler_queue.json",
    "scheduler_queue.md",
]


def main() -> int:
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    remote_hash_before = sync.remote_events_hash(backend)
    pull = sync.pull_state(backend, TDIR)

    # --- events -----------------------------------------------------------
    ev_path = TDIR / "events.jsonl"
    events = sync.parse_events_text(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else []
    type_counts = Counter(e.get("event_type") for e in events)
    finished = {(e.get("payload") or {}).get("game_id")
                for e in events if e.get("event_type") == "GameFinished"}
    finished.discard(None)
    all_no_upload = all((e.get("payload") or {}).get("no_upload") is True for e in events) if events else True
    forbidden_present = sorted(set(type_counts) & _FORBIDDEN)

    # local events sha must match the remote hash we read (proves a faithful pull)
    local_sha = hashlib.sha256(ev_path.read_bytes()).hexdigest() if ev_path.is_file() else None
    hash_matches = (local_sha == remote_hash_before)

    # --- manifest ---------------------------------------------------------
    man_path = TDIR / "storage_manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {}
    manifest_event_count_matches = manifest.get("event_count") == len(events)

    # --- projections ------------------------------------------------------
    proj_present = {name: (PROJ / name).is_file() for name in _EXPECTED_PROJECTIONS}
    all_projections_present = all(proj_present.values())
    ts_path = PROJ / "tournament_state.json"
    tstate = json.loads(ts_path.read_text(encoding="utf-8")) if ts_path.is_file() else {}

    # --- sidecars + runs --------------------------------------------------
    games = sorted(p.name for p in (TDIR / "games").glob("*.json.gz")) if (TDIR / "games").is_dir() else []
    runs = sorted(p.name for p in (TDIR / "runs").glob("*.json")) if (TDIR / "runs").is_dir() else []

    # Every finished game should have a durable sidecar (gid -> games/<gid>.json.gz)
    sidecar_names = set(games)
    missing_sidecars = sorted(
        gid for gid in finished
        if f"{gid}.json.gz" not in sidecar_names
    )

    snapshot_ok = (
        hash_matches and all_no_upload and not forbidden_present
        and all_projections_present and manifest_event_count_matches
        and not missing_sidecars
        and manifest.get("no_upload") is True and manifest.get("auto_submit") is False
    )

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "C", "read_only_backend": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "backend": backend.name, "prefix": backend.prefix,
        "remote_events_sha256": remote_hash_before,
        "local_events_sha256_after_pull": local_sha,
        "remote_local_hash_matches": hash_matches,
        "pull": {"count": pull["count"], "bytes": pull["bytes"],
                 "cleared": pull["cleared"], "keys": pull["keys"]},
        "events": {
            "total": len(events),
            "by_type": dict(sorted(type_counts.items())),
            "finished_game_ids": len(finished),
            "all_no_upload_true": all_no_upload,
            "forbidden_events_present": forbidden_present,
        },
        "manifest": {
            "schema": manifest.get("schema"),
            "no_upload": manifest.get("no_upload"),
            "auto_submit": manifest.get("auto_submit"),
            "event_count": manifest.get("event_count"),
            "event_count_matches_ledger": manifest_event_count_matches,
            "last_event_id": manifest.get("last_event_id"),
            "files": len(manifest.get("files", [])),
            "status": manifest.get("status"),
            "tick_id": manifest.get("tick_id"),
        },
        "projections": {"present": proj_present, "all_present": all_projections_present},
        "tournament_state_totals": tstate.get("totals"),
        "registered_candidates": tstate.get("registered_candidates"),
        "schedulable_candidates": tstate.get("schedulable_candidates"),
        "game_sidecars": len(games),
        "tick_runs": len(runs),
        "tick_run_files": runs,
        "missing_sidecars": missing_sidecars,
        "snapshot_ok": snapshot_ok,
    }
    (EXP / "pass38_remote_state_snapshot.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    tt = tstate.get("totals") or {}
    md = [
        "# Pass 38 — Production state snapshot (Part C)", "",
        "> OPS / read-only against the backend. Pulled persistent state into the "
        "disposable working dir; the backend was NEVER written. NO upload, NO "
        "submit, NO push, NO candidate generation. Internal diagnostics; NOT a "
        "Kaggle leaderboard.", "",
        f"- backend: `{backend.name}` prefix `{backend.prefix or '(root)'}`",
        f"- pulled keys: **{pull['count']}** ({pull['bytes']} bytes); "
        f"cleared local managed state: {pull['cleared']}",
        f"- remote events sha256 == pulled local events sha256: "
        f"**{yn(hash_matches)}**", "",
        "## Event ledger",
        f"- total events: **{len(events)}**; finished games: **{len(finished)}**",
        f"- every event carries no_upload=true: **{yn(all_no_upload)}**",
        f"- forbidden upload/submit events present: "
        f"**{yn(bool(forbidden_present))}** {forbidden_present or ''}",
        "- counts by type:",
        *[f"    - `{t}`: {n}" for t, n in sorted(type_counts.items())],
        "",
        "## Storage manifest",
        f"- schema: `{manifest.get('schema')}` status: `{manifest.get('status')}`",
        f"- no_upload: **{yn(manifest.get('no_upload'))}** "
        f"auto_submit: **{yn(manifest.get('auto_submit'))}**",
        f"- event_count {manifest.get('event_count')} matches ledger "
        f"({len(events)}): **{yn(manifest_event_count_matches)}**",
        f"- last_event_id: `{manifest.get('last_event_id')}` "
        f"files tracked: {len(manifest.get('files', []))}", "",
        "## Projections",
        f"- all expected projections present: **{yn(all_projections_present)}**",
        *[f"    - `{n}`: {yn(ok)}" for n, ok in proj_present.items()],
        "",
        "## Games + ticks",
        f"- tournament totals: games {tt.get('games')} (ok {tt.get('ok')}, "
        f"invalid {tt.get('invalid')}, timeout {tt.get('timeout')}, "
        f"draw {tt.get('draw')})",
        f"- registered candidates: {tstate.get('registered_candidates')}  "
        f"schedulable: {tstate.get('schedulable_candidates')}",
        f"- game sidecars on backend: **{len(games)}**  tick run records: "
        f"**{len(runs)}**",
        f"- every finished game has a sidecar: **{yn(not missing_sidecars)}** "
        f"{('missing: ' + str(missing_sidecars)) if missing_sidecars else ''}", "",
        f"## Verdict: snapshot_ok = **{yn(snapshot_ok)}**",
    ]
    (EXP / "pass38_remote_state_snapshot.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"snapshot: ok={snapshot_ok} events={len(events)} finished={len(finished)} "
          f"sidecars={len(games)} runs={len(runs)} hash_match={hash_matches} "
          f"forbidden={forbidden_present}")
    return 0 if snapshot_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
