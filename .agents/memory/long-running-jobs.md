---
name: Long-running jobs in this Repl
description: How to run >120s jobs when bash/background processes get orphan-killed
---
# Long-running jobs (>120s)

Background processes do NOT survive across agent tool calls here — both `bash &`
and `setsid` get orphan-killed once the spawning tool call returns. The bash tool
also caps at 120s.

**Why:** the sandbox reaps process trees tied to each tool invocation.

**How to apply:** for a long task (e.g. a multi-minute eval driver), register a
TEMPORARY console workflow (via the workflows skill / configureWorkflow), have the
script write a sentinel file on completion (`touch /tmp/<job>.done`) and log to a
file, poll the sentinel + output mtimes from short bash calls, then remove the
workflow when done. The persistent "Start application" workflow is the Kaggle agent
entrypoint (python3 main.py), NOT a server — leave it not-started.
