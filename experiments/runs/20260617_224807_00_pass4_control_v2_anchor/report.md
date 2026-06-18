# pass4_control_v2_anchor

- **Seam:** archetype.baseline_exploit
- **Kind:** combo    **Archetype:** baseline_exploit
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_focused

## Hypothesis
Exact v2 control (v2 deck, no policy override) anchors the Pass 4 scout batch and confirms the harness reproduces the v2 baseline as a ~50% mirror.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 19 / 21 / 0
- raw win rate: 0.47    adjusted win rate: 0.47
- as P0: 10/20 (rate 0.50); as P1: 9/20 (rate 0.45)
- seat balance delta (P0-P1): 0.05
- attack rate: 0.69    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
