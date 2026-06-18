---
name: Kaggle get_last_callable entrypoint ordering
description: Why deck-safety wrappers must use a fresh name, and how the active control's wrapper became inert
---

# Kaggle entrypoint = LAST top-level callable

kaggle_environments picks the agent via `[v for v in env.values() if callable(v)][-1]`
— the LAST callable in module **insertion order**.

**Rule:** Rebinding an existing global name does NOT move it to the end of insertion
order. So `_SAVED = agent; def agent(...)` leaves the ORIGINAL `agent` value reachable
only via the later-inserted `_SAVED` key, which then becomes the last callable. The
new wrapper (`agent`) is NOT last and is silently bypassed on Kaggle.

**Why it matters:** A deck-safety / deck-return wrapper installed by rebinding `agent`
is INERT in production. To actually be the entrypoint, the wrapper must use a FRESH
name defined LAST (the core-pilot compiler emits `core_pilot_agent` last for this).

# Active control caveat (combo_full_safety_v3_fixed)

Its `_PRE_DECK_SAFETY_AGENT = agent; def agent(...)` pattern makes `_PRE_DECK_SAFETY_AGENT`
(the original, deck-unaware strategy agent) the last callable. That original returns the
60-card deck ONLY when the deck obs has explicit `select=None, current=None` keys; it
returns `[]` if those keys are ABSENT. So the control is not provably Kaggle-INVALID, but
its deck-safety hardening is inert and it is fragile to obs-shape variation. The
core-pilot v1/v2 candidates pass both the canonical and keys-absent deck probes.

**How to apply:** Any candidate that wraps the entrypoint must keep a fresh-named callable
LAST. The entrypoint validator (scripts/validate_candidate_entrypoint.py) ratchets this:
it probes multiple deck-obs shapes (incl. keys-absent and a dict-like Struct) and requires
60 on all of them plus legal indices on gameplay.
