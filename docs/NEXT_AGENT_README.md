# Next Agent — Start Here

You are continuing the Pokémon TCG AI Battle Challenge ActiveGraph lab. Read this
first, then read `docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md` before doing anything.

## The five rules you must not break

1. **Read `docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md` first.** It has the golden
   invariants, the pipeline, and the lessons already paid for.
2. **Do not upload to Kaggle by default.** No upload or submit unless a human
   explicitly approves it. Complete the upload checklist in the manual (§8) first.
3. **Do not mutate root files.** Root `main.py` and `deck.csv` are immutable
   (match `data/baselines/v1_kaggle_349_8/`). Verify with `cmp`.
4. **Validate tarballs.** Every candidate must pass
   `scripts/validate_candidate_tarball.py` (key-absent / select-null / empty-dict /
   Struct-like obs, exactly 60 ids, exactly top-level `main.py` + `deck.csv`).
   No failed-validator candidate enters queue/eval/upload.
5. **No raw data commits.** Raw replays and official card data
   (`data/cards/*.csv`, `data/kaggle_ref/*.csv`) stay gitignored. Never invent
   card IDs. Never commit credentials/secrets.

## Things that will bite you

- **Active control is dynamic.** Recompute it from
  `data/kaggle_uploads/live_score_registry.json`; never hardcode a score.
- **The kaggle CLI is often absent** (`kaggle: command not found`). When you
  cannot refresh scores, reuse the last-known-good snapshot and *say so*.
  `build_live_score_registry.py` defaults to a **stale** CSV — pass
  `--csv data/kaggle_uploads/status_before_pass11b.csv`.
- **cabt runs via `kaggle_environments.make("cabt")`** even if `import cabt`
  fails. Don't conclude cabt is missing from an import error.
- **Card id→name comes from `data/cards/EN_Card_Data.csv`** (authoritative), not
  from `archetypes.yaml` names (which had ids 678/756 swapped).
- **Long evals need a Replit workflow.** Background shells die between tool calls.

## What the next research task is

The `unknown_ex_tempo` bucket has been decomposed (Pass 13) into four
evidence-grounded subfamilies — `mega_lucario_ex_tempo`,
`mega_kangaskhan_energy_stack`, `dragapult_ex`, `lightning_bellibolt` — with a
refined meta pool at `experiments/pass13_refined_meta_pool.yaml`.

**Next:** run a proper analysis-only eval of the existing active control and
existing candidates against these refined surrogate decks (5 games/seat,
seat-swapped, no new candidates, no upload), then decide whether any subfamily
warrants a *targeted* candidate built only from confirmed card IDs. The chaos
lane stays closed until a payoff card + measurable trigger is confirmed (see
`docs/CHAOS_PLAYBOOK_LANE.md`).

## Standing tournament ops — current state (Pass 39)

A separate, **internal** standing tournament engine runs as a Replit Scheduled
Deployment (NOT Kaggle; internal standings ≠ Kaggle results). If you touch it, keep
the guardrails: NO upload/submit/auto-submit, NO new candidates, NO root/tarball
mutation, and **never start the root "Start application" workflow** (frozen Kaggle
entrypoint; not-started is EXPECTED).

- Cadence is now **every 20 min** (`*/20 * * * *`); the run signature is unchanged
  (`--max-games 20 --max-seconds 900`). Classify scheduled runs by that **signature**,
  not by tick spacing (the 20-min interval is shorter than the 30-min lease TTL).
- Candidate status is ledger-only: emit `CandidateStatusChanged` (`no_upload=true`);
  `CandidatePool.from_events` folds it. Use
  `scripts/run_tournament_lifecycle_manager.py` (default dry-run) for status marks.
- Authoritative ops docs: `docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md`,
  `docs/PERSISTENT_TOURNAMENT_DAEMON.md`, `docs/TOURNAMENT_CANDIDATE_LIFECYCLE.md`.

## Pass 41 — owned cg_typed candidate spike (local-only)

- The five Pass-40 **public references are benchmark-only** opponents — never a
  candidate/parent/queue/promotion and never toward the active cap. They live on
  `data/tournament/benchmark/benchmark_events.jsonl`, which the normal fold /
  scheduler / lifecycle never read.
- Pass 41 added **one owned** cg_typed candidate
  (`cg_typed_mono_lightning_miraidon_policy_v1`): original typed policy over the
  bundled `cg` SDK; `mutation_parent=internal`; **no reference code copied**.
  **No submission was made; no Kaggle strength claim** — the local benchmark is
  **directional only**. Decision `promising_local_only`, `republish_required=false`.
- The cg_typed candidate ships `cg/` + `import cg`, so it is **correctly rejected**
  by the stdlib submission validators (left byte-unchanged) and accepted only by
  the separate cg_typed lane validator. Keep those lanes separate.
- **Next step depends on the eval outcome:** complete the calibration sweep and
  deepen the parent/child + noise sample before further typed work; do not claim
  public-reference parity at this sample. Detail:
  `data/reports/pass41_reference_calibrated_cg_candidate_report.md`.
