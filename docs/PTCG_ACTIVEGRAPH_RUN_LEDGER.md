# PTCG ActiveGraph Run Ledger — Domain Ontology

This defines the domain ontology for the PTCG strategy lab expressed in ActiveGraph
terms: **objects** (nodes), **relations** (edges), and **events** (the immutable
facts that create/relate objects). The ledger event log / DB is the **source of
truth**; shell stdout/stderr is only a debug artifact and must never be treated as
authoritative.

See `docs/ACTIVEGRAPH_INTEGRATION_AUDIT.md` for why this runs on a clearly-labeled
JSONL fallback adapter (no real `activegraph` package is installed).

## Source-of-truth principle

Every durable fact is an appended event. Object state and relations are
**projections** folded from the event stream — never hand-edited. If a process dies,
its last persisted events define reality; whatever was only in stdout is discarded.
Per-run state files (`run_state.json`, `games/<id>.json`) are atomic-write caches of
those projections for fast resume, regenerable from the event log.

## Objects (nodes)

| Object | Identity | Notes |
| --- | --- | --- |
| `Baseline` | baseline_id (`v1`, `v2`) | v1=349.8/356.9 legacy; v2=479.1 active control (deck_energy_trim_light) |
| `Candidate` | candidate_id (branch_id) | a policy/deck/combo/chaos variant under `experiments/runs*/` |
| `DeckVersion` | deck_version | 60-card list identity used by a candidate/baseline |
| `PolicyVersion` | policy_version | scoring/policy override identity |
| `ExperimentRun` | run_id | one evaluation run; has lifecycle + heartbeats |
| `Game` | game_id | one cabt game: candidate vs control at a seat |
| `Fixture` | fixture_id | a recorded decision used as a legality gate |
| `Replay` | replay_id | an imported Kaggle replay |
| `MetricSet` | metric_set_id | computed metrics for a candidate/run |
| `Artifact` | artifact_id | a file on disk (result json, stdout log, html, tarball) |
| `Submission` | submission_id | a packaged candidate (queued; never auto-uploaded) |
| `StrategySeam` | seam_id | a policy seam family (plan-state, effect-resolution, …) |
| `FailureTag` | tag | a classified failure regime |
| `ReportPage` | page_id | a generated report/site page |

## Relations (edges)

- `candidate_uses_deck` — Candidate → DeckVersion
- `candidate_uses_policy` — Candidate → PolicyVersion
- `run_evaluates_candidate` — ExperimentRun → Candidate
- `game_belongs_to_run` — Game → ExperimentRun
- `game_compares_candidate_to_control` — Game → (Candidate, Baseline)
- `game_emits_metrics` — Game → MetricSet
- `replay_supports_failure_tag` — Replay → FailureTag
- `fixture_tests_policy` — Fixture → PolicyVersion
- `candidate_passes_fixture` — Candidate → Fixture
- `candidate_fails_fixture` — Candidate → Fixture
- `candidate_promoted_from_run` — Candidate → ExperimentRun
- `candidate_rejected_from_run` — Candidate → ExperimentRun
- `submission_packages_candidate` — Submission → Candidate
- `report_cites_artifact` — ReportPage → Artifact

Relations are derived from events (e.g. `GameFinished` with `run_id`+`game_id`
implies `game_belongs_to_run`); they are not stored independently.

## Events (immutable facts)

Lifecycle + evaluation events, each appended to the ledger:

- `ExperimentRunCreated`, `ExperimentRunStarted`, `ExperimentRunHeartbeat`,
  `ExperimentRunFinished`, `ExperimentRunFailed`
- `CandidateRegistered`, `CandidatePackageVerified`, `CandidateSmokeVerified`
- `FixtureGateStarted`, `FixtureGateFinished`
- `GamePlanned`, `GameStarted`, `GameHeartbeat`, `GameFinished`, `GameTimeout`,
  `GameCrashed`, `GameResultRecorded`
- `MetricsComputed`, `CandidateRanked`, `CandidatePromoted`, `CandidateRejected`
- `ArtifactRecorded`, `ReplayImported`, `ReportSiteGenerated`
- `SubmissionQueued`, `SubmissionUploaded`, `KaggleScoreUpdated`

### Event envelope

Every event carries:

| Field | Meaning |
| --- | --- |
| `event_id` | unique id, `evt_<hex>` |
| `run_id` | owning ExperimentRun (top-level grouping key) |
| `timestamp` | unix time (float) |
| `event_type` | one of the types above |
| object ids | e.g. `candidate_id`, `game_id`, `deck_version`, `submission_id` when applicable (in payload) |
| `payload` | type-specific dict (status, seat, duration, error_summary, metrics, …) |
| `artifact_paths` | repo-relative paths to files this event produced/cites |
| `parent_event_ids` | causal links (e.g. `GameFinished` → its `GameStarted`) |
| `tags` | free-form labels (`fallback`, `timeout`, `crash`, `control`, `chaos`) |

`run_id` is the new top-level grouping key (the homegrown `Event` keyed on
`match_id`; the ledger layer adds `run_id` in the payload/index so existing
projections keep working).

## Run lifecycle / status vocabulary

ExperimentRun: `planned → running → (completed | failed)`; heartbeats while running.
Game status: `planned → running → (completed | timeout | crashed | stale | skipped)`.
A `stale` game is a `running` game whose last update exceeds the stale threshold
(default `2 × timeout + 30s`) — the orchestrator died; `--resume` reconciles it.

## How this maps onto storage

- Events → `data/activegraph/ptcg_ledger_events.jsonl` (locked append-only).
- Run index → `data/activegraph/ptcg_ledger_runs.json` (fast `list_runs`).
- Per-run durable caches/artifacts →
  `data/activegraph/artifacts/runs/<run_id>/` (`run_state.json`, `games/<id>.json`,
  stdout/stderr/result logs, `candidates/<id>.json`).
- Exported trace → `data/activegraph/artifacts/<run_id>/trace.jsonl` (or chosen out).

Never `/tmp` as a source of truth.
