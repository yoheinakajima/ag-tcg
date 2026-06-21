---
name: kaggle_environments slices agent call args by co_argcount
description: env.run / Agent.act pass fewer args to agents whose callable advertises a small __code__.co_argcount — bare def f(*args) gets obs=None and silently no-ops.
---

# kaggle_environments dispatches agent args by the callable's co_argcount

`kaggle_environments` (and the cabt/cg duel harnesses built on it) inspects the
agent callable's `__code__.co_argcount` and passes only that many positional args.
A bare `def f(*args)` reports `co_argcount == 0`, so the framework calls it with
**zero** args — `obs` is never delivered, the agent sees `None`, and it silently
returns a degenerate/no-op action. This looks like "the agent does nothing / always
loses / is inert" with NO exception to point at.

**How to apply:** when wiring a custom agent into a kaggle_environments-based duel
(tracers, instrumented policies, cg-vs-cg children), pass an **INSTANCE with a
bound `__call__(self, obs, ...)`** (or a plain `def agent(obs, config)` with the
real positional params), NOT a bare `def f(*args)` wrapper. The bound method
advertises the correct `co_argcount` so `obs` arrives. This bit the Pass-41
non-inertness tracer; fixing it (a `_TracerAgent` instance) made decisions flow.

**Why:** the framework trusts the declared arity for forward/backward-compat arg
slicing; `*args` defeats that introspection rather than satisfying it.
