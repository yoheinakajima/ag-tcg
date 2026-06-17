#!/usr/bin/env python3
"""Run a round-robin tournament among agent/deck entrants.

Requires cabt. Without it, prints the planned schedule and exits.

Usage:
    python scripts/run_tournament.py --deck deck.csv --games 2
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from agent import agent as runtime_agent
from ptcg_activegraph.decks.deck_io import load_deck
from ptcg_activegraph.sim.tournament import Entrant, round_robin


def _random_agent(obs):
    """A trivial baseline opponent: always the fallback-legal first choice."""
    from main import fallback  # reuse the self-contained fallback

    return fallback(obs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", type=str, default="deck.csv")
    parser.add_argument("--games", type=int, default=1, help="games per pair")
    args = parser.parse_args()

    deck = load_deck(args.deck)
    if not deck:
        print(f"Could not load deck from {args.deck}.")
        return 2

    entrants = [
        Entrant("heuristic_v1", runtime_agent, deck),
        Entrant("fallback_baseline", _random_agent, deck),
    ]
    result = round_robin(entrants, games_per_pair=args.games)

    if not result.available:
        print("cabt unavailable. Planned schedule:")
        for a, b in result.schedule:
            print(f"  {a} vs {b}")
        print(f"\nNote: {result.note}")
        return 0

    print("Tournament records:")
    for name, rec in result.records.items():
        print(f"  {name}: {rec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
