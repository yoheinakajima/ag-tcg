#!/usr/bin/env python3
"""Build the ActiveGraph report: static HTML site + Markdown summary.

Reads only the lab's own artifacts (events, ranking, run dirs, queue) and writes
``data/site/*.html`` + ``style.css`` and ``data/reports/activegraph_strategy_report.md``.
Every section degrades to a clear empty state when its input is missing, so this
is safe to run before any candidates exist. Emits ``ReportSiteGenerated``.

Usage:
    python scripts/build_report_site.py
    python scripts/build_report_site.py --runs-root experiments/runs
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, RUNS_ROOT
from ptcg_activegraph.experiments.report import (
    gather,
    write_markdown,
    write_pass11b_report,
    write_site,
)
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    args = parser.parse_args()

    data = gather(runs_root=args.runs_root)
    site_files = write_site(data)
    md_file = write_markdown(data)
    pass11b_md = write_pass11b_report(data)

    store = EventStore(LAB_EVENTS_PATH)
    store.append(new_event(
        EventType.ReportSiteGenerated,
        payload={"site_files": [str(p) for p in site_files], "markdown": str(md_file),
                 "pass11b_report": str(pass11b_md),
                 "candidates": len(data["runs"]), "events": len(data["events"])},
        tags=["report"],
    ))

    print("Report generated:")
    for p in site_files:
        print(f"  {p}")
    print(f"  {md_file}")
    print(f"  {pass11b_md}")
    print(f"\nOpen data/site/index.html  ({len(data['runs'])} candidates, "
          f"{len(data['events'])} events).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
