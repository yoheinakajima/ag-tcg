# Runtime Agent

The runtime agent is what Kaggle runs. It lives in `main.py` (self-contained,
stdlib only) with an optional richer `agent.py`, and is mirrored by the testable
package modules under `src/ptcg_activegraph/runtime/`.

## Contract

```python
def agent(obs_dict: dict) -> list[int]: ...
```

`obs_dict` has:

* `logs` — event logs (list, optional).
* `current` — board state (dict or `None`, e.g. during deck/setup).
* `select` — legal choices: `{"options": [...], "maxCount": int, "minCount": int}`
  (or `None`).

Return: a list of **legal option indices** into `select["options"]`. The engine
only presents legal moves.

## Guarantees

* **Never raises outward.** Any internal error degrades to the fallback.
* **Always legal.** Output is unique, in-range, respects `maxCount`/`minCount`.
* **Handles nulls.** Missing/`None` `current` or `select` → `[]`.
* **Deterministic.** Same observation → same selection (tie-break by lowest
  index).

## The cascade

```
1. Parse the observation defensively.
2. Parse `select`; if missing/empty → return [].
3. Determine maxCount / minCount (clamped to #options).
4. (optional) Search policy — only if cabt present, enabled, and time remains.
5. Heuristic policy — keyword/field ranking of options.
6. Fallback policy — guaranteed-legal default.
7. Validate / repair output (range, uniqueness, count) and return.
```

Implemented in `runtime/agent_core.py:choose` and mirrored inside `main.py`.

## Observation parsing (`runtime/observation.py`)

`parse_observation(obs)` → `ParsedObservation` with `options`, `max_count`,
`min_count`, `legal_indices`, `has_choice`. Tolerates `None`, non-dicts, missing
keys, and malformed option lists. `maxCount` defaults to `1` when options exist
but no count is given (the common "pick one" case).

## Action parsing (`runtime/action.py`)

Since the cabt option schema may vary, options are normalized into an
`OptionView` with:

* `text` — a lower-cased JSON/string serialization for keyword scoring.
* `fields` — a shallow field map for dict-shaped options.

`serialize_option` never raises, even on exotic objects.

## Fallback policy (`runtime/fallback_policy.py`)

Pure legality, no semantics:

* `maxCount == 0` → `[]`
* `maxCount == 1` → `[0]`
* `maxCount > 1` → first `maxCount` options (or `min_count` when set), clamped to
  availability.

`clamp_selection` repairs any proposed selection: drops invalid/out-of-range,
de-dupes, truncates to `maxCount`, pads to `minCount`, and falls back if empty
when a choice is required.

## Heuristic policy v1 (`runtime/heuristic_policy.py`)

Serialize each option to text, score by keywords, prefer higher scores, tie-break
on lower index.

Positive signals: `knock +100`, `prize +80`, `attack +80`, `damage +50`,
`evolve +45`, `attach`/`energy +40`, `draw +35`, `search +35`, `supporter +30`,
`ability`/`skill +30`, `item +25`, `bench +20`, `switch +15`, `active +12`.

Cautious/negative: `end -100`, `pass -100`, `discard -20`, `trash -20`,
`retreat -10`. The discard/trash penalty is **waived** when the option also looks
like draw/search/attack/attach/evolve (discard-as-cost on a good play).

> Scores are additive, so two medium keywords can stack. This is intentional for
> v1 (stable over random). Tuning the weights is the `heuristic_weights` patch
> seam.

For multi-select, the top `maxCount` positively-scored options are returned in
ascending index order (satisfying `minCount` even if remaining options score ≤0).

## Time safety (`runtime/time_manager.py`)

A soft per-call budget. The search path only runs while budget remains; the
manager only *advises*, never enforces, so it can't cause an exception.

## Optional search (`runtime/search_policy.py`)

**Off by default.** When cabt search APIs (`search_begin/step/end/release`) are
importable and search is explicitly enabled, `SearchPolicy.suggest` may evaluate
candidate actions with shallow lookahead. It always releases search resources in
`finally` and returns `None` (defer to heuristic) on any problem. The evaluation
seam is marked and not yet validated.

## How to improve it

* **Weights** → tune `POSITIVE_WEIGHTS` / `NEGATIVE_WEIGHTS` (regime: PRIZE_RACE
  / SEQUENCING). Keep `main.py` in sync with the package.
* **Field-aware scoring** → once the cabt option schema is known, read concrete
  fields (damage numbers, energy cost) in `OptionView.fields` instead of keywords.
* **Search** → wire the `SearchPolicy` evaluation seam and validate within the
  time budget (regime: BELIEF_HIDDEN_INFORMATION).

> Keep `main.py` self-contained. Any change validated in the package must be
> hand-mirrored into `main.py`'s embedded policy (the submission ships `main.py`,
> not `src/`).
