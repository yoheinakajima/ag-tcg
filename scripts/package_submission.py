#!/usr/bin/env python3
"""Package (and preflight) the Kaggle submission tarball.

Runs strict preflight checks (main.py imports, agent returns a list, deck is 60
integers and not a placeholder), builds data/submissions/submission.tar.gz with
top-level-only files, inspects it, and prints its contents.

Usage:
    python scripts/package_submission.py --verify-only
    python scripts/package_submission.py
    python scripts/package_submission.py --main main.py --deck deck.csv \
        --out data/submissions/submission.tar.gz --include agent.py
    python scripts/package_submission.py --allow-placeholder   # NOT for scoring
"""

from __future__ import annotations

import argparse
import tarfile

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
                        help="run preflight checks without building the tarball")
    parser.add_argument("--allow-placeholder", action="store_true",
                        help="permit a placeholder deck (will likely fail scoring)")
    args = parser.parse_args()

    card_db = load_card_db()
    card_db = card_db if len(card_db) > 0 else None

    try:
        report = verify_submission_inputs(
            args.main, args.deck, card_db=card_db,
            allow_placeholder=args.allow_placeholder,
        )
        print("Preflight passed:")
        for k, v in report.items():
            print(f"  {k}: {v}")

        if args.verify_only:
            return 0

        out = build_submission(
            main_py=args.main,
            deck_csv=args.deck,
            out_path=args.out,
            extra_files=args.include,
            card_db=card_db,
            allow_placeholder=args.allow_placeholder,
        )
        print(f"\nBuilt submission: {out}")
        with tarfile.open(out, "r:gz") as tar:
            print("Tarball contents:")
            for info in tar.getmembers():
                print(f"  {info.name}  ({info.size} bytes)")
        return 0
    except SubmissionError as exc:
        print(f"Submission error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
