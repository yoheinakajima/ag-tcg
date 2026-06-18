# Replay Acquisition Workflow (Pass 10B)

This documents how to obtain the missing opponent replays needed to unblock the
external meta archetypes. It records **only commands verified against the
installed Kaggle CLI help** — no guessed command names.

## What raw replays we need

| filename (place under `data/meta_replays/raw/`) | archetype it unblocks | episode | status |
|---|---|---|---|
| `80374966_self_mirror.json` | `water_kyogre_abomasnow_mirror_passive` | 80374966 | **present** |
| `80503804_tellurium_metal_ex.json` | `metal_ex_zacian_ramp` | 80503804 (if available) | **missing** |
| `tymu_water_maxbelt.json` | `water_kyogre_abomasnow_maxbelt` | TYMU water/Maximum Belt | **missing** |
| `other_loss_*.json` | additional loss matchups (optional) | — | optional |
| `other_win_*.json` | additional win matchups (optional) | — | optional |

Exact target filenames (do not rename — the ingest scripts key off them):

```
data/meta_replays/raw/80503804_tellurium_metal_ex.json
data/meta_replays/raw/tymu_water_maxbelt.json
data/meta_replays/raw/other_loss_*.json
data/meta_replays/raw/other_win_*.json
```

## Can the Kaggle CLI download replays?

**No.** The installed CLI (`kaggle` 1.6.17) exposes only these competition
subcommands (verified — see `data/kaggle_uploads/kaggle_competitions_help_pass10b.log`):

```
kaggle competitions {list, files, download, submit, submissions, leaderboard}
```

- `competitions download` fetches **competition data files**, not episode/sim
  replays.
- There is **no** `episode`, `replay`, `simulation`, or `simulations` subcommand.
- `competitions submissions [-v]` lists submissions + scores (used by Part B) but
  does not expose per-episode replay payloads.

Therefore replay JSONs must be obtained **manually** from the Kaggle website.

## Manual download (the supported path)

1. Sign in to Kaggle and open the competition:
   `https://www.kaggle.com/competitions/pokemon-tcg-ai-battle`.
2. Go to **My Submissions** (or the leaderboard) and open a submission whose
   episodes you want.
3. Open an individual **episode / game**; use the page's replay/download control
   to save the episode JSON.
4. Save it under `data/meta_replays/raw/` using the exact filenames above.
5. Re-run the ingest pipeline:
   ```
   python scripts/extract_replay_decks.py
   python scripts/analyze_kaggle_replays.py
   ```
   then rebuild the report (Part I).

## Verified CLI commands actually used this pass (read-only)

```
kaggle competitions submissions pokemon-tcg-ai-battle           # status_before_pass10b.log
kaggle competitions submissions pokemon-tcg-ai-battle -v        # status_before_pass10b.csv
kaggle competitions --help                                      # help logs
kaggle competitions submissions --help
kaggle --help
```

(Invoked via `python -c "from kaggle.cli import main; ..."` because the `kaggle`
console-script is not on PATH; the package itself is installed.)

## Rules

- **Never invent decks or card IDs.** If a raw replay is missing, its archetype
  stays `blocked_missing_replay` in `experiments/meta_pool.yaml` and contributes
  no surrogate.
- Confirm every extracted card ID against the replay payload or card metadata.
- Raw replay JSONs may live under `data/meta_replays/raw/` but **do not commit
  official card CSV/PDF data**.
