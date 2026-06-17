"""Aggregate metrics computed from the event log via projections."""

from __future__ import annotations

from typing import Iterable

from ..graph.events import Event
from ..graph.projections import (
    DeckPerformanceProjection,
    FailureSummaryProjection,
    MatchSummaryProjection,
    PolicyPerformanceProjection,
)


def compute_metrics(events: Iterable[Event]) -> dict:
    """Compute the full metric bundle used by the report generator."""
    events = list(events)
    match_summary = MatchSummaryProjection.project(events)
    matches = match_summary["matches"].values()

    total = len(match_summary["matches"])
    wins = sum(1 for m in matches if m.get("result") == "win")
    losses = sum(1 for m in matches if m.get("result") == "loss")
    draws = sum(1 for m in matches if m.get("result") == "draw")
    fallbacks = sum(m.get("fallback_count", 0) for m in matches)
    actions = sum(m.get("action_count", 0) for m in matches)

    return {
        "total_matches": total,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": round(wins / total, 4) if total else None,
        "fallback_actions": fallbacks,
        "total_actions": actions,
        "fallback_rate": round(fallbacks / actions, 4) if actions else None,
        "failures": FailureSummaryProjection.project(events),
        "deck_performance": DeckPerformanceProjection.project(events),
        "policy_performance": PolicyPerformanceProjection.project(events),
    }
