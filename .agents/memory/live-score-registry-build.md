---
name: Live score registry build input
description: build_live_score_registry.py default CSV is stale; pass --csv with last-known-good.
---

# Always pass --csv to build_live_score_registry.py when refreshing offline

**Rule:** `scripts/build_live_score_registry.py` defaults to
`data/kaggle_uploads/status_before_pass10b.csv` (DEFAULT_CSV). That snapshot is
stale and shows `combo_full_safety_v3_fixed` @ **294.0**, which makes the script
pick `submission.tar.gz` @ 363.0 as active control and *reject* combo. The
correct last-known-good snapshot is `status_before_pass11b.csv`, where
`combo_full_safety_v3_fixed` @ **376.6** is the highest complete score and the
right active control.

**Why:** the kaggle CLI is NOT installed in this environment ("kaggle: command
not found"), so live scores cannot be refreshed. Running the build with no
`--csv` silently rebuilds the registry from the stale default and flips the
active control — exactly the "silently pretend scores are current" failure the
spec warns against. The registry json is gitignored, so there is no committed
copy to restore from.

**How to apply:** when recording live score state offline, write a status note
CSV documenting that kaggle is unavailable, then run
`python scripts/build_live_score_registry.py --csv data/kaggle_uploads/status_before_pass11b.csv`
(the last-known-good). Verify it reports active control
`combo_full_safety_v3_fixed.tar.gz @ 376.6` with no rejections.
