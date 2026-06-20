#!/usr/bin/env python3
"""Pass 37 — deployment-ready ONE-tick worker for the standing tournament engine.

This is the command a **Replit Scheduled Deployment** runs on a cadence. It wraps
the unchanged Pass 36 engine with a persistent-storage sync layer:

    acquire lease -> pull persistent state -> run ONE bounded tick
    -> rebuild projections -> reconcile vs remote -> push verified snapshot
    -> release lease

It treats ``data/tournament/`` as a disposable working copy. In **production** it
fails closed if persistent storage is unavailable (the deployment filesystem is
NOT durable). It NEVER uploads to Kaggle, NEVER submits, NEVER auto-submits, and
NEVER generates candidates. Do NOT use this as a long-running server — it runs one
bounded tick and exits.

Usage (local dev smoke):
  python scripts/tournament_deployment_tick.py --no-games --storage-backend local

Usage (scheduled deployment):
  python scripts/tournament_deployment_tick.py \
      --max-games 20 --max-seconds 900 \
      --storage-backend replit_app_storage --production
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

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
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
SMOKE_JSON = REPO / "data" / "experiments" / "pass37_deployment_tick_smoke.json"
SMOKE_MD = REPO / "data" / "experiments" / "pass37_deployment_tick_smoke.md"
ROOT_GUARDED = ("main.py", "deck.csv")


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def assert_root_unchanged() -> dict:
    """Refuse to run if the root Kaggle artifacts drifted from the baseline."""
    results = {}
    for fn in ROOT_GUARDED:
        root = REPO / fn
        base = BASELINE_DIR / fn
        same = root.is_file() and base.is_file() and filecmp.cmp(root, base, shallow=False)
        results[fn] = bool(same)
        if not same:
            raise RuntimeError(
                f"root {fn} is NOT byte-identical to the frozen baseline "
                f"{base.relative_to(REPO)}; refusing to run (root is immutable)."
            )
    return results


def rebuild_projections() -> dict:
    """Pure fold over the (possibly merged) local ledger — mirrors Pass 36."""
    from ptcg_activegraph.tournament import projections
    from ptcg_activegraph.tournament.ledger import TournamentLedger
    from ptcg_activegraph.tournament.pool import CandidatePool
    from ptcg_activegraph.tournament.scheduler import build_worklist

    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates:
        pool = CandidatePool.load()
    summary = projections.write_projections(pool, events, cfg)
    state = projections.build_scheduler_state(events, ranking=summary["ranked_ids"])
    worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    finished = ledger.finished_game_ids()
    worklist = [g for g in worklist if g.game_id not in finished]
    projections.write_scheduler_queue(worklist, cfg)
    return {
        "registered_candidates": len(pool.candidates),
        "ranked_top": summary["ranked_ids"][: cfg.top_bracket_size],
        "next_queue_size": len(worklist),
    }


def write_smoke(report: dict) -> None:
    SMOKE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Pass 37 — deployment tick smoke",
        "",
        f"- status: **{report.get('status')}**",
        f"- env: {report.get('env')}  backend: {report.get('backend')}  "
        f"prefix: {report.get('prefix')}",
        f"- production: {report.get('production')}  dry_run: {report.get('dry_run')}  "
        f"no_games: {report.get('no_games')}",
        f"- root byte-identical: {report.get('root_unchanged')}",
        f"- lease tick_id: {report.get('tick_id')}",
        f"- pulled keys: {report.get('pull', {}).get('count')}",
        f"- games_played: {report.get('games_played')}",
        f"- push status: {report.get('push', {}).get('status')}  "
        f"drift: {report.get('push', {}).get('drift')}  "
        f"verify_ok: {report.get('push', {}).get('verify', {}).get('ok')}",
        f"- no_upload: {report.get('no_upload')}  auto_submit: {report.get('auto_submit')}",
        "",
        "_Internal diagnostics only. NO Kaggle upload, NO submit, NO auto-submit, "
        "NO candidate generation. Deploy ONLY as a bounded Scheduled Deployment; "
        "production state MUST use persistent storage._",
    ]
    if report.get("error"):
        lines += ["", f"## error", "```", str(report["error"]), "```"]
    SMOKE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Run one deployment-ready tournament tick.")
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--max-seconds", type=int, default=None)
    ap.add_argument("--storage-backend", default=None,
                    help="local | replit_app_storage | memory")
    ap.add_argument("--storage-prefix", default=None)
    ap.add_argument("--env", default=None, help="dev | production")
    ap.add_argument("--production", action="store_true",
                    help="shorthand for --env production (fail closed on storage).")
    ap.add_argument("--dry-run", action="store_true",
                    help="do everything except upload the snapshot.")
    ap.add_argument("--no-games", action="store_true",
                    help="pull/rebuild/push without playing any games.")
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--pull-only", action="store_true")
    ap.add_argument("--ttl-seconds", type=int, default=lease_mod.DEFAULT_TTL_SECONDS)
    args = ap.parse_args()

    env = "production" if args.production else args.env
    settings = resolve_settings(env, args.storage_backend, args.storage_prefix)
    cfg = load_config()

    report: dict = {
        "schema": "pass37_deployment_tick_smoke_v1",
        "generated_at": time.time(),
        "status": "init",
        "env": settings["env"],
        "production": settings["production"],
        "backend": settings["backend"],
        "prefix": settings["prefix"],
        "dry_run": args.dry_run,
        "no_games": args.no_games,
        "pull_only": args.pull_only,
        "push_only": args.push_only,
        "no_upload": True,
        "auto_submit": False,
        "games_played": 0,
    }

    # -- hard guards (refuse before any work) ----------------------------- #
    try:
        assert_no_auto_submit(cfg)
        assert_no_kaggle_upload()
        report["root_unchanged"] = assert_root_unchanged()
    except (AutoSubmitRefusedError, RuntimeError) as exc:
        report["status"] = "refused"
        report["error"] = str(exc)
        write_smoke(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    # -- build backend (fail closed in production) ------------------------ #
    try:
        backend = get_storage_backend(
            env=settings["env"], backend=settings["backend"], prefix=settings["prefix"]
        )
    except (ProductionStorageError, StorageUnavailableError) as exc:
        report["status"] = "storage_unavailable"
        report["error"] = str(exc)
        write_smoke(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3

    # -- lease + work ----------------------------------------------------- #
    lease = None
    try:
        lease = lease_mod.acquire_lease(backend, ttl_seconds=args.ttl_seconds)
        report["tick_id"] = lease.tick_id

        if not args.push_only:
            report["pull"] = sync.pull_state(backend, TOURNAMENT_DIR)
        base_remote_hash = sync.remote_events_hash(backend)
        report["base_remote_hash"] = base_remote_hash

        if args.pull_only:
            report["status"] = "pulled"
        else:
            if not (args.no_games or args.dry_run or args.push_only):
                from ptcg_activegraph.tournament.runner import TournamentEngine
                engine = TournamentEngine(cfg=cfg)
                rec = engine.run_tick(
                    max_games=args.max_games, max_seconds=args.max_seconds
                )
                report["games_played"] = rec.get("games_played", 0)
                report["tick"] = {
                    k: rec.get(k) for k in
                    ("tick_id", "stop_reason", "planned", "games_played",
                     "next_queue_size", "totals")
                }
            report["rebuild"] = rebuild_projections()
            push = sync.push_state(
                backend, TOURNAMENT_DIR,
                base_remote_hash=base_remote_hash, tick_id=lease.tick_id,
                on_remote_drift=rebuild_projections, dry_run=args.dry_run,
            )
            # do not echo full file list into the smoke summary
            report["push"] = {k: push[k] for k in ("status", "drift", "verify")}
            report["push"]["uploaded_count"] = len(push.get("uploaded", []))
            report["status"] = "ok"
    except lease_mod.LeaseHeldError as exc:
        report["status"] = "lease_held"
        report["error"] = str(exc)
        write_smoke(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 4
    except sync.ConflictError as exc:
        report["status"] = "conflict"
        report["error"] = str(exc)
        write_smoke(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 5
    except Exception as exc:  # unexpected
        report["status"] = "error"
        report["error"] = f"{exc}\n{traceback.format_exc()}"
        write_smoke(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        if lease is not None:
            try:
                lease_mod.release_lease(backend, lease)
            except Exception:
                pass

    write_smoke(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
