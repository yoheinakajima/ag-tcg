#!/usr/bin/env python3
"""Record the real cabt observation/option schema via self-play.

Runs a few games with the safe agent (wrapped to capture every observation),
then writes data/matches/schema_examples.json, data/matches/option_examples.jsonl
and docs/CABT_SCHEMA_NOTES.md. Degrades clearly if cabt is unavailable (still
writes empty summaries so the docs file exists).

Usage:
    python scripts/record_schema.py --games 3 [--deck deck.csv]
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from main import agent as runtime_agent
from ptcg_activegraph.decks.deck_io import load_deck
from ptcg_activegraph.sim.kaggle_smoke import kaggle_environments_available
from ptcg_activegraph.sim.schema_recorder import (
    recording_agent,
    summarize_observations,
    write_schema_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--deck", default="deck.csv")
    args = parser.parse_args()

    deck = load_deck(args.deck)
    observations: list = []
    wrapped = recording_agent(runtime_agent, observations)

    if not kaggle_environments_available():
        print("FAIL: kaggle_environments unavailable — recording empty schema.")
        print("Install with: pip install kaggle-environments (see docs/REPLIT_FIRST_RUN.md)")
        summary = summarize_observations(observations)
        paths = write_schema_outputs(summary)
        print(f"Wrote scaffolds: {paths}")
        return 1

    try:
        from kaggle_environments import make  # type: ignore
        env = None
        for cfg in ({"decks": [deck, deck]}, {"deck": deck}, {}):
            try:
                env = make("cabt", configuration=cfg)
                break
            except Exception:
                continue
        if env is None:
            raise RuntimeError("make('cabt', ...) failed for all configurations")
        for _ in range(max(1, args.games)):
            env.run([wrapped, wrapped])
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: runtime/env error: {exc!r}")
        summary = summarize_observations(observations)
        write_schema_outputs(summary)
        return 1

    summary = summarize_observations(observations)
    paths = write_schema_outputs(summary)
    print(f"PASS: recorded {summary['observation_count']} observations.")
    print(f"Wrote: {paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
