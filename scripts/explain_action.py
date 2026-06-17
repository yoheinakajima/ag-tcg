#!/usr/bin/env python3
"""Explain how the heuristic ranks the options in an observation.

Reads a JSON observation from a file (or stdin) and prints each option with its
score, matched keywords, and any recognized structured fields. Useful after
`record_schema.py` to see how the real cabt option schema maps to the heuristic.

Usage:
    python scripts/explain_action.py path/to/obs.json
    cat obs.json | python scripts/explain_action.py -
"""

from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401
from ptcg_activegraph.runtime.heuristic_policy import rank_options_with_reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obs", help="path to a JSON observation file, or '-' for stdin")
    args = parser.parse_args()

    if args.obs == "-":
        raw = sys.stdin.read()
    else:
        with open(args.obs, "r", encoding="utf-8") as f:
            raw = f.read()

    try:
        obs = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Could not parse JSON: {exc}")
        return 1

    rows = rank_options_with_reasons(obs)
    if not rows:
        print("No options found in observation (select missing/empty).")
        return 0

    print(f"{len(rows)} option(s), best first:\n")
    for r in rows:
        print(f"[{r['index']}] score={r['score']}")
        if r["matched"]:
            print(f"     matched: {r['matched']}")
        if r["fields"]:
            print(f"     fields:  {r['fields']}")
        print(f"     text:    {r['text_preview']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
