# Tournament Candidate Lifecycle (Pass 39 · v0)

**Internal diagnostics only. NOT a Kaggle leaderboard. NO upload, NO submit, NO
auto-submit, NO candidate generation, NO tarball mutation/deletion.** Lifecycle is
expressed purely as a candidate **status mark** in the no-upload event ledger.
Tarballs are immutable and never deleted.

This document defines the candidate lifecycle policy enforced by
`src/ptcg_activegraph/tournament/lifecycle.py` and the operator CLI
`scripts/run_tournament_lifecycle_manager.py`.

## Statuses

Defined in `src/ptcg_activegraph/tournament/pool.py`.

| status | schedulable? | meaning |
|---|---|---|
| `active` | yes | normal participant; counts toward the active cap |
| `held_probe` | yes | retained probe held for evidence (protected) |
| `family_champion` | yes | current best-known of a strategy family (protected) |
| `portfolio_anchor` | yes | reference anchor kept for portfolio coverage (protected) |
| `probation` | yes | still scheduled, flagged as under-evidenced |
| `retired` | **no** | gracefully removed from scheduling; kept for lineage |
| `quarantined` | **no** | removed due to hard-failure evidence (invalid/timeout/error) |
| `special_pilot_only` | **no** | only ever run under a manual pilot, never auto-scheduled |
| `invalid` | **no** | failed validation/entrypoint; never scheduled |

- **SCHEDULABLE**: `{active, held_probe, family_champion, portfolio_anchor, probation}`
- **NEVER_SCHEDULE**: `{retired, quarantined, special_pilot_only, invalid}`

## Protected candidates (never demoted)

A candidate is **protected** — the lifecycle manager will never propose demoting or
quarantining it — when ANY of the following hold:

1. its status is one of `{held_probe, family_champion, portfolio_anchor, special_pilot_only}`;
2. it carries a protected tag: `{live_control, water_family_current_best, manual_hold}`;
3. it is the **immediate parent of an `active` child** (lineage protection — a parent
   whose typed child is still being evaluated is kept available as the comparison
   control).

Protection only blocks *demotion*. It is not a schedule guarantee and never forces a
status change of its own.

## Rules v0 (conservative, evidence-based)

Evidence is folded purely from `GameFinished` events (Wilson 95% interval on
decisive games). The placement threshold is
`config.min_placement_games_per_candidate` (default **20**).

1. **Quarantine** — `schedulable & not protected → quarantined`. Hard-failure
   evidence ONLY. Triggers when:
   - the candidate played ≥ `QUARANTINE_MIN_INVALID_ONLY` (3) games, ALL
     invalid/timeout/error, with **zero** decisive results (`all_invalid_no_decisive`); or
   - invalid-rate ≥ `QUARANTINE_INVALID_RATE` (0.5) over ≥ `QUARANTINE_MIN_GAMES` (4)
     games (`high_invalid_rate`).

   This is the **only** status change that is auto-applied (`--apply` without extra
   opt-in), because it removes a broken candidate that wastes tick budget.

2. **Soft probation** — `active → probation` when the active is **under-sampled**
   (games < placement threshold). This is **proposed** in dry-run as
   `eligible_soft_probation` but is **NOT auto-applied**. In early soak every active
   is under-sampled, so demoting them all is churn with no benefit (`probation` is
   still schedulable). Applying it requires the explicit `--allow-soft-probation`
   operator opt-in.

3. **Retain** — everything else (no-op; emits no event). `never_schedule` statuses
   are left untouched. **v0 has NO promotion authority** — promotions (e.g.
   `probation → active`, or crowning a new `family_champion`) are out of scope and
   handled elsewhere.

## Apply semantics & honesty guarantees

- **Default is dry-run.** `--apply` is required to write anything.
- **Idempotent.** No event is emitted when `old_status == new_status`. Because
  `CandidateStatusChanged` is reconciled by unique `event_id` (it is not a per-game
  lifecycle event in `sync.py`), correctness relies on this old-vs-new check.
- **apply_skipped.** When no safe, applicable, non-idempotent mark exists (the
  early-soak default: zero quarantines and soft-probation not opted-in), the run
  writes `apply_skipped=true`, acquires **no lease**, and performs **no push** — it
  does not touch persistent storage.
- **Emitted event:** `CandidateStatusChanged` with payload
  `{candidate_id, old_status, new_status, status_note, reason, action,
  evidence_summary, protected_override:false, pass:"39", no_upload:true}`,
  parented to the candidate's latest registration (and latest `GameFinished`)
  event, tagged `["pass39","lifecycle"]`.
- Marks are folded back by `CandidatePool.from_events` (canonical
  `(timestamp, index)` order; registration replaces the snapshot, status-change
  mutates only status/note), so projections honor lifecycle from the ledger alone.

## Apply orchestration (when marks DO apply)

Mirrors the Pass 37 deployment tick safety envelope:

```
hard guards (no_auto_submit, no_kaggle_upload, root byte-identical)
  → acquire_lease → pull_state → base_remote_hash
  → evaluate → emit CandidateStatusChanged (idempotent) → pool.save
  → rebuild_projections
  → push_state(base_remote_hash, on_remote_drift=rebuild_projections)
  → release_lease (finally) → re-pull → health re-check
```

Lease TTL is **1800s**. The Scheduled Deployment cadence is **every 20 min**
(`*/20 * * * *`); the 1200s interval is **shorter** than the 1800s TTL, so the old
"gap ≥ TTL" spacing heuristic no longer holds. The authoritative scheduled-run
signal is the **run signature (`--max-games 20 --max-seconds 900`)**; lease +
push-merge-by-`event_id` remain the concurrency safety nets. Do not change the TTL
without an explicit request.

## CLI

```
python scripts/run_tournament_lifecycle_manager.py \
    --mode prod \                 # prod | local
    [--apply] \                   # default: dry-run (writes a plan, no mutation)
    [--allow-soft-probation] \    # opt-in to applying under-sampled→probation
    [--storage-backend replit_app_storage] [--storage-prefix ...] \
    [--output-prefix data/experiments/pass39_lifecycle] [--no-pull]
```

## Pass 39 ops status (first run)

> Internal diagnostics only. NO upload/submit/auto-submit, NO candidate generation, NO root/tarball mutation. Every event `no_upload=true`.

Dry-run vs the prod-pulled state: **16 actions — 12 retain, 4 eligible_soft_probation, 0 quarantine; 11 protected.** `--apply` (without `--allow-soft-probation`) → **`apply_skipped=true`** (no safe, evidence-backed mark: zero quarantines because no candidate has hard-failure invalid/timeout/error evidence, and demoting under-sampled actives to probation in early soak is churn with no benefit — probation is still schedulable). No lease taken, no push. Scheduled tick: **confirmed**; prod health: **healthy** (soft warn `placement_sample_size`). Detail: `data/reports/pass39_candidate_lifecycle_report.md`, `data/experiments/pass39_lifecycle_{plan,apply}.{json,md}`.
