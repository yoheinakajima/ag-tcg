#!/usr/bin/env python3
"""Compile a playbook into a stdlib-only candidate run directory (Pass 9).

The candidate dir contains main.py (root agent + injected playbook rules),
deck.csv (copied from the baseline), playbook.yaml, branch.yaml and report.md.

Usage:
    python scripts/compile_playbook.py playbooks/v2_kyogre_abomasnow.yaml \
        --candidate-id playbook_v2_kyogre_abomasnow_v1
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from ptcg_activegraph.playbooks.compiler import (
    DEFAULT_BASELINE, DEFAULT_RUNS_ROOT, compile_playbook)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("playbook", help="path to a playbook YAML file")
    parser.add_argument("--candidate-id", required=True, help="candidate id")
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--hypothesis", default=None)
    args = parser.parse_args()

    run_dir = compile_playbook(
        args.playbook, args.candidate_id,
        runs_root=args.runs_root, baseline_dir=args.baseline,
        hypothesis=args.hypothesis,
    )
    print(f"compiled {args.candidate_id} -> {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
