# pass4_control_v2_anchor

- **Seam:** archetype.baseline_exploit
- **Kind:** combo    **Archetype:** baseline_exploit
- **Parent:** v1_kaggle_349_8
- **Stage:** pass4_scout

## Hypothesis
Exact v2 control (v2 deck, no policy override) anchors the Pass 4 scout batch and confirms the harness reproduces the v2 baseline as a ~50% mirror.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 4 / 6 / 0
- raw win rate: 0.40    adjusted win rate: 0.40
- as P0: 3/5 (rate 0.60); as P1: 1/5 (rate 0.20)
- seat balance delta (P0-P1): 0.40
- attack rate: 0.73    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
