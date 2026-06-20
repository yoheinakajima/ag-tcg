# Persistent Tournament Daemon — Operations (Pass 36, v0)

> Internal diagnostics only. **NOT a Kaggle leaderboard.** **NO upload, NO
> auto-submit, no candidate generation** in v0.

The "daemon" is just a **bounded tick** invoked repeatedly. There is no
long-lived in-process loop (native cabt can hang or leak state), so each tick is
self-contained, crash-safe, and resumable.

## Run one tick locally
```bash
# seed the canonical pool once (idempotent; reads existing tarballs only)
python scripts/seed_tournament_pool.py

# play a bounded tick
python scripts/tournament_daemon_tick.py --max-games 50 --max-seconds 900
```
Re-running is always safe: finished games are durable on the ledger and are
**not** replayed. If the shell (or a background process) is killed mid-tick, just
run the tick again — completed games persist, partial games are simply rescheduled.

**One tick at a time.** `run_tick` takes a non-blocking `flock` single-run lock
(`data/tournament/.tick.lock`). If a scheduled run fires while a previous tick is
still going, the new invocation fails fast with `TickInProgressError` instead of
racing to schedule duplicate games — so it's safe to schedule ticks generously.

## How a Replit deployed/scheduled environment should call it
- Use a **Scheduled Deployment** (or a deployed service that calls the tick on an
  interval). Each scheduled run executes exactly one bounded tick and exits.
- Keep `--max-seconds` comfortably below the scheduled job's time limit.
- Do **not** convert the root `Start application` workflow into this loop — that
  workflow is the Kaggle agent entrypoint, not a server. Create a separate
  console workflow if you want a local recurring tick.

## Scheduled Deployment setup — exact 10 steps (Pass 37)
> Internal diagnostics only. **NO upload, NO submit, NO auto-submit, no candidate
> generation.** Deploy ONLY as a Replit *Scheduled Deployment* bounded tick.
> Regenerate this guidance any time with
> `python scripts/print_replit_scheduled_deployment_config.py` (writes
> `data/experiments/pass37_scheduled_deployment_config.{json,md}`).

1. Open the **Publishing** (Deployments) tool in this Repl.
2. Choose deployment type = **Scheduled Deployment** (NOT Autoscale, NOT Reserved
   VM / Always-on, NOT Static).
3. Set the **schedule** to run every **2 hours** (cron `0 */2 * * *`); leave the
   timezone at the **UTC** default.
4. Set the **job timeout** to **~25 minutes** — keep it **below the 30-min lease
   TTL** so the lease always outlives a tick (invariant: interval > TTL > job
   timeout). The run command caps work at `--max-seconds 900` = 15 min,
   comfortably below the timeout.
5. Set the **build command** (Replit's nix Python is externally-managed, so use
   `--user --break-system-packages`, which installs into the writable
   `.pythonlibs` the runtime keeps on `sys.path`). `kaggle-environments` ships
   the bundled `cabt` game env that the per-game subprocess drives, so it must be
   installed for real games to run (its absence does not fail the tick — games
   just degrade to errors). `pyproject.toml` sets `[tool.uv] package = false` so
   the automatic `uv sync` no longer tries to editable-install the root package
   into the read-only Nix store (that was the original build failure: EACCES on
   `__editable__.ptcg_activegraph-0.1.0.pth`):
   ```bash
   python -m pip install --user --break-system-packages replit-object-storage pyyaml kaggle-environments==1.30.1
   ```
6. Set the **run command** (one bounded tick; fails closed without persistent
   storage):
   ```bash
   python scripts/tournament_deployment_tick.py --max-games 20 --max-seconds 900 --storage-backend replit_app_storage --production
   ```
7. **Secrets:** none are required for tournament-only operation. Do **NOT** add
   Kaggle credentials — there is no upload/submit. (Only a hypothetical future
   read-only score refresh would ever read `KAGGLE_USERNAME`/`KAGGLE_KEY`, and
   only read-only.)
8. Click **Run Now** once to execute a single tick immediately and validate the
   end-to-end pull → lease → tick → reconcile → push flow.
9. Inspect the **Scheduled Deployment logs**, then the synced projections
   (`data/tournament/projections/rankings.md`) to confirm progress; verify the
   logs show `no_upload=true` and no auto-submit.
10. If the run **failed**, fix the cause and **republish**; never enable
    auto-submit, never upload, and never convert this into an always-on server.

## Expected state files (`data/tournament/`)
- `config.yaml` — budgets, caps, safety flags.
- `candidate_pool.json` — canonical pool (status marks only; tarballs immutable).
- `events.jsonl` — **primary durable record** (event-first).
- `games/<game_id>.json.{zst|gz}` — per-game trace sidecars (+ sha256 on the event).
- `projections/` — `tournament_state.json`, `rankings.{json,md}`, `matchups.csv`,
  `candidate_pool.{json,md}`, `lineage.{json,md}`, `scheduler_queue.{json,md}`,
  `non_inertness.{json,md}`.
- `runs/<tick_id>.json` — per-tick run record.

## Stop / resume
- **Stop:** let the current tick finish, or kill it; nothing else to do.
- **Resume:** run the tick again. The scheduler reads completed games from the
  ledger and schedules only new game ids.

## Inspect rankings
```bash
python scripts/build_tournament_projections.py   # rebuild from events (idempotent)
cat data/tournament/projections/rankings.md
cat data/tournament/projections/scheduler_queue.md
```

## Reset production data (only if explicitly needed)
v0 is file-backed. To reset, remove `data/tournament/events.jsonl`,
`data/tournament/games/`, `data/tournament/projections/`, and
`data/tournament/runs/` (the candidate pool and tarballs are kept). Rebuild with
`seed_tournament_pool.py` + `build_tournament_projections.py`. **Never** delete
tarballs and **never** touch root `main.py`/`deck.csv`.

## Storage note
Dev and deployed environments may use different storage. v0 deliberately uses
file-backed `data/tournament/`. A later version can move the ledger behind the
real `ag.adapter` backend without changing the engine interface.

## Production storage durability (Pass 37)
**Do not rely on the deployment filesystem; production state must use persistent
storage.** A Scheduled Deployment's local filesystem is **NOT durable** across
runs — anything written only to `data/tournament/` on a deployed run can vanish
before the next tick. In production the primary state (`events.jsonl`,
`projections/`, `runs/`, `games/`, `candidate_pool.json`, `storage_manifest.json`)
**MUST** live in persistent storage (Replit App / Object Storage); the local
`data/tournament/` directory is only a disposable per-run working dir
(pull → tick → rebuild → reconcile → push → release lease). The
`--production --storage-backend replit_app_storage` worker **fails CLOSED** when
persistent storage is unavailable, so it never silently writes throwaway state to
the deployed disk.
