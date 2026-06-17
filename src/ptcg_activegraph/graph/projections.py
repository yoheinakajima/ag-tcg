"""Pure-function projections over event lists.

Projections fold an ordered list of :class:`Event` into a summary view. They are
deterministic and side-effect free so they can be replayed, forked and compared
freely. No database — just dict outputs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .events import Event, EventType


def _by_match(events: Iterable[Event]) -> dict[str, list[Event]]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for ev in events:
        grouped[ev.match_id or "_unknown"].append(ev)
    return grouped


class MatchSummaryProjection:
    """One row per match: winner, turns, fallback usage, failures."""

    @staticmethod
    def project(events: Iterable[Event]) -> dict:
        matches: dict[str, dict] = {}
        for match_id, evs in _by_match(events).items():
            summary = {
                "match_id": match_id,
                "turns": 0,
                "winner": None,
                "result": None,
                "deck_version": None,
                "policy_version": None,
                "fallback_count": 0,
                "action_count": 0,
                "failure_tags": [],
            }
            for ev in evs:
                if ev.deck_version:
                    summary["deck_version"] = ev.deck_version
                if ev.policy_version:
                    summary["policy_version"] = ev.policy_version
                if ev.event_type == EventType.TurnEnded.value:
                    summary["turns"] += 1
                elif ev.event_type == EventType.ActionApplied.value:
                    summary["action_count"] += 1
                elif ev.event_type == EventType.ActionChosen.value:
                    summary["action_count"] += 1
                elif ev.event_type == EventType.ActionFallbackUsed.value:
                    summary["fallback_count"] += 1
                elif ev.event_type == EventType.FailureTagged.value:
                    summary["failure_tags"].extend(ev.payload.get("tags", []))
                elif ev.event_type == EventType.GameEnded.value:
                    summary["winner"] = ev.payload.get("winner")
                    summary["result"] = ev.payload.get("result")
            matches[match_id] = summary
        return {"matches": matches, "count": len(matches)}


class FailureSummaryProjection:
    """Aggregate failure tags and regimes across all events."""

    @staticmethod
    def project(events: Iterable[Event]) -> dict:
        tag_counter: Counter = Counter()
        regime_counter: Counter = Counter()
        per_match: dict[str, list[str]] = defaultdict(list)
        for ev in events:
            if ev.event_type == EventType.FailureTagged.value:
                for tag in ev.payload.get("tags", []):
                    tag_counter[tag] += 1
                    per_match[ev.match_id or "_unknown"].append(tag)
            elif ev.event_type == EventType.RegimeSelected.value:
                regime = ev.payload.get("regime")
                if regime:
                    regime_counter[regime] += 1
        return {
            "tags": dict(tag_counter),
            "regimes": dict(regime_counter),
            "per_match": dict(per_match),
            "total_failures": sum(tag_counter.values()),
        }


class DeckPerformanceProjection:
    """Win/loss/draw per deck version."""

    @staticmethod
    def project(events: Iterable[Event]) -> dict:
        decks: dict[str, dict] = defaultdict(
            lambda: {"games": 0, "wins": 0, "losses": 0, "draws": 0}
        )
        for match_id, evs in _by_match(events).items():
            deck_version = None
            result = None
            for ev in evs:
                if ev.deck_version:
                    deck_version = ev.deck_version
                if ev.event_type == EventType.GameEnded.value:
                    result = ev.payload.get("result")
            key = deck_version or "_unknown"
            decks[key]["games"] += 1
            if result == "win":
                decks[key]["wins"] += 1
            elif result == "loss":
                decks[key]["losses"] += 1
            elif result == "draw":
                decks[key]["draws"] += 1
        out = {}
        for k, v in decks.items():
            games = v["games"] or 1
            v = dict(v)
            v["win_rate"] = round(v["wins"] / games, 4)
            out[k] = v
        return out


class PolicyPerformanceProjection:
    """Win rate and fallback rate per policy version."""

    @staticmethod
    def project(events: Iterable[Event]) -> dict:
        policies: dict[str, dict] = defaultdict(
            lambda: {"games": 0, "wins": 0, "fallbacks": 0, "actions": 0}
        )
        for match_id, evs in _by_match(events).items():
            policy_version = None
            result = None
            fallbacks = 0
            actions = 0
            for ev in evs:
                if ev.policy_version:
                    policy_version = ev.policy_version
                if ev.event_type == EventType.ActionFallbackUsed.value:
                    fallbacks += 1
                if ev.event_type in (
                    EventType.ActionChosen.value,
                    EventType.ActionApplied.value,
                ):
                    actions += 1
                if ev.event_type == EventType.GameEnded.value:
                    result = ev.payload.get("result")
            key = policy_version or "_unknown"
            policies[key]["games"] += 1
            policies[key]["fallbacks"] += fallbacks
            policies[key]["actions"] += actions
            if result == "win":
                policies[key]["wins"] += 1
        out = {}
        for k, v in policies.items():
            games = v["games"] or 1
            actions = v["actions"] or 1
            v = dict(v)
            v["win_rate"] = round(v["wins"] / games, 4)
            v["fallback_rate"] = round(v["fallbacks"] / actions, 4)
            out[k] = v
        return out
