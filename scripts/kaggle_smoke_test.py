#!/usr/bin/env python3
"""Run a cabt/kaggle smoke test: one full self-play game with the runtime agent.

PASS means the environment built, the deck loaded, and a game completed. Any
failure prints a SPECIFIC status (not a generic message) so you know exactly
what to fix. Exits 0 on PASS, 1 on any FAIL.

Usage:
    python scripts/kaggle_smoke_test.py [--deck deck.csv] [--games 1]
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from main import agent as runtime_agent
from ptcg_activegraph.decks.deck_io import load_deck
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.sim.kaggle_smoke import run_smoke_test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", default="deck.csv")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--out", default="data/matches")
    args = parser.parse_args()

    deck = load_deck(args.deck)
    store = EventStore("data/matches/events.jsonl")

    result = run_smoke_test(
        runtime_agent, deck, games=args.games, out_dir=args.out, event_store=store
    )

    print(result.status)
    if result.detail:
        print(f"  detail: {result.detail}")
    if result.artifacts:
        print(f"  artifacts: {result.artifacts}")
    if result.error:
        print("  --- traceback ---")
        print(result.error)

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
