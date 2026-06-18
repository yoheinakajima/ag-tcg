# combo_full_safety_v3 Kaggle validation failure

Failure type:
- Pre-game deck-selection failure.

Kaggle validation facts:
- statuses: INVALID / INVALID
- rewards: null / null
- step 0 current: null
- step 0 select: null
- action returned: []
- error: "Player 1's deck does not have 60 cards."

Diagnosis:
- cabt expects the agent to return its 60-card deck list when select is null.
- The submitted candidate returned [].
- This indicates candidate main.py did not load/embed deck.csv correctly at runtime.

This is not evidence against combo_full_safety_v3 gameplay strategy.
