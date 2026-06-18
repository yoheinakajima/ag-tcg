# policy_deckout_guard_v1

- **Seam:** policy.deckout_awareness
- **Kind:** combo    **Archetype:** tempo_control
- **Parent:** v1_kaggle_349_8
- **Stage:** pass5_scout

## Hypothesis
Deckout awareness: when the player's own deckCount is at or below a threshold, penalize further search-to-hand draws so the deck is not burned down into a self-inflicted deck-out loss (the seat-0 replay loss). Reads deckCount from the live observation.

## Gates
- package verify: PASS
- one-game smoke: PASS (PASS)

## Match results (vs immutable v1 control)
- games completed: 10 (seat-swap: True)
- wins / losses / draws: 3 / 7 / 0
- raw win rate: 0.30    adjusted win rate: 0.30
- as P0: 2/5 (rate 0.40); as P1: 1/5 (rate 0.20)
- seat balance delta (P0-P1): 0.20
- attack rate: 0.61    pass rate: 0.01
- crashes / timeouts / fallbacks: 0 / 0 / 0
