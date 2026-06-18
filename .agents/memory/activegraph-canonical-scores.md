---
name: ActiveGraph canonical live scores
description: The true live Kaggle scores for the v1/v2 baselines, which differ from the archive directory names.
---

# Canonical live scores

- **v1 live score = 356.9.** The archive dir is named `data/baselines/v1_kaggle_349_8/`
  but that `349_8` is a stale historical name — the live v1 score is **356.9**.
  Keep the dir name as-is (immutability / `cmp` references), but every reported
  *score* must say 356.9, not 349.8.
- **v2 control live score = 479.1**, archived at
  `data/baselines/v2_kaggle_479_1_deck_energy_trim_light/` (its `main.py` == root `main.py`).

**Why:** Multiple report surfaces (HTML header, strategy report, pass final reports)
hardcoded 349.8 from the dir name and were factually wrong. `report.py` exposes
`V1_LIVE_SCORE = 356.9` — reference that constant, never a literal.

**How to apply:** When writing any score into a report/site/markdown, use 356.9 for v1
and 479.1 for v2. Distinguish the *archive path* (may keep `349_8`) from the *score*.
