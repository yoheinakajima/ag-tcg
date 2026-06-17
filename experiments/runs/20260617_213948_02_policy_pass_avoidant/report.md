# policy_pass_avoidant

- **Seam:** policy.pass_avoidance
- **Kind:** policy    **Archetype:** linear_aggro
- **Parent:** v1_kaggle_349_8
- **Stage:** focused

## Hypothesis
Heavier penalties on pass/end (type 14) options should cut the pass rate and keep the agent acting when real plays exist.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 17 / 23 / 0
- raw win rate: 0.42    adjusted win rate: 0.42
- as P0: 7/20 (rate 0.35); as P1: 10/20 (rate 0.50)
- seat balance delta (P0-P1): -0.15
- attack rate: 0.64    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
