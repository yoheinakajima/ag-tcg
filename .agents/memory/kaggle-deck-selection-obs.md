---
name: Kaggle cabt deck-selection observation shape
description: Why candidate agents must detect the deck-selection step without assuming a dict
---

The cabt/Kaggle deck-selection step is signalled by both `select` and `current`
resolving to None. The observation can arrive as a dict with the keys present-None,
a dict with the keys ABSENT, OR an attribute-style object (no `.get`). Local cabt
self-play always includes literal `select`/`current` keys, so it CANNOT reproduce
the production failure — a candidate that only matches `isinstance(obs, dict) and
obs.get("select") is None` passes locally but returns `[]` on Kaggle and fails with
"Player 1's deck does not have 60 cards".

**Why:** the prior `combo_full_safety_v3` submission errored exactly this way; the
fix (`combo_full_safety_v3_fixed`) reads fields via a helper that handles dict,
dict-like `.get`, and `getattr`, and treats it as a deck request only when both
`select` and `current` are None.

**How to apply:** for any submitted candidate, validate deck return against ALL
THREE obs shapes (key-present-None dict, key-absent dict, attribute object) using
the candidate's OWN extracted main.py — `scripts/validate_candidate_tarball.py`
plus the Step-5 direct-behavior check. Do not trust local self-play for this bug.
Keep `game_obs -> [0]` as a delegation sanity gate so the deck-request detector
never swallows normal gameplay.
