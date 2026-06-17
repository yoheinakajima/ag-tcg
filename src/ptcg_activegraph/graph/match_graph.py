"""MatchGraph: a single match reconstructed from its event stream.

Turns the linear event log for one ``match_id`` into a navigable per-turn
structure (observation -> legal frontier -> candidates -> chosen action ->
outcome). Used for replay, debugging and failure classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .events import Event, EventType


@dataclass
class MatchStep:
    turn: int | None = None
    player: int | None = None
    observation: dict | None = None
    legal_options: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    chosen: list | None = None
    fallback_used: bool = False
    events: list[Event] = field(default_factory=list)


@dataclass
class MatchGraph:
    match_id: str
    deck_version: str | None = None
    policy_version: str | None = None
    steps: list[MatchStep] = field(default_factory=list)
    result: str | None = None
    winner: int | None = None

    @classmethod
    def from_events(cls, match_id: str, events: Iterable[Event]) -> "MatchGraph":
        mg = cls(match_id=match_id)
        current = MatchStep()
        has_step = False
        for ev in events:
            if ev.match_id and ev.match_id != match_id:
                continue
            if ev.deck_version:
                mg.deck_version = ev.deck_version
            if ev.policy_version:
                mg.policy_version = ev.policy_version

            et = ev.event_type
            if et == EventType.ObservationReceived.value:
                if has_step:
                    mg.steps.append(current)
                current = MatchStep(turn=ev.turn, player=ev.player)
                current.observation = ev.payload.get("observation")
                current.events.append(ev)
                has_step = True
            elif et == EventType.LegalOptionsProjected.value:
                current.legal_options = ev.payload.get("options", [])
                current.events.append(ev)
            elif et == EventType.CandidateActionGenerated.value:
                current.candidates.append(ev.payload)
                current.events.append(ev)
            elif et == EventType.ActionChosen.value:
                current.chosen = ev.payload.get("selection")
                current.events.append(ev)
            elif et == EventType.ActionFallbackUsed.value:
                current.fallback_used = True
                current.events.append(ev)
            elif et == EventType.GameEnded.value:
                mg.result = ev.payload.get("result")
                mg.winner = ev.payload.get("winner")
                current.events.append(ev)
            else:
                current.events.append(ev)

        if has_step:
            mg.steps.append(current)
        return mg

    @property
    def num_steps(self) -> int:
        return len(self.steps)

    @property
    def fallback_steps(self) -> int:
        return sum(1 for s in self.steps if s.fallback_used)
