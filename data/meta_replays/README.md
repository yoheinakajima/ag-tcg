# Meta Replays (top-player replay corpus)

This directory holds **full top-player replay JSON exports** used to infer the
current competitive meta for the Kaggle PTCG environment. It is intentionally
empty in the repository until real replays are dropped in — Pass 7B only builds
the *scaffolding* that will consume them later. No meta engine candidate is
evaluated yet.

## What to put here

One JSON file per replay, named `*.json` (files beginning with `_` are treated
as indexes/metadata and skipped by the parsers). The analysis scripts accept
either of two shapes and degrade gracefully:

1. **Full replay** — a Kaggle environment replay export with a `steps` array
   (the per-step `[ {observation, action, ...}, ... ]` structure the local
   simulator already understands via `src/ptcg_activegraph/replays/`).
2. **Partial log** — any JSON object with a subset of fields (for example just
   a `deck` list, or a handful of early-step observations). Partial inputs
   produce a *partial* analysis with explicit `uncertain: true` / `unknown`
   markers rather than guesses.

## Hard rules (enforced by the scripts)

- **Never invent card IDs.** If a card's numeric id is not present in the
  source JSON, it is recorded as `unknown` — the scripts never fabricate ids
  from card-name text.
- Missing metadata is labelled `unknown`, never defaulted to a plausible value.
- Partial coverage is always surfaced (`coverage: "partial"`) so downstream
  ranking never over-trusts a thin sample.

## Pipeline

```
data/meta_replays/*.json
        │
        ├─ scripts/analyze_meta_replay.py     # one replay → skeleton + early policy
        ├─ scripts/compare_meta_decks.py      # many skeletons → shared/divergent cards
        └─ scripts/extract_meta_archetypes.py # corpus → archetypes + report markdown
        │
        ▼
data/meta/meta_archetypes.json
data/meta/top_policy_patterns.md
data/meta/top_deck_skeletons.md
```

The inferred strategy tracks these scripts are built around are documented in
`docs/META_ENGINE_STRATEGIES.md`. Those tracks are preserved across passes and
act as the labelling vocabulary for `extract_meta_archetypes.py`.

## Status

- Replay files present: **0** (scaffolding only).
- Future work: drop top-player replay JSONs here, then run the three scripts
  from the repo root. Uploading/submitting anything to Kaggle is out of scope.
