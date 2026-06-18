# policy_setup_kyogre_active

- **Seam:** policy.setup_active_choice
- **Kind:** combo    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Opening setup: prefer placing Kyogre (721) during opening placement prompts as a standalone basic attacker that does not depend on an evolution line being assembled first.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 3 / 7 / 0
- raw win rate: 0.30    adjusted win rate: 0.30
- as P0: 0/5 (rate 0.00); as P1: 3/5 (rate 0.60)
- seat balance delta (P0-P1): -0.60
- attack rate: 0.57    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
