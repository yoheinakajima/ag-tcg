# policy_attach_targeting_v1

- **Seam:** policy.attach_targeting
- **Kind:** policy    **Archetype:** setup_evolution
- **Parent:** v1_kaggle_349_8
- **Stage:** pass4_scout

## Hypothesis
Attach targeting (approx): prefer attach/place actions (type 8) and active-target keywords so energy/tools land on the current attacker. Precise 'attach to next-turn attacker' needs board state, so this is the lightweight keyword/type approximation.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 2 / 8 / 0
- raw win rate: 0.20    adjusted win rate: 0.20
- as P0: 0/5 (rate 0.00); as P1: 2/5 (rate 0.40)
- seat balance delta (P0-P1): -0.40
- attack rate: 0.76    pass rate: 0.02
- crashes / timeouts / fallbacks: 0 / 0 / 0
