---
name: ActiveGraph live scores drift over time
description: v1/v2 baseline live Kaggle scores are point-in-time and DRIFT; archive dir names are historical anchors, not current scores.
---

# Live scores are point-in-time, not canonical-forever

The archive directory names encode *historical* scores and must NOT be read as
the current live score:
- `data/baselines/v1_kaggle_349_8/` — `349_8` is a stale name.
- `data/baselines/v2_kaggle_479_1_deck_energy_trim_light/` — `479_1` is a stale
  name (its `main.py` == root `main.py`).

**Live scores change between passes.** Observed values so far:
- Earlier pass: v1 ≈ 356.9, v2 ≈ 479.1 (these became the `report.py`
  `V1_LIVE_SCORE` / `V2_LIVE_SCORE` constants).
- **Pass 10 (June 18, 2026): v1 = 363.0, v2 (`deck_energy_trim_light`) = 355.2,
  `combo_full_safety_v3_fixed` = 294.0 (live-rejected).** Note v1 now OUTSCORES
  v2 — the early v2 lead (479.1) collapsed.

**Why:** Report surfaces hardcoded the dir-name score (349.8) and were wrong; later
the `V1_LIVE_SCORE`/`V2_LIVE_SCORE` constants themselves went stale as the ladder
moved. A validation-passing line (`combo_full_safety_v3_fixed`) still flopped live
(294.0) — local validation/proxies and early public scores do NOT predict the
settled Kaggle ladder.

**How to apply:** When a pass fetches fresh live scores, treat them as the truth for
that pass and source report values from the pass's own artifacts (e.g.
`experiments/meta_pool.yaml` controls block), NOT from the older `V1_LIVE_SCORE`/
`V2_LIVE_SCORE` constants or the dir names. Do not assume v2 > v1. The shared
`report.py` constants anchor *older* pass sections — leave them, but never reuse
them as "current".
