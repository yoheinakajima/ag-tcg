---
name: cabt eval harness quirks
description: Non-obvious runtime traps when running cabt PTCG self-play games locally for candidate evaluation.
---

# cabt evaluation harness quirks

## Non-terminating games defeat the in-process watchdog
Some cabt games (observed with the `secret_box_v2` policy candidate during a 40-game
focused stage) never terminate. The harness arms a `signal.alarm` (SIGALRM, ~20s)
before `env.run`, but the alarm does NOT interrupt these hangs.

**Why:** the game loop blocks in C-level extension code; Python only runs the SIGALRM
handler between bytecode instructions, so while stuck in C the handler never fires.
A single hung game can consume the entire wall-clock budget with 0 recorded timeouts.

**How to apply:** treat a candidate that stalls a batch as an honest *incomplete*
result — exclude it from the stage ranking (it never reaches `games_completed >= min`),
record the limitation rather than fabricating a number. Do not assume the watchdog
guarantees forward progress. A true fix would need per-game subprocess isolation with
an OS-level kill, not an in-process alarm.

## Background processes do not survive
`nohup`/`setsid` background runs get killed when a tool call returns, and the
workspace periodically resets `/tmp` and stray log files. Concurrent python
interpreters starve CPU and slow every game.

**How to apply:** run scout/focused batches in the FOREGROUND, one batch per tool
call. It is fast enough — a full 10-candidate scout (~10 games each) ran in ~62s;
a single candidate ~15s; cabt import alone ~14s; per-game ~0.6s once imported.
Always run scripts from the repo root.
