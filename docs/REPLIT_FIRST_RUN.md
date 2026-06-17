# Replit / Kaggle First Run

The goal of the first run is **not** a strong bot. It is to: run one full cabt
self-play game and package a valid, scoring submission.

Priority order for first scoring:

```
valid deck > valid return shape > no crashes > no timeouts > simple heuristic > everything else
```

## 0. Where to place Kaggle-provided files

```
data/cards/EN_Card_Data.csv      # official card metadata (for deck generation)
data/cards/JP_Card_Data.csv      # optional
sample_submission/deck.csv       # if the competition ships a sample deck
```

The deck resolver checks all of these automatically.

## 1. Commands (run top to bottom)

```bash
python --version                                   # expect 3.11+
python -m pip install -U pip
python -m pip install kaggle-environments pytest    # cabt comes from the competition pkg

python -m pytest                                   # all green, no cabt needed

python scripts/resolve_deck.py                     # install a REAL deck.csv
python scripts/package_submission.py --verify-only # strict preflight

python scripts/kaggle_smoke_test.py                # one full cabt self-play game
python scripts/record_schema.py --games 3          # capture the real option schema

python scripts/package_submission.py               # build the tarball
tar -tzf data/submissions/submission.tar.gz        # expect top-level main.py + deck.csv
```

`make first-run` chains tests → resolve-deck → verify-submission.

## 2. Installing cabt

`cabt` is provided by the competition (not on PyPI in general). Install it from
the wheel/source the competition supplies, e.g.:

```bash
python -m pip install /path/to/cabt-*.whl
# or follow the competition's setup notes
```

`kaggle_environments` is on PyPI. Both must import for the smoke test to PASS.

## 3. Reading the smoke test result

`python scripts/kaggle_smoke_test.py` prints one of:

| Status | Meaning / fix |
| --- | --- |
| `PASS` | A full game ran. You're ready to package. |
| `FAIL: kaggle_environments unavailable` | `pip install kaggle-environments` |
| `FAIL: cabt environment unavailable` | install `cabt`; check `make("cabt", ...)` config |
| `FAIL: deck invalid` | run `python scripts/resolve_deck.py` |
| `FAIL: runtime exception` | a traceback is printed — fix `main.py` |

## 4. After schema is recorded

`docs/CABT_SCHEMA_NOTES.md` is auto-written with the real option/select keys.
Use `python scripts/explain_action.py data/matches/option_examples.jsonl` (or a
single observation JSON) to see how the heuristic scores real options, then
refine weights in `main.py` if time allows. Validity first, cleverness later.

## 5. Upload

Upload `data/submissions/submission.tar.gz` to the competition. It contains only
`main.py` and `deck.csv` at the archive root.
