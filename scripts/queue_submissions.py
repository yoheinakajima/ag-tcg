#!/usr/bin/env python3
"""Build the Kaggle submission queue from the latest ranking (dry-run by default).

Selects the top promotable candidates (those that passed every hard gate),
respects ``submission_queue.max_per_day`` and the daily limit, builds each
candidate's tarball, and writes ``data/submission_queue.json`` with the exact
command a human would run. With ``auto_submit_enabled: false`` (the default)
this NEVER uploads — it only prints the plan. Emits ``SubmissionQueued`` events.

Usage:
    python scripts/queue_submissions.py --dry-run
    python scripts/queue_submissions.py            # still dry-run unless plan allows upload
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.branch import list_runs, load_branch_yaml
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT, load_config
from ptcg_activegraph.experiments.queue import build_queue
from ptcg_activegraph.experiments.ranker import RANKING_JSON
from ptcg_activegraph.graph.event_store import EventStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="force dry-run (no upload) regardless of plan settings")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    if not RANKING_JSON.exists():
        print(f"No ranking at {RANKING_JSON}. Run scripts/rank_candidates.py first.")
        return 1
    ranked = json.loads(RANKING_JSON.read_text(encoding="utf-8"))

    config = load_config()
    runs_by_branch = {}
    for run_dir in list_runs(args.runs_root):
        b = load_branch_yaml(run_dir)
        if b:
            runs_by_branch[b.branch_id] = str(run_dir)

    store = EventStore(LAB_EVENTS_PATH)
    plan = build_queue(ranked, config, runs_by_branch, event_store=store)

    if args.dry_run:
        plan["mode"] = "DRY-RUN"
        plan["will_upload"] = False

    print(f"Submission queue ({plan['mode']}):")
    print(f"  auto_submit_enabled={plan['auto_submit_enabled']}  "
          f"require_manual_approval={plan['require_manual_approval_for_submit']}  "
          f"max_per_day={plan['max_per_day']}")
    if not plan["candidates"]:
        print("  (no promotable candidates — nothing queued)")
    for c in plan["candidates"]:
        print(f"\n  #{c['rank']} {c['branch_id']} (score={c['score']})")
        print(f"     tarball: {c['tarball']}")
        if c.get("package_error"):
            print(f"     PACKAGE ERROR: {c['package_error']}")
        print(f"     would run: {c['kaggle_command']}")
    print(f"\nWrote data/submission_queue.json. "
          f"{'NO UPLOAD (dry-run).' if not plan['will_upload'] else 'Upload ENABLED.'}")
    print("To actually submit (after enabling switches): scripts/submit_queue.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
