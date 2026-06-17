#!/usr/bin/env python3
"""Resolve a real 60-card ``deck.csv`` from the best available source.

Search order: existing valid (non-placeholder) deck.csv -> Kaggle sample deck ->
provided deck files -> generated baseline from official card CSV. Fails loudly
with instructions if nothing usable is found (never invents card IDs).

Writes (on success): deck.csv, data/decks/resolved_deck.csv,
data/decks/resolved_deck_summary.json, and a deck.meta.json marker.

Usage:
    python scripts/resolve_deck.py [--root .] [--deck deck.csv] [--dry-run]
"""

from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.decks.resolve_deck import resolve_deck, write_resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to search")
    parser.add_argument("--deck", default="deck.csv", help="deck.csv path to write")
    parser.add_argument("--dry-run", action="store_true", help="resolve but do not write")
    args = parser.parse_args()

    card_db = load_card_db()
    card_db = card_db if len(card_db) > 0 else None

    result = resolve_deck(root=args.root, deck_path=args.deck, card_db=card_db)
    print(json.dumps(result.to_dict(), indent=2))

    if not result.ok:
        print("\nDECK UNRESOLVED. Next actions:")
        for line in result.errors:
            print(f"  {line}")
        return 1

    for note in result.notes:
        print(f"note: {note}")
    for warn in result.warnings:
        print(f"warning: {warn}")

    if args.dry_run:
        print("\n[dry-run] not writing files.")
        return 0

    written = write_resolved(result, root=args.root, deck_path=args.deck)
    print("\nWrote:")
    for k, v in written.items():
        print(f"  {k}: {v}")
    print(f"\nResolved deck from source: {result.source} "
          f"({len(result.card_ids)} cards, "
          f"{len(set(result.card_ids))} unique).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
