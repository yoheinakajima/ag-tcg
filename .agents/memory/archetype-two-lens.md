---
name: Two archetype lenses (legacy static vs live replay-derived)
description: Why the meta archetype layer exists twice and must not be unified.
---
The project carries TWO archetype layers on purpose. Do not "fix the contradiction" by merging them.

- **Legacy/static lens** — `meta/archetypes.py` `build_archetypes_yaml_obj()` uses a static `ARCHETYPES` dict (mirror + metal + maxbelt) plus a conservative ~11-card `CONFIRMED_CARDS` set (playbooks schema). Some entries stay BLOCKED. Two invariant tests guard it: `test_archetype_yaml_blocked_rows_carry_no_ids` and `test_archetype_yaml_no_invented_ids_anywhere`. These are valid invariants — leave them untouched.
- **Live/truth lens** — Part D `classify_deck` (broader `SIGNATURE_CARDS`) produces `data/meta_replays/archetypes.yaml`, and Part F `scripts/update_meta_pool_from_replays.py` produces `experiments/meta_pool.yaml`. This is the real, replay-derived meta used for evaluation.

**Why:** the static lens is a conservative, hard-coded safety net (no invented ids, explicit blocks); the live lens reflects whatever real extracted replays prove. They answer different questions (what we're certain of vs what the corpus currently shows). Collapsing them would either leak unconfirmed ids into the conservative layer or weaken the invariant tests.

**How to apply:** when reporting or evaluating, treat `data/meta_replays/archetypes.yaml` + `experiments/meta_pool.yaml` as live truth. Mention the two-lens split in any final report so reviewers don't flag the duplication as a bug.

Note on `meta_pool.yaml` shape: coverage fields (`coverage_status`, `eval_complete`, `blocked_archetypes`) are nested under a top-level `coverage:` block, not at root. `replay_processing_state.json`'s `decks_written` is a list (count it). An `is_ours: True` mirror archetype (e.g. water_kyogre_abomasnow_passive_mirror) legitimately spans all episodes — it's our own deck, not an opponent bucket.
