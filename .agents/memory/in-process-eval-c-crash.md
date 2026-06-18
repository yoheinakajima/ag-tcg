---
name: In-process cabt eval dies silently on C-level crash
description: Why the cabt experiment batch MUST use the per-game subprocess runner, never in-process
---

The cabt evaluation batch must run each game in its own killable subprocess. Do
NOT run it in-process for speed.

**Why:** A single cabt/OpenSpiel game can abort at the C level (SIGABRT/SIGSEGV)
or hang inside C-level `env.run`. In-process, that takes down the whole batch
*silently* — the process just disappears with NO Python traceback (the C abort
bypasses Python try/except entirely). A handful of games run fine in-process,
which is misleading; across a full sample (e.g. 140+ games) at least one trips
the C crash and the batch dies after only printing the "Evaluating..." banner.
This is the exact failure the subprocess-per-game runner was built to isolate:
the parent enforces a wall-clock timeout and kills the child's process group, so
one bad game cannot kill the batch.

**How to apply:** Keep `--subprocess` as the only path in the Pass-6 orchestrator
(`scripts/run_pass6_pipeline.py`). The cost is real: `import kaggle_environments`
unconditionally loads 31 OpenSpiel envs (~15s cold start) on every spawn, so a
full scout+focused run is ~1 hour. There is no supported env var to skip the
OpenSpiel load (it's an unconditional loop in `kaggle_environments/__init__.py`),
and patching that third-party site-package is out of scope and non-durable.
Accept the runtime; correctness/crash-isolation beats speed here.

**Debugging tells:** batch log ends right after the per-stage "Evaluating N
candidate(s)" banner with no traceback and no ranking JSON; `pgrep` shows the
python process gone. That's a C crash, not OOM (check `free -m`) and not OOM-kill.

**Polling gotcha:** never launch a second cabt process (even a quick timing
probe) while the batch runs — two concurrent OpenSpiel loads add memory/CPU
pressure and slow/destabilize the batch. Poll only with cheap checks (ls, wc,
grep on the log, pgrep). Also `pgrep -f <script>` matches your own polling shell;
filter by reading `/proc/<pid>/comm` for `python` to avoid self-match (kill
self-match shows exit code 137).
