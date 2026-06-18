---
name: ledger status projection
description: Run/game status in an event-sourced ledger is derived, not asserted — every state must be in the schema map or it silently vanishes from inspect.
---

# Event-ledger status projection invariants (Pass 7A durable runner)

The durable run ledger is event-sourced: `inspect_run`/`summarize_run` fold the
event stream into status via two maps in `ag/schema.py`
(`GAME_STATUS_BY_EVENT`, `RUN_STATUS_BY_EVENT`). Two invariants that bit us:

1. **Completion is derived from remaining work, never from "the current batch
   finished".** A capped (`max_games`) or resumable `execute` must inspect the
   remaining game states and only emit `ExperimentRunFinished` when nothing is
   left `planned`/`running`/`stale`; otherwise emit `ExperimentRunPartial`
   (status `partial`) and stay resumable.
   **Why:** the original code unconditionally set `completed` after the loop, so
   a 1-of-4-game pass falsely reported completed and corrupted the report's
   completed/partial distinction.
   **How to apply:** any new terminal/partial transition needs both the emit
   site (runner) and the `RUN_STATUS_BY_EVENT` entry.

2. **Every status an object can enter must have an event type in the map.**
   `mark_stale` emitted `GameStale`, but it was missing from `LEDGER_EVENT_TYPES`
   and `GAME_STATUS_BY_EVENT`, so stale games kept their prior (running) status
   in inspect — stale detection was invisible downstream.
   **How to apply:** when you add a lifecycle event, add it to `LEDGER_EVENT_TYPES`
   AND the relevant `*_STATUS_BY_EVENT` map, and add a regression test asserting
   `inspect_run(...)["...status_counts"]` reflects it. Tests that only check the
   on-disk game state file will NOT catch a missing schema-map entry.
