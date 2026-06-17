"""Append-only JSONL event store.

One JSON object per line under ``data/matches/events.jsonl`` by default. The
store is deliberately simple: no database, no schema migration, just durable
facts that projections fold over.

Concurrency note: appends use a best-effort ``fcntl`` advisory lock on POSIX
when available. On platforms without ``fcntl`` (e.g. Windows) concurrent writes
from multiple processes are **not** yet safe — see ``docs/ACTIVEGRAPH.md``.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .events import Event

try:  # POSIX advisory locking; absent on Windows.
    import fcntl  # type: ignore

    _HAVE_FCNTL = True
except Exception:  # pragma: no cover - platform dependent
    _HAVE_FCNTL = False


DEFAULT_PATH = Path("data/matches/events.jsonl")


class EventStore:
    """A JSONL-backed append-only event store."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- writing -----------------------------------------------------------
    @contextmanager
    def _open_append(self) -> Iterator:
        f = open(self.path, "a", encoding="utf-8")
        try:
            if _HAVE_FCNTL:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass
            yield f
        finally:
            if _HAVE_FCNTL:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            f.close()

    def append(self, event: Event) -> Event:
        """Append a single event and return it."""
        with self._open_append() as f:
            f.write(event.to_json() + "\n")
        return event

    def append_many(self, events: Iterable[Event]) -> int:
        """Append many events in one locked open. Returns the count written."""
        count = 0
        with self._open_append() as f:
            for event in events:
                f.write(event.to_json() + "\n")
                count += 1
        return count

    # -- reading -----------------------------------------------------------
    def _iter_raw(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Skip corrupt lines rather than crash the whole load.
                    continue

    def load(self, match_id: str | None = None) -> list[Event]:
        """Load all events, optionally filtered by ``match_id``."""
        out: list[Event] = []
        for d in self._iter_raw():
            if match_id is not None and d.get("match_id") != match_id:
                continue
            out.append(Event.from_dict(d))
        return out

    def query(
        self,
        event_type: str | None = None,
        tags: Iterable[str] | None = None,
        match_id: str | None = None,
    ) -> list[Event]:
        """Filter events by type, tags (all-of), and/or match id."""
        tagset = set(tags) if tags else None
        et = event_type.value if hasattr(event_type, "value") else event_type
        out: list[Event] = []
        for ev in self.load(match_id=match_id):
            if et is not None and ev.event_type != et:
                continue
            if tagset is not None and not tagset.issubset(set(ev.tags)):
                continue
            out.append(ev)
        return out

    def latest(self, event_type: str | None = None) -> Event | None:
        """Return the most recent event (optionally of a given type)."""
        et = event_type.value if hasattr(event_type, "value") else event_type
        result: Event | None = None
        for ev in self.load():
            if et is not None and ev.event_type != et:
                continue
            result = ev
        return result

    def count(self) -> int:
        return sum(1 for _ in self._iter_raw())
