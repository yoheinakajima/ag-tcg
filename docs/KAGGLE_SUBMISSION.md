# Kaggle Submission

How to build and validate the `.tar.gz` the competition expects.

## What the bundle needs

A `.tar.gz` containing, at the archive root:

* **`main.py`** — exposes `agent(obs_dict) -> list[int]`.
* **`deck.csv`** — exactly 60 integer card IDs (one per line).
* (optional) any small runtime modules `main.py` imports.

Docs, tests, data, and replays are **excluded** to keep it small.

## `main.py` requirements

* Defines `agent(obs_dict)` at module top level.
* Standard library only — no third-party imports that may be absent in the
  sandbox.
* Never raises outward; always returns a legal selection. (Ours embeds the
  fallback + heuristic + validation directly, and optionally uses `agent.py` if
  bundled — re-validating its output.)

## `deck.csv` requirements

* 60 lines, each a single integer card ID.
* Standard copy limits (≤4 per card; basic Energy typically exempt) — enforced as
  a **warning** by our validator, since real limits depend on card metadata.

> The shipped `deck.csv` is a **structural placeholder** (ids 1–15 × 4 copies).
> It validates as 60 integers but is **not** a competitive decklist. Replace it
> with real card IDs from the official database (`deck.csv.example` documents the
> format) before submitting for score.

## Build commands

```bash
# Verify only (no tarball):
python scripts/package_submission.py --verify-only
# or: make verify-submission

# Build data/submissions/submission.tar.gz:
python scripts/package_submission.py
# or: make submission

# Include agent.py as a bundled runtime module:
python scripts/package_submission.py --include agent.py
```

The packager (`src/ptcg_activegraph/packaging/make_submission.py`):

1. Verifies `main.py` exists.
2. Loads `deck.csv` and runs `validate_deck` — **hard-fails** if not 60 integers.
3. Writes the tarball with `main.py`, `deck.csv` (+ any `--include` files) at the
   root.

## Validation expectations

* `verify_submission_inputs` raises `SubmissionError` on a missing `main.py` or
  an invalid deck; the CLI prints the reason and exits non-zero.
* Soft warnings (copy counts, missing basics) are reported but do not block — fix
  them before competing for real.

## Common failure modes

| Failure | Cause / fix |
| --- | --- |
| `deck.csv failed validation: ... must be exactly 60` | Wrong card count. |
| `entry N is not an integer card id` | Non-integer line in `deck.csv`. |
| `main.py not found` | Run from the repo root, or pass `--main`. |
| Agent returns illegal index on Kaggle | Shouldn't happen — output is clamped; if it does, check the cabt option schema and re-test `main.py`. |
| Import error in sandbox | `main.py` must stay stdlib-only; don't import `src/`. |

## Sanity check before submitting

```bash
python -m pytest            # all green
python main.py              # prints a demo selection, no crash
make verify-submission      # deck + entrypoint valid
make submission             # tarball built
```
