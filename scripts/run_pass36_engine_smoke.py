#!/usr/bin/env python3
"""Pass 36 — engine smoke: run a tiny real tick, then a second tick to prove
resume/no-duplication. LOCAL ONLY. NO upload, NO candidate generation.

Usage:
  python scripts/run_pass36_engine_smoke.py [--games N] [--seconds S]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament.runner import TournamentEngine  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.graph.events import EventType  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--seconds", type=int, default=600)
    args = ap.parse_args()

    led = TournamentLedger()
    before = led.finished_game_ids()

    engine = TournamentEngine()
    tick1 = engine.run_tick(max_games=args.games, max_seconds=args.seconds)
    ids_after1 = led.finished_game_ids()

    # Second tick: should resume and NOT replay any tick-1 game ids.
    engine2 = TournamentEngine()
    tick2 = engine2.run_tick(max_games=args.games, max_seconds=args.seconds)
    ids_after2 = led.finished_game_ids()

    tick1_ids = ids_after1 - before
    tick2_ids = ids_after2 - ids_after1
    overlap = tick1_ids & tick2_ids

    # No upload events of any kind.
    uploads = [e for e in led.load()
               if e.event_type in (EventType.SubmissionUploaded.value,
                                    EventType.KaggleScoreUpdated.value)]

    summary = {
        "tick1": {"games_played": tick1["games_played"],
                  "stop_reason": tick1["stop_reason"],
                  "new_game_ids": len(tick1_ids)},
        "tick2": {"games_played": tick2["games_played"],
                  "stop_reason": tick2["stop_reason"],
                  "new_game_ids": len(tick2_ids)},
        "duplicate_game_ids_across_ticks": sorted(overlap),
        "resume_ok": len(overlap) == 0,
        "submission_upload_events": len(uploads),
        "no_upload_ok": len(uploads) == 0,
        "totals": tick2["totals"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if (summary["resume_ok"] and summary["no_upload_ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
