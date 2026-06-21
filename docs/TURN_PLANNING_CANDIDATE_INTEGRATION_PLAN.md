# Turn-Planning Candidate Integration Plan

_Pass 46D. FUTURE plan only — no implementation. Read-only / infrastructure. No candidate was generated; primitives are not yet wired into candidate generation. No Kaggle strength claim._

## How candidate generation v1 can use these primitives

- Generate candidate decks as today (deck-composition operators on INTERNAL sources only), then use the primitives to SCREEN a candidate's local trace behavior before admitting it to probation — e.g. flag candidates whose attach destinations or setup behavior look pathological vs their parent.
- Use legal_action_family_summary + family_frame_counts as a cheap behavioral fingerprint to detect inert / no-op mutations (a candidate whose family distribution is byte-identical to its parent is a non-inert-failure signal).

## Stdlib-safe agent subset

- A stdlib-only agent (no `import cg`) can call: safe_get, normalize_option_type, normalize_select_context, classify_option_family, legal_action_family_summary, board_snapshot_from_frame, visible_counts_by_zone, energy_attach_candidates, score_energy_attach_generic, search/discard_candidate_summary, unsupported_claims.
- These operate purely on the raw observation/select dicts already passed to a Kaggle agent, so no extra dependency or runtime is introduced.

## cg_typed / Search-capable full primitive stack

- A cg-typed / Search-API-capable agent can use the full stack AND supply the typed extras the v0 primitives intentionally leave unsupported: exact attach value, attacker readiness/role tags, fetch/discard PRIORITY ordering, and deckout projection (draw_deckout_guard).
- Only such an agent may make damage/lethal/KO claims, and only when backed by the cg Search API — never from a numeric attackId alone.

## Gates required before ANY candidate is generated from this

- Production must NOT be soaking a still-unresolved probation cohort (a fresh readiness check must say a probation candidate is near thresholds first).
- Safety stop-gate (Part A) must pass: root main/deck byte-identical, deployment unchanged, zero reference leakage, zero forbidden events.
- Any candidate screened by these primitives stays LOCAL probation; promotion still requires the existing aggregate AND direct-H2H Wilson gate.
- Public references remain benchmark-only and may never become a source/parent.

## Explicitly NOT implemented in Pass 46D

- No candidate was generated, screened-for-promotion, queued, or promoted in 46D.
- Primitives are infrastructure only; wiring them into candidate generation is a FUTURE v1 pass, not this one.
