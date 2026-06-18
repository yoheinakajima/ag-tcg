# Replay Inbox Workflow

How to feed Kaggle replays into the ActiveGraph meta pool. The inbox is an
**append-only drop folder**: you drop raw replay JSONs in, run four scripts, and
the registry + meta pool update themselves. You never rename or pre-process files
by hand.

## 1. Drop raw replays in

Put raw Kaggle replay JSON files into:

```
data/meta_replays/raw/
```

- Filenames can be **arbitrary numeric names** like `80503687.json`. They can also
  be anything else (`loss_vs_metal.json` works too) — the filename is just a
  label.
- **Do not rename files manually.** The real identity of a replay is its
  `EpisodeId`, which is parsed from inside the JSON, not from the filename. The
  registry handles naming and deduplication for you.
- Raw replay files should generally **not be committed** to the repo unless
  explicitly approved (they can contain large or private payloads). The derived
  artifacts (registry, extracted decks, archetypes) are what we keep.

## 2. Run the pipeline

Run these four scripts in order:

```bash
python scripts/ingest_replay_inbox.py        # 1. index + dedupe + extract decks
python scripts/extract_meta_archetypes.py    # 2. classify archetypes
python scripts/analyze_kaggle_replays.py     # 3. per-replay outcome metrics
python scripts/update_meta_pool_from_replays.py  # 4. rebuild the meta pool
```

What each step does:

1. **ingest_replay_inbox** — scans `raw/`, parses each replay, computes a file
   hash and reads the `EpisodeId`, **dedupes by both `EpisodeId` and file hash**,
   extracts each seat's 60-card deck to `data/meta_replays/decks/`, attributes our
   seat vs the opponent, and writes the registry + processing state.
2. **extract_meta_archetypes** — classifies each opponent deck into an archetype
   using only **card ids that actually appear in the replays** (never invented),
   tagging confidence as `confirmed` / `provisional` / `unknown`.
3. **analyze_kaggle_replays** — computes per-replay metrics (win/loss, fast
   losses, long/deckout games, recurring failure tags, opponent patterns).
4. **update_meta_pool_from_replays** — rebuilds `experiments/meta_pool.yaml` from
   the archetypes + the live score registry, setting coverage to
   `incomplete` / `partial` / `usable`.

## 3. Outputs

| Artifact | Path |
|---|---|
| Replay registry | `data/meta_replays/replay_registry.json` / `.md` |
| Ingest errors | `data/meta_replays/replay_inbox_errors.json` |
| Processing state | `data/meta_replays/replay_processing_state.json` |
| Extracted decks | `data/meta_replays/decks/<episode>_p<seat>_deck.csv` |
| Archetypes | `data/meta_replays/archetypes.yaml` / `.md` |
| Replay analysis | `data/meta_replays/replay_analysis.json` / `.md` |
| Meta pool | `experiments/meta_pool.yaml` + `meta_pool_summary.md` |

## Recommended replay collection cadence

- **After each new submission scores:** download 8–12 replays, prioritizing
  losses and a diverse set of opponents.
- **For the active control:** keep 20–30 replays total.
- **For old baselines:** keep 5–10 anchor replays.
- **Before each new upload:** add the latest 5–10 relevant replays.

## What to prioritize when collecting

- losses to high-scoring opponents
- fast losses
- long deckout / attrition losses
- wins against common archetypes
- rare archetypes / disruption decks

## Notes

- The registry is **idempotent** — re-running ingest on the same `raw/` folder
  produces no duplicates (dedupe is by `EpisodeId` and file hash).
- The local evaluation that consumes this pool
  (`scripts/run_meta_pool_eval.py`) is **surrogate-based and directional only**:
  replays give us opponent *decks*, not opponent *policies*.
