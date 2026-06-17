# combo_evo_pass__baseline_consistency

- **Seam:** combo.evolution_pass_consistency
- **Kind:** combo    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** broad

## Hypothesis
Stacking evolution-priority and pass-avoidance over the consistency deck should keep the agent acting AND setting up, compounding two scout leaders.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 6 (seat-swap: True)
- wins / losses / draws: 3 / 3 / 0
- raw win rate: 0.50    adjusted win rate: 0.50
- as P0: 2/3 (rate 0.67); as P1: 1/3 (rate 0.33)
- seat balance delta (P0-P1): 0.33
- attack rate: 0.47    pass rate: 0.04
- crashes / timeouts / fallbacks: 0 / 0 / 0
