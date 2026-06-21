# cg Search Outcome Oracle v0

_Pass 46E. LOCAL / READ-ONLY / DIAGNOSTIC. A never-raise, subprocess-isolated wrapper over the cg Search API plus a transparent one-step action ranker._

## Modules
- `src/ptcg_activegraph/analysis/search_oracle.py` — pure core (NO cg import at module top). Builds count-based search inputs from a frame, runs the subprocess worker, decodes objective post-state signatures, compares them to ground truth, scores `generic_progress_v0`, and ranks one-step actions. Public: `evaluate_action_once`, `evaluate_actions_batch`, `rank_legal_actions_one_step`, `signature_from_current`, `compare_signatures`, `unsupported_search_claims`.
- `src/ptcg_activegraph/analysis/_search_worker.py` — the ONLY place cg / `libcg.so` is imported. Per-task `SIGALRM` budget, start+result JSONL markers (fsync'd), `search_release`/`search_end` cleanup in `finally`.

## Honesty model
- Hidden zones (opponent deck/hand/prize, your prize) are filled by **count only** with valid basic-Pokémon IDs — a labelled `assumption_based_hidden_state`. Opponent hand *contents* are never read or claimed.
- Supported levels: `exact_full_state_replay` / `assumption_based_hidden_state` / `unsupported_or_failed`.
- Permanently unsupported (asserted, never claimed): `exact_damage`, `lethal`, `missed_ko`, `boss_gust`, `spread`, `best_action`, `globally_optimal`.
- Ranking output is `one_step_score_rank under assumption`, explicitly NOT a best/optimal action.

## Calibration snapshot
- attempted=160, supported=147, exact_rate=0.65, mismatch_rate=0.0813 (exact=104, partial=43, mismatch=13).
- **decision: `search_oracle_ready_for_candidate_pilot`.**

## Reproduce
```
python3 scripts/build_pass46e_search_oracle_calibration.py
python3 scripts/build_pass46e_one_step_planner_diagnostic.py
python3 scripts/build_pass46e_search_oracle.py
```
