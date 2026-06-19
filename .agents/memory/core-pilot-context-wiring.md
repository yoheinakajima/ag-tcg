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
delegated to the base agent — never wire it as a *broad* override. A **narrow ctx0
sub-action** IS permissible if it provably refines only WHICH option (never whether/
how-many) and bails to base on any mismatch — e.g. Pass 22's emergency_backup_bench:
fires only when the bench is literally empty, never touches a type-13 attack option,
never benches a non-benchable card. The compiler emits a single fresh-named callable
(core_pilot_agent) as the LAST top-level def; Kaggle runs the last callable, so the
last-callable invariant is HARD. Candidates whose last resolved callable is anything
else (e.g. _PRE_DECK_SAFETY_AGENT) FAIL the entrypoint validator and are anchor-only.

**Scope discipline (the compiler gates EVERY branch on `_CP_RUNTIME_CONTEXTS`
membership):** a candidate's `runtime_contexts` must equal the proven-base contexts
PLUS only the contexts the current pass actually adds. Listing an extra context
silently ACTIVATES that branch's refinement, broadening scope beyond the claimed
hooks (a real spec-drift bug, not cosmetic). The proven water v2 base refines only
(7,8); a pass that adds one ctx0 hook should ship (0,7,8), NOT inherit unrelated
(1,2,38). Add a test asserting the compiled tarball's `_CP_RUNTIME_CONTEXTS` equals
the intended tuple, and keep the build manifest + final report context list in lockstep.
