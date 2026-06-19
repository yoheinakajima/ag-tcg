# Pass 29 — Observability / Fixture Backlog (Part I)

- Executable now: **2**; one capture away: **1**; needs more observability: **3**.

| fixture | observability | executable now | status | priority |
|---|---|---|---|---|
| effect_loop_exit_guard | fully_observable | True | BUILT_AND_VALIDATED | P0 |
| search_target_ctx7 | observable | True | ready_to_build | P1 |
| single_target_attack | one_capture_ratchet_away | False | blocked_on_cheap_capture | P1 |
| spread_bench_target | needs_more_observability | False | needs_more_observability | P2 |
| supporter_effect_sequencing | needs_more_observability | False | needs_more_observability | P2 |
| in_play_action_source | needs_more_observability | False | needs_more_observability | P3 |

## Evidence

- **effect_loop_exit_guard** — exit option observable 1958/1958 at ctx0; eval verdict effect_loop_exit_candidate_built
- **search_target_ctx7** — search-to-hand (ctx7) target identity resolvable from select.deck / candidate resolver
- **single_target_attack** — attackId observable 1.0; defender active identity captured as null in trace (0.0) — exists in raw obs, add opponent_active to the snapshot
- **spread_bench_target** — opponent bench identity and per-target damage are wholly unobserved; spread cannot be attributed to a bench slot
- **supporter_effect_sequencing** — supporter/Trainer effect OUTCOMES are not linked to the play event; play_from_hand identity 0.0
- **in_play_action_source** — in_play_action source Pokemon identity rarely resolvable (0.031); this is the very loop-head action the guard now fences
