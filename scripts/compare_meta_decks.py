#!/usr/bin/env python3
"""Compare deck skeletons across multiple meta replays.

Reads every replay in a directory via ``analyze_meta_replay.analyze_replay``,
then reports, across the corpus:

* shared cards (numeric ids seen in many decks),
* divergent cards (ids unique to a single deck),
* per-deck coverage and unknown-id counts.

Honest about coverage: decks whose skeletons are ``partial`` (no deck array, or
cards without numeric ids) are reported as such and never back-filled. **Card
ids are never invented** — unknown ids are counted, not guessed.

Usage:
    python scripts/compare_meta_decks.py --replays-dir data/meta_replays
    python scripts/compare_meta_decks.py --replays-dir data/meta_replays --json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401
from analyze_meta_replay import analyze_replay


def _iter_replays(replays_dir: str | Path):
    d = Path(replays_dir)
    if not d.is_dir():
        return
    for path in sorted(d.glob("*.json")):
        if path.name.startswith("_"):
            continue
        yield path


def compare_decks(replays_dir: str | Path = "data/meta_replays") -> dict:
    analyses = []
    for path in _iter_replays(replays_dir):
        analyses.append(analyze_replay(path))

    per_deck = []
    id_doc_freq: Counter = Counter()  # how many decks each id appears in
    for a in analyses:
        if not a.get("ok"):
            per_deck.append({"replay": a["replay"], "coverage": "none",
                             "error": a.get("error")})
            continue
        sk = a["deck_skeleton"]
        ids = set(sk.get("card_ids", []))
        for cid in ids:
            id_doc_freq[cid] += 1
        per_deck.append({
            "replay": a["replay"],
            "coverage": sk.get("coverage"),
            "card_count": sk.get("card_count"),
            "unique_ids": len(ids),
            "unknown_id_cards": sk.get("unknown_id_cards", 0),
        })

    n_decks = sum(1 for a in analyses if a.get("ok"))
    shared = sorted(
        ([cid, n] for cid, n in id_doc_freq.items() if n >= 2 and n_decks >= 2),
        key=lambda kv: (-kv[1], kv[0]),
    )
    divergent = sorted(cid for cid, n in id_doc_freq.items() if n == 1)

    return {
        "replays_dir": str(replays_dir),
        "n_replays": len(analyses),
        "n_decks_with_ids": n_decks,
        "coverage": "empty" if not analyses else (
            "full" if all(d.get("coverage") == "full" for d in per_deck) else "partial"
        ),
        "shared_cards": [{"card_id": cid, "deck_count": n} for cid, n in shared],
        "divergent_cards": divergent,
        "per_deck": per_deck,
        "notes": (
            ["no replays present; comparison is empty (scaffolding only)"]
            if not analyses else
            ["card ids never invented; decks without numeric ids reported as partial"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replays-dir", default="data/meta_replays")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = compare_decks(args.replays_dir)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"replays={result['n_replays']} decks_with_ids={result['n_decks_with_ids']} "
              f"coverage={result['coverage']}")
        print(f"shared_cards={len(result['shared_cards'])} "
              f"divergent_cards={len(result['divergent_cards'])}")
        for n in result["notes"]:
            print(f"  - {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
