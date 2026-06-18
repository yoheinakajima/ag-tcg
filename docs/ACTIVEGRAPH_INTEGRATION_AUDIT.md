# ActiveGraph Integration Audit (Pass 7A)

This audit is the prerequisite for Part D. It records what ActiveGraph tooling is
actually available in this environment **before** any adapter is written, so we
reuse rather than rebuild, and so the fallback (if any) is honestly labeled.

Date: 2026-06-18. Method: `importlib.util.find_spec`, `pip show`, CLI probe, and a
recursive `find` over the repo and parent dirs.

## 1. Is the real `activegraph` package installed?

**No.** `importlib.util.find_spec("activegraph")` → `None`. `pip show activegraph`
returns nothing. There is no `activegraph` import available to Python.

## 2. Is `activegraph_labs` present?

**No.** `find_spec("activegraph_labs")` → `None`; `find_spec("active_graph")` →
`None`. `pip show activegraph-labs` returns nothing. A recursive `find . .. -maxdepth
4 -iname '*activegraph*'` finds **only this repo's own files** (no sibling
`../activegraph-labs` checkout):

- `src/ptcg_activegraph/` — our package (NOT the external one)
- `docs/ACTIVEGRAPH.md`, `docs/ACTIVEGRAPH_LABS_NOTES.md` — our design notes
- `data/activegraph/lab_events.jsonl` — our existing event stream
- `data/reports/activegraph_strategy_report.md` — our report
- `.agents/memory/activegraph-*.md` — our memory notes

## 3. Is an `activegraph` CLI available?

**No.** `which activegraph` → not found; `activegraph --help` / `inspect` /
`export-trace` / `fork` → command not found. No CLI subcommands to wrap.

## 4. What store URLs / storage patterns are supported?

There is no external ActiveGraph, so there is no documented store-URL format
(sqlite://, file://, etc.) to honor. The **only** storage pattern present is this
repo's homegrown event-sourced core:

- `src/ptcg_activegraph/graph/event_store.py` — `EventStore`: append-only **JSONL**,
  one JSON object per line, default `data/matches/events.jsonl`, best-effort POSIX
  `fcntl` advisory lock on append, corrupt lines skipped on load.
- `src/ptcg_activegraph/graph/events.py` — `Event` dataclass + `EventType` enum +
  `new_event()`. Fields: `event_id` (`evt_<hex>`), `event_type`, `timestamp`,
  `match_id`, `turn`, `player`, `policy_version`, `deck_version`, `payload`,
  `parent_event_ids`, `tags`; `to_dict`/`to_json`/`from_dict`.
- `src/ptcg_activegraph/graph/projections.py` — pure fold functions over an event
  list (match/failure/deck/policy summaries). No database.
- Existing stream on disk: `data/activegraph/lab_events.jsonl` (~698 KB).

## 5. What programmatic APIs exist for append / run / inspect / replay / fork / export?

From the homegrown core only:

| Need | Existing API |
| --- | --- |
| append event | `EventStore.append(Event)` / `append_many(iter)` (fcntl-locked) |
| load / filter | `EventStore.load(match_id=…)`, `query(event_type, tags, match_id)`, `latest(...)`, `count()` |
| construct event | `new_event(EventType, **fields)` |
| project / inspect | `projections.*Projection.project(events)`; `match_graph.MatchGraph` rebuilds one match |
| run id | **MISSING** — events key on `match_id`, there is no first-class `run_id` or per-run lifecycle (created/started/heartbeat/finished/failed) |
| replay / fork / export-trace | **MISSING** — no run-scoped export or fork helper exists |

So the event *substrate* (durable append + typed events + projections) exists and is
good; what is missing for Pass 7A is the **run-scoped ledger layer** (run lifecycle,
heartbeats, stale detection, per-run trace export, artifact registration).

## 6. Recommended database-backed storage pattern

There is no external DB integration to adopt. The recommended (and only available)
durable pattern is **append-only JSONL as the source of truth**, exactly as
`EventStore` already does, plus a small run-index JSON for O(1) run listing. SQLite
is intentionally NOT introduced: it would add a dependency and migration surface for
no benefit over locked-append JSONL at this scale, and the spec's fallback paths are
JSON/JSONL. If a real ActiveGraph with a documented store URL later appears, the
adapter's narrow interface (below) is the single seam to swap.

## 7. What to reuse instead of rebuilding

- **Reuse** `EventStore`'s locked append-only JSONL mechanism and the `Event` /
  `EventType` / `new_event` model as the persistence substrate.
- **Reuse** `projections.py` patterns for any roll-up the ledger inspect needs.
- **Reuse** the subprocess game runner (`experiments/runner.run_one_game_subprocess`
  + `_game_subprocess.py`) for Part E — it already does killable per-game subprocess
  with SIGTERM→SIGKILL process-group teardown and timeout→`timeout` result.
- **Do NOT** rebuild a parallel event framework, and do NOT introduce a new DB.

## 8. Compatibility wrapper needed

**Yes — a clearly-labeled FALLBACK adapter.** Because no real `activegraph` package
or CLI exists, Part D ships `src/ptcg_activegraph/ag/` exposing the narrow
`ActiveGraphLedger` interface required by the spec
(`create_run`/`append_event`/`heartbeat`/`inspect_run`/`export_trace`/`list_runs`/
`mark_artifact`). The adapter:

- probes for a real `activegraph` package/CLI at construction;
- if found, routes through it (narrow seam, no duplication);
- if not found (current state), uses the JSONL fallback and emits a one-time
  warning: **"Using fallback JSONL ledger, not real ActiveGraph."**
- fallback store paths (per spec, never `/tmp`):
  `data/activegraph/ptcg_ledger_events.jsonl` and
  `data/activegraph/ptcg_ledger_runs.json`; artifacts under
  `data/activegraph/artifacts/`.

This keeps the lab working today while leaving exactly one place to integrate a real
ActiveGraph later.
