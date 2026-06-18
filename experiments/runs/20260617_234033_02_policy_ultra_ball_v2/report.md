# policy_ultra_ball_v2

- **Seam:** policy.ultra_ball_discard_and_search
- **Kind:** combo    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_focused

## Hypothesis
Ultra Ball (1121) board-aware resolution: when paying the Ultra Ball discard cost, prefer discarding spare energy over the Snover/Mega/Kyogre line that is not yet on board, then fetch the missing attacker/evolution piece (Snover first, then Mega Abomasnow, Kyogre).

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 16 / 24 / 0
- raw win rate: 0.40    adjusted win rate: 0.40
- as P0: 8/20 (rate 0.40); as P1: 8/20 (rate 0.40)
- seat balance delta (P0-P1): 0.00
- attack rate: 0.65    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
