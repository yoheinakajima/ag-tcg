---
name: tournament ledger <-> storage manifest lockstep
description: Any offline op that appends to the tournament event ledger must also refresh storage_manifest.json locally, or a hard health check fails.
---

# Ledger append must refresh the storage manifest in lockstep

`data/tournament/storage_manifest.json` (schema `pass37_storage_manifest_v1`) records an
`event_count` snapshot of `data/tournament/events.jsonl`. The local health check
`manifest_event_count_matches` (in `scripts/check_tournament_health.py`, run by
`health.run_checks(health._local_bundle())`) is a **HARD** check: `manifest.event_count`
must equal the live ledger length.

**Rule:** any offline / out-of-band operation that emits events to the tournament ledger
(e.g. candidate admission) must, as its local-finalization tail, refresh the storage
manifest by calling `sync.build_manifest(sync.TOURNAMENT_DIR, sync.collect_local_keys(...),
base_remote_hash=<preserved>, tick_id=<preserved>, status="clean")`. That writer is
LOCAL-only and stamps `no_upload=True`; it never touches the remote backend. Do NOT use
`sync.push_state` for this — push_state pulls/merges/writes remote.

**Why:** the standing daemon does emit-events → rebuild-projections → `push_state`
(which calls `build_manifest`) at the tail of every tick, so the manifest never drifts in
normal operation. An offline pass that appends events but skips the manifest refresh leaves
local state inconsistent and turns the next `pass36-42` regression run hard-red on pass38.

**How to apply:** preserve `base_remote_hash` and `tick_id` from the prior manifest (you are
not changing remote state). `collect_local_keys` already excludes the manifest/lock files, so
it won't try to hash itself. Re-running the op stays idempotent on *events* (0 re-emitted);
only the manifest's `generated_at` + file SHAs + `event_count` refresh — that is expected and
correct, not a regression.
