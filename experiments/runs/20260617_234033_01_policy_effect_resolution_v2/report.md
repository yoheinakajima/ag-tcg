# policy_effect_resolution_v2

- **Seam:** policy.effect_resolution_targeting
- **Kind:** combo    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_focused

## Hypothesis
Board-aware effect resolution: on discard prompts, protect setup pieces (Snover 722 / Mega Abomasnow ex 723 / Kyogre 721) that are not yet in play and steer the discard toward spare Basic {W} Energy (3); on search-to-hand prompts, fetch the missing engine/attacker. Directly targets the replay failures (Secret Box discarded Snover; Ultra Ball discarded Mega Abomasnow).

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 40 (seat-swap: True)
- wins / losses / draws: 17 / 23 / 0
- raw win rate: 0.42    adjusted win rate: 0.42
- as P0: 5/20 (rate 0.25); as P1: 12/20 (rate 0.60)
- seat balance delta (P0-P1): -0.35
- attack rate: 0.57    pass rate: 0.03
- crashes / timeouts / fallbacks: 0 / 0 / 0
