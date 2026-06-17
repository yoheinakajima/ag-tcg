"""Markdown fragments for the Strategy report.

Kept separate so the section structure can be edited without touching the
generation logic.
"""

from __future__ import annotations

REPORT_TITLE = "# PTCG ActiveGraph — Strategy Report (Draft)"

SECTIONS = [
    "Executive summary",
    "Agent architecture",
    "Deck concept",
    "ActiveGraph event-sourced development loop",
    "Regimes taxonomy",
    "Stability methodology",
    "Heuristic policy",
    "Belief/search roadmap",
    "Local evaluation results",
    "Failure analysis",
    "Promoted/rejected changes",
    "Known limitations",
    "Next experiments",
]


def h2(title: str) -> str:
    return f"\n## {title}\n"


def todo(note: str) -> str:
    return f"> **TODO:** {note}\n"


def kv_table(rows: list[tuple[str, object]]) -> str:
    out = ["| Metric | Value |", "| --- | --- |"]
    for k, v in rows:
        out.append(f"| {k} | {v} |")
    return "\n".join(out) + "\n"
