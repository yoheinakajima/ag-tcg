#!/usr/bin/env python3
"""Pass 39 — Part H: scheduler audit AFTER the lifecycle pass.

Confirms the deterministic scheduler honors the candidate lifecycle: the next
bounded worklist contains ONLY schedulable candidates (zero never_schedule
appearances), is byte-for-byte deterministic across two builds, and matches the
persisted ``scheduler_queue`` projection. Read-only; writes only diagnostics under
``data/experiments/``. NO upload, NO submit, NO candidate generation.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import projections  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import NEVER_SCHEDULE, CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402

EXP = REPO / "data" / "experiments"
PROJ_DIR = REPO / "data" / "tournament" / "projections"


def _worklist(pool, events, cfg):
    agg = projections.fold_games(events)
    rankings = projections.compute_rankings(pool, agg)
    ranked = [r["candidate_id"] for r in rankings]
    state = projections.build_scheduler_state(events, ranking=ranked)
    wl = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    finished = TournamentLedger().finished_game_ids()
    return [g for g in wl if g.game_id not in finished]


def main() -> int:
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates:
        pool = CandidatePool.load()

    wl1 = _worklist(pool, events, cfg)
    wl2 = _worklist(pool, events, cfg)
    deterministic = [g.to_dict() for g in wl1] == [g.to_dict() for g in wl2]

    status_of = {c.candidate_id: c.status for c in pool.candidates}
    appearances: dict[str, int] = {}
    never_in_queue: list[dict] = []
    by_priority: dict[int, int] = {}
    by_reason: dict[str, int] = {}
    for g in wl1:
        by_priority[g.priority] = by_priority.get(g.priority, 0) + 1
        by_reason[g.reason] = by_reason.get(g.reason, 0) + 1
        for cid in (g.candidate_a, g.candidate_b):
            appearances[cid] = appearances.get(cid, 0) + 1
            if status_of.get(cid) in NEVER_SCHEDULE:
                never_in_queue.append({"game_id": g.game_id, "candidate": cid,
                                       "status": status_of.get(cid)})

    schedulable_ids = {c.candidate_id for c in pool.schedulable()}
    blocked = sorted(
        ({"candidate_id": c.candidate_id, "status": c.status}
         for c in pool.candidates if not c.schedulable),
        key=lambda d: d["candidate_id"])
    appearing = set(appearances)
    leaked = sorted(appearing - schedulable_ids)

    # Cross-check against the persisted scheduler_queue projection (from the pull).
    persisted = None
    qpath = PROJ_DIR / "scheduler_queue.json"
    if qpath.is_file():
        persisted = json.loads(qpath.read_text(encoding="utf-8")).get("count")
    persisted_matches = (persisted is None) or (persisted == len(wl1))

    ok = (not never_in_queue) and deterministic and (not leaked) and persisted_matches
    payload = {
        "schema": "pass39_scheduler_after_lifecycle_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True,
        "ok": ok,
        "queue_size": len(wl1),
        "deterministic_two_builds": deterministic,
        "never_schedule_in_queue": never_in_queue,
        "leaked_non_schedulable": leaked,
        "blocked_candidates": blocked,
        "schedulable_count": len(schedulable_ids),
        "queue_by_priority": {str(k): by_priority[k] for k in sorted(by_priority)},
        "queue_by_reason": by_reason,
        "candidate_appearances": dict(sorted(appearances.items())),
        "persisted_queue_count": persisted,
        "persisted_matches_rebuild": persisted_matches,
        "status_counts": pool.stats(),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass39_scheduler_after_lifecycle.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md = [
        "# Pass 39 — Scheduler audit after lifecycle", "",
        "_Internal diagnostics only. NO upload, NO submit, NO candidate generation._", "",
        f"- **ok: {ok}**",
        f"- queue size: {len(wl1)}  deterministic(2 builds): {deterministic}",
        f"- never_schedule in queue: {len(never_in_queue)}  "
        f"leaked non-schedulable: {len(leaked)}",
        f"- schedulable candidates: {len(schedulable_ids)}  "
        f"blocked: {len(blocked)}",
        f"- persisted queue count: {persisted}  matches rebuild: {persisted_matches}",
        f"- queue by priority: {payload['queue_by_priority']}",
        f"- queue by reason: {by_reason}",
        f"- status counts: {pool.stats()}", "",
        "## Blocked (never scheduled)",
    ]
    for b in blocked:
        md.append(f"- `{b['candidate_id']}` — {b['status']}")
    (EXP / "pass39_scheduler_after_lifecycle.md").write_text("\n".join(md) + "\n",
                                                             encoding="utf-8")
    print(f"scheduler-after-lifecycle: ok={ok} queue={len(wl1)} "
          f"never_in_queue={len(never_in_queue)} deterministic={deterministic} "
          f"persisted_matches={persisted_matches}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
