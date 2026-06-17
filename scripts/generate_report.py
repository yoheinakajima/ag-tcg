#!/usr/bin/env python3
"""Generate the Strategy report draft from the event log.

If no events exist, writes a scaffold with TODOs.

Usage:
    python scripts/generate_report.py [--events PATH] [--out PATH]
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.reporting.report_generator import (
    DEFAULT_REPORT_PATH,
    generate_strategy_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=str, default="data/matches/events.jsonl")
    parser.add_argument("--out", type=str, default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    store = EventStore(args.events)
    events = store.load()
    path = generate_strategy_report(events, out_path=args.out)
    print(f"Wrote strategy report to {path} ({len(events)} events considered).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
