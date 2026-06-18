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
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.experiments import branch as branch_mod
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT, load_config
from ptcg_activegraph.experiments.generator import (
    generate_combo_candidate,
    generate_deck_candidate,
    generate_policy_candidate,
    plan_candidates,
    plan_generation2,
    plan_pass4,
    plan_pass5,
)
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=8,
                        help="max candidates to generate (by priority)")
    parser.add_argument("--generation", type=int, choices=[1, 2], default=1,
                        help="1 = priority single-seam plan; 2 = control + "
                             "single-seam confirmations + combination candidates")
    parser.add_argument("--group", choices=["pass4", "pass5_replay_policy"], default=None,
                        help="pass4 = replay-derived effect-resolution + chaos "
                             "scout batch; pass5_replay_policy = replay-informed "
                             "board-aware candidates over the v2 deck "
                             "(both override --generation)")
    parser.add_argument("--no-optional-combos", action="store_true",
                        help="generation 2: skip the optional (non-required) combos")
    parser.add_argument("--baseline-main", default="main.py")
    parser.add_argument("--baseline-deck", default="deck.csv")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    config = load_config()
    store = EventStore(LAB_EVENTS_PATH)
    card_db = load_card_db()

    if args.group == "pass4":
        full_plan = plan_pass4(config)
    elif args.group == "pass5_replay_policy":
        full_plan = plan_pass5(config)
    elif args.generation == 2:
        full_plan = plan_generation2(config, include_optional=not args.no_optional_combos)
        full_plan = full_plan[: args.limit] if args.limit and args.limit > 0 else full_plan
    else:
        full_plan = [p for p in plan_candidates(config) if p["testable"]][: args.limit]

    # Blocked items (e.g. Pass 4 chaos archetypes) are recorded honestly but not
    # generated: a legal deck cannot be built without inventing card ids.
    blocked = [p for p in full_plan if not p.get("testable", True)]
    plan = [p for p in full_plan if p.get("testable", True)]
    if not plan and not blocked:
        print("No testable candidates to generate.")
        return 0

    if blocked:
        blocked_records = [
            {"branch_id": p["branch_id"], "seam_id": p["seam_id"],
             "track": p["track"], "reason": p.get("reason", ""),
             "hypothesis": p["spec"].get("hypothesis", ""),
             "core_card_ids": p["spec"].get("core_card_ids", [])}
            for p in blocked
        ]
        out = Path("data/experiments/pass4_blocked_candidates.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(blocked_records, indent=2), encoding="utf-8")
        for rec in blocked_records:
            store.append(new_event(
                EventType.IdeaGenerated,
                payload={"branch_id": rec["branch_id"], "seam_id": rec["seam_id"],
                         "status": "blocked", "reason": rec["reason"]},
                tags=["experiment", "pass4", "chaos", "blocked"],
            ))
            print(f"  ~ BLOCKED {rec['branch_id']:<34} {rec['reason'][:60]}")
        print(f"  (wrote {out})")

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
            elif track == "combo":
                b = generate_combo_candidate(
                    spec, args.baseline_main, args.baseline_deck,
                    runs_root=args.runs_root, card_db=card_db, ts=run_ts,
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
