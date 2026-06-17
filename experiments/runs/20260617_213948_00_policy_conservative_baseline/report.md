# policy_conservative_baseline

- **Seam:** archetype.baseline_exploit
- **Kind:** control    **Archetype:** baseline_exploit
- **Parent:** v1_kaggle_349_8
- **Stage:** focused

## Hypothesis
An exact copy of the v1 control (no overrides) anchors the batch and confirms the harness reproduces the baseline.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 24 / 16 / 0
- raw win rate: 0.60    adjusted win rate: 0.60
- as P0: 9/20 (rate 0.45); as P1: 15/20 (rate 0.75)
- seat balance delta (P0-P1): -0.30
- attack rate: 0.63    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
