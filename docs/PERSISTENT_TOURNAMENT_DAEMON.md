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
3. Set the **schedule** to run every **20 minutes** (cron `*/20 * * * *`); leave the
   timezone at the **UTC** default. _(Pass 39: cadence changed from the original
   every-2-hours `0 */2 * * *`; the run signature is unchanged — see the Pass 39
   addendum for why the scheduled signal is now the 20/900 run signature, not tick
   spacing.)_
4. Set the **job timeout** to **~25 minutes** (unchanged). With the 20-min cadence
   the relationship is now **lease TTL (30 min) > job timeout (~25 min) > schedule
   interval (20 min) > `--max-seconds` (15 min)**: actual work (≤15 min) finishes
   inside the 20-min interval so normal ticks never overlap, and because the lease
   TTL (30 min) still exceeds the interval, a hung tick's lease keeps protecting the
   next run (which is *refused* rather than double-pushing). Do **not** change the
   lease TTL unless explicitly asked.
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

<!-- PASS38_ADDENDUM_START -->
## Pass 38 — Deployment incident addendum & soak status (OPS only)

> Internal diagnostics only. **NOT a Kaggle leaderboard.** **NO upload, NO submit, NO auto-submit, no new candidates, no root mutation.** The root "Start application" workflow stays not-started (frozen Kaggle entrypoint) — that is EXPECTED.

### What went wrong at publish (Pass 37) and the durable fixes
- **uv editable-install into the read-only Nix store** — the deploy build auto-runs `uv sync`, which editable-installed the root project and wrote `__editable__*.pth` into the read-only store → EACCES → build failed. **Fix:** `[tool.uv] package = false` (the worker puts `src/` on `sys.path` itself; no install needed). Do not add dependency-groups/default-groups.
- **uv cannot install deploy deps** — install deploy-only deps in the BUILD command with `python -m pip install --user --break-system-packages` so they land in the writable `.pythonlibs` (PYTHONUSERBASE).
- **bundled cabt env** — games run via `kaggle_environments.make("cabt")`; the cabt env ships INSIDE the `kaggle-environments==1.30.1` wheel, so that pin must be in the build command or every game errors (publish still succeeds → silent zero progress).
- **publish-success is decoupled from game-success** — a failing game is recorded `timeout`/`error` and never fails the tick; the worker exits non-zero only on top-level/storage/refused/conflict/lease errors. When debugging a publish failure, separate "does the run exit 0" from "do games progress".

### Pass 38 soak status (live)
- root `main.py`/`deck.csv` byte-identical to the frozen baseline + deploy config verified: **yes**
- controlled production tick: played **3** internal games, ledger **64 → 77** events, push self-verified: **yes**
- health checker (prod + local) healthy: **yes** (soft warnings: ['placement_sample_size'])
- scheduled production run observed yet: **no** (all 5 recorded ticks are manual/smoke; 5 classified manual — the deployment is published and ready but a real scheduled tick has not yet fired in the ledger/deployment logs)
- guardrails intact: held probe retained, special-pilot-only decks never scheduled, `auto_submit` refused, every event `no_upload=true`.

Detail: `data/reports/pass38_scheduled_deployment_ops_report.md`; runbook `docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md`; per-part artifacts `data/experiments/pass38_*.{json,md}`.
<!-- PASS38_ADDENDUM_END -->

<!-- PASS39_ADDENDUM_START -->
## Pass 39 — Scheduled-tick confirmation, 20-min cadence & candidate lifecycle v0 (OPS only)

> Internal diagnostics only. **NOT a Kaggle leaderboard.** **NO upload, NO submit, NO auto-submit, NO new candidates, NO root/tarball mutation.** The root "Start application" workflow stays not-started (frozen Kaggle entrypoint) — that is EXPECTED. Every new event carries `no_upload=true`.

### Cadence change (operator)
- The Scheduled Deployment cron changed from `0 */2 * * *` (every 2h) to **`*/20 * * * *` (every 20 min)**. The run command **signature is unchanged**: `tournament_deployment_tick.py --max-games 20 --max-seconds 900 --storage-backend replit_app_storage --production`.
- The 20-min interval (1200s) is now **shorter** than the 30-min lease TTL (1800s), so the old "scheduled ticks are ≥ TTL apart" spacing heuristic no longer holds. The authoritative scheduled signal is the **run signature (20/900)**; the lease (refuses concurrent ticks) + push-merge-by-`event_id` remain the safety nets. Lease TTL unchanged (do not change unless asked).

### Status this pass
- root/deploy safety preflight: **pass** (root byte-identical, auto_submit off, no upload/push/candidate-gen).
- scheduled-tick confirmation: **scheduled_tick_confirmed** — a real scheduled run with the 20/900 signature is present in the ledger/run metadata.
- prod health: **healthy** (0 hard failures; soft warning `placement_sample_size`).
- candidate lifecycle v0 (dry-run vs prod): 16 actions — **12 retain, 4 eligible_soft_probation, 0 quarantine**; 11 protected. `--apply` → **apply_skipped=true** (no safe evidence-backed mark: zero quarantines, soft-probation of under-sampled actives not opted in — churn with no benefit; probation is still schedulable). No lease taken, no push.
- scheduler-after-lifecycle audit: deterministic worklist, **0 never-schedule decks** queued, matches the persisted projection. Event/projection idempotency audit: all checks green (folding `CandidateStatusChanged` is deterministic + idempotent; a later registration replaces a mark).

Detail: `data/reports/pass39_candidate_lifecycle_report.md`; lifecycle spec `docs/TOURNAMENT_CANDIDATE_LIFECYCLE.md`; per-part artifacts `data/experiments/pass39_*.{json,md}`.
<!-- PASS39_ADDENDUM_END -->


<!-- PASS40_BENCHMARK_LANE_NOTE -->
## Pass 40 — public-reference benchmark lane (additive)

Pass 40 adds an `external_reference` **benchmark lane**: public Kaggle rule-based sample
agents registered on a SEPARATE ledger (`data/tournament/benchmark/benchmark_events.jsonl`)
and played against our schedulable candidates via `PublicBenchmark*` events. These
references are **benchmark opponents only** — never in our candidate pool, submission
queue, promotion, lifecycle, family-champion set, active-cap, mutation lineage, or any
"our best" ranking; the normal fold / scheduler / lifecycle never read the
`PublicBenchmark*` events, so folding is unbroken. Internal benchmark scores are NOT
Kaggle scores and NOT a strength claim. See `docs/PASS40_REFERENCE_AGENT_INTAKE.md` and
`data/reports/pass40_public_reference_agent_intake_report.md`.
