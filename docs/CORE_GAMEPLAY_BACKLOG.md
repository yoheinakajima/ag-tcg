# Core Gameplay Backlog (Pass 28)

> Evidence-gated roadmap. **No upload** is the default for every item. Internal-league evidence is our-vs-our, NOT the Kaggle leaderboard.

- **top proven gap:** `effect_loop_termination`
- **rejected (refuted by trace):** color_match_attach, attack_pressure
- No deck-AGNOSTIC high-confidence core-rule gap is proven by the trace. The Pass-27 color/attack hypotheses are refuted. The highest-evidence proven gaps are DECK-SPECIFIC (venusaur effect loop, durant init/mill); the remaining generic suspicions are UNOBSERVABLE and need more diagnostics.

### A. Immediate core rules (if evidence supports)

| item | evidence | scope | risk | tests | validation deck | recommended |
|---|---|---|---|---|---|---|
| color-matched energy attachment | REJECTED — 0 off-deck-plan attaches across all decks | none (already correct) | n/a | regression: assert on-plan attach holds | league_raging_bolt_ogerpon (positive control) | False |
| attack pressure | REJECTED — 0 attack-available-not-taken across all decks | none (already correct) | n/a | regression: assert attack-when-able holds | all league decks (positive control) | False |
| evolution sequencing | MEDIUM — charizard first attack median step 6 / min 4 (on tempo in most games, long tail of stalled Mega-line games) | evolution-path planning + Rare Candy use; blocked on play_from_hand identity observability | medium | fx_evolution_sequencing_speed | league_mega_charizard_x_burst | False |
| search target planning | UNKNOWN — search choices not surfaced in option schema | needs observability first | low | observability harness | any | False |
| discard safety | UNKNOWN — discard choices not surfaced | needs observability first | low | observability harness | any | False |

### B. Requires more observability

| item | evidence | scope | risk | tests | validation deck | recommended |
|---|---|---|---|---|---|---|
| spread targeting | dragapult targets not surfaced | extend trace to capture attack sub-targets | low | observability assertion | league_dragapult_spread | True |
| retreat/switch | switch choice not surfaced | capture in_play_action sub-type | low | observability assertion | any | True |
| prize race | prize_count present; no policy observed | derive prize-race features | low | observability assertion | any | True |
| lethal counting | all-in timing not surfaced | capture damage/HP state in trace | medium | observability assertion | league_raging_bolt_ogerpon | True |

### C. Requires deck-specific / special pilot

| item | evidence | scope | risk | tests | validation deck | recommended |
|---|---|---|---|---|---|---|
| Raging Bolt all-in energy-discard attack | attacks fire every turn but energy-discard scaling not surfaced; loss is structural, not pilot color/attack | deck-specific pilot IF a generic rule is infeasible | medium | fx (blocked on observability) | league_raging_bolt_ogerpon | False |
| Charizard all-in energy-discard attack | high-variance setup (first attack median step 6 / min 4, long tail of stalled games); combo engine not accelerated | deck-specific pilot | medium | fx_evolution_sequencing_speed | league_mega_charizard_x_burst | False |
| Gardevoir ramp | ramp ability under-used | ramp-aware deck-specific pilot | medium | fx_ramp_sequencing | league_mega_gardevoir_psychic_ramp | False |
| Venusaur effect-loop termination | ~1957-iteration forced-effect loop; near-zero attacks | generic effect-loop termination policy (highest-evidence proven gap) | medium | fx_effect_loop_termination | league_mega_venusaur_tank | True |
| Durant deckout/chaos | INVALID at engine init; never reaches turn 1 | init-legality fix + special deckout pilot | high | fx_mill_deckout_init_legality | league_durant_deckout_carousel | False |
