# policy_secret_box_v2

- **Seam:** policy.secret_box_mode_selection
- **Kind:** combo    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Secret Box (1092) board-aware resolution: never discard the Snover/Mega/Kyogre line to pay a cost when it is not on board (the exact step-11 replay bug), and fetch a coherent engine package (Ultra Ball, Mega Signal, the Snover line) on the to-hand side.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 7 / 3 / 0
- raw win rate: 0.70    adjusted win rate: 0.70
- as P0: 3/5 (rate 0.60); as P1: 4/5 (rate 0.80)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.63    pass rate: 0.03
- crashes / timeouts / fallbacks: 0 / 0 / 0
