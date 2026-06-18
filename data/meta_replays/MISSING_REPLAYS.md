# Missing meta replays (Pass 10)

Pass 10 needs real top-player replay JSONs to calibrate local evaluation against
the live Kaggle meta. Only ONE real replay is currently present.

## Present
- `raw/80374966_self_mirror.json` — episode 80374966. **Self / mirror** game:
  both seats submit the **exact v2 `deck_energy_trim_light` 60-card list**
  (agents both labelled "Yohei Nakajima"). rewards `[-1, 1]` → seat 1 won.
  Useful for v2-mirror tempo/board-development metrics only. It is NOT an
  external-opponent matchup.

## Missing (please download from the Kaggle submission page and drop here)
Place raw replay JSONs under `data/meta_replays/raw/` with these names:

- `80503804_tellurium_metal_ex.json` — loss vs `tellurium_rrr` metal/Zacian ex
  deck (episode 80503804 if available). Needed to derive the
  `metal_ex_zacian_ramp` archetype's real 60-card deck and card IDs.
- `tymu_water_maxbelt.json` — loss vs "AI Agent By TYMU" water mirror /
  Maximum Belt deck. Needed to confirm Maximum Belt / Cyrano / Waitress card
  IDs and the `water_kyogre_abomasnow_maxbelt` archetype deck.

## Why this matters
- Without these, the only meta surrogate available is the **v2 mirror**.
- External archetypes (`metal_ex_zacian_ramp`, `water_kyogre_abomasnow_maxbelt`)
  remain **provisional / blocked**: their card IDs are NOT in the confirmed set
  (`src/ptcg_activegraph/playbooks/schema.py`) and we never invent IDs.
- Per the Pass 10 rules, with external replay decks missing the evaluation is
  marked **incomplete** and **no candidate may be queued as promotable**.

## How to export
1. Open the Kaggle competition submission page for `pokemon-tcg-ai-battle`.
2. Open each relevant episode and download its replay JSON.
3. Save under `data/meta_replays/raw/` using the names above.
4. Re-run `python scripts/analyze_kaggle_replays.py` and
   `python scripts/extract_replay_decks.py`.

(Do NOT commit official card CSV/PDF data; raw replay JSONs are fine.)
