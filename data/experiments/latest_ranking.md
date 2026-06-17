# Candidate ranking — broad (scout)

| Rank | Branch | Seam | Score | Adj WR | 80% CI | Games | SeatΔ | Label |
|----:|--------|------|------:|-------:|--------|------:|------:|-------|
| 1 | deck_energy_trim_light | deck.energy_trim | 751.7 | 0.65 | 0.55–0.74 | 40 | -0.20 | promotable |
| 2 | policy_conservative_baseline | archetype.baseline_exploit | 723.5 | 0.60 | 0.50–0.69 | 40 | -0.30 | inconclusive |
| 3 | deck_energy_trim_medium | deck.energy_trim | 647.3 | 0.60 | 0.50–0.69 | 40 | +0.10 | inconclusive |
| 4 | combo_draw_search__baseline_consistency | combo.search_consistency | 626.1 | 0.50 | 0.27–0.73 | 6 | -0.33 | inconclusive |
| 5 | combo_evo_bias__baseline_consistency | combo.evolution_consistency | 566.2 | 0.50 | 0.27–0.73 | 6 | +0.33 | inconclusive |
| 6 | combo_evo_attack__baseline_consistency | combo.evolution_attack_consistency | 560.3 | 0.50 | 0.27–0.73 | 6 | +0.33 | inconclusive |
| 7 | combo_evo_pass__baseline_consistency | combo.evolution_pass_consistency | 552.5 | 0.50 | 0.27–0.73 | 6 | +0.33 | inconclusive |
| 8 | policy_pass_avoidant | policy.pass_avoidance | 549.3 | 0.42 | 0.33–0.53 | 40 | -0.15 | inconclusive |
| 9 | deck_baseline_consistency | deck.consistency_engine | 542.0 | 0.50 | 0.27–0.73 | 6 | -1.00 | inconclusive |
| 10 | policy_energy_bias | policy.energy_priority | 459.7 | 0.38 | 0.28–0.48 | 40 | +0.05 | inconclusive |
| 11 | policy_setup_evolution | archetype.setup_evolution | 437.2 | 0.35 | 0.26–0.45 | 40 | -0.20 | inconclusive |
| 12 | combo_setup_evo__energy_trim_medium | combo.setup_archetype_trim | 427.7 | 0.33 | 0.15–0.59 | 6 | -0.67 | inconclusive |
| 13 | combo_energy_bias__energy_trim_light | combo.energy_priority_trim | 411.9 | 0.33 | 0.15–0.59 | 6 | +0.67 | inconclusive |
| 14 | combo_evo_attack__energy_trim_medium | combo.evolution_attack_energy_trim | 411.2 | 0.33 | 0.15–0.59 | 6 | +0.00 | inconclusive |
| 15 | combo_evo_pass__energy_trim_medium | combo.evolution_pass_energy_trim | 405.9 | 0.33 | 0.15–0.59 | 6 | +0.00 | inconclusive |
| 16 | policy_draw_search_bias | policy.search_targeting | 397.9 | 0.33 | 0.15–0.59 | 6 | -0.67 | inconclusive |
| 17 | policy_attack_heavy | policy.attack_priority | 397.7 | 0.33 | 0.15–0.59 | 6 | -0.67 | inconclusive |
| 18 | policy_evolution_bias | policy.evolution_priority | 247.2 | 0.17 | 0.05–0.43 | 6 | -0.33 | inconclusive |
| 19 | combo_evo_bias__energy_trim_medium | combo.evolution_energy_trim | 235.5 | 0.17 | 0.05–0.43 | 6 | -0.33 | inconclusive |

## Interpretations
- **deck_energy_trim_light** (promotable): Adjusted win rate 0.65 over 40 games with an 80% lower bound of 0.55 (> 0.50) and beats the control (0.60). Strong enough to queue for manual review.
- **policy_conservative_baseline** (inconclusive): Control anchor (adjusted win rate 0.60 over 40 games); used as the comparison baseline, not a promotion target.
- **deck_energy_trim_medium** (inconclusive): Adjusted win rate 0.60 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **combo_draw_search__baseline_consistency** (inconclusive): Adjusted win rate 0.50 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_bias__baseline_consistency** (inconclusive): Adjusted win rate 0.50 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_attack__baseline_consistency** (inconclusive): Adjusted win rate 0.50 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_pass__baseline_consistency** (inconclusive): Adjusted win rate 0.50 over 6 games is not distinguishable from the control at this sample size.
- **policy_pass_avoidant** (inconclusive): Adjusted win rate 0.42 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **deck_baseline_consistency** (inconclusive): Adjusted win rate 0.50 over 6 games is not distinguishable from the control at this sample size.
- **policy_energy_bias** (inconclusive): Adjusted win rate 0.38 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **policy_setup_evolution** (inconclusive): Adjusted win rate 0.35 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **combo_setup_evo__energy_trim_medium** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **combo_energy_bias__energy_trim_light** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_attack__energy_trim_medium** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_pass__energy_trim_medium** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **policy_draw_search_bias** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **policy_attack_heavy** (inconclusive): Adjusted win rate 0.33 over 6 games is not distinguishable from the control at this sample size.
- **policy_evolution_bias** (inconclusive): Adjusted win rate 0.17 over 6 games is not distinguishable from the control at this sample size.
- **combo_evo_bias__energy_trim_medium** (inconclusive): Adjusted win rate 0.17 over 6 games is not distinguishable from the control at this sample size.
