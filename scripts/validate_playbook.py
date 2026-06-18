#!/usr/bin/env python3
"""Validate a playbook YAML file (ActiveGraph Pass 9).

Checks required fields, integer card ids, no invented ids (vs the confirmed set
and the card metadata when available), referenced ids present in the baseline
deck, serializable rules, and a producible report summary.

Usage:
    python scripts/validate_playbook.py playbooks/v2_kyogre_abomasnow.yaml
    python scripts/validate_playbook.py <playbook.yaml> --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.playbooks import load_playbook, validate_playbook
from ptcg_activegraph.playbooks.compiler import DEFAULT_BASELINE
from ptcg_activegraph.playbooks.compiler import _load_deck_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("playbook", help="path to a playbook YAML file")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE,
                        help="baseline run dir whose deck.csv ids are checked")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    playbook = load_playbook(args.playbook)
    deck_ids = _load_deck_ids(Path(args.baseline) / "deck.csv") or None
    result = validate_playbook(playbook, deck_ids=deck_ids)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Playbook: {args.playbook}")
        print(f"  valid={'PASS' if result.valid else 'FAIL'}")
        for e in result.errors:
            print(f"  ERROR: {e}")
        for w in result.warnings:
            print(f"  warn:  {w}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
