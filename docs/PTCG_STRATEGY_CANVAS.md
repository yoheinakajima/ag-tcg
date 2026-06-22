# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 46B.

_The internal tournament, parent/child H2H confirmations, and the replay-derived meta sanity are LOCAL diagnostics: every seat is OUR own portfolio deck driven by the SAME deck-agnostic base pilot (meta sanity uses replay-derived surrogate opponents). They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

_Honesty mandate: attack damage/effect, lethal, KO target, spread placement, Boss/gust are UNSUPPORTED by the option schema (numeric attackId only); the typed layer refuses to fabricate them. Raging Bolt gets NO fake color-match fix (Pass 28 refuted it)._

## Pass 46B — reference-gap + turn-planning diagnostic (READ-ONLY / LOCAL)

- **Decision: `reference_gap_diagnostic_complete_soak_continue`.** READ-ONLY/LOCAL: no
  prod mutation, no tick, no lifecycle/generation/promotion/upload, no forbidden events;
  references benchmark-only. Safety stop-gate green (root byte-identical before+after;
  deploy→tick; `auto_submit` falsy; refs absent from pool+worklist).
- **The reference gap is behavioral.** Internal candidates beat the public references only
  ~9.3% of decisive benchmark games (12 W / 117 L / 3 D over 134), across all families
  (mega weakest ~5%, diamond best ~40%) → it is gameplay **policy / turn planning**, not
  deck-list counts.
- **Honest evidence limit.** Decision frames exist in ONLY one local Kaggle replay (268);
  sidecars + benchmark records are outcome-only (step COUNT). Trace metrics illustrative
  (n=1); outcome-level gap well supported. Numbers are diagnostics, NOT Kaggle scores.
- **Forward (not executed):** reusable turn-planning primitives — typed board decode,
  legal option taxonomy, energy planner, search-capable policy lane
  (`docs/TURN_PLANNING_PRIMITIVES_BACKLOG.md`). **26** tests + `pass42–46` regression green.

## Pass 44 — post-republish production probation registration + verification bridge

- **Decision: `production_probation_registered_promotion_gate_ready`.** After the operator republished the Scheduled Deployment from the current commit (baking the Pass-42 tarballs into the deploy image, attested `case_1_deploy_visible_os_missing`), the 3 probation candidates (`generated_diamond_diamondtoolbox_eratio_v1`, `generated_dragapult_leaguedragapul_bdens_v1`, `generated_lightning_monolightningm_dsratio_v1`) were registered into **production** Object Storage — KEY-SCOPED (ledger 2893→2902, pool 16→19, 15 keys uploaded, ~950 sidecars untouched), manifest==ledger (2902==2902).
- **Binding runtime proof:** a controlled production tick resolved all 3 tarballs and ran a real bounded `cabt` game from the live prod scheduler queue to completion — no missing-tarball/import failure.
- **Gate rerun:** 0 actionable; all 3 `insufficient_evidence`; `--apply` skipped (no promotion/demotion). Scheduler deterministic, all 3 probation placed, zero public-ref/never-schedule leakage, no active-cap replacement. **28** Pass-44 tests + `pass36_44` regression green; NO upload/submit/queue/promotion; root byte-unchanged.

## Pass 43 — production probation registration + Promotion Gate v1

- **Decision: `production_registration_blocked_republish_required`.** The 3 Pass-42 probation candidates (`generated_diamond_diamondtoolbox_eratio_v1`, `generated_dragapult_leaguedragapul_bdens_v1`, `generated_lightning_monolightningm_dsratio_v1`) are local-only: git-tracked tarballs, absent from prod OS, deploy-image visibility unconfirmed → registering now risks missing-tarball error games. Republish first, then conditional `--apply`. Production NOT mutated; root byte-unchanged.
- **Promotion Gate v1 (dry-run default, conservative):** 19 thresholds / 9 actions; raw win-rate alone NEVER promotes; ACTIVATE requires direct parent-H2H superiority and PROMOTE requires direct champion-H2H superiority (out-farming weaker opponents in the aggregate is not enough); protected statuses never demoted; public refs never in the candidate set; tarballs never deleted. Dry-run over 19 candidates → 0 actionable; all 3 generated → `insufficient_evidence` (0 placement games). Scheduler unchanged by the gate (deterministic, no leakage). 38 Pass-43 tests + pass36–43 regression green; NO upload/submit/queue/promotion.

## Pass 35 — typed board-aware strategy layer

- Lane: Option B stdlib typed-lite (`stdlib_typed_lite`), embed-not-import, refine-then-fallback.
- Profiles: 11 (9 executable + 2 special-pilot-only).
- Typed strategy gate: PASS; firing probe 2.5% with 0 illegal refinements.

## Internal tournament standings (NOT Kaggle)

| rank | typed child | adj win_rate | Wilson | label |
|---|---|---|---|---|
| 1 | mega_venusaur_tank_typed35 | 63.9% | [0.4757, 0.7752] | strong |
| 2 | mega_charizard_x_burst_typed35 | 52.8% | [0.3701, 0.6801] | above_even_noisy |
| 3 | raging_bolt_ogerpon_basic_aggro_typed35 | 50.0% | [0.3447, 0.6553] | above_even_noisy |
| 4 | mono_lightning_miraidon_easy_typed35 | 33.3% | [0.2021, 0.4967] | weak |
| 5 | diamond_toolbox_diancie_typed35 | 50.0% | [0.3363, 0.6637] | above_even_noisy |
| 6 | water_basic_density_v1_typed35 | 46.9% | [0.3087, 0.6355] | below_even |
| 7 | dragapult_spread_control_typed35 | 43.8% | [0.2817, 0.6067] | below_even |
| 8 | mega_gardevoir_psychic_ramp_typed35 | 40.6% | [0.2552, 0.5774] | below_even |
| 9 | water_core_reference_typed35 | 40.6% | [0.2552, 0.5774] | below_even |

## Parent/child confirmation (control-calibrated)

- any_superiority_claim: no; no_regression=5, inconclusive=4 — no child clears the self-mirror noise floor.

## Meta sanity (directional, surrogate)

- sanity_passed: yes; best `mega_charizard_x_burst_typed35` @ 60.0%; 0 collapses.

## Next move

`Keep water_basic_density_v1 as the single HELD dry-run probe (carried, unchanged). The Pass-35 typed board-aware layer is adopted as SAFE (0 illegal refinements, always falls back, ~2.5% live firing) and meta-sane (0 collapses), but NO typed child clearly beats its untyped parent once calibrated against the self-mirror noise floor, so none is promoted to the queue. No upload/submit performed.` Keep `water_basic_density_v1` as the single held dry-run probe; adopt the typed layer as SAFE infrastructure but DO NOT submit. Run a larger confirmation batch before any human submit. Toxic + Durant stay special-pilot-only.

## Pass 36 — Standing tournament engine v0 (internal diagnostics, NOT Kaggle)

The deprecated per-pass one-off tournaments are replaced by a reusable **event-first, resumable, bounded-tick** engine (`src/ptcg_activegraph/tournament/`). The event ledger is the source of truth; all projections rebuild from it. **NO upload, NO auto-submit, no new candidates.**

- Smoke: 2 ticks, 5 cabt games (all ok), resume proven (no duplicate game ids; next queue 0 overlap).
- Root `main.py`/`deck.csv` untouched; held probe `water_basic_density_v1` still held; Toxic/Durant special-pilot-only (never scheduled).
- Internal standings are NOT a Kaggle leaderboard and NOT a promotion/upload signal.

See `data/reports/pass36_standing_tournament_engine_report.md`, `docs/TOURNAMENT_ENGINE_PLAN.md`, `docs/PERSISTENT_TOURNAMENT_DAEMON.md`.

## Pass 37 — Deployment-ready tournament worker (Scheduled Deployment + persistent storage, NOT Kaggle)

The Pass 36 engine is made safe to run as a Replit **Scheduled Deployment** with **persistent storage** via a thin storage/sync/lease wrapper (`src/ptcg_activegraph/tournament/{storage,sync,lease}.py` + worker `scripts/tournament_deployment_tick.py`). `data/tournament/` is a disposable working dir: pull → bounded tick → rebuild → reconcile (merge by `event_id`, abort on conflict) → push sha-verified manifest → release lease. **NO upload, NO submit, NO auto-submit, no new candidates.**

- Production **fails closed** without persistent storage; storage validated end-to-end on Replit Object Storage (no duplicate game ids, 0 upload events, manifest shas match).
- Deploy ONLY as a Scheduled Deployment bounded tick (never an always-on server, never the root "Start application" workflow). Schedule every 2h · job timeout ~25 min (< 30-min lease TTL).
- Root `main.py`/`deck.csv` untouched; held probe held; Toxic/Durant special-pilot-only; 28 tests pass.

See `data/reports/pass37_deployment_ready_tournament_worker_report.md`, `scripts/print_replit_scheduled_deployment_config.py`, `docs/PERSISTENT_TOURNAMENT_DAEMON.md`.

<!-- PASS38_ADDENDUM_START -->
## Pass 38 — Deployment incident addendum & soak status (OPS only)

> Internal diagnostics only. **NOT a Kaggle leaderboard.** **NO upload, NO submit, NO auto-submit, no new candidates, no root mutation.** The root "Start application" workflow stays not-started (frozen Kaggle entrypoint) — that is EXPECTED.

### What went wrong at publish (Pass 37) and the durable fixes
- **uv editable-install into the read-only Nix store** — the deploy build auto-runs `uv sync`, which editable-installed the root project and wrote `__editable__*.pth` into the read-only store → EACCES → build failed. **Fix:** `[tool.uv] package = false` (the worker puts `src/` on `sys.path` itself; no install needed). Do not add dependency-groups/default-groups.
- **uv cannot install deploy deps** — install deploy-only deps in the BUILD command with `python -m pip install --user --break-system-packages` so they land in the writable `.pythonlibs` (PYTHONUSERBASE).
- **bundled cabt env** — games run via `kaggle_environments.make("cabt")`; the cabt env ships INSIDE the `kaggle-environments==1.30.1` wheel, so that pin must be in the build command or every game errors (publish still succeeds → silent zero progress).
- **publish-success is decoupled from game-success** — a failing game is recorded `timeout`/`error` and never fails the tick; the worker exits non-zero only on top-level/storage/refused/conflict/lease errors. When debugging a publish failure, separate "does the run exit 0" from "do games progress".

### Pass 38 soak status (live)
- root `main.py`/`deck.csv` byte-identical to the frozen baseline + deploy config verified: **yes**
- controlled production tick: played **3** internal games, ledger **64 → 77** events, push self-verified: **yes**
- health checker (prod + local) healthy: **yes** (soft warnings: ['placement_sample_size'])
- scheduled production run observed yet: **no** (all 5 recorded ticks are manual/smoke; 5 classified manual — the deployment is published and ready but a real scheduled tick has not yet fired in the ledger/deployment logs)
- guardrails intact: held probe retained, special-pilot-only decks never scheduled, `auto_submit` refused, every event `no_upload=true`.

Detail: `data/reports/pass38_scheduled_deployment_ops_report.md`; runbook `docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md`; per-part artifacts `data/experiments/pass38_*.{json,md}`.
<!-- PASS38_ADDENDUM_END -->

## Pass 39 — Scheduled-tick confirmation + candidate lifecycle v0 (OPS only, NOT Kaggle)

> Internal diagnostics only. NO upload, NO submit, NO auto-submit, NO new candidates, NO root/tarball mutation. Root "Start application" stays not-started (frozen Kaggle entrypoint) — EXPECTED. Every new event `no_upload=true`.

- **Cadence:** Scheduled Deployment cron now `*/20 * * * *` (every 20 min); run signature unchanged (20/900). Interval (1200s) < lease TTL (1800s) → classify scheduled runs by the **run signature**, not tick spacing.
- **Scheduled tick:** **confirmed** (a real 20/900 scheduled run is present in the ledger).
- **Prod health:** healthy (0 hard failures; soft warning `placement_sample_size`).
- **Candidate lifecycle v0 (dry-run vs prod):** 16 actions — 12 retain, 4 eligible_soft_probation, 0 quarantine; 11 protected. `--apply` → **apply_skipped=true** (no safe evidence-backed mark; no lease, no push).
- **Audits:** scheduler-after-lifecycle deterministic with 0 never-schedule decks queued; event/projection idempotency all-green (`CandidateStatusChanged` folding deterministic + idempotent).

Detail: `data/reports/pass39_candidate_lifecycle_report.md`; `docs/TOURNAMENT_CANDIDATE_LIFECYCLE.md`; `data/experiments/pass39_*`.

## Pass 41 — reference-calibrated cg_typed candidate spike (LOCAL, NOT Kaggle)

_The five Pass-40 public references are **benchmark-only** opponents on a separate ledger — never a candidate/parent/queue/promotion and never toward the active cap. The cg_typed candidate here is **ours**. **No submission was made; no Kaggle strength claim.** The local benchmark is **directional only**._

- **Calibration (honest tranche):** 134 of ~260 games done; 13 internal subjects × 5 public references. Internal candidates are broadly below the references; the default family `mono_lightning_miraidon_easy` sits at decisive WR 0.10 (CI [0.018, 0.404]).
- **Target selection:** default `mono_lightning_miraidon_easy` holds — evidence tied, **no** family's Wilson CI is disjoint from the default's, so none is a distinguishable higher-leverage target.
- **Owned candidate:** `cg_typed_mono_lightning_miraidon_policy_v1` — original typed policy over the bundled `cg` SDK (decodes `cg.api` dataclasses; prize/board/attacker-readiness reasoning), parent deck unchanged, `mutation_parent=internal`, no reference code copied.
- **Lanes:** cg_typed validator ACCEPTS; both stdlib validators (byte-unchanged) REJECT (they forbid `import cg`). Smoke 9/9 clean.
- **Eval (honest):** beats parent 10–0 (Wilson [0.7225, 1.0]) **above** the self-mirror noise floor (pooled Fisher p=0.0085); above `water_control` + `internal_leader`; **below** `dragapult` reference; **below** all public references overall (1/20 decisive, WR 0.05). Non-inert: 61.8% decisions changed, **0 illegal**, 0 uncaught exceptions.
- **Decision:** `promising_local_only`; `republish_required=false`; candidate stays **local-only** (not queued/submitted/promoted).
- **Next step depends on the eval outcome:** complete the calibration sweep + deepen the parent/child + noise sample before any further typed work; no public-reference parity claims at this sample.

Detail: `data/reports/pass41_reference_calibrated_cg_candidate_report.md`; design `docs/PASS41_CG_TYPED_POLICY_DESIGN.md`; `data/experiments/pass41_*`.

## Pass 42 — candidate generation v0 (LOCAL factory, probation-only)

_A deterministic, LOCAL-only candidate **factory**: mutate **internal** source decks with stdlib-safe operators, validate via hard gates, admit passing ones as **probation**. **No promotion, queue, upload/submit, GitHub push, root mutation, or tarball overwrite/delete.** The five public references stay **benchmark-only** — never a source/parent/candidate/queue/promotion. No Kaggle strength claim._

- **Deterministic factory:** seed = hash(pass_id + `candgen_v0` + sorted eligible source ids + their tarball/main/deck SHA); rerun rebuilds identical tarballs and re-emits 0 events. Budgets 3/run, 1/family.
- **Operators:** 3 deck-composition operators (basic-density / energy-ratio / draw-search; source-IDs-only, 60-card legal) admitted; `conservative_policy_weight_delta` + `noop_sentinel` are **regression rejections** (duplicate/inert; policy-only non-inertness deferred to v1).
- **Admitted (3, probation):** `generated_diamond_diamondtoolbox_eratio_v1`, `generated_dragapult_leaguedragapul_bdens_v1`, `generated_lightning_monolightningm_dsratio_v1` — full lineage; 9/9 hard gates each; provenance events folded by neither pool path; projection rebuildable; storage-manifest event_count in lockstep (214=214).
- **Scheduler:** all 3 appear at p1 placement vs their own anchors, never as champions, never replacing protected decks, no reference in worklist/pool, deterministic double-build.
- **Eval (liveness only, NOT promotion evidence):** 12 ledger-free games; lanes separate; each candidate split its parent seats and lost its anchor game; reference games directional (1 our_win / 2 reference_win).
- **Decision:** `candidate_generation_v0_enabled`; `republish_required=false`; admitted candidates stay **local-only probation**. **28** Pass 42 tests + pass36–42 regression green.

Detail: `data/reports/pass42_candidate_generation_v0_report.md`; design `docs/CANDIDATE_GENERATION_V0.md`; `data/experiments/pass42_*`.

## Pass 46D — turn-planning primitives v0 (LOCAL infrastructure, READ-ONLY)

_Pure, tested, never-raise **turn-planning primitives** over the Pass-46C decision frames
— **infrastructure only**. **No production mutation/tick/generation/promotion/queue/
upload/republish/lifecycle/root mutation.** Public references **benchmark-only**. **No
Kaggle strength claim;** unsupported claims (exact damage / lethal / missed-KO / Boss-gust
/ spread / best-action) stay explicit._

- **Module:** `src/ptcg_activegraph/analysis/turn_primitives.py` — 13 pure primitives over
  the pure `action_resolver` + `turn_planning` decoders only (no storage / eventstore /
  prod / reference-policy import). Never raises on malformed/partial frames.
- **Honesty:** opponent hand never read (visible counts only); search/discard list only
  resolvable card ids; setup is hand-select with **no** active/bench destination in the
  trace, so the setup primitive reports phase only (destination labelling = backlog).
  Energy attach destinations DO resolve (active/bench) and a **generic, deck-agnostic**
  ordering (fuel active before bench) is provided — explicitly not a value/lethal claim.
- **Evidence:** 8 embedded-frame fixtures; fixture validation `all_ok`; 12-game behavior
  comparison grouped internal-candidate / internal-parent / public-reference, marked
  **directional / small-n** (options presented, not chosen). 52 Pass-46D tests +
  pass42–46d regression green.
- **Decision:** `turn_planning_primitives_ready_soak_continue` — keep soaking; wire these
  into candidate generation only in a **future** v1 pass behind the existing safety +
  promotion gates.

Detail: `data/reports/pass46d_turn_planning_primitives_report.md`;
`docs/TURN_PLANNING_PRIMITIVES_V0.md`;
`docs/TURN_PLANNING_CANDIDATE_INTEGRATION_PLAN.md`; `data/experiments/pass46d_*`.

## Pass 46E (cg Search oracle v0) — decision: search_oracle_partial_diagnostic_only
- A read-only one-step lookahead over real frames now exists, honestly labelled `assumption_based_hidden_state` / `one_step_score_rank under assumption`. It is calibrated, not trusted: ~79% of frames yield a supported prediction, 0.2125 decisive mismatch.
- Strategic read: lookahead is feasible but hidden-state fidelity (not the API) is the bottleneck. Treat as analysis tooling until exact-replay + card-reveal seeding land.

## Pass 46E (cg Search oracle v0) — decision: search_oracle_ready_for_candidate_pilot
- A read-only one-step lookahead over real frames now exists, honestly labelled `assumption_based_hidden_state` / `one_step_score_rank under assumption`. It is calibrated, not trusted: ~91% of frames yield a supported prediction, 0.0938 decisive mismatch.
- Strategic read: lookahead is feasible but hidden-state fidelity (not the API) is the bottleneck. Treat as analysis tooling until exact-replay + card-reveal seeding land.

## Pass 46E (cg Search oracle v0) — decision: search_oracle_ready_for_candidate_pilot
- A read-only one-step lookahead over real frames now exists, honestly labelled `assumption_based_hidden_state` / `one_step_score_rank under assumption`. It is calibrated, not trusted: ~92% of frames yield a supported prediction, 0.0813 decisive mismatch.
- Strategic read: lookahead is feasible but hidden-state fidelity (not the API) is the bottleneck. Treat as analysis tooling until exact-replay + card-reveal seeding land.

## Pass 46F — search-calibrated fast turn-planner candidate (LOCAL-ONLY, NOT Kaggle) — decision: insufficient_evidence
- **Strategic bet:** keep the expensive Pass-46E Search oracle **offline** and distill it into a cheap, interpretable per-family scorer the live policy can run in the hot path. Scorer is a single pure module + JSON profile, inlined byte-identically into the candidate (parity-verified) — so the same code is testable in-repo and shippable in the cg tarball.
- **What the evidence says:** the policy is genuinely different (58.1% divergence) and never crashes, and the offline fit is strong in-sample (+8.0 median oracle lift). But live cabt games do **not** yet show an edge over the parent (0.55 [0.342, 0.742] n=20; asymmetric seats 0.40/0.70; Fisher inconclusive). Honest read: calibration quality (diagnostic-grade oracle, fabricated hidden zones) and sample size are the bottlenecks, not the architecture.
- **Decision:** `insufficient_evidence` — safe, runnable, non-inert, but no resolvable gain. LOCAL-ONLY; references benchmark-only; no upload/promote/tick/republish. Promote the **pattern** (offline-oracle → fast scorer) only once n≥60 seat-balanced H2H + richer-label calibration clear the Wilson+Fisher gate.

Detail: `data/reports/pass46f_search_calibrated_turnplanner_candidate_report.md`; `data/experiments/pass46f_*`.

## Pass 46G — multi-profile turn-planner sprint (LOCAL-ONLY, NOT Kaggle) — decision: no_profile_promising_continue_iteration
- **Strategic bet:** generalise the 46F offline-oracle→fast-scorer pattern across multiple families and make the scorer **phase- and role-aware**, to see whether an interpretable profile produces a separable, attributable gameplay gain. Four candidates (water × diamond) × (phase, role) on a single pure V2 scorer, inlined byte-identically into each candidate (parity-verified).
- **What the evidence says — the phase/role hypothesis is falsified at this fidelity.** Phase and role give **identical** offline fit; the role layer **equals the family-only floor** at the actual decision (top-1, 0.0% divergence); and in live games the phase profile is **indistinguishable from its own family-only sibling** (intra-family CI spans 0.5). The layer adds interpretability vocabulary but no separable signal.
- **A real but unattributable transfer signal.** diamond `phase_aware_tempo` went 8/2 over its parent (vs 46F's 0/2) — encouraging, but Wilson_low 0.49 is not 95%-confident and the gain is the cg_typed **family-weighted scorer transfer**, not the phase/role profile. Below all public references (benchmark-only, expected).
- **Decision:** `no_profile_promising_continue_iteration` — safe, runnable, non-inert, but no profile-attributable edge. LOCAL-ONLY; references benchmark-only; no upload/promote/tick/register/republish; all five workflows stayed not-started. Pivot next to **within-family per-option value features** (the cross-family phase layer is structurally top-1-inert), and confirm the diamond transfer at larger N before any edge claim.

Detail: `data/reports/pass46g_multi_profile_turnplanner_sprint_report.md`; `data/experiments/pass46g_*`.

## Pass 46I — water option-value confirmation (LOCAL-ONLY, NO redeploy) — decision: water_option_value_not_promising
- **Strategic test:** take 46H's one surviving "coherent floor-escape" (`cg_typed_water_option_value_v1`) and decide it cleanly with a two-arm pre-registered design at larger N — ATTRIBUTION (vs its own family-only floor) AND PRACTICAL (vs the real parent) — reusing the 46H tarballs byte-for-byte.
- **What the evidence says — the per-option value layer adds no separable gameplay signal.** Versus its own floor control the treatment is a coin flip (22/43 = 0.512, CI [0.368, 0.654]); the 46H live-menu divergence does not convert into a gameplay edge. Versus the real parent it is only directional (0.605, CI spans 0.5, seat-asymmetric) — and a Fisher increment vs the floor (p=1.0) shows that signal is the **floor's**, not the value head's.
- **Durable lesson:** live top-1 menu divergence is necessary but **not sufficient** for a gameplay edge; and a "beats the parent" reading must be **decomposed against the family-only floor** before it can be credited to the layer under test.
- **Decision:** `water_option_value_not_promising` — LOCAL-ONLY; references benchmark-only & excluded (below refs); no upload/promote/register/tick/republish; all five workflows stayed not-started; shared site not regenerated. Next: iterate on the family-only floor (it carries the directional parent signal), not the option-value overlay; only revisit the value head with a much larger cached oracle label set.

Detail: `data/reports/pass46i_water_option_value_confirmation_report.md`; `data/experiments/pass46i_*`.

## Pass 46J — diamond cg_typed specialist turn-planner (LOCAL-ONLY, NOT Kaggle) — decision: diamond_specialist_promising_local_only
- **Strategic bet:** after 46G falsified the cross-family phase/role layer and 46I retired the per-option *value head* (both flat scorers, both top-1/floor-inert), test the **stronger** hypothesis — a **deck-specific turn PLANNER** (board→roles→turn-plan→per-context policy) — and demand that any parent edge be **attributable to the planning structure**, not inherited from the generic 46H diamond scorers.
- **What the evidence says — the planner posts the first attributable parent edge of the 46F→46J arc.** Practical: 32/43 = 0.744 vs the real parent, Wilson95 [0.598, 0.851] (95%-confident), clean seats — while both generic 46H scorers *lose* to the same parent (0.485 / 0.394). Attribution: a one-sided Fisher increment over both generic-vs-parent rates is significant (p=0.0021 / p=0.0186) and the planner beats the family-only floor head-to-head (0.818). Divergence is real (44.7% vs parent) and **94% plan-field-driven**, not cosmetic.
- **Durable lesson (and honest caveat):** structure beats flat weighting here — a planner that *reads roles and forms a turn plan* separated from the parent where generic family/option scorers could not. But the win is **not** a clean direct H2H over the *strongest* generic scorer (`spec_vs_generic_ov` 0.590, CI spans 0.5); attribution leans on the Fisher increment + the floor H2H, and N is modest (43 decisive). "Promising", not "proven".
- **Decision `diamond_specialist_promising_local_only`** — a LOCAL signal to invest more N, NOT a promotion or prod change (human approval required first). LOCAL-ONLY; references benchmark-only & excluded; no upload/promote/register/tick/republish/redeploy; all five workflows stayed not-started; shared site not regenerated. Next: confirm at N≥60–80 seat-balanced (especially vs the generic option_value scorer) before any edge claim hardens; the planner pattern — not a flat scorer — is the lever to carry forward in diamond.

Detail: `data/reports/pass46j_diamond_specialist_planner_report.md`; `data/experiments/pass46j_*`.
