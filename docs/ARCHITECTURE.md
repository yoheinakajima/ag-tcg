# Architecture

This project is deliberately **two systems** with a one-way flow of improvements.

```
                 ┌────────────────────────────────────────────┐
                 │            ActiveGraph Lab (rich)            │
                 │                                              │
  matches ─────▶ │  event store ─▶ projections ─▶ regimes ─▶   │
                 │  classifier ─▶ patch plans ─▶ validation ─▶ │
                 │  promotion ─▶ report generator              │
                 └───────────────┬──────────────────────────────┘
                                 │  (compiles validated changes:
                                 │   deck list, heuristic weights,
                                 │   action priorities, role tags …)
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │        Kaggle Runtime Agent (compact)        │
                 │   main.py / agent.py  —  stdlib only         │
                 │   parse ▶ heuristic ▶ fallback ▶ validate    │
                 └────────────────────────────────────────────┘
```

## Why two systems?

The Kaggle runtime must be **compact, fast, legal, stable, deterministic, and
self-contained**. It runs inside a sandbox with tight time limits and unknown
dependencies. Anything rich — logging, search, learning, LLM analysis — is a
liability there.

The development system around it can be much richer. It records everything,
reasons about failures, and runs experiments. But it never ships. Instead it
*compiles* validated improvements into small, reviewable changes to the runtime:
a new deck list, tuned heuristic weights, a reordered action priority, a new role
tag. This keeps the thing that actually competes simple and trustworthy while the
thing that improves it can be as elaborate as needed.

## Data flow

1. **Runtime** receives an observation, parses it defensively, ranks legal
   options by heuristic, and returns a validated legal selection. (In the lab,
   the same decision can additionally emit events.)
2. **Lab** records the match as an append-only event stream
   (`data/matches/events.jsonl`).
3. **Projections** fold events into match/deck/policy/failure summaries.
4. **Classifier** tags failures and assigns a **regime**.
5. **Regime** constrains which **patch seams** a fix may touch, which
   **validation protocol** it must pass, and the **promotion rule**.
6. **Validation** runs the proposed change over self-play / baseline / matrix
   games; only passing changes are **promoted** into the runtime.
7. **Report generator** turns the accumulated evidence into a Strategy report.

## Why event sourcing?

* **Replay & fork** — any match can be reconstructed and re-run with a tweaked
  policy to test a hypothesis.
* **Provenance** — every decision carries its `policy_version`, `deck_version`,
  legal frontier, candidates, and the chosen action, so regressions are
  attributable.
* **Append-only** — no destructive updates; the log *is* the source of truth.
  Projections are disposable, recomputable views.

## Why Regimes?

Unconstrained "just make it better" leads to overfitting and instability. Regimes
impose discipline: a failure is classified, and that classification *limits* what
kind of change is allowed and how it must be proven before promotion. A stability
bug may only touch fallback ordering / action rules and must show zero crashes; a
prize-race weakness may touch heuristic weights and must show a win-rate
improvement. See [`REGIMES.md`](REGIMES.md).

## Why the runtime must stay simple

* Kaggle time limits punish heavy per-step computation.
* Unknown sandbox = minimize dependencies (stdlib only).
* Determinism makes failures reproducible and promotion decisions sound.
* A guaranteed-legal fallback means the agent can *never* crash the match, which
  is worth more on a leaderboard than a clever-but-fragile policy.

## Key invariants

* `main.py` exposes `agent(obs_dict) -> list[int]` and never raises outward.
* Every returned selection is unique, in-range, and respects
  `maxCount`/`minCount`.
* The lab is import-optional: tests and the runtime never require `cabt`.
