#!/usr/bin/env python3
"""Pass 36 — run ONE bounded tick of the standing tournament engine. LOCAL ONLY.

This is the unit a persistent Replit daemon would call repeatedly. It is safe to
re-run: finished games are durable on the ledger and are not replayed. It does
NOT generate candidates and NEVER uploads or submits.

Usage:
  python scripts/tournament_daemon_tick.py [--max-games N] [--max-seconds S]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament.runner import TournamentEngine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one bounded tournament tick.")
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--max-seconds", type=int, default=None)
    args = ap.parse_args()

    engine = TournamentEngine()
    rec = engine.run_tick(max_games=args.max_games, max_seconds=args.max_seconds)
    print(json.dumps({k: rec[k] for k in
                      ("tick_id", "stop_reason", "planned", "games_played",
                       "next_queue_size", "totals")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
