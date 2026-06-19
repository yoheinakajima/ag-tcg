# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 30.

_The internal tournament, parent/child confirmations and meta sanity are LOCAL diagnostics: both seats are OUR portfolio decks driven by the SAME generic core pilot, run subprocess-isolated and seat-swapped. They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

## Current live reference (Kaggle, read-only)

- live_score_leader: `league_water_anti_disruption_pivot_v1.tar.gz` @ 376.5
- water_family_current_best: `league_water_anti_disruption_pivot_v1.tar.gz` @ 376.5
- portfolio_reference: `league_water_core_reference.tar.gz` @ 222.3
- distinction preserved: yes

## Pass 30 — existing portfolio hardening tournament

We hardened and ranked OUR existing portfolio to pick the next human-approved probe. Internal Stage-1 standings (NOT Kaggle):

| rank | candidate | family | adj win_rate | label |
|---|---|---|---|---|
| 1 | league_water_core_reference | water | 74.3% | strong_reference |
| 2 | league_dragapult_v1_search_only | dragapult | 72.5% | candidate_for_confirmation |
| 3 | league_mega_charizard_x_burst | charizard | 72.2% | keep_as_benchmark |
| 4 | league_dragapult_v1_draw_only | dragapult | 70.6% | candidate_for_confirmation |
| 5 | league_water_anti_disruption_pivot_v1 | water | 69.0% | strong_reference |
| 6 | league_dragapult_spread | dragapult | 68.6% | candidate_for_confirmation |
| 7 | effect_loop_exit_guard_v1 | venusaur | 60.6% | candidate_for_confirmation |
| 8 | core_pilot_water_v2_runtime | water | 60.0% | strong_reference |
| 9 | league_mega_venusaur_tank | venusaur | 43.4% | legal_but_weak |
| 10 | league_mega_gardevoir_psychic_ramp | gardevoir | 26.8% | keep_as_benchmark |
| 11 | league_raging_bolt_consistency_v1 | raging_bolt | 13.2% | needs_special_pilot |
| 12 | league_raging_bolt_ogerpon | raging_bolt | 11.1% | needs_special_pilot |
| 13 | league_raging_bolt_energy_attacker_v1 | raging_bolt | 7.0% | needs_special_pilot |

## Family hardening verdicts

| family | action | helped | stay active | best deck |
|---|---|---|---|---|
| water | reuse_benchmark_only | None | True | league_water_core_reference |
| dragapult | reuse_confirm_children | True | True | league_dragapult_v1_search_only |
| venusaur | reuse_runtime_loop_guard | True | True | effect_loop_exit_guard_v1 |
| raging_bolt | built_two_new_structural_variants | False | False | league_raging_bolt_consistency_v1 |
| diagnostics | reuse_as_benchmark | None | True | league_mega_charizard_x_burst |

## Meta sanity (directional, surrogate)

- best: `league_dragapult_v1_search_only` @ 85.1% (> water 64.0%)
- collapses: league_raging_bolt_ogerpon (Raging Bolt = expected control)

## Next move

`Queue league_dragapult_v1_search_only as the single HELD dry-run probe candidate, pending human approval. No upload/submit performed.` Stop building Raging Bolt decklists — its next move is a PILOT/policy change. Keep Water as the always-on benchmark.
