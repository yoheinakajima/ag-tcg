# policy_ultra_ball_v1

- **Seam:** policy.ultra_ball_discard_and_search
- **Kind:** policy    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass4_scout

## Hypothesis
Ultra Ball (1121) emphasis (approx): nudge toward playing Ultra Ball and toward fetching the missing attacker/evolution line (Mega Abomasnow / Snover / Kyogre). 'Discard energy first' is a board decision the keyword hook cannot target, so only the search-target side is approximated here.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 5 / 5 / 0
- raw win rate: 0.50    adjusted win rate: 0.50
- as P0: 2/5 (rate 0.40); as P1: 3/5 (rate 0.60)
- seat balance delta (P0-P1): -0.20
- attack rate: 0.73    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
