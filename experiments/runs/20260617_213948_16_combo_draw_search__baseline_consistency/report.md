# combo_draw_search__baseline_consistency

- **Seam:** combo.search_consistency
- **Kind:** combo    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** broad

## Hypothesis
Draw/search policy bias over the consistency deck doubles down on setup density; tests for over-drawing diminishing returns.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 6 (seat-swap: True)
- wins / losses / draws: 3 / 3 / 0
- raw win rate: 0.50    adjusted win rate: 0.50
- as P0: 1/3 (rate 0.33); as P1: 2/3 (rate 0.67)
- seat balance delta (P0-P1): -0.33
- attack rate: 0.65    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
