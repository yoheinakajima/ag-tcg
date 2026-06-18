#!/usr/bin/env python3
"""Extract per-seat submitted decks from raw Kaggle replay JSONs.

For every replay under ``data/meta_replays/raw/`` (or paths given on the CLI),
write ``data/meta_replays/decks/<episode>_p0_deck.csv`` and ``..._p1_deck.csv``
containing the 60 integer card ids each seat submitted at the deck-selection
step.

Hard rule: only ids actually present in the replay action are written. No id is
ever invented or inferred from card-name text.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"


def _iter_replays(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    if not RAW_DIR.exists():
        return []
    return sorted(
        p for p in RAW_DIR.glob("*.json") if not p.name.startswith("_")
    )


def extract_one(path: Path) -> dict:
    replay = load_replay(path)
    episode = replay.episode_id
    decks = replay.submitted_decks()
    written: list[str] = []
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    for seat, ids in sorted(decks.items()):
        out = DECKS_DIR / f"{episode}_p{seat}_deck.csv"
        out.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
        written.append(str(out.relative_to(REPO)))
    return {
        "source": str(path.relative_to(REPO) if path.is_relative_to(REPO) else path),
        "episode": episode,
        "seats": {str(s): {"count": len(ids), "unique": len(set(ids)),
                            "counts": dict(Counter(ids))}
                  for s, ids in decks.items()},
        "written": written,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("replays", nargs="*", help="explicit replay JSON paths")
    args = ap.parse_args(argv)

    replays = _iter_replays(args.replays)
    if not replays:
        print("No replays found under data/meta_replays/raw/ (nothing to extract).")
        return 0

    for path in replays:
        if not path.exists():
            print(f"skip (missing): {path}")
            continue
        result = extract_one(path)
        print(f"episode {result['episode']}: {len(result['written'])} deck(s) extracted")
        for seat, info in result["seats"].items():
            print(f"  seat {seat}: {info['count']} cards, {info['unique']} unique")
        for w in result["written"]:
            print(f"  -> {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
