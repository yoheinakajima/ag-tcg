# Report Site ← ActiveGraph Run Ledger (Pass 7A, Part I)

This documents how the strategy-lab report (`data/site/*.html` and
`data/reports/activegraph_strategy_report.md`) now surfaces the **durable
ActiveGraph run ledger** built in Parts D/E, and the single principle that keeps
the report honest.

## Source-of-truth principle

> The ledger is the source of truth. The report is a *projection* of the ledger,
> never the other way round.

Every run/candidate/game/artifact/crash/timeout/heartbeat/metric/promotion is
persisted incrementally as an append-only event in
`data/activegraph/ptcg_ledger_events.jsonl` (with a runs index in
`ptcg_ledger_runs.json`). The report reads those events through the *same
adapter the runner writes with* and folds them into a summary. It does not
recompute, cache, or fabricate run state — if a number is in the report, it came
from a recorded event.

## How the report reads the ledger

`src/ptcg_activegraph/experiments/report.py`:

- `_load_run_ledger()` opens `ActiveGraphLedger(warn=False)` (the Part D
  adapter), calls `list_runs()`, and `inspect_run(run_id)` for each. The result
  is added to the `gather()` dict under the `run_ledger` key.
- `_run_ledger_html(data)` renders a "Durable run ledger" section near the top of
  `index.html`: one row per run with `run_id`, status, candidate count, game
  count, per-status game breakdown, and total event count.
- `_run_ledger_md(data)` renders the same table into the Markdown report.

Each `inspect_run` summary comes from `ag/inspect.py::summarize_run`, which folds
a run's events into: `status`, `event_count`, `events_by_type`,
`candidate_count`, `game_count`, `game_status_counts`, `artifact_paths`,
`last_heartbeat_at`, and first/last event timestamps.

## Graceful degradation

The report never hard-depends on the ledger:

- No ledger file / no runs ⇒ `_load_run_ledger()` returns `[]` and both
  renderers show a clear empty state ("No durable runs recorded yet").
- Any exception while reading the ledger is swallowed and treated as "no runs",
  so report generation can never be broken by a malformed or partially-written
  ledger. The rest of the report (rankings, event stream, lineage) is unaffected.

This mirrors the existing report convention: every section degrades to an
explicit empty state rather than failing or inventing data.

## Why "light"

Per the Pass 7A spec this is an intentionally light integration: it *surfaces*
the durable ledger as a first-class report source without restructuring the
existing two-stage ranking report. A future pass can add per-run drill-down
pages (game-level tables, artifact links, heartbeat timelines) on top of the
same `inspect_run` data already wired in here.
