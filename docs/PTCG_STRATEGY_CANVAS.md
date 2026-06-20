# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 33.

_The internal composition tournament, correlations, parent/child confirmations and meta sanity are LOCAL diagnostics: both seats are OUR portfolio decks driven by the SAME generic core pilot (meta sanity uses replay-derived surrogate opponents). They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

## Current live reference (Kaggle, read-only)

- live_score_leader: `submission.tar.gz` @ 363.0
- water_family_current_best: `league_water_anti_disruption_pivot_v1.tar.gz` @ 340.0
- dragapult_family_best: `league_dragapult_v1_search_only.tar.gz` @ 306.7 (above water: no)
- portfolio_reference: `league_water_core_reference.tar.gz` @ 219.5

## Pass 33 — deck composition stress test

We stress-tested OUR portfolio by composition to pick the next human-approved probe. Internal Stage-1 standings (NOT Kaggle):

| rank | candidate | family | adj win_rate | label |
|---|---|---|---|---|
| 1 | core_pilot_water_v2_runtime | water | 71.0% | strong_reference |
| 2 | league_water_core_reference | water | 70.8% | strong_reference |
| 3 | water_basic_density_v1 | water | 67.2% | density_variant_under_test |
| 4 | water_basic_density_v2 | water | 67.2% | density_variant_under_test |
| 5 | league_dragapult_spread | dragapult | 60.9% | candidate_for_confirmation |
| 6 | league_water_anti_disruption_pivot_v1 | water | 60.9% | strong_reference |
| 7 | league_dragapult_v1_search_only | dragapult | 58.5% | candidate_for_confirmation |
| 8 | league_mega_charizard_x_burst | charizard | 53.8% | keep_as_benchmark |
| 9 | effect_loop_exit_guard_v1 | venusaur | 47.7% | legal_but_weak |
| 10 | league_mega_venusaur_tank | venusaur | 25.0% | legal_but_weak |
| 11 | league_mega_gardevoir_psychic_ramp | gardevoir | 12.1% | keep_as_benchmark |
| 12 | league_raging_bolt_ogerpon | raging_bolt | 0.0% | needs_special_pilot |

## Water Basic-density ladder

| deck | Basics | no-Basic prob | internal adj win_rate |
|---|---|---|---|
| league_water_anti_disruption_pivot_v1 | 8 | 34.6% | 60.9% |
| water_basic_density_v1 | 12 | 19.1% | 67.2% |
| water_basic_density_v2 | 16 | 9.9% | 67.2% |

## Meta sanity (directional, surrogate)

- best: `league_mega_charizard_x_burst` @ 70.7%
- probe `water_basic_density_v1` collapses: none (Raging Bolt = expected control)

## Next move

`Queue water_basic_density_v1 as the single HELD dry-run probe candidate (candidate_for_deeper_confirmation), pending human approval. No upload/submit performed.` Hold `water_basic_density_v1` as a deeper-confirmation probe (halves mulligan risk, ties Water internally). Keep Water as the always-on benchmark; Dragapult stays a reference until it clears Water live.
