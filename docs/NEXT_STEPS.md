# Next Steps

Prioritized roadmap from this first version toward a competitive, well-documented
submission.

## Pass 46B — reference-gap + turn-planning diagnostic (current state)

> READ-ONLY / LOCAL. NO production mutation, no tick, no lifecycle/generation/
> promotion/upload, no forbidden events. Public references stay benchmark-only.
> Internal/benchmark metrics are NOT Kaggle leaderboard scores.

- **Decision: `reference_gap_diagnostic_complete_soak_continue`.** Built a reusable,
  pure turn-planning extractor (`src/ptcg_activegraph/analysis/turn_planning.py`) and
  honest diagnostic artifacts (`data/experiments/pass46b_*`, report
  `data/reports/pass46b_reference_gap_turn_planning_report.md`). Safety stop-gate passed
  all hard checks (root byte-identical before+after; deploy points to the tick not root;
  `auto_submit` falsy; references absent from pool+worklist).
- **Key finding:** the gap to public references is broad and **behavioral** — our
  candidates beat references only ~9.3% of decisive benchmark games (12 W / 117 L / 3 D
  over 134). It is gameplay **policy / turn planning**, not deck-list counts. Mega lines
  are weakest (~5%); diamond best (~40%).
- **Honest evidence limit:** full decision frames exist only in ONE local Kaggle replay;
  tournament/benchmark records are outcome-only (no frames). Trace-level turn-planning
  metrics are illustrative (n=1); outcome-level gap is well supported.
- **Next:** keep soaking; do NOT start full Pass 47 yet; do NOT optimize one deck. The
  next improvement pass should build **reusable turn-planning primitives** (a
  `cg_typed`/search-capable policy lane) — see `docs/TURN_PLANNING_PRIMITIVES_BACKLOG.md`
  (top 3: typed board decode wrapper, legal option taxonomy, energy planner). **26**
  Pass-46B tests + `pass42–46` regression green.

## Pass 45 — production probation soak + promotion-readiness audit

> READ-ONLY / AUDIT / SOAK. NO Kaggle upload/submit/auto-submit, NO queue/promotion/
> status-change events, NO generation/deck-mutation/single-deck-opt/cg_typed, NO
> root/tarball mutation, NO production mutation.

- **Status: `probation_soak_continue`.** The deployed Scheduled Deployment is healthy
  and accruing placement evidence for the 3 Pass-42 probation candidates on its ~20-min
  cron (prod ledger 3030 events, 52 ticks, 932 games, 418 W / 502 L / 12 D, 0%
  hard-fail rate, manifest==ledger). All 3 are registered, schedulable, and gaining
  games (diamond 0-3, dragapult 3-4, lightning 2-6 decisive).
- **Promotion readiness:** none ready. Each candidate is >20 decisive games and 17
  parent-H2H games short of the locked v1 activate floor (total≥40, decisive≥30,
  H2H≥20) → all `insufficient_evidence`. The promotion gate ran **dry-run only** (0
  actionable, no apply). No quarantine warranted (hard-fail rate 0; `decisive==0` alone
  never quarantines).
- **Next:** let the daemon keep accruing placement / parent-H2H games on its cron, then
  re-run this readiness audit + gate. Only once a candidate approaches the sample-size /
  H2H / anchor minimums can activation be considered (still gated, still no Kaggle
  upload). See `data/reports/pass45_production_probation_soak_report.md`.

## Pass 44 — post-republish production probation registration (superseded by Pass 45)

> Internal diagnostics + lifecycle plumbing only. NO Kaggle upload/submit/auto-submit,
> NO queue/promotion events, NO root/tarball mutation, NO new candidates.

- **Status: `production_probation_registered_promotion_gate_ready`.** The operator
  republished the Scheduled Deployment from the current commit, baking the Pass-42
  tarballs into the deploy image. The 3 probation candidates are now registered in the
  **production** registry (KEY-SCOPED: ledger 2893→2902, pool 16→19, 15 keys uploaded,
  no sidecar re-push), and a controlled production tick proved the live deploy path
  resolves and runs the new tarballs (real bounded game to completion, no missing-tarball
  failure).
- **Promotion gate:** rerun → all 3 still `insufficient_evidence`; `--apply` skipped.
- **Next:** let the deployed daemon accrue placement games against the 3 candidates on
  its cron schedule, then re-run the gate. Only once a candidate clears the sample-size
  / parent-H2H / anchor / deck-delta gates can activation be considered (still no Kaggle
  upload). See `data/reports/pass44_post_republish_probation_registration_report.md`.

## Pass 43 — production probation registration + Promotion Gate v1 (superseded by Pass 44)

> Internal diagnostics + lifecycle plumbing only. NO Kaggle upload/submit/auto-submit,
> NO queue/promotion events, NO root/tarball mutation, NO new candidates.

- **Status: `production_registration_blocked_republish_required`.** The 3 Pass-42
  probation candidates are local-only (git-tracked tarballs, absent from prod OS and not
  confirmed on the live deploy image). Production was NOT mutated.
- **Immediate operator step (when ready):** republish the tournament Scheduled Deployment
  from the current commit to bake the Pass-42 tarballs into the image, then run the
  5-step runbook (confirm committed → republish → prod health → `--apply` registration →
  bounded prod tick) — see §13 of `docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md`.
- **Promotion Gate v1** is installed dry-run-default and conservative
  (`src/ptcg_activegraph/tournament/promotion.py`,
  `scripts/run_tournament_promotion_gate.py`). It recommends nothing until candidates
  accrue real placement games; raw win-rate alone never promotes. Re-run the dry-run
  after the daemon plays the new candidates.

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

## Pass 42 — Candidate generation v0 (local factory, probation-only)

- **What landed:** a deterministic, LOCAL-only candidate **factory** — mutate
  **internal** source decks with stdlib-safe operators, validate via hard gates,
  admit passing ones as **probation**. 3 admitted
  (`generated_diamond_diamondtoolbox_eratio_v1`,
  `generated_dragapult_leaguedragapul_bdens_v1`,
  `generated_lightning_monolightningm_dsratio_v1`) from 3 families; 2 regression
  operators (policy-only, no-op) rejected with reasons. **No promotion, queue,
  upload, submit, push, root mutation, or tarball overwrite/delete.** The 5 public
  references stay benchmark-only — never a source/parent/candidate.
- **Honest signal:** the 12-game probation eval is **liveness/placement only — NOT
  promotion evidence** (each candidate split its parent seats and lost its anchor
  game). Decision: `candidate_generation_v0_enabled`, `republish_required=false`;
  admitted candidates stay local-only probation.
- **Next (no republish):** let the standing daemon accrue real placement games for
  the 3 probation candidates against their anchors before any parent/child verdict;
  treat policy-only non-inertness and sibling-family verified-ID transfer as the
  **v1** workstream (prove them before admitting). Do **not** promote until an
  adequately-sampled, noise-controlled eval + approved decision justify it. Detail:
  `data/reports/pass42_candidate_generation_v0_report.md`.

## Pass 46D — turn-planning primitives v0 (LOCAL infrastructure, READ-ONLY)

_Reusable, tested, never-raise **turn-planning primitives** over the Pass-46C decision
frames — **infrastructure only**. **No production mutation, no tick, no candidate
generation/promotion/queue/upload/republish, no lifecycle change, no root mutation.**
The public references stay **benchmark-only**. **No Kaggle strength claim**; unsupported
claims (exact damage / lethal / missed-KO / Boss-gust / spread / best-action) stay
explicitly unsupported._

- **Module:** `src/ptcg_activegraph/analysis/turn_primitives.py` — 13 pure primitives
  (safe_get, option/select normalization, family classification + taxonomy, board
  snapshot + visible per-zone counts, energy attach candidates + generic deck-agnostic
  ordering, setup/search/discard summaries, unsupported-claims guard). Imports only the
  pure `action_resolver` + `turn_planning` decoders — no storage/eventstore/prod/
  reference-policy code. Accepts a Kaggle-replay seat object, raw observation, bare
  select, or a `DecisionFrame`.
- **Honest limits:** opponent hand is never read (counts only); search/discard surface
  only positively-resolvable card ids; these traces encode setup as a hand-select with
  **no** active/bench destination, so `setup_candidate_summary` reports phase only (the
  destination-labelling path is backlog for a richer cg-typed observation).
- **Validation:** 8 trace fixtures (raw frames embedded) across attach / attack / search /
  discard / setup / low-choice; fixture validation `all_ok` (taxonomy correct, min/max +
  option counts preserved, energy destinations resolve to active/bench, visible ids only,
  no hidden-hand exposure, unsupported guard intact). Behavior comparison over the 12-game
  panel is **directional / small-n** (options presented, not actions chosen).
- **Decision:** `turn_planning_primitives_ready_soak_continue`; keep production soaking.
  Do **not** run a generation pass until a fresh readiness check shows a probation
  candidate near thresholds. **52** Pass-46D tests + pass42–46d regression green.

Detail: `data/reports/pass46d_turn_planning_primitives_report.md`;
`docs/TURN_PLANNING_PRIMITIVES_V0.md`;
`docs/TURN_PLANNING_CANDIDATE_INTEGRATION_PLAN.md`; `data/experiments/pass46d_*`.

## Pass 46E — cg Search Outcome Oracle + one-step planner v0 (decision: search_oracle_partial_diagnostic_only)
- Built never-raise, subprocess-isolated cg Search oracle (`search_oracle.py` + `_search_worker.py`); cg confined to the worker.
- Calibrated vs Pass-46C traces: supported=126/160, exact_rate=0.425, mismatch_rate=0.2125.
- Decision **search_oracle_partial_diagnostic_only** — fabricated hidden zones keep predictions diagnostic-grade; no candidate created. Next: seed revealed cards, add a full-state-replay path, improve setup/KO transitions.

## Pass 46E — cg Search Outcome Oracle + one-step planner v0 (decision: search_oracle_ready_for_candidate_pilot)
- Built never-raise, subprocess-isolated cg Search oracle (`search_oracle.py` + `_search_worker.py`); cg confined to the worker.
- Calibrated vs Pass-46C traces: supported=145/160, exact_rate=0.6375, mismatch_rate=0.0938.
- Decision **search_oracle_ready_for_candidate_pilot** — fabricated hidden zones keep predictions diagnostic-grade; no candidate created. Next: seed revealed cards, add a full-state-replay path, improve setup/KO transitions.

## Pass 46E — cg Search Outcome Oracle + one-step planner v0 (decision: search_oracle_ready_for_candidate_pilot)
- Built never-raise, subprocess-isolated cg Search oracle (`search_oracle.py` + `_search_worker.py`); cg confined to the worker.
- Calibrated vs Pass-46C traces: supported=147/160, exact_rate=0.65, mismatch_rate=0.0813.
- Decision **search_oracle_ready_for_candidate_pilot** — fabricated hidden zones keep predictions diagnostic-grade; no candidate created. Next: seed revealed cards, add a full-state-replay path, improve setup/KO transitions.

## Pass 46F — Search-calibrated fast turn-planner candidate pilot v0 (decision: insufficient_evidence)
- Built ONE owned `cg_typed` candidate (`cg_typed_water_anti_disruption_searchcal_v1`, sha `f58048a0…`) whose **fast** hot-path scorer is calibrated **offline** to the Pass-46E Search oracle — **no online Search in the live hot path**. Deck byte-copied from internal parent `league_water_anti_disruption_pivot_v1` (policy-only change).
- **Scorer = single source of truth:** pure `src/ptcg_activegraph/analysis/turn_scorer.py` + JSON profile `data/experiments/pass46f_score_profile.json` (`search_calibrated_v0`); the candidate `main.py` **inlines** a byte-identical, behaviorally-identical copy (parity test passes).
- **Calibration:** robust-median per-family weights (attach 1.5 > attack 0.975 > ability 0.6 > play 0.4 > select 0.3 > end_turn −0.5); in-sample median lift +8.0, top-1 agreement 0.686 over 51 frames (NOT a win-rate claim).
- **Safety/runnable/non-inert:** Part-A preflight `all_ok`; smoke 9/9 clean; non-inertness `non_inert_and_safe` (58.1% divergence over 43 parent frames, 0 illegal / 0 fallback / 0 exceptions). References stay benchmark-only (0/12, never source/parent/candidate).
- **Decision `insufficient_evidence`:** parent H2H 0.55 [0.342, 0.742] n=20, seats 0.40/0.70 (not both winning), self-mirror Fisher inconclusive → no resolvable edge. No promotion, no upload. Next: raise H2H to n≥60 seat-balanced + richer oracle labels before any edge claim.
- **Tests:** 40 Pass-46F tests + pass41–46e regression green; no Pass-46F script uploads, promotes, ticks, mutates root, or emits a forbidden event.

Detail: `data/reports/pass46f_search_calibrated_turnplanner_candidate_report.md`; `data/experiments/pass46f_*`.

## Pass 46G — Multi-profile turn-planner sprint v1 (LOCAL-ONLY, NOT Kaggle) — decision: no_profile_promising_continue_iteration
- Built a SMALL BATCH of **four** owned `cg_typed` candidates (water × diamond) × (`phase_aware_tempo_v1`, `role_aware_energy_v1`) on a NEW pure scorer `src/ptcg_activegraph/analysis/turn_planner_profiles.py` (schema `pass46g_turn_scorer_v1`, owned `INLINE_SCORER_V2`); 46F `turn_scorer.py` untouched. Decks byte-copied from internal parents `league_water_anti_disruption_pivot_v1` / `diamond_toolbox_diancie` (policy-only). **No online Search in the live hot path.**
- **Profiles measured offline vs the Pass-46E oracle:** phase & role both lift oracle top-1 to **0.814** (+4.0 median) over the 0.729 baseline — but **identically** to each other (first red flag).
- **The phase/role layer is the thing that failed — twice.** Internal distinguishability: role == family-only floor at top-1 (0.0% divergence) in both families; phase moves the menu only in diamond (7.9%) not water (4.7%). In gameplay the intra-family phase-vs-role test spans 0.5 (6/4, [0.31,0.83]) → indistinguishable.
- **Eval panel (56 games, 0 err/timeout):** `parent_h2h_edge_candidates_95=[]` — no candidate clears Wilson_low>0.5. diamond_phase posts **8/2** over its parent (Wilson [0.49,0.94], just misses) — a real improvement over 46F's 0/2, but a **family-weighted TRANSFER** signal, NOT a phase/role success. Below all public references (benchmark-only).
- **Safety/runnable/non-inert:** Part-A preflight `all_ok`; smoke 8/8 clean; all four `non_inert_and_safe` (34–63% divergence, 0 illegal/fallback/exception). References stay benchmark-only (never source/parent/candidate, not pooled). No upload/promote/tick/pool-register/republish; 24 LOCAL `no_upload` events (clean, incl. report-site) + 1 benchmark.
- **Decision `no_profile_promising_continue_iteration`.** Next: (1) replace the additive phase×family / role-target layer with **within-family per-option value features**; (2) confirm the diamond transfer at N≥40 seat-balanced before any edge claim; (3) consider cut Lightning/Dragapult families + a from-scratch value head. **48** Pass-46G tests + pass41–46f regression green.

Detail: `data/reports/pass46g_multi_profile_turnplanner_sprint_report.md`; `data/experiments/pass46g_*`.
