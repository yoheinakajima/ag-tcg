# Turn-Planning Diagnostic Schema (Pass 46B)

Reusable, **read-only** schema for decoding PTCG game traces into honest turn-planning
diagnostics. Implemented by `src/ptcg_activegraph/analysis/turn_planning.py` (pure; no
production mutation, no network, no storage writes). Reuses the pure
`action_resolver` option decoder.

> Internal/benchmark metrics here are **not** Kaggle leaderboard scores. A "gap" is a
> diagnostic signal, never a promotion/submit signal.

## Trace formats

`detect_format(obj)` returns one of:

| tag | meaning | frames? |
|---|---|---|
| `kaggle_replay` | `steps` is a list of per-seat dicts each with `observation` | yes |
| `cabt_sidecar_frames` | tournament sidecar whose `steps` is a list of frame dicts | yes |
| `cabt_sidecar_outcome_only` | tournament sidecar whose `steps` is an **integer count** | **no** |
| `unknown` | anything else | no |

**Data reality (Pass 46B):** the live tournament sidecars
(`data/tournament/games/*.json.gz`) are `cabt_sidecar_outcome_only` — `steps` is a
count plus outcome metadata, with **no decision frames**. Full decision frames exist
only in the single local Kaggle replay (`data/replays/80374966.json`). The extractor
returns `[]` frames for outcome-only sidecars rather than fabricating any.

## `read_trace(path)`
Reads `.json` and gzipped `.json.gz`. Pure read; raises on missing/corrupt input.

## Option-type normalization
`type` may be an **integer** enum (`13`), a **numeric string** (`"13"`), or a known
**enum name** (`"attack"`). All three are accepted. Unknown strings are left intact
and resolve to the `unknown` family — never guessed.

## `DecisionFrame` fields
`game_id, source, step, turn, acting_player, your_index, context, select_type,
min_count, max_count, n_options, selected_indices, selected_families, option_families,
primary_family, self_board, opponent_board, hand_count, deck_count, prize_remaining,
discard_count, bench_count, supporter_played, stadium_played, energy_attached,
observed_log_events, retreat_observed, legality_ok, legality_notes, notes`.

* `prize_remaining` = `len(player.prize)` (cards left; 6 == took zero).
* `legality_ok` is tri-state: `True`/`False` when verifiable, `None` when not
  checkable. It checks selected indices are in `[0, n_options)` and the pick count is
  within `[min_count, max_count]`. An empty selection with `minCount==0` is a
  legitimate legal pass (`True`); an empty selection with `minCount>0` is **not**
  flagged illegal — in real Kaggle replays the per-seat `action` field does not always
  align with the `select` shown in the same frame, so it is reported `None` with an
  explicit note rather than a fabricated `False`.
* Hidden hand **contents** are never read — only counts.

## Action families
`setup_active, setup_bench, main_play, attach, evolve, ability, retreat, attack,
search_to_hand, discard, switch_to_active, end, unknown`.

Mapping is conservative (`direct_option` from option type, `inferred_from_state` for
setup/evolve, `unknown` otherwise). Retreat is recognized only when an
active↔bench swap appears in engine logs.

## `TurnPlanSummary` fields
`game_id, acting_player, n_frames, first_attack_turn, first_ko_turn, first_prize_turn,
setup_bench_count, bench_occupancy_by_turn, energy_attachments_by_turn,
turns_ending_without_attack, main_end_with_alternatives, search_action_count,
search_card_ids, discard_action_count, discard_card_ids, retreat_switch_count,
ability_use_count, hand_count_trajectory, deck_count_trajectory, dead_low_action_turns,
invalid, timeout, error, unsupported, notes`.

* `first_ko_turn` / `first_prize_turn` are **approximated from opponent
  prize-remaining deltas** (observable), never from inferred damage.
* `first_attack_turn` is the earliest turn where an attack option was actually
  **selected**.

## Always-unsupported claims
`unsupported_flags()` always maps these to `"unsupported / not inferable from trace"`:
`lethal_availability, exact_damage, missed_ko, boss_gust_target_correctness,
spread_placement_correctness, hidden_hand_contents, best_action,
counterfactual_attack_outcome`.

These require a validated Search API / exact attack-outcome oracle that this module
deliberately does not use. Missed-lethal is therefore **never** classified.
