# Candidate ranking — focused (seat-swap confirmation)

| Rank | Branch | Seam | Score | Adj WR | 80% CI | Games | SeatΔ | Label |
|----:|--------|------|------:|-------:|--------|------:|------:|-------|
| 1 | deck_energy_trim_light | deck.energy_trim | 751.7 | 0.65 | 0.55–0.74 | 40 | -0.20 | promotable |
| 2 | policy_conservative_baseline | archetype.baseline_exploit | 723.5 | 0.60 | 0.50–0.69 | 40 | -0.30 | inconclusive |
| 3 | deck_energy_trim_medium | deck.energy_trim | 647.3 | 0.60 | 0.50–0.69 | 40 | +0.10 | inconclusive |
| 4 | policy_pass_avoidant | policy.pass_avoidance | 549.3 | 0.42 | 0.33–0.53 | 40 | -0.15 | inconclusive |
| 5 | policy_energy_bias | policy.energy_priority | 459.7 | 0.38 | 0.28–0.48 | 40 | +0.05 | inconclusive |
| 6 | policy_setup_evolution | archetype.setup_evolution | 437.2 | 0.35 | 0.26–0.45 | 40 | -0.20 | inconclusive |

## Interpretations
- **deck_energy_trim_light** (promotable): Adjusted win rate 0.65 over 40 games with an 80% lower bound of 0.55 (> 0.50) and beats the control (0.60). Strong enough to queue for manual review.
- **policy_conservative_baseline** (inconclusive): Control anchor (adjusted win rate 0.60 over 40 games); used as the comparison baseline, not a promotion target.
- **deck_energy_trim_medium** (inconclusive): Adjusted win rate 0.60 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **policy_pass_avoidant** (inconclusive): Adjusted win rate 0.42 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **policy_energy_bias** (inconclusive): Adjusted win rate 0.38 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
- **policy_setup_evolution** (inconclusive): Adjusted win rate 0.35 over 40 games does not beat the control (0.60); confirmed as no improvement at this sample size.
