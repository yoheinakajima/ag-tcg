#!/usr/bin/env python3
"""Rank evaluated candidates and write the ranking artifacts.

Reads every ``experiments/runs/*/metrics.json`` produced by the batch runner,
applies the transparent ranking (hard rejects for gate/crash/timeout failures,
soft score + diversity bonus for survivors), and writes
``data/experiments/latest_ranking.{json,md}``. Emits ``CandidateRanked`` events.

Usage:
    python scripts/rank_candidates.py
    python scripts/rank_candidates.py --runs-root experiments/runs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.branch import list_runs, load_branch_yaml
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT
from ptcg_activegraph.experiments.ranker import rank, save_ranking
from ptcg_activegraph.graph.event_store import EventStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["broad", "focused"], default="broad",
                        help="broad -> latest_ranking.*; focused -> focused_ranking.* "
                             "(only ranks candidates evaluated at that stage)")
    parser.add_argument("--min-games", type=int, default=None,
                        help="minimum completed games before a candidate is promotable")
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    metrics_list = []
    for run_dir in list_runs(args.runs_root):
        mpath = Path(run_dir) / "metrics.json"
        if not mpath.exists():
            continue
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        # The focused ranking only considers candidates actually re-evaluated in
        # the focused (high-game, seat-swap) stage, so stale broad metrics from
        # un-promoted candidates never dilute the confirmation board.
        if args.stage == "focused" and m.get("stage") != "focused":
            continue
        metrics_list.append(m)

    if not metrics_list:
        hint = ("Run the focused stage first: run_experiment_batch.py --stage focused"
                if args.stage == "focused"
                else "Run scripts/run_experiment_batch.py first.")
        print(f"No metrics.json for stage '{args.stage}'. {hint}")
        return 1

    # Sensible default minimum-game gate per stage.
    min_games = args.min_games
    if min_games is None:
        min_games = 30 if args.stage == "focused" else 8

    store = EventStore(LAB_EVENTS_PATH)
    ranked = rank(metrics_list, event_store=store, min_games=min_games)
    json_path, md_path = save_ranking(ranked, stage=args.stage)

    print(f"[{args.stage}] Ranked {len(ranked)} candidate(s) (min_games={min_games}):\n")
    for e in ranked:
        status = ("REJECTED (" + "; ".join(e["reject_reasons"]) + ")"
                  if e["rejected"] else e.get("label", "ok"))
        sc = "-" if e.get("score") is None else f"{e['score']:.1f}"
        print(f"  #{e['rank']:<2} {e['branch_id']:<34} score={sc:<8} {status}")
    print(f"\nWrote {json_path} and {md_path}")
    nxt = ("scripts/queue_submissions.py --dry-run ; scripts/build_report_site.py"
           if args.stage == "focused"
           else "run_experiment_batch.py --stage focused --top 5")
    print(f"Next: {nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
