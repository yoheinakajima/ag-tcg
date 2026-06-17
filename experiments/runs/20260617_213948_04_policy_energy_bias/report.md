# policy_energy_bias

- **Seam:** policy.energy_priority
- **Kind:** policy    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** focused

## Hypothesis
Prioritising attach/energy (and placement type 8) when no attack is available should accelerate powering up attackers.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 15 / 25 / 0
- raw win rate: 0.38    adjusted win rate: 0.38
- as P0: 8/20 (rate 0.40); as P1: 7/20 (rate 0.35)
- seat balance delta (P0-P1): 0.05
- attack rate: 0.73    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
