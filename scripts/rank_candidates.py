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
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    metrics_list = []
    for run_dir in list_runs(args.runs_root):
        mpath = Path(run_dir) / "metrics.json"
        if not mpath.exists():
            continue
        try:
            metrics_list.append(json.loads(mpath.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    if not metrics_list:
        print("No metrics.json found. Run scripts/run_experiment_batch.py first.")
        return 1

    store = EventStore(LAB_EVENTS_PATH)
    ranked = rank(metrics_list, event_store=store)
    json_path, md_path = save_ranking(ranked)

    print(f"Ranked {len(ranked)} candidate(s):\n")
    for e in ranked:
        status = "REJECTED (" + "; ".join(e["reject_reasons"]) + ")" if e["rejected"] else "ok"
        sc = "-" if e.get("score") is None else f"{e['score']:.1f}"
        print(f"  #{e['rank']:<2} {e['branch_id']:<28} score={sc:<8} {status}")
    print(f"\nWrote {json_path} and {md_path}")
    print("Next: scripts/build_report_site.py ; scripts/queue_submissions.py --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
