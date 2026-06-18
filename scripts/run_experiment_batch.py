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
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.cards import load_card_db
from ptcg_activegraph.experiments.branch import list_runs, load_branch_yaml
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT, load_config
from ptcg_activegraph.experiments.ranker import (
    PASS5_SCOUT_RANKING_JSON,
    PASS6_SCOUT_RANKING_JSON,
    RANKING_JSON,
    is_control_entry,
)
from ptcg_activegraph.experiments.runner import cabt_available, evaluate_candidate
from ptcg_activegraph.graph.event_store import EventStore


def _top_branch_ids(top: int, source_json: Path = RANKING_JSON) -> list[str]:
    """Read a scout ranking and return the top-N non-rejected CANDIDATE ids.

    Controls and anchors (v2 active control, v1 legacy baseline, integrity
    anchors) are excluded from the top-N — they are baselines, not candidates.
    """
    if not source_json.exists():
        return []
    try:
        ranked = json.loads(source_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    ids = [e["branch_id"] for e in ranked
           if not e.get("rejected") and not is_control_entry(e)]
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
    parser.add_argument("--stage",
                        choices=["broad", "focused", "pass4_scout",
                                 "pass5_scout", "pass5_focused",
                                 "pass6_scout", "pass6_focused"], default=None,
                        help="broad/pass4_scout/pass5_scout/pass6_scout = scout "
                             "all runs; focused/pass5_focused/pass6_focused = "
                             "only top-N candidates (controls always kept)")
    parser.add_argument("--top", type=int, default=5,
                        help="for --stage focused: how many top-ranked candidates to confirm")
    parser.add_argument("--branch", action="append", default=[],
                        help="only run branches whose id contains this (repeatable)")
    parser.add_argument("--only-branch", action="append", default=[],
                        help="only run the branch with EXACTLY this id (repeatable)")
    parser.add_argument("--subprocess", dest="subprocess", action="store_true",
                        default=True,
                        help="run each game in a killable child process (default)")
    parser.add_argument("--no-subprocess", dest="subprocess", action="store_false",
                        help="run games in-process (legacy SIGALRM watchdog only)")
    parser.add_argument("--game-timeout-seconds", type=int, default=90,
                        help="per-game wall-clock budget; a child exceeding it is "
                             "killed and the game recorded as a timeout (default 90)")
    parser.add_argument("--skip-existing", "--resume", dest="skip_existing",
                        action="store_true",
                        help="skip branches that already have metrics.json (resume)")
    parser.add_argument("--control-main", default="main.py")
    parser.add_argument("--control-deck", default="deck.csv")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    config = load_config()
    cap = int(config.setting("max_local_games_per_candidate", 20))

    # Resolve the seat schedule + per-candidate game budget.
    stage = args.stage
    games_per_seat = args.games_per_seat
    if stage in ("focused", "pass5_focused", "pass6_focused") and games_per_seat is None:
        games_per_seat = 20
    if (stage in ("broad", "pass4_scout", "pass5_scout", "pass6_scout")
            and games_per_seat is None and not args.seat_swap):
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
    if stage in ("focused", "pass5_focused", "pass6_focused"):
        source = {
            "pass6_focused": PASS6_SCOUT_RANKING_JSON,
            "pass5_focused": PASS5_SCOUT_RANKING_JSON,
        }.get(stage, RANKING_JSON)
        top_ids = _top_branch_ids(args.top, source_json=source)
        if not top_ids:
            print(f"No scout ranking at {source}. Run the scout stage + "
                  "rank_candidates first.")
            return 1
        # Always keep the control/anchor branches in the focused stage so the v2
        # active control is co-evaluated as the comparison baseline.
        runs = [r for r in runs if any(tid in r.name for tid in top_ids)
                or "control" in r.name or "conservative_baseline" in r.name
                or "anchor" in r.name]
    elif args.only_branch:
        wanted = set(args.only_branch)
        kept = []
        for r in runs:
            b = load_branch_yaml(r)
            if b is not None and b.branch_id in wanted:
                kept.append(r)
        runs = kept
    elif selectors:
        runs = [r for r in runs if any(tok in r.name for tok in selectors)]

    if args.skip_existing:
        before = len(runs)
        runs = [r for r in runs if not (r / "metrics.json").exists()]
        skipped = before - len(runs)
        if skipped:
            print(f"--skip-existing: skipping {skipped} branch(es) with metrics.json.")

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
    runmode = (f"subprocess (kill >{args.game_timeout_seconds}s)"
               if args.subprocess else "in-process (SIGALRM)")
    print(f"[{stage or 'default'}] Evaluating {len(runs)} candidate(s) "
          f"at {budget} vs control [{runmode}]...\n")

    summary = []
    for run_dir in runs:
        b = load_branch_yaml(run_dir)
        if b is None:
            continue
        metrics = evaluate_candidate(
            b, args.control_main, args.control_deck,
            n_games=games, card_db=card_db, event_store=store,
            games_per_seat=games_per_seat, seat_swap=args.seat_swap, stage=stage,
            use_subprocess=args.subprocess,
            game_timeout_seconds=args.game_timeout_seconds,
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
