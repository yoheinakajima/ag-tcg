# Dashboard Data Contract (read-only)

This document defines the **read-only data contract** that a *separate* Replit Autoscale
dashboard app uses to read this core tournament app's production tournament state. It is
deliberately **non-secret**: it contains **no** bucket IDs, environment values, secrets,
tokens, deployment IDs, or credentials. Those are supplied only via the dashboard app's
own Secrets pane (see "Connection — names only" below) and never committed to any repo.

The dashboard is **read-only**. It must never write, delete, push, emit events, promote,
quarantine, submit, or upload. The deployed Scheduled Deployment is the single writer.

---

## Connection — names only (no values)

The dashboard resolves the bucket and prefix at runtime from its **own** environment
(set these in the dashboard app's Secrets, not here):

- `DEFAULT_OBJECT_STORAGE_BUCKET_ID` — name of the env var that holds the Object Storage
  bucket to read. (Value lives in Secrets; never in repo files.)
- `TOURNAMENT_STORAGE_PREFIX` — name of the env var that holds the read prefix. The core
  default is `tournament/v0`.

All object keys below are **relative to the prefix** (full key = `<prefix>/<relative-key>`).

---

## Read-only keys (relative to `TOURNAMENT_STORAGE_PREFIX`)

Top-level:

| relative key | content | format |
|---|---|---|
| `events.jsonl` | append-only tournament event ledger | JSON Lines (one event/line) |
| `candidate_pool.json` | candidate registry snapshot | JSON |
| `config.yaml` | engine config (bounded-tick budgets, caps, safety contract) | YAML |
| `storage_manifest.json` | integrity manifest (`event_count`, key digests) | JSON |

Projections (`projections/*.json` and companions):

| relative key | content |
|---|---|
| `projections/rankings.json` | internal self-play standings (per candidate) |
| `projections/rankings.md` | human-readable rankings |
| `projections/scheduler_queue.json` | upcoming worklist (pairings + priority) |
| `projections/candidate_pool.json` | pool projection |
| `projections/non_inertness.json` | typed-layer non-inertness diagnostics |
| `projections/lineage.json` | candidate lineage graph |
| `projections/matchups.csv` | head-to-head matchup matrix |
| `projections/tournament_state.json` | folded engine state snapshot |

Per-tick + per-game:

| relative key | content | note |
|---|---|---|
| `runs/*.json` | per-tick run summaries | small, safe to read |
| `games/*.json.gz` | per-game replay sidecars | **large, gzip — lazy-load single keys on demand only; never bulk-read** |

---

## Event shape (observed in the current ledger)

Each line of `events.jsonl` is a JSON object with these top-level fields:

```
{
  "event_id": "<id>",
  "event_type": "<type>",
  "timestamp": <float epoch seconds>,
  "match_id": <str|null>,
  "parent_event_ids": [<id>, ...],
  "payload": { ... type-specific ... },
  "tags": [<str>, ...],
  "deck_version": <str|null>,
  "policy_version": <str|null>,
  "player": <str|null>,
  "turn": <int|null>
}
```

Event types observed: `TournamentEngineInitialized`, `TournamentParticipantRegistered`,
`TournamentTickStarted`, `GameScheduled`, `GameStarted`, `GameFinished`,
`TournamentRankingUpdated`, `TournamentProjectionUpdated`, `TournamentTickFinished`,
`CandidateGenerated`, `CandidateValidationFinished`, `CandidateStatusChanged`.

Key payload fields by type (non-exhaustive):

- `GameFinished.payload`: `candidate_a`, `candidate_b`, `result` (`win`/`loss`/`draw`
  from `candidate_a`'s perspective, else invalid/error), `a_seat`, `game_id`, `run_id`,
  `no_upload` (always `true`); on failure may carry `timeout` / `error`.
- `TournamentTickStarted` / `TournamentTickFinished.payload`: `run_id` (a.k.a. `tick_id`),
  `games_played`, `no_upload`.
- `TournamentParticipantRegistered.payload`: `candidate_id`, `family_id`, `status`,
  `tarball_path`, and a nested `candidate` record (fingerprints shown as opaque digests).
- `CandidateStatusChanged.payload`: `candidate_id`, `from_status`, `new_status`.

> The dashboard should treat `result` from `candidate_a`'s perspective and flip it for
> `candidate_b`. Non-`win/loss/draw` results are runtime failures (invalid/timeout/error).

---

## Projection shapes (observed)

`projections/rankings.json`:

```
{
  "generated_at": "<ISO-8601>",
  "caveat": "Internal self-play diagnostics only. NOT a Kaggle leaderboard ...",
  "no_upload": true,
  "rankings": [
    {"candidate_id": "<id>", "family_id": "<fam>", "status": "<status>",
     "games": <int>, "wins": <int>, "losses": <int>, "draws": <int>,
     "invalid": <int>, "adj_win_rate": <float>,
     "wilson_low": <float>, "wilson_high": <float>}
  ]
}
```

`projections/scheduler_queue.json`:

```
{
  "generated_at": "<ISO-8601>",
  "no_upload": true,
  "count": <int>,
  "queue": [
    {"game_id": "<id>", "candidate_a": "<id>", "candidate_b": "<id>",
     "a_seat": <int>, "priority": <int>, "reason": "<scheduling-reason>"}
  ]
}
```

---

## Caveats (must surface in the dashboard)

- **Internal rankings only.** All standings are internal self-play diagnostics. They are
  **NOT** a Kaggle leaderboard and are **not** predictive of leaderboard placement.
- **No upload.** Every event carries `no_upload: true`; the engine never uploads/submits.
- **Sidecars are large.** `games/*.json.gz` are per-game replays — lazy-load individual
  keys on demand only. **Do not bulk-read `games/`.**
- **Read-only.** The dashboard never writes, deletes, pushes, emits, promotes,
  quarantines, submits, or uploads.
- **Not dashboard data.** `locks/` (lease/lock state), `.tick.lock`, and
  `conflict_report.json` are internal daemon coordination artifacts — do not read or
  surface them.
- **Eventual consistency.** Projections lag the ledger by up to one tick; cross-check
  `storage_manifest.json`'s `event_count` against `events.jsonl` length when integrity
  matters.
