---
name: Kaggle cabt / OpenSpiel env quirks (local vs Kaggle)
description: Why local cabt self-play masks the deck-return bug and why the full smoke can't run in a single sandbox tool call.
---

# cabt deck-request observation differs: local env vs Kaggle

**Fact:** The LOCAL `kaggle_environments.make("cabt")` env passes a deck-selection
observation whose Struct *includes the literal key* `select` (so
`"select" in obs` is True with value None). Kaggle's real env passes an
observation where that key is **absent** (membership is False, `.get("select")`
is None).

**Why it matters:** A deck-request detector written as
`"select" in obs and obs["select"] is None` evaluates True locally (game runs a
full clean self-play) but False on Kaggle → the agent returns `[]` → Kaggle
rejects the submission pre-game with "Player 1's deck does not have 60 cards".

**How to apply:** Detect the deck step with `.get("current") is None and
.get("select") is None` (key-absent safe), and ALWAYS return an embedded 60-card
deck constant (never rely on file I/O or cwd). Validate candidates against
*key-absent* observation shapes, not just key-present ones — a local self-play
game CANNOT discriminate the fixed vs broken candidate (both complete locally).
The discriminating gate is the static validator that feeds key-absent obs to the
candidate's own extracted `main.py`.

# kaggle_environments import is too slow for one sandbox tool call

**Fact:** A fresh `import kaggle_environments` / `make("cabt")` triggers OpenSpiel
env registration that takes ~115s+ in this sandbox, leaving no room for the game
inside the 120s tool wall. Backgrounded/`setsid` processes do NOT survive across
tool calls (the sandbox reaps them when the launching call returns).

**Why it matters:** The full candidate self-play smoke (`make("cabt")` +
`env.run`) cannot be completed locally here. Do not block delivery on it.

**How to apply:** Rely on the fast deterministic gates (static tarball validator
+ pytest) which reproduce the exact Kaggle key-absent failure mode. State the
smoke's local infeasibility honestly in reports rather than faking a PASS.
Blocking `pyspiel` via `sys.meta_path` to skip registration was attempted and
still got SIGKILLed — not a reliable workaround.
