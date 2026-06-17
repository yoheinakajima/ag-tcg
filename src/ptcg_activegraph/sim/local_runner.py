"""LocalRunner: run matches and emit ActiveGraph events.

Wraps :class:`CabtAdapter` to execute matches while recording the event stream
(MatchStarted, DeckLoaded, GameEnded, ...) into an :class:`EventStore`. Degrades
to a clear message when cabt is unavailable.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event
from .cabt_adapter import CabtAdapter, CabtUnavailableError


class LocalRunner:
    def __init__(
        self,
        event_store: EventStore | None = None,
        policy_version: str = "heuristic_v1",
        deck_version: str = "deck_v0",
    ) -> None:
        self.adapter = CabtAdapter()
        self.store = event_store or EventStore()
        self.policy_version = policy_version
        self.deck_version = deck_version

    def available(self) -> bool:
        return self.adapter.available()

    def run_match(
        self,
        agent0: Callable[[dict], list[int]],
        agent1: Callable[[dict], list[int]],
        deck0: list[int],
        deck1: list[int],
        match_id: str | None = None,
        render_html_path: str | None = None,
    ) -> dict:
        """Run one match and emit events. Returns the match result dict."""
        match_id = match_id or f"m_{uuid.uuid4().hex[:10]}"
        events = [
            new_event(
                EventType.MatchStarted,
                match_id=match_id,
                policy_version=self.policy_version,
                deck_version=self.deck_version,
                payload={"agents": ["agent0", "agent1"]},
            ),
            new_event(
                EventType.DeckLoaded,
                match_id=match_id,
                deck_version=self.deck_version,
                payload={"deck0_size": len(deck0), "deck1_size": len(deck1)},
            ),
        ]

        result: dict
        try:
            result = self.adapter.run_game(
                agent0, agent1, deck0, deck1, render_html_path=render_html_path
            )
        except CabtUnavailableError as exc:
            events.append(
                new_event(
                    EventType.FailureTagged,
                    match_id=match_id,
                    payload={"tags": ["unknown"], "reason": str(exc)},
                    tags=["cabt_unavailable"],
                )
            )
            self.store.append_many(events)
            raise

        events.append(
            new_event(
                EventType.GameEnded,
                match_id=match_id,
                policy_version=self.policy_version,
                deck_version=self.deck_version,
                payload={
                    "winner": result.get("winner"),
                    "result": result.get("result"),
                    "turns": result.get("turns", 0),
                },
            )
        )
        self.store.append_many(events)
        result["match_id"] = match_id
        return result

    def run_self_play(
        self,
        agent: Callable[[dict], list[int]],
        deck: list[int],
        n_games: int = 10,
    ) -> list[dict]:
        return [
            self.run_match(agent, agent, deck, deck)
            for _ in range(max(0, int(n_games)))
        ]
