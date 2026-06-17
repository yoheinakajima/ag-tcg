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
