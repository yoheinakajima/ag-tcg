# v2 Kaggle baseline — deck_energy_trim_light

Status:
- Kaggle validation passed
- Public score/rating: 479.1
- Previous v1 baseline score: 356.9
- Improvement: +122.2 rating points
- Local hypothesis: trimming 4 Basic Water Energy for +2 Kyogre + +2 Ultra Ball improved attacker/search density without breaking energy availability.
- This is now the active local control baseline for future experiments.

Root main.py/deck.csv are not automatically replaced by this baseline in this pass.

## Correction note — v1 archive directory name

The v1 baseline archive directory is named `v1_kaggle_349_8` because 349.8 was
the public score recorded when that archive was first created. After the
deck-loader fix, live Kaggle later showed the v1 control at **356.9**. The
directory is intentionally **not** renamed (to preserve the historical archive
path and avoid a destructive rename); treat **356.9** as the corrected live v1
score for all v1-vs-v2 comparisons. The score delta to v2 (479.1) is therefore
**+122.2** measured against the corrected v1 score of 356.9.

## Composition vs v1 control

Delta from the root/v1 60-card list:
- Basic {W} Energy (id 3): 33 -> 29 (-4)
- Kyogre (id 721): 2 -> 4 (+2)
- Ultra Ball (id 1121): 2 -> 4 (+2)

Tarball contains only top-level `main.py` and `deck.csv`. The runtime policy
(`main.py`) is identical to the v1 control; only the deck list changed.

## Live score drift note (Pass 10, 2026-06-18)

The `479.1` above was the **historical/early** public score recorded when this
baseline was created. Live Kaggle status fetched during Pass 10 shows the active
control's **current** public score has settled to approximately **355.2** as the
ladder accumulated more games (see `data/kaggle_uploads/status_before_pass10.log`).

- historical/local/early score: **479.1**
- current live score (Pass 10 observation): **~355.2**
- `deck_energy_trim_light` remains the **designated active control** because it is
  the best *currently-complete* submission we control for this deck line.
- Observed discrepancy: the v1 control currently shows **363.0**, slightly above
  this v2 score (355.2). v2 is retained as the designated control per the Pass 10
  instruction, but the v1/v2 live gap has compressed and should be revisited.

The directory is intentionally **not** renamed (preserves the historical archive
path; avoids a destructive rename).
