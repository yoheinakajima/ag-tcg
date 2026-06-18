# combo_effect_resolution_v2__deckout_guard

- **Seam:** combo.effect_resolution_deckout
- **Kind:** combo    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Combine board-aware effect resolution (protect setup, fetch the missing line) with deckout awareness (stop over-searching when the deck runs low) to test whether the two replay-derived fixes compound.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 5 / 5 / 0
- raw win rate: 0.50    adjusted win rate: 0.50
- as P0: 2/5 (rate 0.40); as P1: 3/5 (rate 0.60)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.53    pass rate: 0.03
- crashes / timeouts / fallbacks: 0 / 0 / 0
