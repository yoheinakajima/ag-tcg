# policy_draw_search_bias

- **Seam:** policy.search_targeting
- **Kind:** policy    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** broad

## Hypothesis
Boosting draw/search/supporter/item preference should improve setup consistency turn over turn.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 6 (seat-swap: True)
- wins / losses / draws: 2 / 4 / 0
- raw win rate: 0.33    adjusted win rate: 0.33
- as P0: 0/3 (rate 0.00); as P1: 2/3 (rate 0.67)
- seat balance delta (P0-P1): -0.67
- attack rate: 0.56    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
