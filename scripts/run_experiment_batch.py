#!/usr/bin/env python3
"""Run local cabt evaluations for generated candidate branches.

For each branch under ``experiments/runs/`` (or those matching ``--branch``):
  1. package preflight (hard gate),
  2. one-game cabt smoke (hard gate),
  3. N games vs the immutable v1 control, alternating seats.

Writes ``metrics.json`` per branch and appends ActiveGraph events. One bad game
never aborts the batch. cabt is required; without it each branch is recorded as
``unavailable`` (no fabricated results).

Usage:
    python scripts/run_experiment_batch.py --games 5
    python scripts/run_experiment_batch.py --games 10 --branch policy_attack_heavy
"""

from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.experiments.branch import list_runs, load_branch_yaml
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT, load_config
from ptcg_activegraph.experiments.runner import cabt_available, evaluate_candidate
from ptcg_activegraph.graph.event_store import EventStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=5,
                        help="games per candidate vs the control")
    parser.add_argument("--branch", action="append", default=[],
                        help="only run branches whose id contains this (repeatable)")
    parser.add_argument("--control-main", default="main.py")
    parser.add_argument("--control-deck", default="deck.csv")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    config = load_config()
    games = min(args.games, int(config.setting("max_local_games_per_candidate", 20)))

    if not cabt_available():
        print("cabt (kaggle_environments) unavailable — cannot evaluate. "
              "Install it to run local matches. No results fabricated.")
        return 2

    runs = list_runs(args.runs_root)
    if args.branch:
        runs = [r for r in runs if any(tok in r.name for tok in args.branch)]
    if not runs:
        print(f"No candidate runs found under {args.runs_root}/. "
              "Run generate_candidates.py first.")
        return 1

    store = EventStore(LAB_EVENTS_PATH)
    card_db = load_card_db()
    print(f"Evaluating {len(runs)} candidate(s) at {games} games each vs control...\n")

    summary = []
    for run_dir in runs:
        b = load_branch_yaml(run_dir)
        if b is None:
            continue
        metrics = evaluate_candidate(
            b, args.control_main, args.control_deck,
            n_games=games, card_db=card_db, event_store=store,
        )
        wr = metrics.get("win_rate")
        wr_s = "-" if wr is None else f"{wr:.2f}"
        gate = "ok" if (metrics.get("package_ok") and metrics.get("smoke_ok")) else "GATE-FAIL"
        print(f"  {b.branch_id:<28} games={metrics.get('games_completed', 0):<3} "
              f"win_rate={wr_s:<5} attack={metrics.get('attack_rate')} "
              f"pass={metrics.get('pass_rate')} crashes={metrics.get('crashes')} [{gate}]")
        summary.append(metrics)

    print(f"\nEvaluated {len(summary)} candidate(s). Next: scripts/rank_candidates.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
