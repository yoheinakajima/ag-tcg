# PTCG Strategy Canvas

> Living strategy canvas. Updated through Pass 34.

_The internal new-deck tournament and the replay-derived meta sanity are LOCAL diagnostics: both seats are OUR portfolio decks driven by the SAME deck-agnostic generic pilot (meta sanity uses replay-derived surrogate opponents). They are NOT the Kaggle leaderboard and are NOT a promotion or upload signal._

## Current live reference (Kaggle, read-only)

- live_score_leader: `league_dragapult_v1_search_only.tar.gz` @ 380.2
- water_family_current_best: `league_water_anti_disruption_pivot_v1.tar.gz` @ 340.0
- dragapult_family_best: `league_dragapult_v1_search_only.tar.gz` @ 380.2 (above water: yes)
- portfolio_reference: `league_water_core_reference.tar.gz` @ 219.5

## Pass 34 — new-deck intake + lane split

Four new families ingested and split into two lanes. Internal tournament standings (NOT Kaggle):

| rank | candidate | family | lane | adj win_rate | label |
|---|---|---|---|---|---|
| 1 | water_basic_density_v1 | water | benchmark | 73.2% | strong_benchmark |
| 2 | league_water_anti_disruption_pivot_v1 | water | benchmark | 68.3% | strong_benchmark |
| 3 | league_dragapult_v1_search_only | dragapult | benchmark | 67.5% | strong_benchmark |
| 4 | mono_lightning_miraidon_easy | miraidon_new | normal | 50.0% | promising_but_noisy |
| 5 | diamond_toolbox_diancie | diamond_new | normal | 48.8% | below_benchmark |
| 6 | league_mega_charizard_x_burst | charizard | benchmark | 48.7% | below_benchmark |
| 7 | league_mega_venusaur_tank | venusaur | benchmark | 40.6% | below_benchmark |
| 8 | league_mega_gardevoir_psychic_ramp | gardevoir | benchmark | 2.4% | legal_but_weak |

## Lanes

- **Normal lane (built + tournament-eligible):** `mono_lightning_miraidon_easy`, `diamond_toolbox_diancie`
- **Special-pilot lane (legal decklist, pilot-blocked):** `toxic_trap_poison_lock`, `deckout_carousel_durant_v2`

## Meta sanity (directional, surrogate)

- sanity_passed: no; best: `water_basic_density_v1` @ 90.0%
- new decks collapses: Miraidon none, Diamond none

## Next move

`Keep water_basic_density_v1 as the single HELD dry-run probe (re-affirmed by Pass 34). Label Miraidon/Diamond candidate_for_confirmation (clean but not tournament-strong; not queued). Open special-pilot tasks for Toxic (priority 1) and Durant (priority 2). No upload/submit performed.` Keep `water_basic_density_v1` as the held probe (rank 1, no collapse). Miraidon/Diamond = candidate_for_confirmation. Open special-pilot sprint for Toxic (P1) and Durant (P2). Dragapult stays the non-Water reference.
