#!/usr/bin/env python3
"""Run local self-play games and record ActiveGraph events.

Requires cabt / kaggle-environments for actual play. Without them, prints clear
install instructions and exits non-zero (use --allow-missing to exit 0).

Usage:
    python scripts/run_self_play.py --games 50 --deck deck.csv --out data/matches/events.jsonl
    python scripts/run_self_play.py --games 50 --render data/reports/replay.html
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from agent import agent as runtime_agent
from ptcg_activegraph.decks.deck_io import load_deck
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.sim.cabt_adapter import INSTALL_HINT
from ptcg_activegraph.sim.local_runner import LocalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=10, help="number of self-play games")
    parser.add_argument("--deck", type=str, default="deck.csv", help="deck file")
    parser.add_argument("--out", type=str, default="data/matches/events.jsonl",
                        help="event store JSONL path")
    parser.add_argument("--render", type=str, default=None, help="optional replay HTML path")
    parser.add_argument("--allow-missing", action="store_true",
                        help="exit 0 even if cabt is unavailable")
    args = parser.parse_args()

    deck = load_deck(args.deck)
    if not deck:
        print(f"Could not load a deck from {args.deck}. Need 60 integer card IDs.")
        return 2

    runner = LocalRunner(event_store=EventStore(args.out))
    if not runner.available():
        print("Local simulation unavailable.\n")
        print(INSTALL_HINT)
        return 0 if args.allow_missing else 1

    print(f"Running {args.games} self-play game(s) with deck '{args.deck}'...")
    results = runner.run_self_play(runtime_agent, deck, n_games=args.games)
    wins = sum(1 for r in results if r.get("result") == "win")
    print(f"Completed {len(results)} games. Recorded events to {args.out}.")
    print(f"Win-ish results: {wins} (interpretation depends on cabt outcome schema).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
