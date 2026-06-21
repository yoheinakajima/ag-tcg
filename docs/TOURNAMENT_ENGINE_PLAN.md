# Standing ActiveGraph Tournament Engine — Plan (Pass 36, v0)

> Internal self-play diagnostics only. **NOT a Kaggle leaderboard** and not
> predictive of leaderboard placement. The engine performs **NO upload**, **NO
> auto-submit**, and creates **no new candidates** in v0.

## Why build *in*, not rebuild
Prior passes (pass30/33/34/35) re-implemented a one-off tournament each time and
emitted `passNN` summary events *after* the games ran. That pattern is now
deprecated. Pass 36 consolidates the proven substrate into a standing, reusable,
event-first engine:

- reuse the append-only `graph.EventStore` (fcntl-locked JSONL) as the durable record;
- reuse the cabt game runner (`run_meta_pool_eval._run_game` / `_outcome_for_seat`)
  through a subprocess-isolated worker;
- reuse immutable candidate tarballs and the existing validators;
- add only a thin tournament layer (pool, scheduler, ledger, runner, projections).

## Module map (`src/ptcg_activegraph/tournament/`)
| module | responsibility |
|---|---|
| `config.py` | `TournamentConfig` loaded from `data/tournament/config.yaml` (safe defaults; `auto_submit` can only be flipped by a literal `true`). |
| `pool.py` | `Candidate` model + `CandidatePool` (load/save/query) + lifecycle statuses. Tarballs immutable; status marks only. |
| `ledger.py` | `TournamentLedger` over `EventStore` at `data/tournament/events.jsonl`. Forces `no_upload=true`; **refuses** to emit `SubmissionUploaded`/`KaggleScoreUpdated`. |
| `artifacts.py` | Compressed per-game sidecars (zstd preferred, **gzip fallback** when zstd absent — recorded honestly) + sha256 + safe tarball extraction. |
| `scheduler.py` | Deterministic, bounded `build_worklist(pool, state, cfg)`. |
| `projections.py` | Pure fold of the event log into all projection files + `SchedulerState`. |
| `runner.py` | `TournamentEngine.run_tick()` — event-first, bounded, resumable. |

Scripts: `seed_tournament_pool.py`, `tournament_daemon_tick.py`,
`build_tournament_projections.py`, `run_pass36_engine_smoke.py`,
`_tournament_game_worker.py` (subprocess game worker).

## Event vocabulary (additive `EventType` members)
`TournamentEngineInitialized`, `TournamentTickStarted`, `TournamentTickFinished`,
`TournamentParticipantRegistered`, `GameScheduled`, `GameStarted`, `GameFinished`,
`MatchupFinished`, `TournamentRankingUpdated`, `CandidatePoolUpdated`,
`CandidateStatusChanged`, `CandidateNonInertnessMeasured`,
`TournamentProjectionUpdated`, `TournamentReportGenerated`.

Every game event carries: `event_id`, `timestamp`, `parent_event_ids`
(tick → schedule → start → finish chain), `tick_id`/`run_id`, `game_id`,
`tournament_id`, `candidate_a`/`candidate_b`, seat assignment, `result`
(win/loss/draw/invalid/timeout/error), `steps`, `elapsed_s`, artifact path +
sha256, and `no_upload=true`.

## Projection specs (all rebuildable from events alone)
`tournament_state.json`, `rankings.{json,md}` (adjusted win rate + Wilson 95% CI),
`matchups.csv`, `candidate_pool.{json,md}`, `lineage.{json,md}`,
`scheduler_queue.{json,md}`, `non_inertness.{json,md}` (parent-child evidence —
**no improvement claims**). Both inputs are event-sourced: results fold over
`GameFinished`, and the candidate **registry is reconstructed from
`TournamentParticipantRegistered` full snapshots** via `CandidatePool.from_events`
(every candidate registered once), so `build_tournament_projections.py` never
needs `candidate_pool.json` to rebuild (the seed file is only a pre-registration
fallback).

## Concurrency
`run_tick` holds a non-blocking `flock` single-run lock
(`data/tournament/.tick.lock`); an overlapping daemon invocation fails fast with
`TickInProgressError` rather than racing to schedule duplicate game ids.

## Candidate lifecycle
`active · held_probe · family_champion · portfolio_anchor · probation · retired ·
quarantined · special_pilot_only · invalid`. Schedulable = the first five.
Retired/quarantined/special/invalid are **never** scheduled. Special-pilot-only
entries (Toxic, Durant) are registered but excluded until a real pilot exists.

## Scheduler priority policy
1. validation/smoke gaps → 2. new/probation/held vs anchors → 3. parent-child
confirmation (seat-swapped) → 4. top-bracket round-robin (least-played first) →
5. exploration (fewest games) → 6. regression sentinels (none active in v0).
Tie-breakers: fewer matchup games, older last_played, lexicographic id,
deterministic seat alternation. Game ids embed a per-(pair,seat) sequence so
re-ticking never collides and resume never replays.

## Pool cap / retirement policy
Active soft cap 16, hard cap 24. Keep live/water control, portfolio references,
one champion per family, the held probe, and the immediate parent of any active
child. Retire grandparents unless champion/reference/held/submitted. Special-only
entries don't count toward the cap. Invalid entries are quarantined, never deleted.

## Deployment plan
One bounded tick = one `tournament_daemon_tick.py` invocation. A Replit Scheduled
Deployment (or a deployed loop calling the tick) runs it repeatedly. v0 is
file-backed under `data/tournament/`; a later version can swap in a real
`ag.adapter` backend behind the same interface. See
`docs/PERSISTENT_TOURNAMENT_DAEMON.md`.

## Caveats
- Internal scores ≠ Kaggle leaderboard.
- v0 does not generate candidates and does not auto-submit.
- Typed-lite (Pass 35) children are **not** a proven win-rate gain; the engine
  evaluates them but claims no promotion.
- Per-game subprocess re-imports cabt (isolation over throughput); a streamed
  batch worker is a future optimization.

## Pass 39 — candidate lifecycle manager v0 + 20-min cadence (OPS only)

> Internal diagnostics only. NO upload/submit/auto-submit, NO candidate generation, NO root/tarball mutation.

- `CandidatePool.from_events` now folds **`CandidateStatusChanged`** (additive, backward-compatible) in canonical `(timestamp, index)` order — registration replaces the snapshot, a status mark mutates `status`/`status_note`; unknown candidate ids and invalid statuses are ignored. Projections honor lifecycle marks **ledger-only** (no out-of-band pool edits).
- New module `src/ptcg_activegraph/tournament/lifecycle.py` (`evaluate_lifecycle`, `apply_lifecycle_plan` — `dry_run=True` default, Wilson 95% evidence) + CLI `scripts/run_tournament_lifecycle_manager.py`. Marks are emitted with `no_upload=true`; the apply path is hard-guarded (no-auto-submit, no-kaggle-upload, root byte-identical) and lease-protected; it short-circuits to `apply_skipped` when no safe mark applies (no lease, no push).
- Scheduler unchanged: `schedulable()` + defence-in-depth `blocked` set keep never-schedule decks out of the worklist. Cadence is now every 20 min (`*/20 * * * *`), signature 20/900 unchanged.
