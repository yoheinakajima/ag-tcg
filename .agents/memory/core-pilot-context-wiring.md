---
name: core-pilot context wiring
description: Rules for expanding compiled core-pilot runtime context coverage safely.
---

Wire a cabt context into the compiled runtime ONLY when it is confirmed cross-source:
the empirical replay shape (select_type, option types, min/max counts) AND the live
self-play trace shape must match. Single-source (replay_only or live_only) contexts are
NOT wire-eligible — defer them.

**Why:** Wiring an unconfirmed context risks emitting an action shape Kaggle rejects
(INVALID) or hijacking a decision the base agent handled better. Pass 16's confirmed set
was [0,1,2,3,4,7,8,22,38,41]; the v3 candidate wired only (1,2,7,8,38) and still lost to v2.

**How to apply:** Broad Main (ctx 0, type0 with attackId/inPlayArea options) MUST stay
delegated to the base agent — never wire it. The compiler emits a single fresh-named
callable (core_pilot_agent) as the LAST top-level def; Kaggle runs the last callable, so
the last-callable invariant is HARD. Candidates whose last resolved callable is anything
else (e.g. _PRE_DECK_SAFETY_AGENT) FAIL the entrypoint validator and are anchor-only.
