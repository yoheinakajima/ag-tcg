---
name: Sandbox kills background processes
description: Why long durable eval runs must run foreground in bounded chunks, not nohup/background.
---

Background processes (e.g. `nohup ... &`) are KILLED when the spawning tool call
returns in this environment. A long durable eval launched in the background will
be terminated mid-run, leaving games in a `stale`/partial state.

**Why:** the agent's bash sandbox does not keep a session alive across tool
calls; detached children get reaped when the call that started them ends.

**How to apply:** run long durable evals in the FOREGROUND, in bounded chunks
(e.g. `--max-games 20`, ~4.3s/game with the fast import stub). The durable
ActiveGraph ledger makes this safe and resumable — recover interrupted games
with `--mark-stale` then `--retry-stale`, and re-invoke until all planned games
are `completed`. Never assume a backgrounded run will finish.
