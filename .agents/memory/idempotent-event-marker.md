---
name: idempotent multi-step event emission must strip by a UNIQUE marker tag
description: A re-runnable emitter that "delete-then-reappend my events" must filter by a tag UNIQUE to that sub-step, never the shared pass tag — or it deletes earlier sub-steps' events on the same ledger.
---

# Idempotent re-emit must key on a unique sub-step marker, not the shared pass tag

A re-runnable event emitter that achieves idempotency by "remove my prior events,
then append the current set" must select the rows to remove by a tag that is
**unique to that emitter/sub-step** (e.g. `pass41_eventset`), NOT by the broad
shared pass tag (e.g. bare `pass41`). Multiple sub-steps of the same pass write to
the SAME ledger and all carry the shared pass tag; stripping by the shared tag
deletes the OTHER sub-steps' events too (e.g. the per-game benchmark events an
earlier part wrote), silently corrupting the ledger on the second run.

**How to apply:** give each idempotent emitter its own marker tag and strip only
rows carrying that marker. Keep the shared pass tag for reporting/scans, but never
use it as the idempotency delete key. Verify by running the emitter twice and
asserting BOTH ledgers' event counts are stable AND earlier sub-steps' events
survive.

**Why:** event tags are a shared namespace across a pass; idempotency that deletes
by a shared key is destructive to siblings, and the loss is invisible until you
diff event counts across re-runs.
