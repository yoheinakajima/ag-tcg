# Turn-Planning Primitive Backlog (Pass 46B)

Reusable turn-planning primitives proposed by the Pass-46B reference-gap diagnostic.
The diagnostic's central finding: the gap to public references is broad and
**behavioral (gameplay policy / turn planning)**, not deck-list counts. The next
improvement pass should build **reusable primitives** (a `cg_typed` / search-capable
policy lane), **not** another one-off deck.

> Read-only planning artifact. Nothing here promotes, generates, submits, or mutates
> production. Internal/benchmark metrics are not Kaggle scores.

## Status legend
`ready_for_design` · `needs_more_trace_evidence` · `needs_cg_typed_lane` ·
`needs_search_api` · `special_pilot_only` · `blocked_or_unsupported`

## Primitives

| id | title | status | notes |
|---|---|---|---|
| `typed_board_decode_wrapper` | Typed board decode wrapper | ready_for_design | Pass-46B extractor already yields honest counts; promote to a reusable typed view. |
| `legal_option_taxonomy` | Legal option taxonomy | ready_for_design | `action_resolver` + `classify_action_family` cover positively-observed codes with safe unknown fallback. |
| `turn_phase_plan` | Turn phase plan | needs_more_trace_evidence | setup-active → setup-bench → development → attack → recovery → prize-race. |
| `energy_planner` | Energy planner | needs_cg_typed_lane | attach to current vs future attacker; avoid over-attaching; enable retreat. |
| `search_planner` | Search planner | needs_cg_typed_lane | basics if bench thin, evolution if base present, energy to unlock attack, draw if hand dead. |
| `discard_planner` | Discard planner | needs_more_trace_evidence | preserve unique basics/evolutions/energy thresholds; shed excess late. |
| `attack_planner` | Attack planner | needs_cg_typed_lane | attack when available and productive; **never** claim lethal/missed-KO without a validated Search API. |
| `retreat_switch_planner` | Retreat/switch planner | needs_more_trace_evidence | promote attacker-ready mon; preserve high-prize damaged attacker when possible. |
| `deckout_draw_safety_gate` | Deckout / draw-safety gate | ready_for_design | avoid drawing into deckout; protect deck count late. |
| `prize_race_heuristics` | Prize-race heuristics | needs_cg_typed_lane | track prize differential; bias plays to win the prize race. |
| `reference_parity_benchmark_gate` | Reference-parity benchmark gate | ready_for_design | benchmark-only closeness-to-references gate **before** any promotion. |
| `search_api_counterfactual_probe` | Search API counterfactual probe | needs_search_api | small bounded read-only feasibility only; no live policy. |

## Top 3 to build next
1. `typed_board_decode_wrapper` — foundation for every other primitive.
2. `legal_option_taxonomy` — robust, safe-fallback action classification.
3. `energy_planner` — highest-leverage behavioral gap (slow setup / attack lag).

## Honesty boundary
Primitives that require knowing exact attack outcomes, lethal availability, or hidden
hand contents are gated behind `needs_search_api` and are out of scope until a
validated Search API exists. They must never ship as confident heuristics built on
inferred damage.
