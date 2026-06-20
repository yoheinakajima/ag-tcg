"""Event-first tournament ledger.

Thin wrapper over the proven graph ``EventStore`` (append-only JSONL). The
tournament's primary durable record is ``data/tournament/events.jsonl`` — game
events are emitted *live* during a tick, not retroactively. Projections fold
over this log.

Hard safety guard: this ledger refuses to emit upload/submit events. Every event
it writes carries ``no_upload=true`` in its payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..graph.events import Event, EventType
from ..graph.event_store import EventStore

REPO_ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT_DIR = REPO_ROOT / "data" / "tournament"
DEFAULT_EVENTS_PATH = TOURNAMENT_DIR / "events.jsonl"

# Events this engine must never emit (upload/submit/leaderboard side effects).
_FORBIDDEN = {
    EventType.SubmissionUploaded.value,
    EventType.KaggleScoreUpdated.value,
    "SubmissionUploaded",
    "KaggleScoreUpdated",
}

_BASE_TAGS = ("pass36", "tournament")


class TournamentLedger:
    """Append-only, event-first tournament ledger with a no-upload guard."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.store = EventStore(path or DEFAULT_EVENTS_PATH)

    # -- writing -----------------------------------------------------------
    def emit(
        self,
        event_type: "EventType | str",
        payload: dict | None = None,
        *,
        parent_event_ids: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
    ) -> Event:
        et = event_type.value if hasattr(event_type, "value") else str(event_type)
        if et in _FORBIDDEN:
            raise PermissionError(
                f"TournamentLedger refuses to emit upload/submit event {et!r}: "
                "the standing engine v0 performs NO upload and NO auto-submit."
            )
        body = dict(payload or {})
        body["no_upload"] = True
        all_tags = list(_BASE_TAGS) + [t for t in (tags or []) if t not in _BASE_TAGS]
        ev = Event(
            event_type=et,
            payload=body,
            parent_event_ids=list(parent_event_ids or []),
            tags=all_tags,
        )
        return self.store.append(ev)

    # -- reading -----------------------------------------------------------
    def load(self) -> list[Event]:
        return self.store.load()

    def by_type(self, event_type: "EventType | str") -> list[Event]:
        et = event_type.value if hasattr(event_type, "value") else str(event_type)
        return [e for e in self.load() if e.event_type == et]

    def finished_game_ids(self) -> set[str]:
        """Game ids already durably finished — used to resume without dup work."""
        out: set[str] = set()
        for e in self.by_type(EventType.GameFinished):
            gid = e.payload.get("game_id")
            if gid:
                out.add(str(gid))
        return out

    def count(self) -> int:
        return self.store.count()
