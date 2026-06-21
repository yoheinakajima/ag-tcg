---
name: deploy-image tarball visibility + key-scoped prod registration
description: How to safely register new candidate tarballs into prod OS for a Scheduled Deployment whose engine resolves tarballs from the deploy-image filesystem, not Object Storage.
---

# Deploy-image tarball visibility & key-scoped production registration

Candidate `.tar.gz` tarballs are **NOT** in the Object-Storage sync set (only
`events.jsonl`, `candidate_pool.json`, `config.yaml`, projections/runs/games). The
deployed daemon resolves a game's tarball from the **deploy-image filesystem**
(`data/submissions/<tarball_path>`). So a pool entry can sync to prod OS while its
tarball is absent from the running image → schedulable candidate the daemon can't
load → missing-tarball error games.

**Rule:** never register a new candidate into prod OS until its tarball is proven
present in the deploy image. The image only gets a new tarball when the operator
**republishes** from a commit that contains it.

**Honest deploy-visibility inference (not proof):** `deploy_image_has_tarball=true`
only if the tarball is git-tracked at the published commit AND its sha256 matches the
generation manifest AND the working tree is clean for the tarball + root paths. Mark
this explicitly as inference. The **binding** confirmation is a controlled production
tick that actually resolves and runs the tarball.
**Why:** you cannot read the deploy image's filesystem directly from the interactive
env; baked-bytes can only be inferred from git + verified by a live run.

**Binding runtime proof when a full tick is infeasible:** a full `--production` tick
over ~950 keys exceeds the interactive tool timeout (serial `pull_state`) and is
unsafe (lease/manifest contention with the live daemon). Instead run a single
bounded in-process game pulled from the real `prod_scheduler_queue`, confirming the
engine resolves all target tarballs and the game runs to completion. The deployed
daemon does the full pull/push on its own cron; deploy logs confirm it.

**Key-scoped registration when prod is far ahead of local:** the deployed daemon
accrues hundreds of game sidecars, so prod ledger ≫ local. Register by appending
ONLY the missing candidate events (lease → pull events+pool+config only → reconcile →
append → rebuild → refresh manifest → sha-verified push of only changed keys →
release). Push events/pool/config/manifest family only — **never** re-push the game
sidecars. Verify `manifest.event_count == ledger length` after.
**Why:** a full pull/push of all keys times out and risks clobbering daemon-written
sidecars; the registry is fully event-sourced so the pool rebuilds from events alone.

**Fail-closed gating:** prod mutation is permitted ONLY when the availability
decision is deploy-visible (`case_1*`) AND the safety preflight is safe. While a
republish is still required the decision must resolve to no-mutation. Tests should
assert this invariant, not the pre/post-republish literal (the shared decision
artifact legitimately flips case across passes).
