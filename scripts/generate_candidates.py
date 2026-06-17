#!/usr/bin/env python3
"""Generate candidate branches into isolated run directories.

For each testable candidate (highest priority first, up to ``--limit``):
  * policy candidates = baseline main.py + injected override block,
  * deck candidates   = baseline main.py + a validated 60-card deck variant.

Each lands in ``experiments/runs/<ts>_<branch_id>/`` with ``main.py``,
``deck.csv`` and ``branch.yaml``. The root ``main.py``/``deck.csv`` (v1 control)
are read-only here and never modified. Emits ``BranchCreated`` /
``DeckVariantBuilt`` / ``PolicyVariantBuilt`` events.

Usage:
    python scripts/generate_candidates.py --limit 8
    python scripts/generate_candidates.py --limit 12 --baseline-main main.py
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.experiments import branch as branch_mod
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT, load_config
from ptcg_activegraph.experiments.generator import (
    generate_deck_candidate,
    generate_policy_candidate,
    plan_candidates,
)
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=8,
                        help="max candidates to generate (by priority)")
    parser.add_argument("--baseline-main", default="main.py")
    parser.add_argument("--baseline-deck", default="deck.csv")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    config = load_config()
    store = EventStore(LAB_EVENTS_PATH)
    card_db = load_card_db()

    plan = [p for p in plan_candidates(config) if p["testable"]][: args.limit]
    if not plan:
        print("No testable candidates to generate.")
        return 0

    ts = branch_mod.timestamp()
    created = []
    for i, item in enumerate(plan):
        spec, track = item["spec"], item["track"]
        # Unique per-branch timestamp suffix keeps run dirs distinct.
        run_ts = f"{ts}_{i:02d}"
        try:
            if track == "policy":
                b = generate_policy_candidate(
                    spec, args.baseline_main, args.baseline_deck,
                    runs_root=args.runs_root, ts=run_ts,
                )
                ev_type = EventType.PolicyVariantCreated
            else:
                b = generate_deck_candidate(
                    spec, args.baseline_main, args.baseline_deck,
                    runs_root=args.runs_root, card_db=card_db, ts=run_ts,
                )
                ev_type = EventType.DeckVariantCreated
        except Exception as exc:  # noqa: BLE001
            print(f"  ! skipped {spec['branch_id']}: {exc}")
            continue

        store.append(new_event(
            EventType.ExperimentBranchCreated,
            payload={"branch_id": b.branch_id, "seam_id": b.seam_id,
                     "kind": b.kind, "run_dir": b.run_dir},
            tags=["experiment", track],
        ))
        store.append(new_event(
            ev_type,
            payload={"branch_id": b.branch_id, "run_dir": b.run_dir,
                     "hypothesis": b.hypothesis,
                     "deck_diff": b.deck_diff, "policy_diff": b.policy_diff},
            tags=["experiment", track],
        ))
        created.append(b)
        print(f"  + {b.kind:<7} {b.branch_id:<28} -> {b.run_dir}")

    print(f"\nGenerated {len(created)} candidate(s) under {args.runs_root}/")
    print("Next: scripts/run_experiment_batch.py --games 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
