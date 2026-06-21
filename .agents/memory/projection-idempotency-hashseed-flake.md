---
name: projection idempotency hash-seed flake
description: pass36 projection-idempotency regression test is PYTHONHASHSEED-sensitive and flakes in the full suite, not a real regression
---

`tests/test_pass36_tournament_engine.py::test_projections_rebuild_from_events_idempotent`
can fail intermittently when the full `pass36_*` regression runs without a pinned
`PYTHONHASHSEED`. It passes in isolation and with `PYTHONHASHSEED=0` (and/or
`-p no:randomly`).

**Why:** the projection rebuild's equality check is sensitive to dict/set iteration
order, which varies across processes under hash randomization. The two rebuilds inside
one process agree, but cross-run ordering of some candidate/string fields differs,
tripping a strict comparison. It is a test-determinism quirk, NOT a soak/audit
regression — read-only passes (e.g. Pass-45) never touch projections.

**How to apply:** if a `pass36_NN_regression` workflow goes red ONLY on this test,
re-run with `PYTHONHASHSEED=0 ... -p no:randomly` before treating it as a real break.
The regression workflows intentionally do NOT pin the seed (matches prior-pass
convention); don't pin it just to hide the flake — that would mask the underlying
ordering nondeterminism.
