# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 27.

_The internal league is a LOCAL surrogate (our own decks, one generic core pilot, subprocess-isolated, seat-swapped). It is NOT the Kaggle leaderboard and is NOT a promotion signal._

## Current live reference (Kaggle)

- live_score_leader: `league_water_anti_disruption_pivot_v1.tar.gz` @ 376.5
- water_family_current_best: `league_water_anti_disruption_pivot_v1.tar.gz` @ 376.5
- distinction preserved: True

## Pass 27 — multi-archetype portfolio

The generic core pilot was applied unchanged across 7 archetypes to find where it breaks. Internal league standings (surrogate, not Kaggle):

| rank | deck | adj win rate | record |
|---|---|---|---|
| 1 | league_water_core_reference | 0.8286 | 29-6-1 |
| 2 | core_pilot_water_v2_runtime | 0.7429 | 26-9-1 |
| 3 | league_dragapult_spread | 0.7059 | 24-10-2 |
| 4 | league_mega_charizard_x_burst | 0.5312 | 17-15-4 |
| 5 | league_mega_venusaur_tank | 0.5 | 13-13-10 |
| 6 | league_mega_gardevoir_psychic_ramp | 0.1944 | 7-29-0 |
| 7 | league_raging_bolt_ogerpon | 0.0 | 0-34-2 |

## Open core-pilot gaps (priority order)

- **color-matched energy attachment** (deck-agnostic, highest)
- **spread/bench target planning** (deck-specific, high)
- **combo/ramp sequencing** (deck-agnostic, high)
- **lethal counting / all-in attack timing** (deck-agnostic, high)
- **prize-race awareness** (deck-specific, medium)
- **mill/deckout win condition** (deck-specific, medium)
- **recovery/recursion** (deck-specific, low)

## Next move

`build_aggro_core_rules_next` — color-matched energy attachment; then `expand_deck_portfolio`. Keep Water as the live reference.
