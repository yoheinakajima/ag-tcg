# PTCG ActiveGraph — Pokémon TCG AI Battle Challenge

An **ActiveGraph-powered experiment factory** for the
[The Pokémon Company — PTCG AI Battle Challenge](https://www.kaggle.com/) Kaggle
simulation competition, plus a compact, safe, self-contained runtime agent ready
to package and submit.

> **The goal is not just a bot.** It is a system that can *generate, evaluate,
> debug, and document* progressively better Pokémon TCG agents — recording every
> match as an event log, classifying failures into regimes, and promoting only
> validated improvements into a deliberately simple Kaggle runtime.

## Two-system architecture

| System | Where | Job | Dependencies |
| --- | --- | --- | --- |
| **Runtime agent** | `main.py`, `agent.py` | Pick legal moves fast, deterministically, never crash | **stdlib only** |
| **ActiveGraph lab** | `src/ptcg_activegraph/` | Record, classify, validate, promote, report | optional (`cabt`, `kaggle-environments`) |

The lab compiles improvements *down into* the runtime. The runtime never makes
live LLM calls and never depends on the lab being installed. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Competition context

* **Submit** a `.tar.gz` containing `main.py` and `deck.csv`.
* Each step the engine calls `agent(obs_dict)` with `logs`, `current`, `select`.
* The agent returns a list of **legal option indices**. The engine only ever
  presents legal moves.
* Simulator/API: `cabt`, built for `kaggle-environments`.

## Quickstart

```bash
# 1. (optional) create a venv, then install dev tooling
pip install pytest

# 2. run the tests (pure-python; no cabt required)
python -m pytest            # or: make test

# 3. see the runtime agent decide on a demo observation
python main.py              # or: make demo

# 4. resolve a REAL deck.csv from sample/provided/generated sources
python scripts/resolve_deck.py           # or: make resolve-deck

# 5. preflight + package a submission (blocks placeholder decks by default)
python scripts/package_submission.py --verify-only
python scripts/package_submission.py     # or: make submission
```

**First Kaggle/Replit run:** follow [`docs/REPLIT_FIRST_RUN.md`](docs/REPLIT_FIRST_RUN.md)
and the [`docs/FIRST_KAGGLE_SUBMISSION_CHECKLIST.md`](docs/FIRST_KAGGLE_SUBMISSION_CHECKLIST.md).
With `cabt` installed, `python scripts/kaggle_smoke_test.py` runs one full
self-play game (`make smoke`) and `python scripts/record_schema.py --games 3`
captures the real option schema (`make record-schema`).

> The shipped `deck.csv` is a **placeholder** and is intentionally rejected by
> the packager until you run `scripts/resolve_deck.py` (or pass
> `--allow-placeholder`, which will not score).

## Install

* **Runtime / tests:** Python 3.11+, standard library only. `pip install pytest`
  to run the suite.
* **Local simulation (optional):** `pip install kaggle-environments` and install
  `cabt` from the competition's provided package. Without these, the simulation
  scripts print install instructions and exit cleanly. See
  [`docs/LOCAL_SIMULATION.md`](docs/LOCAL_SIMULATION.md).

## Common commands

```bash
make test            # unit tests
make smoke           # main.py demo decision
make selfplay        # local self-play (needs cabt)
make tournament      # round-robin (needs cabt)
make inspect-cards   # show card DB + role tags
make report          # generate Strategy report draft
make verify-submission   # validate main.py + deck.csv
make submission      # build data/submissions/submission.tar.gz
```

Each `scripts/*.py` also supports `--help`.

## Repo map

```
main.py            Self-contained Kaggle entrypoint (stdlib only)
agent.py           Runtime agent wrapper (richer if package importable)
deck.csv           60-id placeholder decklist (replace with a real deck)
deck.csv.example   Documented decklist template
src/ptcg_activegraph/
  runtime/         Observation/action parsing, fallback + heuristic policy,
                   belief & search scaffolding, evaluator, time manager
  graph/           Event model, JSONL event store, projections, card/deck/match graphs
  regimes/         Failure taxonomy, classifier, patch plans, validation protocols
  cards/           Card DB, CSV loader, heuristic role tagging
  decks/           Deck IO, validator, features, baseline/placeholder decks
  sim/             cabt adapter, local runner, tournament, replay IO
  reporting/       Metrics + Strategy report generator
  packaging/       Submission tarball builder
scripts/           CLI entrypoints (self-play, tournament, inspect, report, package)
docs/              One markdown doc per subsystem
data/              cards/ decks/ matches/ reports/ submissions/ artifacts
tests/             Pure-python unit tests (no cabt required)
```

## Current status

| Capability | State |
| --- | --- |
| Safe runtime agent (`main.py`) | ✅ implemented, self-contained |
| Fallback + heuristic policy | ✅ implemented + tested |
| ActiveGraph event store + projections | ✅ implemented + tested |
| Regime taxonomy + classifier + patch plans | ✅ implemented + tested |
| Card/deck graph, role tags, deck validator | ✅ implemented + tested |
| Submission packager | ✅ implemented + tested |
| Strategy report generator | ✅ scaffold implemented |
| Belief state + world sampler | 🟡 scaffolded (data structures + extractor) |
| cabt search policy | 🟡 scaffolded, **off by default** |
| Local simulation / tournament | 🟡 guarded; needs `cabt` installed |
| Real card data + competitive deck | ⬜ requires official CSV / Kaggle deck |

## Limitations

* `cabt` / `kaggle-environments` are **not** assumed installed. Simulation paths
  are guarded skeletons until they are; the exact cabt observation/return schema
  is validated once the package is available.
* `deck.csv` ships as a **structural placeholder** (15 ids × 4 copies). Replace
  it with real card IDs from the official database before competing — see
  [`docs/KAGGLE_SUBMISSION.md`](docs/KAGGLE_SUBMISSION.md).
* The belief sampler and search policy are scaffolded, not yet wired into live
  decisions.

See [`docs/NEXT_STEPS.md`](docs/NEXT_STEPS.md) for the prioritized roadmap.

## License

MIT (see `LICENSE`).
