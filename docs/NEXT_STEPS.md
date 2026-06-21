# Next Steps

Prioritized roadmap from this first version toward a competitive, well-documented
submission.

## Top 10

1. **Install the simulator.** `pip install kaggle-environments` and install
   `cabt` from the competition package. Confirm `sim.is_available()` is `True`.
2. **Ingest official card CSV.** Drop `EN_Card_Data.csv` / `JP_Card_Data.csv`
   into `data/cards/`. Run `make inspect-cards` and tighten `cards/role_tags.py`
   against the real schema.
3. **Choose an initial deck.** Replace the placeholder `deck.csv` with a real,
   legal 60-card archetype. Validate with `make verify-submission`.
4. **Baseline the policies.** Random vs fallback vs heuristic over N self-play
   games; record win/fallback rates via projections.
5. **Wire the real battle loop.** Finalize `CabtAdapter.run_game` against the
   installed cabt observation/return schema (remove the placeholder seam).
6. **Turn on ActiveGraph traces in-match.** Emit `ObservationReceived`,
   `LegalOptionsProjected`, `ActionChosen`, `ActionFallbackUsed` per step so
   `MatchGraph` and the failure classifier have rich evidence.
7. **Run the failure classifier on real matches.** Generate `PatchPlan`s per
   regime; act on the most common failure tags first.
8. **Add belief-sampled shallow search.** Implement `WorldSampler.sample` to draw
   plausible hidden states and wire `SearchPolicy` into `cabt.search_*`, gated by
   the time budget. Validate via `belief_search`.
9. **Run deck tournaments.** Use `sim/tournament.py` to compare archetypes;
   promote the best via a `DECK_CONSTRUCTION` patch plan.
10. **Prepare the first submission + Strategy report.** `make submission` and
    `make report`; hand-edit the report's prose sections.

## Field-aware heuristic (after schema is known)

Once cabt option objects have concrete fields (damage numbers, energy cost,
target), upgrade `heuristic_policy` from keyword scoring to field-aware scoring
(read `OptionView.fields`). Keep `main.py` mirrored.

## Stability hardening

* Add a fuzz test that throws random/garbage observations at `main.py:agent` in a
  loop and asserts it never raises and always returns legal indices.
* Add a timeout guard around the (future) search path using `TimeManager`.

## Concurrency

* The JSONL event store is not multi-writer-safe on non-POSIX platforms. If
  parallel self-play is needed, shard event files per worker and merge on read.

## Reach goals

* Card graph synergy/combo detection feeding a deck optimizer.
* Offline LLM analysis of failure clusters (lab-only; never in the runtime).
* Promotion automation that compiles validated package changes into `main.py`.

## Standing tournament ops (Pass 39 → next)

The internal standing tournament runs as a Scheduled Deployment every 20 min
(`*/20 * * * *`), signature 20/900. It is internal diagnostics only — NOT Kaggle,
no upload/submit/auto-submit, no new candidates, no root/tarball mutation, and the
root "Start application" workflow stays not-started (frozen Kaggle entrypoint).

- **Now:** scheduled tick confirmed; prod healthy; candidate lifecycle v0 dry-run
  proposes 12 retain / 4 eligible_soft_probation / 0 quarantine (11 protected);
  `--apply` → `apply_skipped` until evidence accrues.
- **Next:** let games accumulate so actives clear the placement threshold (≥20
  games), then re-run `scripts/run_tournament_lifecycle_manager.py` — soft-probation
  becomes meaningful and quarantine evidence (invalid/timeout/error) can appear. Keep
  marks ledger-only via `CandidateStatusChanged`; never edit the pool out-of-band.

## Pass 41 — Reference-calibrated cg_typed candidate spike (local-only)

- **What landed:** one **owned** cg_typed candidate
  (`cg_typed_mono_lightning_miraidon_policy_v1`) — original typed policy over the
  bundled `cg` SDK, parent deck unchanged, `mutation_parent=internal`. The five
  Pass-40 **public references are benchmark-only** opponents and were never made a
  candidate/parent/queue/promotion. **No submission was made; no Kaggle strength
  claim** — the local benchmark is **directional only**.
- **Honest signal:** beats its parent 10–0 (above the self-mirror noise floor) and
  two internal anchors, but is **below** the public references (1/20 decisive) and
  below the `dragapult` reference. Decision: `promising_local_only`,
  `republish_required=false`.
- **Next (depends on eval outcome):** finish the remaining ~126 calibration games
  to complete the public-reference sweep, then deepen the parent/child + noise
  sample before any further typed work. Do **not** pursue public-reference parity
  claims or consider republish until a completed calibration + approved decision
  justify it. Detail: `data/reports/pass41_reference_calibrated_cg_candidate_report.md`.
