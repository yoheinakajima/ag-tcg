"""ActiveGraph lab core: event model, append-only store, and projections.

The event log is the source of truth for the development system. Matches,
observations, legal-option frontiers, chosen/candidate actions, beliefs, search
results, failures, patches, validations and promotions are all recorded as
typed events and replayed into projections. See ``docs/ACTIVEGRAPH.md``.
"""

from .events import Event, EventType, new_event
from .event_store import EventStore
from .projections import (
    DeckPerformanceProjection,
    FailureSummaryProjection,
    MatchSummaryProjection,
    PolicyPerformanceProjection,
)

__all__ = [
    "Event",
    "EventType",
    "new_event",
    "EventStore",
    "MatchSummaryProjection",
    "FailureSummaryProjection",
    "DeckPerformanceProjection",
    "PolicyPerformanceProjection",
]
