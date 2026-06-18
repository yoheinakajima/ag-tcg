#!/usr/bin/env python3
"""Durable, resumable evaluator CLI (Pass 7A Part E + Pass 7B Parts C/F/G/I).

Runs ONLY bounded, resumable evaluations that write per-game state to the
durable ActiveGraph ledger. It never launches an unbounded batch and never
uploads to Kaggle. Run from repo root.

Examples::

    # Plan a curated scout (Pass 7B Part F)
    python scripts/run_durable_eval.py --plan-only --stage pass7b_scout \\
        --runs-root experiments/runs_pass6 \\
        --control data/baselines/v2_kaggle_479_1_deck_energy_trim_light \\
        --games-per-seat 3 --seats 0,1 \\
        --candidate-id policy_effect_resolution_v3 \\
        --candidate-id policy_secret_box_safety_v1

    # Execute/resume bounded chunks with the fast import stub
    python scripts/run_durable_eval.py --run-id <id> --execute --subprocess \\
        --fast-import-stub --game-timeout-seconds 120 --max-games 12
    python scripts/run_durable_eval.py --run-id <id> --resume --subprocess \\
        --fast-import-stub --game-timeout-seconds 120 --max-games 12

    # Inspect / export / rank / dry-run queue
    python scripts/run_durable_eval.py --run-id <id> --status
    python scripts/run_durable_eval.py --run-id <id> --export-trace
    python scripts/run_durable_eval.py --run-id <id> --rank
    python scripts/run_durable_eval.py --run-id <id> --rank --queue-dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from ptcg_activegraph.experiments.durable_runner import DurableRunner


def _dummy_executor(game):
    """Synthetic game: completes instantly. For durability tests without cabt."""
    return {"completed": True, "candidate_won": True, "steps": 1, "error": None,
            "timeout": False, "dummy": True, "candidate_seat": game.seat,
            "fast_import_stub_enabled": False, "import_optimization_mode": "normal",
            "import_optimization_validated": None}


def _parse_seats(args) -> tuple[int, ...]:
    if args.seat_swap:
        return (0, 1)
    if args.seats:
        return tuple(int(s.strip()) for s in args.seats.split(",") if s.strip() != "")
    return (0, 1)


def _load_fixture_status(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    rows = data.get("results") or data.get("candidates") or []
    for row in rows:
        cid = row.get("candidate_id")
        if cid:
            out[cid] = row.get("status", "advisory")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Durable resumable evaluator (Pass 7B)")
    # actions
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--mark-stale", action="store_true")
    p.add_argument("--export-trace", action="store_true")
    p.add_argument("--rank", action="store_true")
    p.add_argument("--queue-dry-run", action="store_true")

    # planning / selection
    p.add_argument("--run-id", default=None)
    p.add_argument("--runs-root", default="experiments/runs_pass6")
    p.add_argument("--control", default="data/baselines/v2_kaggle_479_1_deck_energy_trim_light")
    p.add_argument("--stage", default="pass7_ledger_smoke")
    p.add_argument("--games-per-seat", type=int, default=1)
    p.add_argument("--seats", default=None, help="comma list, e.g. 0,1")
    p.add_argument("--seat-swap", action="store_true", help="use both seats (0,1)")
    p.add_argument("--limit-candidates", type=int, default=None)
    p.add_argument("--candidate-id", action="append", default=None,
                   help="branch_id (repeatable); curated selection")

    # execution
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--game-timeout-seconds", type=int, default=90)
    p.add_argument("--subprocess", action="store_true", help="use real cabt subprocess executor")
    p.add_argument("--fast-import-stub", action="store_true",
                   help="enable opt-in cabt fast-import stub in the per-game child")
    p.add_argument("--dummy", action="store_true", help="use synthetic instant games (no cabt)")
    p.add_argument("--retry-stale", action="store_true")
    p.add_argument("--skip-existing", action="store_true",
                   help="(default) skip already-completed games on execute/resume")

    # ranking / queue outputs
    p.add_argument("--fixture-gate", default="data/experiments/pass7b_fixture_gate.json")
    p.add_argument("--rank-json", default="data/experiments/pass7b_scout_ranking.json")
    p.add_argument("--rank-md", default="data/experiments/pass7b_scout_ranking.md")
    p.add_argument("--trace-out", default=None)

    args = p.parse_args(argv)
    runner = DurableRunner(fast_import_stub=args.fast_import_stub)
    executor = _dummy_executor if args.dummy else None  # None => real cabt executor

    if args.plan_only:
        run_id = runner.plan(
            runs_root=args.runs_root,
            control_dir=args.control,
            stage=args.stage,
            games_per_seat=args.games_per_seat,
            seats=_parse_seats(args),
            limit_candidates=args.limit_candidates,
            candidate_ids=args.candidate_id,
            runner_mode="dummy" if args.dummy else (
                "subprocess_per_game_fast_stub" if args.fast_import_stub
                else "subprocess_per_game"),
            cabt_timeout_seconds=args.game_timeout_seconds,
            run_id=args.run_id,
        )
        out = {"run_id": run_id, "planned": True}
        missing = getattr(runner, "_missing_candidate_ids", [])
        if missing:
            out["missing_candidate_ids"] = missing
        print(json.dumps(out))
        return 0

    if not args.run_id:
        p.error("--run-id is required for execute/resume/status/mark-stale/export/rank")

    if args.mark_stale:
        print(json.dumps({"marked_stale": runner.mark_stale(args.run_id)}))
        return 0
    if args.execute:
        out = runner.execute(args.run_id, max_games=args.max_games, executor=executor)
        print(json.dumps(out, default=str))
    if args.resume:
        out = runner.resume(args.run_id, max_games=args.max_games,
                            retry_stale=args.retry_stale, executor=executor)
        print(json.dumps(out, default=str))
    if args.status:
        print(json.dumps(runner.status(args.run_id), indent=2, default=str))
    if args.export_trace:
        out_path = args.trace_out or f"data/activegraph/artifacts/{args.run_id}/trace.jsonl"
        path = runner.ledger.export_trace(args.run_id, out_path)
        print(json.dumps({"trace": str(path)}))
    if args.rank:
        from ptcg_activegraph.experiments.ledger_ranking import write_ranking

        rank = write_ranking(
            args.run_id, args.rank_json, args.rank_md,
            ledger=runner.ledger,
            fixture_status=_load_fixture_status(args.fixture_gate),
        )
        print(json.dumps({"ranking_json": args.rank_json, "ranking_md": args.rank_md,
                          "candidates": len(rank["candidates"])}))
        if args.queue_dry_run:
            from ptcg_activegraph.experiments.dry_run_queue import build_dry_run_queue

            doc = build_dry_run_queue(args.run_id, rank, artifacts_root=runner.artifacts_root)
            print(json.dumps({"queue_path": "data/submission_queue.json",
                              "queued": doc["queued_candidate_count"],
                              "reason": doc["selection_reason"]}))
        return 0
    if args.queue_dry_run and not args.rank:
        p.error("--queue-dry-run requires --rank (queue is built from the ranking)")

    if not any([args.execute, args.resume, args.status, args.export_trace]):
        p.error("specify an action: --plan-only/--execute/--resume/--status/"
                "--mark-stale/--export-trace/--rank")
    return 0


if __name__ == "__main__":
    sys.exit(main())
