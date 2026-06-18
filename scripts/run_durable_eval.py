#!/usr/bin/env python3
"""Durable, resumable evaluator CLI (Pass 7A, Part E).

This pass uses it ONLY for tiny durability tests (max-games 1-2). It never runs a
full scout/focused batch. Run from repo root.

Examples::

    python scripts/run_durable_eval.py --plan-only \\
        --runs-root experiments/runs_pass6 \\
        --control data/baselines/v2_kaggle_479_1_deck_energy_trim_light \\
        --stage pass7_ledger_smoke --games-per-seat 1 --limit-candidates 1
    python scripts/run_durable_eval.py --run-id <id> --execute --max-games 1 \\
        --subprocess --game-timeout-seconds 90
    python scripts/run_durable_eval.py --run-id <id> --resume --max-games 2
    python scripts/run_durable_eval.py --run-id <id> --status
    python scripts/run_durable_eval.py --run-id <id> --mark-stale
"""

from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401

from ptcg_activegraph.experiments.durable_runner import DurableRunner


def _dummy_executor(game):
    """Synthetic game: completes instantly. For durability tests without cabt."""
    return {"completed": True, "candidate_won": True, "steps": 1, "error": None,
            "timeout": False, "dummy": True}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Durable resumable evaluator")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--mark-stale", action="store_true")

    p.add_argument("--run-id", default=None)
    p.add_argument("--runs-root", default="experiments/runs_pass6")
    p.add_argument("--control", default="data/baselines/v2_kaggle_479_1_deck_energy_trim_light")
    p.add_argument("--stage", default="pass7_ledger_smoke")
    p.add_argument("--games-per-seat", type=int, default=1)
    p.add_argument("--limit-candidates", type=int, default=None)
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--game-timeout-seconds", type=int, default=90)
    p.add_argument("--subprocess", action="store_true", help="use real cabt subprocess executor")
    p.add_argument("--dummy", action="store_true", help="use synthetic instant games (no cabt)")
    p.add_argument("--retry-stale", action="store_true")

    args = p.parse_args(argv)
    runner = DurableRunner()
    executor = _dummy_executor if args.dummy else None  # None => real cabt executor

    if args.plan_only:
        run_id = runner.plan(
            runs_root=args.runs_root,
            control_dir=args.control,
            stage=args.stage,
            games_per_seat=args.games_per_seat,
            limit_candidates=args.limit_candidates,
            runner_mode="dummy" if args.dummy else "subprocess_per_game",
            cabt_timeout_seconds=args.game_timeout_seconds,
            run_id=args.run_id,
        )
        print(json.dumps({"run_id": run_id, "planned": True}))
        return 0

    if not args.run_id:
        p.error("--run-id is required for --execute/--resume/--status/--mark-stale")

    if args.mark_stale:
        marked = runner.mark_stale(args.run_id)
        print(json.dumps({"marked_stale": marked}))
        return 0
    if args.status:
        print(json.dumps(runner.status(args.run_id), indent=2, default=str))
        return 0
    if args.execute:
        out = runner.execute(args.run_id, max_games=args.max_games, executor=executor)
        print(json.dumps(out, default=str))
        return 0
    if args.resume:
        out = runner.resume(
            args.run_id, max_games=args.max_games, retry_stale=args.retry_stale, executor=executor
        )
        print(json.dumps(out, default=str))
        return 0

    p.error("specify one of --plan-only/--execute/--resume/--status/--mark-stale")
    return 2


if __name__ == "__main__":
    sys.exit(main())
