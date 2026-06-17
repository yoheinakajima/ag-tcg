---
name: cabt local evaluation gotchas
description: How to correctly run kaggle_environments "cabt" games locally for PTCG agent eval
---

Running `kaggle_environments.make("cabt")` + `env.run([a, b])` locally for the
Pokémon TCG (PTCG) baseline has three non-obvious requirements. Get any wrong
and games silently end after ~2 steps as a draw (with `debug=False` the engine
swallows the agent error).

**Rule 1 — pass decks via configuration.** `make("cabt", configuration={"decks": [deck0, deck1]})`
with each deck a list of 60 int card ids in seat order. Without it the game can't
start. The smoke test tries `{"decks":[d,d]}`, then `{"deck":d}`, then `{}` (the
last relies on the agent returning its deck during the `select=None` phase).

**Rule 2 — the agent callable must accept extra positional args.** cabt calls the
agent as `agent(observation, configuration)` (2 args), but the baseline
`main.py` `agent(obs_dict)` takes one. A plain wrapper `__call__(self, obs)`
raises `TypeError: takes 2 positional arguments but 3 were given`, which is
swallowed when `debug=False`. Wrapper must be `__call__(self, *args, **kwargs)`
and forward only `args[0]` (the observation) to `module.agent`.

**Rule 3 — obs is a `kaggle_environments` `Struct`, not a plain dict**, but Struct
subclasses dict, so `.get(...)`/`.items()`/`isinstance(x, dict)` all work. The
real decision obs has `obs["select"]` as a Struct with `options` (list) and
`maxCount`; deck phase has `select=None`.

**Why:** debugging this cost several runs because `debug=False` turns the agent
TypeError into a 2-step draw with no traceback. Always reproduce a suspicious
"everyone draws / win_rate 0.0 / decisions 0" result with `debug=True` first.

**How to apply:** see `src/ptcg_activegraph/experiments/runner.py` (`_make_cabt`,
`_InstrumentedAgent`). Final-reward parse: walk `env.steps` in reverse, first
step where `step[seat]["reward"]` is not None; reward 1=win, -1=loss.
