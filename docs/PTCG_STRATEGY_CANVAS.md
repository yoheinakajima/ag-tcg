# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 28.

_The cross-deck forensic trace is a LOCAL diagnostic: both seats are OUR portfolio decks driven by the SAME generic core pilot, run subprocess-isolated and seat-swapped. It measures what ACTIONS the pilot takes — it is NOT the Kaggle leaderboard and is NOT a promotion signal._

## Current live reference (Kaggle)

- live_score_leader: `league_water_anti_disruption_pivot_v1.tar.gz` @ 376.5
- portfolio_reference (Water): `league_water_core_reference.tar.gz` @ 222.3
- distinction preserved: True

## Pass 28 — cross-deck forensic trace

The generic core pilot was traced unchanged across every portfolio deck to find which MECHANICS it fails. Per-deck action-trace diagnosis:

| deck | decisions | attacks | first attack | classification |
|---|---|---|---|---|
| water | 588 | 211 | median step 8 | ? |
| dragapult | 474 | 113 | median step 14 | ? |
| raging_bolt | 346 | 104 | median step 6 | deck_skeleton / structural_bad_matchup |
| gardevoir | 357 | 234 | median step 5 | ramp sequencing (ramp engine under-used) — NOT attack timing (it attacks early and often); secondary deck_skeleton |
| charizard | 782 | 72 | median step 6 | high-variance combo setup vs generic pilot — typically attacks early (median step 6) but a long tail of stalled games where the Mega line never comes online; generic pilot does not accelerate the combo (partial support, not a clean uniform-slow failure) |
| venusaur | 5957 | 18 | median step 7 | unsupported_mechanic — effect-loop termination: the generic pilot cannot exit a repeated forced/optional effect (contexts 33+21), so it rarely reaches an attack; deck-specific |
| durant | ? | ? | median step ? | simulator_legality_issue + deck_structural_problem |

## Open core-pilot gaps (priority order)

- **effect_loop_termination** (high) — league_mega_venusaur_tank
- **mill_deckout_unsupported** (high (failure) / unknown (whether a legal line exists)) — league_durant_deckout_carousel
- **ramp_sequencing** (medium) — league_mega_gardevoir_psychic_ramp
- **evolution_sequencing_speed** (medium) — league_mega_charizard_x_burst
- **spread_target_selection_observability** (unknown -> need_more_diagnostics) — league_dragapult_spread
- **engine_card_play_observability** (unknown -> need_more_diagnostics) — league_raging_bolt_ogerpon

## Refuted hypotheses (proven wrong by trace)

- ~~color_match_attach~~ — 0 off-deck-plan attaches across ALL decks; raging_bolt attaches only L/F/G (its plan) and Bellowing Thunder discards F+L from across the board, so F/L on Ogerpon still feeds the plan
- ~~attack_pressure~~ — 0 attack-available-not-taken across ALL decks; raging_bolt attacks 104x from step 6

## Next move

`gather_more_traces` — action-trace OBSERVABILITY for attack-target / spread-target / search-target / supporter-card selection (resolve play_from_hand + attack sub-target identity). Validate on `league_mega_venusaur_tank`; keep Water as the live reference.
