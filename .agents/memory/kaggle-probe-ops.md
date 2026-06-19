---
name: Kaggle probe operations (cabt lab)
description: Non-obvious environment quirks for running a live Kaggle submission probe in this repl (CLI absent, smoke chdir, event types, score drift).
---

# Kaggle probe operations

Durable gotchas learned doing live Kaggle calibration probes for the `pokemon-tcg-ai-battle`
competition. None are discoverable from the code alone.

## Kaggle CLI is NOT on PATH — use the Python API
- `which kaggle` fails and `python3 -m kaggle` errors (`No module named kaggle.__main__`).
  The `kaggle` package is installed but ships no runnable module/console-script here.
- Use: `from kaggle.api.kaggle_api_extended import KaggleApi; api = KaggleApi(); api.authenticate()`.
- Auth comes from the `KAGGLE_USERNAME` / `KAGGLE_KEY` env secrets automatically — never print,
  echo, or write those values. `authenticate()` picks them up without a `kaggle.json`.
- Read-only listing: `api.competition_submissions("pokemon-tcg-ai-battle")` (newest first).
  Submit once: `api.competition_submit(tarball, message, competition)`.
- Expect a harmless `outdated API Version` warning (server 2.2.x / client 1.6.17).

## Candidate smoke script chdir trap
- `scripts/kaggle_candidate_smoke_test.py` `os.chdir`s into the tarball extraction temp dir
  while running, so a **relative** `--out` resolves against that temp dir and write fails.
  **Pass an absolute path** (e.g. `--out "$PWD/data/experiments/pass20_smoke"`); `--out` is a
  directory, not a file.

## Emitting submission lifecycle events
- `scripts/ag_strategy_event.py` `emit()` only allows `STRATEGY_EVENT_TYPES`; submission events
  (`SubmissionQueued`, `SubmissionUploaded`, `KaggleScoreUpdated`) are NOT in that tuple.
  Emit them directly: `EventStore(LAB_EVENTS_PATH).append(new_event(EventType.X, payload=..., tags=..., parent_event_ids=...))`.
- Don't `import ag_strategy_event` from an arbitrary cwd — it does `import _bootstrap` (a
  `scripts/`-local module). Import `EventStore`/`new_event`/`LAB_EVENTS_PATH` from their packages instead.

## Live scores drift — never hardcode the active control
**Why:** between passes the same submission's public score changed materially (active control
`combo_full_safety_v3_fixed` read 376.6 one pass, 391.1 the next; `deck_energy_trim_light` 386.5 → 288.4).
**How to apply:** always recompute the active control from a fresh read-only listing via
`scripts/build_live_score_registry.py` (picks highest publicScore among complete/non-error). Note that
`combo_full_safety_v3_fixed` is the live high scorer but FAILS the entrypoint validator, so it's a
reference only, never an eligible submitted candidate.
