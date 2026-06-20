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
