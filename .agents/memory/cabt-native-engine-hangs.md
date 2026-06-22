---
name: cabt / open_spiel native engine hangs
description: Why every cabt game must run in a subprocess with a hard wall-clock timeout, not an in-process SIGALRM watchdog.
---

# cabt games can hang inside native C; SIGALRM cannot interrupt them

`kaggle_environments.make("cabt")` + `env.run(...)` can wedge inside the native
open_spiel C engine for specific deck/pilot pairings. A Python-level
`signal.alarm` watchdog set in the SAME process CANNOT interrupt a hang in native
code — the alarm never fires until control returns to Python, which never
happens.

**Rule:** run every cabt game in a CHILD PROCESS and enforce the timeout from the
parent with `subprocess.run(..., timeout=GAME_TIMEOUT_S + slack)`; on
`TimeoutExpired` record the game as a timeout and move on. The repo's
`scripts/_pass34_game_worker.py` is the canonical single-game worker for this.

**Also covers `validate_candidate_entrypoint.py --smoke`:** its internal `--smoke`
step runs one live cabt game with an in-process SIGALRM watchdog, so calling
`_VENT.validate(tar, smoke=True)` in-process can hang the whole harness. Invoke
the validator as a SUBPROCESS CLI (`python validate_candidate_entrypoint.py TAR
--smoke`) wrapped in `subprocess.run(timeout=...)` instead.

**Why:** a Pass-35 validation harness hung for >600s on the gardevoir/raging_bolt
candidates' in-process `--smoke` game; isolating it into a hard-timeout
subprocess fixed it. Always make game-running harnesses resumable + per-candidate
checkpointed so a kill mid-run loses at most one candidate's work.

## Amortize the import for many-game runs (tournaments)

Per-game subprocess isolation is correct for safety but the `kaggle_environments`
import dominates cost (~7-8s import vs ~0.5-3s for a short cabt game), so a 200+
game tournament would spend most of its time re-importing. For large batches use a
MULTI-game worker that imports ONCE and plays a batch in-process, but keep both
hang-safety and crash-safety:
- Stream one JSON line PER GAME to a **persistent** JSONL (`flush()` + `os.fsync`),
  NOT a temp file. Then the parent can hard-kill the worker on a native hang (or
  the 120s tool cap can kill the whole harness) and completed games still survive;
  the next call folds the JSONL back in (idempotent by game_id) with zero replay.
- Emit a `start` marker before each game and a `result` after; a `start` with no
  matching `result` is the game that wedged the engine — cap it as a timeout after
  N attempts so one bad pairing can't loop forever.
- Size worker budget so `budget + game_timeout + slack < 120s` (the bash tool cap),
  e.g. budget≈80, game_timeout≈28. Re-invoke the harness until it self-reports
  complete (delete its progress file on completion).

**Why:** Pass-35's internal 9-deck two-stage tournament (216 games) finished in 2
calls this way vs ~18 with per-game subprocess isolation; warm-engine batch games
ran ~0.5s each.

## Reaping the warm worker: never `subprocess.run(capture_output=True)` for it

The orchestrator that spawns the warm batch worker must NOT reap it with
`subprocess.run(..., capture_output=True, timeout=...)`. The native cg/open_spiel
engine can leave a grandchild holding the worker's stdout/stderr pipe, so
`communicate()` blocks on pipe-EOF FOREVER — past the timeout — and the
orchestrator never returns or writes its summary (it just gets killed at the 120s
tool cap, with the ledger silently advancing each run).

**Rule:** spawn the worker with `subprocess.Popen(..., stdout=DEVNULL,
stderr=DEVNULL, start_new_session=True)` (no pipe to drain), `proc.wait(timeout=...)`,
and on `TimeoutExpired` `os.killpg(os.getpgid(proc.pid), SIGKILL)` to take down the
whole process group (the grandchild too). Worker progress is already crash-safe via
the fsync'd JSONL, so a group-kill loses at most the in-flight game.

**Why:** Pass-46J's eval orchestrator (copied from 46I) hung twice at the 120s cap
with zero stdout even though the JSONL kept gaining ~30 results/run; the fix was
swapping `subprocess.run(capture_output=True)` for Popen+DEVNULL+killpg.
