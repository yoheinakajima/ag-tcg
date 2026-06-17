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
from ptcg_activegraph.experiments.ranker import RANKING_JSON
from ptcg_activegraph.experiments.runner import cabt_available, evaluate_candidate
from ptcg_activegraph.graph.event_store import EventStore


def _top_branch_ids(top: int) -> list[str]:
    """Read the broad ranking and return the top-N non-rejected branch ids."""
    if not RANKING_JSON.exists():
        return []
    try:
        ranked = json.loads(RANKING_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    ids = [e["branch_id"] for e in ranked if not e.get("rejected")]
    return ids[: max(0, int(top))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=5,
                        help="games per candidate vs the control (legacy alternating)")
    parser.add_argument("--games-per-seat", type=int, default=None,
                        help="seat-swap: play this many games as P0 AND as P1")
    parser.add_argument("--seat-swap", action="store_true",
                        help="balance first-/second-player advantage by swapping seats")
    parser.add_argument("--stage", choices=["broad", "focused", "pass4_scout"], default=None,
                        help="broad/pass4_scout = scout all runs; focused = only top ranked")
    parser.add_argument("--top", type=int, default=5,
                        help="for --stage focused: how many top-ranked candidates to confirm")
    parser.add_argument("--branch", action="append", default=[],
                        help="only run branches whose id contains this (repeatable)")
    parser.add_argument("--control-main", default="main.py")
    parser.add_argument("--control-deck", default="deck.csv")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    config = load_config()
    cap = int(config.setting("max_local_games_per_candidate", 20))

    # Resolve the seat schedule + per-candidate game budget.
    stage = args.stage
    games_per_seat = args.games_per_seat
    if stage == "focused" and games_per_seat is None:
        games_per_seat = 20
    if stage in ("broad", "pass4_scout") and games_per_seat is None and not args.seat_swap:
        games_per_seat = 5
    if games_per_seat is not None:
        games_per_seat = max(1, min(games_per_seat, cap))
    games = min(args.games, cap)

    if not cabt_available():
        print("cabt (kaggle_environments) unavailable — cannot evaluate. "
              "Install it to run local matches. No results fabricated.")
        return 2

    runs = list_runs(args.runs_root)
    selectors = list(args.branch)
    if stage == "focused":
        top_ids = _top_branch_ids(args.top)
        if not top_ids:
            print("No broad ranking found. Run the broad stage + rank_candidates first.")
            return 1
        # Always keep the control anchor in the focused stage for comparison.
        runs = [r for r in runs if any(tid in r.name for tid in top_ids)
                or "control" in r.name or "conservative_baseline" in r.name]
    elif selectors:
        runs = [r for r in runs if any(tok in r.name for tok in selectors)]
    if not runs:
        print(f"No candidate runs found under {args.runs_root}/. "
              "Run generate_candidates.py first.")
        return 1

    store = EventStore(LAB_EVENTS_PATH)
    card_db = load_card_db()
    if games_per_seat:
        budget = f"{games_per_seat}/seat ({2 * games_per_seat} total, seat-swap)"
    else:
        budget = f"{games} alternating"
    print(f"[{stage or 'default'}] Evaluating {len(runs)} candidate(s) "
          f"at {budget} vs control...\n")

    summary = []
    for run_dir in runs:
        b = load_branch_yaml(run_dir)
        if b is None:
            continue
        metrics = evaluate_candidate(
            b, args.control_main, args.control_deck,
            n_games=games, card_db=card_db, event_store=store,
            games_per_seat=games_per_seat, seat_swap=args.seat_swap, stage=stage,
        )
        wr = metrics.get("win_rate")
        wr_s = "-" if wr is None else f"{wr:.2f}"
        awr = metrics.get("adjusted_win_rate")
        awr_s = "-" if awr is None else f"{awr:.2f}"
        gate = "ok" if (metrics.get("package_ok") and metrics.get("smoke_ok")) else "GATE-FAIL"
        print(f"  {b.branch_id:<34} games={metrics.get('games_completed', 0):<3} "
              f"wr={wr_s:<5} adj={awr_s:<5} "
              f"seatΔ={metrics.get('seat_balance_delta')} "
              f"crashes={metrics.get('crashes')} [{gate}]")
        summary.append(metrics)

    nxt = ("scripts/rank_candidates.py --stage focused" if stage == "focused"
           else "scripts/rank_candidates.py --stage broad")
    print(f"\nEvaluated {len(summary)} candidate(s). Next: {nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
