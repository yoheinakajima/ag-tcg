# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 35.

_The internal tournament, parent/child H2H confirmations, and the replay-derived meta sanity are LOCAL diagnostics: every seat is OUR own portfolio deck driven by the SAME deck-agnostic base pilot (meta sanity uses replay-derived surrogate opponents). They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

_Honesty mandate: attack damage/effect, lethal, KO target, spread placement, Boss/gust are UNSUPPORTED by the option schema (numeric attackId only); the typed layer refuses to fabricate them. Raging Bolt gets NO fake color-match fix (Pass 28 refuted it)._

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
