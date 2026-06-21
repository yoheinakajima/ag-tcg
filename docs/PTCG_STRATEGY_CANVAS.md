# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 44.

_The internal tournament, parent/child H2H confirmations, and the replay-derived meta sanity are LOCAL diagnostics: every seat is OUR own portfolio deck driven by the SAME deck-agnostic base pilot (meta sanity uses replay-derived surrogate opponents). They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

_Honesty mandate: attack damage/effect, lethal, KO target, spread placement, Boss/gust are UNSUPPORTED by the option schema (numeric attackId only); the typed layer refuses to fabricate them. Raging Bolt gets NO fake color-match fix (Pass 28 refuted it)._

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
