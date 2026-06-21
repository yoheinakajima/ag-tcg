#!/usr/bin/env python3
"""Pass 39 — candidate lifecycle manager (status-mark hygiene; ops only).

DEFAULT IS DRY-RUN. Evaluates the standing-tournament candidate pool against the
ledger evidence and writes a conservative lifecycle PLAN. With ``--apply`` it
writes ONLY safe, evidence-backed marks (quarantines; and under-sampled→probation
only when ``--allow-soft-probation`` is given) — otherwise it records
``apply_skipped=true`` and touches nothing.

It NEVER generates candidates, NEVER mutates the frozen root / tarballs, and NEVER
uploads/submits. The apply path reuses the Pass 37 safety envelope (hard guards →
lease → pull → emit → rebuild → push-merge-by-event_id → release → re-pull/health).

Usage:
  # dry-run plan against the live prod state (read-only pull):
  python scripts/run_tournament_lifecycle_manager.py --mode prod

  # apply safe marks (early soak: expect apply_skipped=true, no lease/push):
  python scripts/run_tournament_lifecycle_manager.py --mode prod --apply
"""
from __future__ import annotations

import argparse
import filecmp
import json
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402
from ptcg_activegraph.tournament import lifecycle as lc  # noqa: E402
from ptcg_activegraph.tournament import projections, sync  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    AutoSubmitRefusedError,
    ProductionStorageError,
    StorageUnavailableError,
    assert_no_auto_submit,
    assert_no_kaggle_upload,
    get_storage_backend,
    resolve_settings,
)

TOURNAMENT_DIR = REPO / "data" / "tournament"
BASELINE_DIR = REPO / "data" / "baselines" / "v1_kaggle_349_8"
ROOT_GUARDED = ("main.py", "deck.csv")


def assert_root_unchanged() -> dict:
    """Refuse to run if the frozen Kaggle root artifacts drifted from baseline."""
    results = {}
    for fn in ROOT_GUARDED:
        root, base = REPO / fn, BASELINE_DIR / fn
        same = root.is_file() and base.is_file() and filecmp.cmp(root, base, shallow=False)
        results[fn] = bool(same)
        if not same:
            raise RuntimeError(
                f"root {fn} is NOT byte-identical to the frozen baseline; refusing "
                "to run (root is immutable).")
    return results


def _load_pool_and_events() -> tuple[CandidatePool, list]:
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates:
        pool = CandidatePool.load()
    return pool, events


def rebuild_projections() -> dict:
    """Pure fold over the (possibly merged) local ledger — mirrors Pass 36/37."""
    cfg = load_config()
    pool, events = _load_pool_and_events()
    summary = projections.write_projections(pool, events, cfg)
    state = projections.build_scheduler_state(events, ranking=summary["ranked_ids"])
    worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    finished = TournamentLedger().finished_game_ids()
    worklist = [g for g in worklist if g.game_id not in finished]
    projections.write_scheduler_queue(worklist, cfg)
    return {"registered_candidates": len(pool.candidates),
            "schedulable": pool.active_count(),
            "next_queue_size": len(worklist)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the candidate lifecycle manager.")
    ap.add_argument("--mode", choices=["prod", "local"], default="prod")
    ap.add_argument("--apply", action="store_true",
                    help="write safe marks (default: dry-run plan only).")
    ap.add_argument("--allow-soft-probation", action="store_true",
                    help="opt-in to applying under-sampled active -> probation.")
    ap.add_argument("--storage-backend", default=None,
                    help="local | replit_app_storage | memory")
    ap.add_argument("--storage-prefix", default=None)
    ap.add_argument("--output-prefix", default="data/experiments/pass39_lifecycle")
    ap.add_argument("--no-pull", action="store_true",
                    help="evaluate the local working dir without pulling first.")
    ap.add_argument("--ttl-seconds", type=int, default=lease_mod.DEFAULT_TTL_SECONDS)
    args = ap.parse_args()

    dry_run = not args.apply
    env = "production" if args.mode == "prod" else "dev"
    settings = resolve_settings(env, args.storage_backend, args.storage_prefix)
    cfg = load_config()
    out_json = Path(f"{args.output_prefix}_{'plan' if dry_run else 'apply'}.json")
    out_md = Path(f"{args.output_prefix}_{'plan' if dry_run else 'apply'}.md")

    report: dict = {
        "schema": "pass39_lifecycle_run_v1",
        "generated_at": time.time(),
        "status": "init",
        "mode": args.mode,
        "env": settings["env"],
        "backend": settings["backend"],
        "prefix": settings["prefix"],
        "dry_run": dry_run,
        "allow_soft_probation": args.allow_soft_probation,
        "no_upload": True,
        "auto_submit": False,
    }

    # -- hard guards (refuse before any work) ----------------------------- #
    try:
        assert_no_auto_submit(cfg)
        assert_no_kaggle_upload()
        report["root_unchanged"] = assert_root_unchanged()
    except (AutoSubmitRefusedError, RuntimeError) as exc:
        report["status"] = "refused"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    # -- backend (fail closed in production) ------------------------------ #
    try:
        backend = get_storage_backend(env=settings["env"], backend=settings["backend"],
                                      prefix=settings["prefix"])
    except (ProductionStorageError, StorageUnavailableError) as exc:
        report["status"] = "storage_unavailable"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3

    try:
        # Read-only pull so we evaluate against authoritative persistent state.
        if not args.no_pull:
            report["pull"] = sync.pull_state(backend, TOURNAMENT_DIR)

        pool, events = _load_pool_and_events()
        plan = lc.evaluate_lifecycle(pool, events, cfg)

        # ---- DRY-RUN: just write the plan, no lease, no push ------------- #
        if dry_run:
            apply_result = lc.apply_lifecycle_plan(
                plan, pool, TournamentLedger(), events,
                dry_run=True, allow_soft_probation=args.allow_soft_probation)
            lc.write_lifecycle_report(
                plan, out_json=out_json, out_md=out_md, apply_result=apply_result,
                mode=args.mode, backend=settings["backend"],
                header="Candidate Lifecycle PLAN (dry-run)",
                extra={"run": report})
            report["status"] = "planned"
            report["apply_skipped"] = apply_result["apply_skipped"]
            print(json.dumps({k: report[k] for k in report
                              if k not in ("root_unchanged", "pull")}, indent=2))
            print(f"lifecycle plan: actions={plan['summary']['action_counts']} "
                  f"apply_skipped={apply_result['apply_skipped']}")
            return 0

        # ---- APPLY: short-circuit if nothing safe applies --------------- #
        applicable = [a for a in plan["actions"]
                      if lc._applicable(a, args.allow_soft_probation)]
        if not applicable:
            apply_result = lc.apply_lifecycle_plan(
                plan, pool, TournamentLedger(), events,
                dry_run=False, allow_soft_probation=args.allow_soft_probation)
            lc.write_lifecycle_report(
                plan, out_json=out_json, out_md=out_md, apply_result=apply_result,
                mode=args.mode, backend=settings["backend"],
                header="Candidate Lifecycle APPLY (skipped — no safe marks)",
                extra={"run": report})
            report["status"] = "apply_skipped"
            report["apply_skipped"] = True
            print(json.dumps({k: report[k] for k in report
                              if k not in ("root_unchanged", "pull")}, indent=2))
            print("lifecycle apply: apply_skipped=true (no lease, no push)")
            return 0

        # ---- APPLY: full safety envelope (lease -> emit -> push) --------- #
        lease = None
        try:
            lease = lease_mod.acquire_lease(backend, ttl_seconds=args.ttl_seconds)
            report["tick_id"] = lease.tick_id
            report["pull2"] = sync.pull_state(backend, TOURNAMENT_DIR)
            base_remote_hash = sync.remote_events_hash(backend)
            pool, events = _load_pool_and_events()
            plan = lc.evaluate_lifecycle(pool, events, cfg)
            apply_result = lc.apply_lifecycle_plan(
                plan, pool, TournamentLedger(), events,
                dry_run=False, allow_soft_probation=args.allow_soft_probation)
            pool.save()
            report["rebuild"] = rebuild_projections()
            push = sync.push_state(
                backend, TOURNAMENT_DIR, base_remote_hash=base_remote_hash,
                tick_id=lease.tick_id, on_remote_drift=rebuild_projections)
            report["push"] = {k: push[k] for k in ("status", "drift", "verify")}
            report["status"] = "applied"
            report["apply_skipped"] = apply_result["apply_skipped"]
        finally:
            if lease is not None:
                try:
                    lease_mod.release_lease(backend, lease)
                except Exception:
                    pass

        # Re-pull so the working dir mirrors what we just pushed.
        report["pull3"] = sync.pull_state(backend, TOURNAMENT_DIR)
        lc.write_lifecycle_report(
            plan, out_json=out_json, out_md=out_md, apply_result=apply_result,
            mode=args.mode, backend=settings["backend"],
            header="Candidate Lifecycle APPLY", extra={"run": report})
        print(json.dumps({k: report[k] for k in report
                          if k not in ("root_unchanged", "pull", "pull2", "pull3")},
                         indent=2))
        print(f"lifecycle apply: applied={apply_result['applied_count']} "
              f"apply_skipped={apply_result['apply_skipped']}")
        return 0

    except lease_mod.LeaseHeldError as exc:
        report["status"] = "lease_held"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 4
    except sync.ConflictError as exc:
        report["status"] = "conflict"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 5
    except Exception as exc:  # unexpected
        report["status"] = "error"
        report["error"] = f"{exc}\n{traceback.format_exc()}"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
