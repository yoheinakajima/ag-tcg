---
name: Long cabt eval runs
description: How to run multi-game cabt/kaggle_environments evaluations (leagues, meta sanity) without hangs or lost processes.
---

Running many cabt (`kaggle_environments` "cabt") games for an evaluation has two
traps that each cost a full debug cycle:

1. **In-process game loops hang/OOM.** Playing ~100 games in one Python process
   leaks memory across games and eventually wedges; a `signal.SIGALRM` watchdog
   does NOT interrupt the engine's C code, so the whole run hangs indefinitely.
   Single games are fast (~0.1–0.9s); the problem is accumulation.

2. **`nohup` background processes do not survive between agent tool calls.** A
   `nohup ... &` launched in one bash call repeatedly died with an empty log and
   no sentinel — the platform does not keep these alive across turns.

**The pattern that works:**
- Run the long eval as a **managed Replit workflow** (`configureWorkflow`,
  `outputType: "console"`, `python3 -u ...`), poll a **sentinel file** the script
  writes on completion, then `removeWorkflow`. Workflows persist across turns.
- Inside the eval, play each matchup-seat **batch in a fresh subprocess worker**
  (one process plays N games then exits). This amortises the ~8s
  kaggle_environments/OpenSpiel import over N games, bounds memory (process exits
  before the runaway regime), and gives a real, enforceable `subprocess` timeout.
  The worker should flush partial results after each game so a parent-side
  timeout still recovers finished games.

**Agent inputs:** `kaggle_environments` accepts a `main.py` **path** as an agent
(an extracted candidate or a materialized surrogate). Passing a `.tar.gz` path
instead yields `status: ERROR` / `steps: 2` — extract first.

**Why:** discovered while building the Pass-18 internal league + meta sanity; the
batched-subprocess + workflow-sentinel combination is the only one that ran a
~100-game league (5/seat) to completion (~98s) reliably.
