# ActiveGraph (event-sourced lab core)

ActiveGraph is the architecture of the lab: an **append-only event log is the
source of truth**, and everything else is a recomputable projection over it.

If a standalone `activegraph` package/repo is available it should be integrated
here; this repo ships a **minimal, compatible** event-sourced core so the system
works standalone today.

## Event model

Each event is an immutable record (`src/ptcg_activegraph/graph/events.py`):

| Field | Meaning |
| --- | --- |
| `event_id` | unique id, e.g. `evt_ab12cd34ef56` |
| `event_type` | one of the types below |
| `timestamp` | unix time |
| `match_id` | match this event belongs to |
| `turn` | turn number (nullable) |
| `player` | player index (nullable) |
| `policy_version` | which runtime policy produced it |
| `deck_version` | which deck was in play |
| `payload` | type-specific dict |
| `parent_event_ids` | causal links to prior events |
| `tags` | free-form labels (e.g. `exception`, `fallback`) |

### Event types

```
MatchStarted            DeckLoaded               ObservationReceived
LegalOptionsProjected   BeliefStateProjected     CandidateActionGenerated
SearchStarted           SearchWorldSampled       SearchActionEvaluated
ActionChosen            ActionFallbackUsed       ActionApplied
TurnEnded               GameEnded                FailureTagged
RegimeSelected          PatchPlanCreated         ValidationRunStarted
ValidationRunFinished   PolicyPromoted           DeckPromoted
SubmissionPackaged      ReportGenerated
```

## Event store

`EventStore` (`graph/event_store.py`) is a JSONL append-only log, one JSON object
per line, default path `data/matches/events.jsonl`.

```python
from ptcg_activegraph.graph import EventStore, new_event, EventType

store = EventStore()                       # data/matches/events.jsonl
store.append(new_event(EventType.MatchStarted, match_id="m1"))
store.append_many([...])
store.load(match_id="m1")                   # list[Event]
store.query(event_type="GameEnded", tags=["loss"])
store.latest(EventType.TurnEnded)
```

* **Append** uses a best-effort POSIX `fcntl` advisory lock.
* **Concurrency caveat:** on platforms without `fcntl` (e.g. Windows),
  concurrent multi-process writes are **not yet safe**. Single-process or
  single-writer use is fine. (A future upgrade is per-process shard files merged
  on read.)
* Corrupt lines are skipped on load rather than crashing.

## Projections

Pure functions over an event list (`graph/projections.py`). No database.

* `MatchSummaryProjection` — per-match winner, turns, fallback count, failures.
* `FailureSummaryProjection` — aggregate failure tags + regimes.
* `DeckPerformanceProjection` — win/loss/draw and win rate per deck version.
* `PolicyPerformanceProjection` — win rate + fallback rate per policy version.

```python
from ptcg_activegraph.graph import MatchSummaryProjection
summary = MatchSummaryProjection.project(store.load())
```

`MatchGraph` (`graph/match_graph.py`) reconstructs a single match into navigable
per-turn steps (observation → legal frontier → candidates → chosen → outcome).

## The replay / fork / validate / promote loop

1. **Record** a match as events.
2. **Project** to find weaknesses; **classify** failures into regimes.
3. **Fork**: propose a `PatchPlan` (data, not code) limited to the regime's
   allowed seams.
4. **Validate**: replay/run the protocol's games with the change.
5. **Promote** only if the promotion rule's thresholds are met; emit
   `PolicyPromoted` / `DeckPromoted`.
6. **Report**: regenerate the Strategy report from the log.

## Integrating a real ActiveGraph

If an external ActiveGraph implementation is introduced, map our `Event` fields
onto its node/edge model (events as nodes, `parent_event_ids` as edges), and back
the `EventStore` interface (`append`/`load`/`query`/`latest`) with it. The
projection and regime layers consume only that interface, so they need no
changes.
