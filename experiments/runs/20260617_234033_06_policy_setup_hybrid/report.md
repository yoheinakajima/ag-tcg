# policy_setup_hybrid

- **Seam:** policy.setup_active_choice
- **Kind:** combo    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Opening setup (hybrid): prefer the Snover (722) line first but also value Kyogre (721) during placement, so the opening keeps both the evolution line and a standalone attacker available.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 3 / 7 / 0
- raw win rate: 0.30    adjusted win rate: 0.30
- as P0: 1/5 (rate 0.20); as P1: 2/5 (rate 0.40)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.58    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
