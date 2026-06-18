# Candidate ranking — pass 5 scout (replay-informed board-aware, seat-swap)

| Rank | Branch | Seam | Score | Adj WR | 80% CI | Games | SeatΔ | Label |
|----:|--------|------|------:|-------:|--------|------:|------:|-------|
| 1 | pass5_control_v2_anchor | archetype.baseline_exploit | 1107.2 | 1.00 | 0.55–1.00 | 2 | +0.00 | inconclusive |
| 2 | policy_ultra_ball_v2 | policy.ultra_ball_discard_and_search | 831.6 | 0.70 | 0.50–0.85 | 10 | -0.20 | scout_promising |
| 3 | policy_secret_box_v2 | policy.secret_box_mode_selection | 772.2 | 0.70 | 0.50–0.85 | 10 | -0.20 | scout_promising |
| 4 | policy_effect_resolution_v2 | policy.effect_resolution_targeting | 678.4 | 0.60 | 0.40–0.77 | 10 | -0.40 | scout_promising |
| 5 | combo_effect_resolution_v2__deckout_guard | combo.effect_resolution_deckout | 609.1 | 0.50 | 0.31–0.69 | 10 | -0.20 | inconclusive |
| 6 | policy_setup_snover_active | policy.setup_active_choice | 577.5 | 0.50 | 0.31–0.69 | 10 | -0.20 | inconclusive |
| 7 | policy_deckout_guard_v1 | policy.deckout_awareness | 371.2 | 0.30 | 0.15–0.50 | 10 | +0.20 | inconclusive |
| 8 | policy_setup_hybrid | policy.setup_active_choice | 368.2 | 0.30 | 0.15–0.50 | 10 | -0.20 | inconclusive |
| 9 | policy_setup_kyogre_active | policy.setup_active_choice | 367.1 | 0.30 | 0.15–0.50 | 10 | -0.60 | inconclusive |
| 10 | policy_setup_evolution | archetype.setup_evolution | 293.9 | 0.20 | 0.09–0.40 | 10 | +0.40 | inconclusive |
| 11 | combo_setup_evo__energy_trim_medium | combo.setup_archetype_trim | 292.0 | 0.20 | 0.09–0.40 | 10 | +0.40 | inconclusive |
| 12 | policy_mega_signal_v2 | policy.mega_signal_evolution_search | 278.1 | 0.20 | 0.09–0.40 | 10 | +0.00 | inconclusive |

## Interpretations
- **pass5_control_v2_anchor** (inconclusive): Control anchor (adjusted win rate 1.00 over 2 games); used as the comparison baseline, not a promotion target.
- **policy_ultra_ball_v2** (scout_promising): Scout-level signal (adjusted 0.70 over only 10 games); needs a focused, higher-game confirmation before promotion.
- **policy_secret_box_v2** (scout_promising): Scout-level signal (adjusted 0.70 over only 10 games); needs a focused, higher-game confirmation before promotion.
- **policy_effect_resolution_v2** (scout_promising): Scout-level signal (adjusted 0.60 over only 10 games); needs a focused, higher-game confirmation before promotion.
- **combo_effect_resolution_v2__deckout_guard** (inconclusive): Adjusted win rate 0.50 over 10 games is not distinguishable from the control at this sample size.
- **policy_setup_snover_active** (inconclusive): Adjusted win rate 0.50 over 10 games is not distinguishable from the control at this sample size.
- **policy_deckout_guard_v1** (inconclusive): Adjusted win rate 0.30 over 10 games is not distinguishable from the control at this sample size.
- **policy_setup_hybrid** (inconclusive): Adjusted win rate 0.30 over 10 games is not distinguishable from the control at this sample size.
- **policy_setup_kyogre_active** (inconclusive): Adjusted win rate 0.30 over 10 games is not distinguishable from the control at this sample size.
- **policy_setup_evolution** (inconclusive): Adjusted win rate 0.20 over 10 games is not distinguishable from the control at this sample size.
- **combo_setup_evo__energy_trim_medium** (inconclusive): Adjusted win rate 0.20 over 10 games is not distinguishable from the control at this sample size.
- **policy_mega_signal_v2** (inconclusive): Adjusted win rate 0.20 over 10 games is not distinguishable from the control at this sample size.
