#!/usr/bin/env python3
"""Inspect the available card database and role tags.

Loads cards from local CSV or cabt (if present), prints a summary and a few
sample records with their heuristic role tags.

Usage:
    python scripts/inspect_cards.py [--limit N] [--name NAME] [--csv PATH]
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sys.path side effect)
from ptcg_activegraph.cards import load_card_db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="sample records to show")
    parser.add_argument("--name", type=str, default=None, help="search by card name")
    parser.add_argument("--csv", type=str, default=None, help="extra CSV path to try first")
    args = parser.parse_args()

    db = load_card_db(extra_csv_paths=[args.csv] if args.csv else None)
    print(f"Card DB source: {db.source}")
    print(f"Total cards: {len(db)}")

    if len(db) == 0:
        print(
            "\nNo card data found. Provide one of:\n"
            "  data/cards/EN_Card_Data.csv\n"
            "  data/cards/JP_Card_Data.csv\n"
            "or install cabt so all_card_data() is available.\n"
            "See docs/CARD_AND_DECK_GRAPH.md."
        )
        return 0

    if args.name:
        matches = db.search_name(args.name)
        print(f"\n{len(matches)} match(es) for '{args.name}':")
        for rec in matches[: args.limit]:
            print(f"  {rec.get('card_id')}: {rec.get('name')} -> {rec.get('roles')}")
        return 0

    print(f"\nSample of {min(args.limit, len(db))} cards:")
    for rec in db.all()[: args.limit]:
        print(f"  {rec.get('card_id')}: {rec.get('name')} -> {rec.get('roles')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
