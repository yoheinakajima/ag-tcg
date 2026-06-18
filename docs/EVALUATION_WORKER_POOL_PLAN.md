# Evaluation Worker-Pool Plan (Pass 7A, Part G)

**Status:** design document only. Nothing here is implemented in this pass. The
immediate, shipped deliverable for Pass 7A is the durable ActiveGraph-backed run
ledger (Parts D/E) plus the *optional, benchmark-validated* fast-import stub
(Part F). The persistent worker pool below is the recommended long-term
architecture, captured here so a future pass can build it deliberately.

---

## Why this document exists

A candidate evaluation is "play N games of `control` vs `candidate`, both seats".
The cost that dominates everything is **cabt / OpenSpiel cold-start**: the first
`kaggle_environments.make("cabt")` in a fresh interpreter pays a one-time
registration cost (~7-15s) before any game runs. Once warm, a single game
finishes in well under a second.

Every execution mode below is a different answer to one question: *how do we pay
that cold-start cost as few times as possible without letting a hung or crashing
game take down the whole batch?*

---

## Mode 1 — `in_process_fast_unsafe`

Run games in the orchestrator process, reusing one warm cabt import.

- **Fast:** cold-start paid once for the whole batch.
- **Unsafe:** a native crash inside cabt/OpenSpiel (C-level segfault) kills the
  orchestrator *silently* — the batch dies with no Python traceback and no
  partial results. A non-terminating game hangs the whole batch.
- **Verdict:** acceptable only for a *tiny* exploratory smoke (1-2 games) where a
  human is watching. **Never** for broad evaluation. This is the failure mode
  that motivated the durable ledger: in-process death loses everything not yet
  persisted.

## Mode 2 — `subprocess_per_game_safe_slow` (current safe baseline)

Fork a fresh subprocess per game; the parent enforces a wall-clock timeout and
classifies the child as completed / timeout / crashed from its exit status.

- **Safe:** a child segfault or hang is contained — the parent observes a
  non-zero exit or kills on timeout, records the outcome in the ledger, and moves
  on. This is what `experiments/durable_runner.py` drives today.
- **Slow:** every game pays the full cabt cold-start again (~7-15s/game), so a
  100-game evaluation spends almost all its wall-clock in repeated imports.
- **Verdict:** the proven, durable default. Correct but expensive.

## Mode 3 — `subprocess_per_game_fast_stub_candidate`

Mode 2, but each child first calls `enable_fast_cabt_import_stub()` (Part F) to
skip the heavy unused deps (`litellm` via the werewolf env, etc.) before
importing `kaggle_environments`.

- **Safe if validated:** still one subprocess per game, so crash/hang isolation
  is unchanged.
- **Faster:** the Pass 7A benchmark
  (`data/experiments/cabt_import_benchmark.json`) measured the stub cutting
  import from ~7.4s to ~1.6s (**~4.5x**) with an *identical* one-game result
  shape vs the normal import. Per-game cold-start still happens, but it is much
  cheaper.
- **Guardrail:** opt-in only. The stub self-validates (import + `make("cabt")` +
  one smoke game + shape compare) and rolls itself back to a normal import on any
  failure. Do **not** flip this on by default in the bulk runner until the
  benchmark has validated it in the target environment.
- **Verdict:** the cheapest *safe* win available right now. A good incremental
  step before building the worker pool.

## Mode 4 — `persistent_worker_pool_future` (recommended long-term)

A small pool of long-lived worker processes. Each worker imports cabt **once**
(ideally with the Mode 3 stub), then loops: receive a game spec from the parent,
play it, return the result.

- **Worker:** imports cabt once; then `while True: spec = recv(); send(play(spec))`.
- **Parent:** owns the game queue, hands specs to idle workers, and records every
  result into the durable ledger as it lands.
- **Heartbeat:** each worker emits a heartbeat (or updates its current
  `GameState.updated_at`) while a game is in flight. The parent watches it.
- **Hang/crash recovery:** if a worker misses its heartbeat past the stale
  threshold, or exits unexpectedly, the parent **kills the process group and
  restarts a fresh worker**, marks the in-flight game `stale`/`crashed` in the
  ledger, and re-queues it. One bad game costs one worker restart, not the batch.
- **Why best:** cold-start is paid `pool_size` times for the *entire* batch
  instead of once per game, while crash/hang isolation is preserved at the
  process boundary.
- **Cost:** the most complex to build correctly — IPC protocol, heartbeat
  bookkeeping, group-kill semantics, and re-queue idempotency. It depends on the
  durable ledger (already built) so that a re-queued game cleanly supersedes its
  stale attempt.

---

## Recommended sequencing

1. **Done (this pass):** durable ledger + resumable runner (Modes 1/2 already
   wired through `durable_runner.py`), and the validated import-stub building
   block (Mode 3's dependency).
2. **Next:** enable Mode 3 in the runner behind an explicit flag, after running
   `scripts/benchmark_cabt_import.py` in the target environment.
3. **Later:** build Mode 4 on top of the ledger, reusing the same
   `GameState`/heartbeat/stale machinery the resumable runner already uses.

## Ledger touchpoints (already in place)

The worker pool needs no new persistence model — it reuses what Parts D/E
already provide:

- `GameStarted` / heartbeat (`GameState.updated_at`) / `GameFinished` /
  `GameTimeout` / `GameCrashed` / `GameStale` events.
- `is_stale()` (default threshold `2 * timeout + 30s`) to decide when a worker is
  presumed dead.
- Resume semantics: completed games are skipped; stale games are re-queued only
  when retry is requested. A restarted worker's replacement game supersedes the
  stale attempt by `game_id`.
