#!/usr/bin/env python3
"""Plan the experiment batch: which candidates are testable now, by priority.

Reads ``experiments/experiment_plan.yaml`` + ``experiments/strategy_seams.yaml``,
annotates every candidate spec with its priority and whether it is testable in
the current environment, and prints the ordered plan. Emits ``IdeaGenerated``
events. Nothing is generated or run here.

Usage:
    python scripts/plan_experiments.py
    python scripts/plan_experiments.py --json
"""

from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, load_config
from ptcg_activegraph.experiments.generator import plan_candidates
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit plan as JSON")
    parser.add_argument("--no-events", action="store_true",
                        help="do not append IdeaGenerated events")
    args = parser.parse_args()

    config = load_config()
    plan = plan_candidates(config)

    if not args.no_events:
        store = EventStore(LAB_EVENTS_PATH)
        for item in plan:
            store.append(new_event(
                EventType.IdeaGenerated,
                payload={"branch_id": item["branch_id"], "seam_id": item["seam_id"],
                         "priority": item["priority"], "testable": item["testable"],
                         "reason": item["reason"]},
                tags=["experiment", "plan", item["track"]],
            ))

    if args.json:
        slim = [{k: v for k, v in item.items() if k != "spec"} for item in plan]
        print(json.dumps(slim, indent=2))
        return 0

    testable = [p for p in plan if p["testable"]]
    blocked = [p for p in plan if not p["testable"]]
    print(f"Experiment plan: {len(plan)} candidates "
          f"({len(testable)} testable, {len(blocked)} blocked)\n")
    print(f"{'PRI':>4}  {'TRACK':<7} {'BRANCH':<28} {'SEAM':<28} STATUS")
    print("-" * 92)
    for item in plan:
        status = "testable" if item["testable"] else f"BLOCKED: {item['reason']}"
        print(f"{item['priority']:>4}  {item['track']:<7} {item['branch_id']:<28} "
              f"{item['seam_id']:<28} {status}")
    print("\nNext: scripts/generate_candidates.py --limit N")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
