# Turn-Planning Primitives v0

_Pass 46D. Pure, read-only, never-raising building blocks for turn-planning diagnosis and (future) candidate generation. Infrastructure only — NOT a Kaggle strength claim, no production mutation, no candidate generation._

Module: `src/ptcg_activegraph/analysis/turn_primitives.py`

## Design invariants
- pure / read-only (no Object Storage or EventStore writes, no network)
- never raises on malformed/missing data (structured unknown results)
- no dependency on production state
- no public-reference policy code import
- no deck-specific card strategy beyond generic role classification
- hidden opponent hand contents never read or fabricated (counts only)

## Primitives (v0 implemented vs backlog)

### typed_board_decode_wrapper — `implemented_v0`

Decode any accepted frame shape (Kaggle-replay seat object, raw observation, bare select, or DecisionFrame) into a normalized, never-raising board snapshot with per-zone visible counts.

- **v0 functions:** safe_get, board_snapshot_from_frame, visible_counts_by_zone
- **backlog:** Native cg-typed (cg.api dataclass) decode path; richer per-Pokemon attached-energy / HP decode when a typed observation is supplied.

### legal_option_taxonomy — `implemented_v0`

Normalize option type codes/strings/enum-names and classify each legal option into a conservative action family + coarse taxonomy bucket.

- **v0 functions:** normalize_option_type, normalize_select_context, classify_option_family, legal_action_family_summary
- **backlog:** Disambiguate move_energy vs retreat without logs; evolve vs bench-place for play_in_play when a typed board is available.

### board_role_summary — `implemented_v0`

Summarize the acting seat's and (counts-only) opponent's board roles: active presence, bench occupancy, hand/deck/discard/prize counts.

- **v0 functions:** board_snapshot_from_frame, visible_counts_by_zone
- **backlog:** Attacker-readiness / role tags (attacker vs support vs pivot) which require card typing from a cg-typed observation.

### energy_planner — `implemented_v0`

Enumerate attach-energy options with their visible destination zone and give a GENERIC (deck-agnostic) ordering: fuel the active attacker before developing the bench. No value/lethal computation.

- **v0 functions:** energy_attach_candidates, score_energy_attach_generic
- **backlog:** Value-of-information / attacker-cost-aware attach scoring (requires attack cost typing + a trusted Search API).

### setup_planner — `implemented_v0_partial`

Detect the setup phase (turn 0/1 or absent self-active) and, when the trace encodes placement destinations, list active vs bench candidates.

- **v0 functions:** setup_candidate_summary
- **backlog:** These traces encode setup as a hand-select with NO active/bench destination in the option schema, so destination labelling needs a richer (cg-typed) observation; only phase + active-presence are honest here.

### search_priority_planner — `implemented_v0`

Enumerate deck-search (select-from-deck) options and surface ONLY the card ids positively resolvable from select.deck[index].

- **v0 functions:** search_candidate_summary
- **backlog:** Priority ORDERING of fetch targets (needs card typing + role goals); v0 only lists visible candidates, it does not rank them.

### discard_priority_planner — `implemented_v0`

Enumerate discard (select-from-discard) options and surface ONLY the resolvable card ids.

- **v0 functions:** discard_candidate_summary
- **backlog:** Priority ORDERING of what to discard (needs card typing); v0 only lists.

### draw_deckout_guard — `backlog`

Surface deck-out risk from the visible deck_count so a future policy can avoid lethal self-deckout.

- **v0 functions:** visible_counts_by_zone (exposes deck_count)
- **backlog:** The raw input (deck_count) is already exposed by visible_counts_by_zone, but the guard policy (draw-count modelling, deckout-turn projection) is deferred to v1.

### unsupported_claim_guard — `implemented_v0`

Expose the fixed, stable set of claims the primitives REFUSE to infer from a bare trace, so callers/tests can assert guarantees never shrink.

- **v0 functions:** unsupported_claims
- **backlog:** None — guard is intentionally static; new unsupported claims are added only when a corresponding trusted source is introduced.

## Honesty contract

The following are ALWAYS marked unsupported and are never inferred from a bare trace (see `unsupported_claims()`):

- `best_action`
- `boss_gust_target_correctness`
- `chosen_action_recovery`
- `counterfactual_attack_outcome`
- `exact_attach_value`
- `exact_damage`
- `hidden_hand_contents`
- `lethal_availability`
- `missed_ko`
- `spread_placement_correctness`

Numeric `attackId` alone is insufficient for a damage/lethal claim.
