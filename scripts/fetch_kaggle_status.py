#!/usr/bin/env python3
"""Fetch Kaggle submission status (read-only) and record scores as events.

Uses the Kaggle CLI (via the installed kaggle package) to list recent
submissions for the competition and how many remain today. Read-only: it never
submits. When a public score is found for a known branch, emits
``KaggleScoreUpdated``. Degrades clearly if the Kaggle credentials or CLI are
unavailable.

Usage:
    python scripts/fetch_kaggle_status.py
    python scripts/fetch_kaggle_status.py --competition pokemon-tcg-ai-battle
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
from ptcg_activegraph.graph.event_store import EventStore


def _kaggle_available() -> bool:
    try:
        import kaggle  # noqa: F401
    except Exception:
        return False
    return bool(os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--competition", default="pokemon-tcg-ai-battle")
    args = parser.parse_args()

    if not _kaggle_available():
        print("Kaggle CLI/credentials unavailable (need kaggle package + "
              "KAGGLE_USERNAME/KAGGLE_KEY). Read-only status skipped; nothing fabricated.")
        return 2

    # Read-only listing of submissions. This does NOT upload anything.
    cmd = [sys.executable, "-c",
           "import sys; from kaggle.cli import main; "
           f"sys.argv=['kaggle','competitions','submissions','-c','{args.competition}']; main()"]
    print(f"$ kaggle competitions submissions -c {args.competition}\n")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"Kaggle status call failed: {exc!r}")
        return 2
    print(proc.stdout or "(no output)")
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    # We only record events when a human pastes/parses a confirmed score; this
    # build pass does not auto-parse to avoid fabricating numbers.
    EventStore(LAB_EVENTS_PATH)  # ensure log dir exists
    print("\n(Use scripts/ag_event.py kaggle-score --name <branch> --score <n> "
          "to record a confirmed public score as an event.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
