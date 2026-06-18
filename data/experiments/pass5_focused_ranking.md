# Candidate ranking — pass 5 focused (board-aware confirmation, seat-swap)

| Rank | Branch | Seam | Score | Adj WR | 80% CI | Games | SeatΔ | Label |
|----:|--------|------|------:|-------:|--------|------:|------:|-------|
| 1 | pass5_control_v2_anchor | archetype.baseline_exploit | 718.0 | 0.60 | 0.50–0.69 | 40 | -0.20 | inconclusive |
| 2 | pass4_control_v2_anchor | archetype.baseline_exploit | 555.6 | 0.47 | 0.38–0.58 | 40 | +0.05 | inconclusive |
| 3 | policy_effect_resolution_v2 | policy.effect_resolution_targeting | 539.7 | 0.42 | 0.33–0.53 | 40 | -0.35 | inconclusive |
| 4 | policy_conservative_baseline | archetype.baseline_exploit | 532.2 | 0.45 | 0.35–0.55 | 40 | -0.50 | inconclusive |
| 5 | policy_ultra_ball_v2 | policy.ultra_ball_discard_and_search | 476.1 | 0.40 | 0.31–0.50 | 40 | +0.00 | inconclusive |

## Interpretations
- **pass5_control_v2_anchor** (inconclusive): Control anchor (adjusted win rate 0.60 over 40 games); used as the comparison baseline, not a promotion target.
- **pass4_control_v2_anchor** (inconclusive): Control anchor (adjusted win rate 0.47 over 40 games); used as the comparison baseline, not a promotion target.
- **policy_effect_resolution_v2** (inconclusive): Adjusted win rate 0.42 over 40 games does not beat the control (0.45); confirmed as no improvement at this sample size.
- **policy_conservative_baseline** (inconclusive): Control anchor (adjusted win rate 0.45 over 40 games); used as the comparison baseline, not a promotion target.
- **policy_ultra_ball_v2** (inconclusive): Adjusted win rate 0.40 over 40 games does not beat the control (0.45); confirmed as no improvement at this sample size.
