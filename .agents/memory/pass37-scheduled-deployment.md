---
name: scheduled-deployment tournament worker
description: how the Pass 36 engine is wrapped to run safely as a bounded Replit Scheduled Deployment with persistent object storage, AND why its deployment build originally failed (uv editable-install) plus the durable build fixes.
---

# Scheduled-deployment wrapper around the standing tournament engine

A storage/sync/lease layer wraps the UNCHANGED Pass 36 engine so it can run as a
bounded Replit **Scheduled Deployment** (never an always-on server, never the root
"Start application" workflow — that workflow's not-started state is EXPECTED).

**Rule:** `data/tournament/` is a DISPOSABLE working dir; persistent object storage
is the source of truth. Each tick: pull state → run one bounded tick → rebuild
projections → reconcile vs remote → push verified manifest → release lease.
**Why:** the deployment filesystem is not durable, so primary state must live in
storage; production fails CLOSED (raises) if persistent storage is unavailable.

**Rule:** the local backend store must live OUTSIDE the working dir (e.g.
`data/tournament_storage`) so `pull_state` can safely clear the working dir first.
`pull_state` deletes events.jsonl + manifest/conflict reports + projections/runs/games
before download, but KEEPS bootstrap `config.yaml`/`candidate_pool.json` (seed a brand
new tournament when remote is empty) and `locks/` (the lease).
**Why:** a stale local-only file that survives a pull would be pushed back, making the
working dir — not storage — the source of truth.

**Rule:** push must treat base_remote_hash=None + current_remote_hash!=None as DRIFT
(another worker created the remote since we pulled an empty backend) → reconcile/merge,
never overwrite. **Why:** otherwise a late worker silently destroys the other's events.

**Rule (reconcile honesty):** merge by event_id, then enforce one lifecycle event per
(type, game_id):
- GameFinished idempotency is keyed on `artifact_sha256` ONLY — same sha collapses even
  when runtime metadata differs (elapsed_s/result/steps/rewards/run_id/tick_id);
  different non-null sha for the same game_id → ConflictError.
- GameScheduled/GameStarted collapse on a CURATED stable-identity allowlist (game_id,
  candidates, seat_assignment, tournament_id), not "payload minus a volatile blocklist".
- Divergent events are never silently discarded (collapse-as-identical or raise).
**Why:** GameFinished payloads carry volatile runtime fields, so a blanket payload
comparison spuriously aborts legitimate same-sha duplicates; an allowlist is robust to
new volatile fields appearing later.

**Concurrency invariant** (Object Storage has no atomic CAS, so lease is best-effort +
local flock): `interval(2h) > lease TTL(30min) > job timeout(~25min) > --max-seconds(15min)`.
cabt game ≈ 11–15s.

**Deploy:** Scheduled Deployment, cron `0 */2 * * *` UTC, job timeout 25–30 min.
Run cmd: `python scripts/tournament_deployment_tick.py --max-games 20 --max-seconds 900
--storage-backend replit_app_storage --production`. NO Kaggle secrets needed for
tournament-only. NO upload/submit; auto_submit stays false (refuse truthy); internal
scores are local diagnostics, NOT Kaggle. `scripts/print_replit_scheduled_deployment_config.py`
prints the exact setup steps.

# Deployment BUILD failure + fixes (the "build failed to publish" debug)

## uv editable-install into the read-only Nix store (the original build failure)
Replit's deployment build auto-runs `uv sync`. By default uv builds + editable-installs
the ROOT project, writing `__editable__.<pkg>.pth` into the Nix store — which is
read-only in the deploy build → EACCES → build fails.
**Fix:** set `[tool.uv] package = false` in pyproject. Do NOT add dependency-groups /
default-groups — those make uv hit the read-only store too. The worker puts `src/` on
`sys.path` itself, so the package never needs installing.
**How to apply:** whenever `uv sync` runs in a Replit deploy build for a root package,
expect editable-install EACCES unless `package = false`. Verify with `uv sync` → should
print "Audited" with no store write.

## uv cannot install deploy deps; use pip --user in the BUILD command
uv targets the read-only Nix store even for plain deps. Install deploy-only deps with
`python -m pip install --user --break-system-packages <pkgs>` → lands in the writable
`.pythonlibs` (PYTHONUSERBASE) which the runtime python keeps on `sys.path`. The
`--user` flag is essential (without it the install is wrong/blocked).

## The game engine is kaggle_environments' BUNDLED "cabt" env, NOT the standalone cabt module
Games run via `kaggle_environments.make("cabt")`. The standalone `cabt` python module is
NOT importable in this workspace and is NOT needed — the "cabt" env (cabt.json + cabt.py
+ native cg lib) ships INSIDE the kaggle-environments wheel (validated on 1.30.1; in its
dist RECORD).
**Why:** a deploy build installing only object-storage + pyyaml runs games that all error
(missing kaggle_environments) → zero tournament progress even though publish "succeeds".
So `kaggle-environments==1.30.1` must be in the build command.
**How to apply:** pin to the workspace-validated kaggle-environments version; a newer
release could drop/alter the bundled cabt env.

## A failing game NEVER fails the tick (publish-success is decoupled from game-success)
Each game runs in an isolated subprocess; on crash/timeout/exception the runner records
result=timeout/error and CONTINUES — game failures are never raised to the tick.
`tournament_deployment_tick` returns non-zero ONLY on a top-level unexpected exception or
storage-unavailable / refused / conflict / lease_held. So the Scheduled Deployment
promote (run command must exit 0) succeeds even if every game errors.
**How to apply:** when debugging a deploy publish failure, separate "does the run exit 0"
(publish) from "do games make progress" (engine health) — they have independent fixes.
