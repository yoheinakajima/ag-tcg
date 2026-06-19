---
name: Background jobs do not survive across tool calls
description: Why long cabt batches must run in-process within one tool call, not backgrounded
---

# Background processes die when their launching tool call returns

`nohup ... &`, `setsid ... < /dev/null &`, and `disown` all FAIL to keep a job
alive across separate bash tool calls in this Replit Agent environment. A
detached marker job that should have written 20 ticks wrote only 1 — it was
killed the moment the launching call returned. Polling the output file in a later
call finds the process gone (`kill -0 <pid>` fails) and no result written.

**Why:** the bash tool appears to terminate its whole process group/session on
return. Detachment flags do not escape it.

**How to apply:** any cabt evaluation (smoke, internal league) MUST complete
inside ONE tool call (~120s cap). Do NOT background it and poll later — that
silently loses the run.

# Make long cabt runs fit in one call: run IN-PROCESS, not subprocess-per-batch

`kaggle_environments` import costs ~13s; a single cabt self-game is ~1.3s. The
subprocess-per-seat-batch worker re-pays the ~13s import every batch, so a
7-candidate smoke (≈26 batches) blows past 120s. Running games IN-PROCESS
(import `make("cabt")` once, loop games with a SIGALRM per-game watchdog) pays
the import ONCE: ~26 games ≈ 13s + 26×1.3s ≈ 50s, fits one call.

**Caveat:** a very long-lived in-process loop (hundreds of games) can grow memory
and risk OOM, so keep total games modest (≲100) and honor a global time budget;
for larger leagues reduce participants/games-per-seat rather than backgrounding.
