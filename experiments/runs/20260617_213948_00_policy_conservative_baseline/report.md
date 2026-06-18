# policy_conservative_baseline

- **Seam:** archetype.baseline_exploit
- **Kind:** control    **Archetype:** baseline_exploit
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_focused

## Hypothesis
An exact copy of the v1 control (no overrides) anchors the batch and confirms the harness reproduces the baseline.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 18 / 22 / 0
- raw win rate: 0.45    adjusted win rate: 0.45
- as P0: 4/20 (rate 0.20); as P1: 14/20 (rate 0.70)
- seat balance delta (P0-P1): -0.50
- attack rate: 0.70    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
