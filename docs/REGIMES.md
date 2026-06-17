# Regimes

A **regime** is a discipline for improvement. It maps:

```
failure class  →  allowed patch seam  →  validation protocol  →  promotion rule
```

Source: `src/ptcg_activegraph/regimes/`.

## Why constrain patches?

"Make it better" with no constraints produces overfitting, instability, and
unattributable regressions. Regimes force every change to declare *what kind of
problem it solves*, which *bounds the code it may touch* and *defines the proof
it must provide* before promotion.

## Regime categories

| Regime | Concerned with |
| --- | --- |
| `STABILITY` | crashes, timeouts, invalid returns, empty selects, fallback overuse |
| `DECK_CONSTRUCTION` | bricks, no basics, decking out |
| `SEQUENCING` | bad energy attachment / evolution / retreat / bench ordering |
| `PRIZE_RACE` | missed attacks/knockouts, low damage, losing the race |
| `BELIEF_HIDDEN_INFORMATION` | missing opponent threats, hidden-info mistakes |
| `META_LEADERBOARD` | overfitting to a single opponent/meta |
| `UNKNOWN` | insufficient evidence; triage only |

## Failure tags

```
exception  timeout  invalid_return  empty_select  fallback_used
lost_game  draw_game  missed_attack  missed_knockout  bad_energy_attachment
bad_evolution  bad_retreat  bad_bench  deck_brick  no_basic  low_damage
deck_out  opponent_threat_missed  overfit_suspected  unknown
```

`regime_for_tags(tags)` resolves the single governing regime; when tags span
multiple regimes, a **priority order** applies (STABILITY > DECK_CONSTRUCTION >
SEQUENCING > PRIZE_RACE > BELIEF_HIDDEN_INFORMATION > META_LEADERBOARD), because
foundational problems must be fixed before subtler ones.

## Allowed patch seams

A patch is **data describing a constrained change**, never an automatic code
mutation. Seams:

```
deck_list  card_role_tags  heuristic_weights  action_priority_rules
belief_sampler_parameters  search_depth_budget  state_evaluator_formula
fallback_ordering
```

Each regime allows only a subset, e.g.:

| Regime | Allowed seams |
| --- | --- |
| `STABILITY` | `fallback_ordering`, `action_priority_rules` |
| `DECK_CONSTRUCTION` | `deck_list`, `card_role_tags` |
| `SEQUENCING` | `action_priority_rules`, `heuristic_weights`, `card_role_tags` |
| `PRIZE_RACE` | `heuristic_weights`, `action_priority_rules`, `state_evaluator_formula` |
| `BELIEF_HIDDEN_INFORMATION` | `belief_sampler_parameters`, `search_depth_budget`, `state_evaluator_formula` |
| `META_LEADERBOARD` | `deck_list`, `heuristic_weights` |

## Validation protocols & promotion rules

Protocols (`regimes/validation.py`) are data evaluated by the lab. Examples:

| Protocol | Games | Opponent | Gate |
| --- | --- | --- | --- |
| `stability_smoke` | 100 | self | 0 crashes; fallback rate must not rise |
| `deck_matrix` | 200 | matrix | +2% win rate; no new bricks |
| `sequencing_baseline` | 300 | baseline | +3% win rate; fewer sequencing tags |
| `prize_race_baseline` | 500 | baseline | +3% win rate; missed_knockout rate < 10% |
| `belief_search` | 500 | baseline | +2% win rate; within time budget |
| `meta_holdout` | 500 | matrix | +2% on held-out opponents (anti-overfit) |

`evaluate_validation(protocol, results)` returns a pass/fail report against the
measured `crashes`, `fallback_rate`, `winrate`, `baseline_winrate`,
`failure_tag_rate`.

## A patch plan

```python
from ptcg_activegraph.regimes import classify_summary, new_patch_plan

c = classify_summary(match_summary)         # tags + regime + evidence
plan = new_patch_plan(c.regime, c.tags, hypothesis="raise knockout weight to 120")
# plan.allowed_patch_seams is restricted to the regime
# plan.validation_protocol carries the games/thresholds
# plan.status: proposed → validating → passed/rejected → promoted
```

## Example walk-through

1. A match summary shows `fallback_count=4` and `result="loss"`.
2. `classify_summary` tags `fallback_used` + `lost_game`; regime = `STABILITY`
   (fallback wins priority).
3. `new_patch_plan` permits only `fallback_ordering` / `action_priority_rules`
   and attaches `stability_smoke`.
4. We tweak action priority, run 100 self-play games, confirm **zero crashes**
   and fallback rate did not increase.
5. Promote → emit `PolicyPromoted`; otherwise reject with evidence.
