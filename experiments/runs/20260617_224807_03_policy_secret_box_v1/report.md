# policy_secret_box_v1

- **Seam:** policy.secret_box_mode_selection
- **Kind:** policy    **Archetype:** consistency_engine
- **Parent:** v1_kaggle_349_8
- **Stage:** pass4_scout

## Hypothesis
Secret Box (1092) mode selection (approx): boost choosing Secret Box and high-leverage classes by name (Ultra Ball, Mega Signal, Lillie's Determination, Powerglass, Surfing Beach). Stays conservative where names are absent. Keyword-weight approximation only.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 4 / 6 / 0
- raw win rate: 0.40    adjusted win rate: 0.40
- as P0: 1/5 (rate 0.20); as P1: 3/5 (rate 0.60)
- seat balance delta (P0-P1): -0.40
- attack rate: 0.84    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
