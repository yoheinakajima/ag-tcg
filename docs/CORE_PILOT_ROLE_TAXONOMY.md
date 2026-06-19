# Pass 27 — Role Taxonomy (Part D)

> LOCAL ONLY. One role vocabulary shared across all archetypes. Cards taken from the validated deck registry — no invented ids.

## Role vocabulary

- **pokemon**: `setup_basic`, `backup_basic`, `primary_basic_attacker`, `primary_evolution_attacker`, `secondary_attacker`, `evolution_mid`, `evolution_payoff`, `ramp_engine`, `draw_engine_pokemon`, `utility_pokemon`, `wall`, `mill_attacker`, `spread_attacker`, `finisher`
- **trainer**: `search_cards`, `draw_support`, `disruption`, `gust`, `recovery`, `rare_candy`, `stadium_engine`, `tool_damage`, `tool_defense`, `energy_search`, `energy_acceleration`, `switch_or_retreat`, `deck_conservation`, `recursion`, `chaos_payoff`
- **energy**: `primary_energy`, `secondary_energy`, `splash_energy`, `discard_fuel`, `ramp_fuel`

## Roles with NO generic-pilot runtime support

| role | why unsupported |
|---|---|
| `spread_attacker` | no bench-damage target selection; attacks default target |
| `ramp_engine` | no energy-ramp accumulation plan; attaches greedily/at random |
| `mill_attacker` | no deckout/mill win condition; races prizes instead |
| `finisher` | no lethal-counting/all-in timing; cannot recognise a closing turn |
| `chaos_payoff` | no chaos/stall win condition; will misplay the carousel |
| `recursion` | no recursion loop planning for a mill/value engine |
| `energy_acceleration` | attaches without a colour/scaling plan; cannot sequence selective acceleration |

## Per-deck role maps

### water_core_reference — `league_water_core_reference` (evolution_tempo_reference)
- buildable: True  blocked_from_league: False
- roles present: `draw_support`, `energy_acceleration`, `evolution_payoff`, `primary_basic_attacker`, `primary_energy`, `primary_evolution_attacker`, `search_cards`, `setup_basic`, `stadium_engine`, `tool_defense`
- **unsupported roles this deck leans on:** `energy_acceleration`

| card | name | n | roles |
|---|---|---|---|
| 3 | Basic {W} Energy | 29 | primary_energy |
| 721 | Kyogre | 4 | primary_basic_attacker |
| 722 | Snover | 4 | setup_basic |
| 723 | Mega Abomasnow ex | 4 | evolution_payoff, primary_evolution_attacker |
| 1092 | Secret Box | 1 | search_cards |
| 1121 | Ultra Ball | 4 | search_cards |
| 1145 | Mega Signal | 2 | search_cards |
| 1163 | Powerglass | 2 | energy_acceleration, tool_defense |
| 1219 | Team Rocket's Petrel | 4 | draw_support |
| 1227 | Lillie's Determination | 4 | draw_support |
| 1262 | Surfing Beach | 2 | stadium_engine |

### raging_bolt_ogerpon_basic_aggro — `league_raging_bolt_ogerpon` (basic_aggro)
- buildable: True  blocked_from_league: False
- roles present: `draw_engine_pokemon`, `draw_support`, `energy_acceleration`, `energy_search`, `finisher`, `gust`, `primary_basic_attacker`, `primary_energy`, `recovery`, `search_cards`, `secondary_attacker`, `secondary_energy`, `splash_energy`
- **unsupported roles this deck leans on:** `energy_acceleration`, `finisher`

| card | name | n | roles |
|---|---|---|---|
| 63 | Raging Bolt ex | 4 | primary_basic_attacker, finisher |
| 96 | Teal Mask Ogerpon ex | 4 | secondary_attacker, draw_engine_pokemon |
| 1198 | Crispin | 4 | energy_search, energy_acceleration |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1224 | Cheren | 4 | draw_support |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 1182 | Boss's Orders | 4 | gust |
| 1097 | Night Stretcher | 4 | recovery |
| 6 | Basic {F} Energy | 13 | primary_energy |
| 4 | Basic {L} Energy | 8 | secondary_energy |
| 1 | Basic {G} Energy | 3 | splash_energy |

### dragapult_spread_control — `league_dragapult_spread` (evolution_control)
- buildable: True  blocked_from_league: False
- roles present: `draw_support`, `energy_acceleration`, `evolution_mid`, `evolution_payoff`, `gust`, `primary_energy`, `rare_candy`, `recovery`, `search_cards`, `secondary_energy`, `setup_basic`, `spread_attacker`, `utility_pokemon`
- **unsupported roles this deck leans on:** `energy_acceleration`, `spread_attacker`

| card | name | n | roles |
|---|---|---|---|
| 119 | Dreepy | 4 | setup_basic |
| 120 | Drakloak | 3 | evolution_mid |
| 121 | Dragapult ex | 4 | evolution_payoff, spread_attacker |
| 131 | Duskull | 2 | setup_basic, utility_pokemon |
| 133 | Dusknoir | 2 | utility_pokemon, spread_attacker |
| 1079 | Rare Candy | 4 | rare_candy |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1224 | Cheren | 4 | draw_support |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 1182 | Boss's Orders | 4 | gust |
| 1097 | Night Stretcher | 4 | recovery |
| 5 | Basic {P} Energy | 11 | primary_energy |
| 2 | Basic {R} Energy | 6 | secondary_energy |

### durant_deckout_carousel — `league_durant_deckout_carousel` (chaos_mill_control)
- buildable: True  blocked_from_league: True
- roles present: `chaos_payoff`, `disruption`, `draw_engine_pokemon`, `draw_support`, `energy_acceleration`, `evolution_mid`, `gust`, `mill_attacker`, `primary_energy`, `recovery`, `recursion`, `search_cards`, `secondary_attacker`, `setup_basic`, `stadium_engine`, `utility_pokemon`, `wall`
- **unsupported roles this deck leans on:** `chaos_payoff`, `energy_acceleration`, `mill_attacker`, `recursion`

| card | name | n | roles |
|---|---|---|---|
| 198 | Durant ex | 4 | mill_attacker |
| 227 | Deino | 4 | setup_basic |
| 228 | Zweilous | 4 | evolution_mid, wall |
| 1247 | Neutralization Zone | 4 | stadium_engine, chaos_payoff |
| 162 | Slowpoke | 4 | utility_pokemon |
| 27 | Iron Leaves | 2 | secondary_attacker, utility_pokemon |
| 815 | Whimsicott | 4 | draw_engine_pokemon, utility_pokemon |
| 1199 | Lacey | 4 | draw_support |
| 1228 | Acerola's Mischief | 2 | recursion, recovery |
| 1213 | Judge | 4 | disruption, draw_support |
| 1182 | Boss's Orders | 4 | gust |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 7 | Basic {D} Energy | 8 | primary_energy |

### mega_gardevoir_psychic_ramp — `league_mega_gardevoir_psychic_ramp` (evolution_ramp)
- buildable: True  blocked_from_league: False
- roles present: `disruption`, `draw_support`, `energy_acceleration`, `evolution_mid`, `evolution_payoff`, `finisher`, `gust`, `primary_energy`, `ramp_engine`, `rare_candy`, `recovery`, `search_cards`, `setup_basic`
- **unsupported roles this deck leans on:** `energy_acceleration`, `finisher`, `ramp_engine`

| card | name | n | roles |
|---|---|---|---|
| 745 | Ralts | 4 | setup_basic |
| 746 | Kirlia | 4 | evolution_mid, ramp_engine |
| 747 | Mega Gardevoir ex | 3 | evolution_payoff, finisher, ramp_engine |
| 1079 | Rare Candy | 4 | rare_candy |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 1182 | Boss's Orders | 3 | gust |
| 1097 | Night Stretcher | 2 | recovery |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1224 | Cheren | 4 | draw_support |
| 1199 | Lacey | 2 | draw_support |
| 1213 | Judge | 2 | disruption, draw_support |
| 5 | Basic {P} Energy | 20 | primary_energy |

### mega_charizard_x_burst — `league_mega_charizard_x_burst` (evolution_burst)
- buildable: True  blocked_from_league: False
- roles present: `backup_basic`, `draw_support`, `energy_acceleration`, `energy_search`, `evolution_mid`, `evolution_payoff`, `finisher`, `gust`, `primary_energy`, `rare_candy`, `recovery`, `search_cards`, `secondary_attacker`, `setup_basic`
- **unsupported roles this deck leans on:** `energy_acceleration`, `finisher`

| card | name | n | roles |
|---|---|---|---|
| 788 | Charmander | 4 | setup_basic |
| 789 | Charmeleon | 3 | evolution_mid |
| 790 | Mega Charizard X ex | 3 | evolution_payoff, finisher |
| 795 | Oricorio ex | 2 | backup_basic, secondary_attacker |
| 1232 | Firebreather | 3 | energy_acceleration |
| 1198 | Crispin | 3 | energy_search, energy_acceleration |
| 1079 | Rare Candy | 4 | rare_candy |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 1182 | Boss's Orders | 3 | gust |
| 1097 | Night Stretcher | 2 | recovery |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1224 | Cheren | 3 | draw_support |
| 2 | Basic {R} Energy | 18 | primary_energy |

### mega_venusaur_tank — `league_mega_venusaur_tank` (evolution_tank)
- buildable: True  blocked_from_league: False
- roles present: `draw_support`, `energy_acceleration`, `evolution_mid`, `evolution_payoff`, `gust`, `primary_energy`, `rare_candy`, `recovery`, `search_cards`, `setup_basic`, `stadium_engine`, `wall`
- **unsupported roles this deck leans on:** `energy_acceleration`

| card | name | n | roles |
|---|---|---|---|
| 650 | Bulbasaur | 4 | setup_basic |
| 651 | Ivysaur | 3 | evolution_mid |
| 652 | Mega Venusaur ex | 3 | evolution_payoff, wall |
| 1261 | Forest of Vitality | 2 | stadium_engine, energy_acceleration |
| 1079 | Rare Candy | 4 | rare_candy |
| 1121 | Ultra Ball | 4 | search_cards |
| 1086 | Buddy-Buddy Poffin | 4 | search_cards |
| 1182 | Boss's Orders | 3 | gust |
| 1097 | Night Stretcher | 2 | recovery |
| 1231 | Dawn | 4 | draw_support, energy_acceleration |
| 1224 | Cheren | 4 | draw_support |
| 1199 | Lacey | 2 | draw_support |
| 1 | Basic {G} Energy | 21 | primary_energy |

_Unsupported roles mean the generic pilot can legally place the card but does not pilot the role's intent; they are the direct input to the Part-J core gameplay gap analysis._
