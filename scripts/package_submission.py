#!/usr/bin/env python3
"""Package the Kaggle submission tarball.

Verifies main.py and deck.csv, then builds data/submissions/submission.tar.gz
containing exactly the runtime files.

Usage:
    python scripts/package_submission.py
    python scripts/package_submission.py --main main.py --deck deck.csv \
        --out data/submissions/submission.tar.gz --include agent.py
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.packaging.make_submission import (
    SubmissionError,
    build_submission,
    verify_submission_inputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=str, default="main.py")
    parser.add_argument("--deck", type=str, default="deck.csv")
    parser.add_argument("--out", type=str, default="data/submissions/submission.tar.gz")
    parser.add_argument("--include", action="append", default=[],
                        help="extra runtime file to include (repeatable)")
    parser.add_argument("--verify-only", action="store_true",
                        help="only verify inputs, do not build the tarball")
    args = parser.parse_args()

    # Use card metadata for richer (soft) deck checks when available.
    card_db = load_card_db()
    card_db = card_db if len(card_db) > 0 else None

    try:
        if args.verify_only:
            report = verify_submission_inputs(args.main, args.deck, card_db=card_db)
            print("Verification passed:")
            for k, v in report.items():
                print(f"  {k}: {v}")
            return 0

        out = build_submission(
            main_py=args.main,
            deck_csv=args.deck,
            out_path=args.out,
            extra_files=args.include,
            card_db=card_db,
        )
        print(f"Built submission: {out}")
        return 0
    except SubmissionError as exc:
        print(f"Submission error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
