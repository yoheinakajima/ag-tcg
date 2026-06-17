---
name: cabt agent runtime quirks
description: How the cabt (PTCG AI Battle) Kaggle engine loads and calls the agent — non-obvious env behavior.
---

# cabt / PTCG AI Battle agent runtime

- **Deck file path**: the engine exec()s the agent's `main.py`, so `__file__` and cwd do NOT reliably point at the agent directory. Resolving `deck.csv` only via `dirname(abspath(__file__))` yields an empty deck in the sandbox → submission fails the validation episode with `"Player N's deck does not have 60 cards."`
  - **Why**: a single bad base (e.g. `__file__` undefined) raised inside the path-resolution expression and aborted the whole loader, leaving 0 cards.
  - **How to apply**: always include the documented fallback path `"/kaggle_simulations/agent/deck.csv"` (this is what the official sample `read_deck_csv()` does), and resolve each candidate path independently so one failure can't abort the rest.

- **Deck submission step**: on step 0 the engine passes an observation whose `select` key is present but `null`; the agent must return its 60 integer card IDs (not option indices) in response.

- **Deck legality**: basic Energy cards have NO 4-copy limit. Card ID `3` = "Basic {W} Energy" — many copies (30+) is legal. A package "card 3 appears 33 times (>4)" warning is a false alarm for basic energy. ACE SPEC cards (e.g. 1092 Secret Box) are limited to 1 per deck.

- **CLI**: classic `kaggle==1.6.17` exposes only list/files/download/submit/submissions/leaderboard — NO command to download episode replays / agent logs / validation logs. Those are only on the competition submission web page.
