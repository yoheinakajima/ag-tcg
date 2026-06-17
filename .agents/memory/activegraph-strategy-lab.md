---
name: ActiveGraph Strategy Lab invariants
description: Safety invariants and gotchas for the experiment lab wrapped around the immutable Kaggle PTCG v1 baseline.
---

# ActiveGraph Strategy Lab — invariants worth keeping

The lab (src/ptcg_activegraph/experiments/ + scripts/) generates policy/deck
candidates around the immutable v1 control (root main.py/deck.csv, public 349.8),
evals them locally with cabt, ranks, and queues (never auto-submits) Kaggle uploads.

## Deck legality is warning-only in the shared validator
`decks/validator.py` + `packaging/make_submission.verify_submission_inputs()` treat
"non-energy card > 4 copies" as a **warning, not an error** — by design, because the
baseline deck has ~33 basic energy (card id 3) and must not fail.
**Why it matters:** candidate generation could otherwise package/queue an illegal
deck. The lab therefore enforces strict copy limits itself in
`generator._illegal_copy_counts` (hard-fail in `generate_deck_candidate`).
**Gotcha:** `card_db.basic_features(3)["is_energy"]` returns **False** for the deck's
basic energy (id 3) — the card_db does not flag it. So energy exemption must fall
back to the known `ENERGY_ID = 3`, not rely on the card_db alone.

## Silent agent failures must be hard-rejected, not scored
The local runner wraps each agent; if the candidate's `agent()` raises mid-game it
counts a **fallback** (returns `[]`) and the game can still "complete".
**Rule:** any `fallbacks > 0` is a hard-reject in `ranker.hard_reject_reasons`,
alongside package/smoke fail, crashes, timeouts. Hard rejects must skip soft scoring
entirely (score = None), or a broken candidate with a high win_rate looks promotable.

## Three locks before any Kaggle upload
Only `scripts/submit_queue.py` can upload, and only when ALL THREE align:
`--i-understand-this-uploads` (CLI) + `auto_submit_enabled: true` +
`require_manual_approval_for_submit: false` (both in experiments/experiment_plan.yaml).
Defaults ship as disabled/manual. `queue_submissions.py` is always dry-run.

## Run-dir accumulation
`run_experiment_batch.py` evaluates **every** dir under `experiments/runs/`. Stale
dirs from prior sessions cause duplicate branch_ids in the ranking/queue. Clear
`experiments/runs/*` before a clean batch if you want exactly one entry per branch.
