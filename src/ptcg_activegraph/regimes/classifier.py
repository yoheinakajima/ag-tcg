"""Rule-based failure classifier.

Input is either a list of events or a match summary dict. Output is a
:class:`FailureClassification` with failure tags, the governing regime, and the
evidence strings that justified each tag. Deliberately simple and transparent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .taxonomy import FailureTag, RegimeCategory, regime_for_tags


@dataclass
class FailureClassification:
    tags: list[str] = field(default_factory=list)
    regime: str = RegimeCategory.UNKNOWN.value
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"tags": self.tags, "regime": self.regime, "evidence": self.evidence}


def _add(tags: list[str], evidence: list[str], tag: FailureTag, why: str) -> None:
    if tag.value not in tags:
        tags.append(tag.value)
    evidence.append(f"{tag.value}: {why}")


def classify_summary(summary: dict) -> FailureClassification:
    """Classify a match summary dict (as from MatchSummaryProjection)."""
    tags: list[str] = []
    evidence: list[str] = []

    if not isinstance(summary, dict):
        return FailureClassification(
            tags=[FailureTag.unknown.value],
            regime=RegimeCategory.UNKNOWN.value,
            evidence=["summary was not a dict"],
        )

    # Carry through any explicit tags already recorded.
    for tag in summary.get("failure_tags", []) or []:
        if tag not in tags:
            tags.append(tag)
            evidence.append(f"{tag}: recorded in summary")

    fallback_count = summary.get("fallback_count", 0) or 0
    if fallback_count > 0:
        _add(tags, evidence, FailureTag.fallback_used,
             f"{fallback_count} fallback selection(s)")

    result = summary.get("result")
    if result == "loss":
        _add(tags, evidence, FailureTag.lost_game, "match result was loss")
    elif result == "draw":
        _add(tags, evidence, FailureTag.draw_game, "match result was draw")

    action_count = summary.get("action_count", 0) or 0
    turns = summary.get("turns", 0) or 0
    if turns == 0 and action_count == 0 and result is None:
        _add(tags, evidence, FailureTag.unknown, "no turns/actions/result recorded")

    if not tags:
        tags.append(FailureTag.unknown.value)
        evidence.append("no failure signals detected")

    regime = regime_for_tags(tags).value
    return FailureClassification(tags=tags, regime=regime, evidence=evidence)


def classify_events(events: Iterable) -> FailureClassification:
    """Classify directly from a list of events.

    Looks for exceptions, empty selects, fallbacks, invalid returns, deck
    issues and outcome signals via event types/tags/payloads.
    """
    tags: list[str] = []
    evidence: list[str] = []

    events = list(events or [])
    for ev in events:
        et = getattr(ev, "event_type", None) or (
            ev.get("event_type") if isinstance(ev, dict) else None
        )
        payload = getattr(ev, "payload", None)
        if payload is None and isinstance(ev, dict):
            payload = ev.get("payload", {})
        payload = payload or {}
        ev_tags = getattr(ev, "tags", None)
        if ev_tags is None and isinstance(ev, dict):
            ev_tags = ev.get("tags", [])
        ev_tags = ev_tags or []

        # Direct failure events.
        if et == "FailureTagged":
            for tag in payload.get("tags", []):
                if tag not in tags:
                    tags.append(tag)
                    evidence.append(f"{tag}: FailureTagged event")

        if et == "ActionFallbackUsed":
            _add(tags, evidence, FailureTag.fallback_used, "ActionFallbackUsed event")

        # Tag-based evidence.
        for tag in ev_tags:
            if tag == "exception":
                _add(tags, evidence, FailureTag.exception, "event tagged exception")
            elif tag == "timeout":
                _add(tags, evidence, FailureTag.timeout, "event tagged timeout")
            elif tag == "invalid_return":
                _add(tags, evidence, FailureTag.invalid_return,
                     "event tagged invalid_return")
            elif tag == "no_basic":
                _add(tags, evidence, FailureTag.no_basic, "event tagged no_basic")
            elif tag == "deck_brick":
                _add(tags, evidence, FailureTag.deck_brick, "event tagged deck_brick")

        # Outcome.
        if et == "GameEnded":
            result = payload.get("result")
            if result == "loss":
                _add(tags, evidence, FailureTag.lost_game, "GameEnded result=loss")
            elif result == "draw":
                _add(tags, evidence, FailureTag.draw_game, "GameEnded result=draw")

        # Deck issues at load time.
        if et == "DeckLoaded":
            if payload.get("basic_count", 1) == 0:
                _add(tags, evidence, FailureTag.no_basic,
                     "deck loaded with zero Basic Pokémon")
            if payload.get("valid") is False:
                _add(tags, evidence, FailureTag.deck_brick,
                     "deck loaded but failed validation")

    if not tags:
        tags.append(FailureTag.unknown.value)
        evidence.append("no failure signals detected in events")

    regime = regime_for_tags(tags).value
    return FailureClassification(tags=tags, regime=regime, evidence=evidence)
