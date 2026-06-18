---
name: Kaggle/cabt compiled-agent entrypoint is the LAST callable
description: Why appending code after the agent function silently breaks a compiled kaggle_environments submission
---

# cabt/kaggle picks the LAST top-level callable as the agent

`kaggle_environments.agent.get_last_callable` resolves a file-based agent as
`[v for v in module_globals.values() if callable(v)][-1]` — the **last callable
in module insertion order**, NOT a function literally named `agent`.

**Why this bit us:** the pilot compiler embeds a decision layer and wrapper
functions by appending them AFTER the base submission's deck-safety `agent`
entrypoint. That made a helper (`_cp_embedded`) the last callable, so cabt
invoked it directly and bypassed deck-selection handling — the agent returned
`[]` on the deck step and the whole game came back `status=INVALID` on move 1.
It passed every offline check (tarball validator calls `agent`/deck fn by name;
the reduced-model gate calls `core_pilot_decide` directly) yet was 100% broken in
real games. **Only a live `kaggle_environments.make("cabt").run([...])` catches
this** — always smoke-run one real game after compiling.

**How to apply:**
- Any code generator/compiler that appends to an existing kaggle submission MUST
  ensure the intended entrypoint is the last top-level callable defined.
- The final entrypoint must use a FRESH name. Re-binding an existing global
  (`agent = ...` or re-`def agent`) does NOT move its key to the end of the
  module dict, so it will not become last. Define e.g. `def core_pilot_agent(obs)`
  last and have it delegate to the real deck-safe agent.
- Detect regressions by loading the built `main.py` and asserting
  `[k for k,v in vars(m).items() if callable(v)][-1]` is the expected entrypoint.
