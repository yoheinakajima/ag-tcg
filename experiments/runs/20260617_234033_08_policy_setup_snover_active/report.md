# policy_setup_snover_active

- **Seam:** policy.setup_active_choice
- **Kind:** combo    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Opening setup: prefer placing Snover (722) during opening placement prompts so the Mega Abomasnow ex evolution line starts on board. Reads the option's resolved card id during placement contexts.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 5 / 5 / 0
- raw win rate: 0.50    adjusted win rate: 0.50
- as P0: 2/5 (rate 0.40); as P1: 3/5 (rate 0.60)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.66    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
