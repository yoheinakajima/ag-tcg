# policy_effect_resolution_v1

- **Seam:** policy.effect_resolution_targeting
- **Kind:** policy    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass4_scout

## Hypothesis
Effect-resolution targeting (approx): on search/to-hand prompts, bias toward high-value targets by card name (Ultra Ball, Mega Signal, Secret Box, Lillie's Determination, Mega Abomasnow line, Kyogre) over first-legal/basic energy. Keyword-weight approximation only — board state is not reachable through the override hook.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 3 / 7 / 0
- raw win rate: 0.30    adjusted win rate: 0.30
- as P0: 1/5 (rate 0.20); as P1: 2/5 (rate 0.40)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.58    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
