#!/usr/bin/env python3
"""Pass 36 — rebuild ALL tournament projections from the event ledger alone.

Projections are a pure fold over ``data/tournament/events.jsonl``; this script is
idempotent and safe to re-run. It also recomputes the next scheduler queue.
Internal diagnostics only; NO upload.

Usage: python scripts/build_tournament_projections.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import projections  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402


def main() -> int:
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()

    # Rebuild the candidate registry from the ledger ALONE when registration
    # events exist (true event-sourcing); fall back to the seed file only if the
    # ledger has no participant registrations yet.
    pool = CandidatePool.from_events(events)
    source = "ledger"
    if not pool.candidates:
        pool = CandidatePool.load()
        source = "seed_file"

    summary = projections.write_projections(pool, events, cfg)
    state = projections.build_scheduler_state(events, ranking=summary["ranked_ids"])
    worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    finished = ledger.finished_game_ids()
    worklist = [g for g in worklist if g.game_id not in finished]
    projections.write_scheduler_queue(worklist, cfg)

    print(json.dumps({
        "registry_source": source,
        "registered_candidates": len(pool.candidates),
        "totals": summary["totals"],
        "ranked": summary["ranked_ids"][:cfg.top_bracket_size],
        "next_queue_size": len(worklist),
        "projections_dir": str(projections.PROJ_DIR.relative_to(REPO)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
