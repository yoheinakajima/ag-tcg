"""Tests for regime taxonomy and the failure classifier."""

from ptcg_activegraph.graph.events import EventType, new_event
from ptcg_activegraph.regimes.classifier import classify_events, classify_summary
from ptcg_activegraph.regimes.patch_plan import new_patch_plan
from ptcg_activegraph.regimes.taxonomy import RegimeCategory, regime_for_tags


def test_exception_maps_to_stability():
    assert regime_for_tags(["exception"]) == RegimeCategory.STABILITY


def test_fallback_used_maps_to_stability():
    assert regime_for_tags(["fallback_used"]) == RegimeCategory.STABILITY


def test_no_basic_and_deck_brick_map_to_deck_construction():
    assert regime_for_tags(["no_basic"]) == RegimeCategory.DECK_CONSTRUCTION
    assert regime_for_tags(["deck_brick"]) == RegimeCategory.DECK_CONSTRUCTION


def test_missed_knockout_maps_to_prize_race():
    assert regime_for_tags(["missed_knockout"]) == RegimeCategory.PRIZE_RACE


def test_priority_stability_wins_over_prize():
    assert regime_for_tags(["missed_knockout", "exception"]) == RegimeCategory.STABILITY


def test_classify_summary_fallback():
    summary = {"fallback_count": 3, "result": "loss", "turns": 5, "action_count": 10}
    c = classify_summary(summary)
    assert "fallback_used" in c.tags
    assert "lost_game" in c.tags
    # Stability wins (fallback) over prize-race (loss).
    assert c.regime == RegimeCategory.STABILITY.value
    assert c.evidence


def test_classify_events_exception_tag():
    events = [
        new_event(EventType.ObservationReceived, match_id="m1"),
        new_event(EventType.FailureTagged, match_id="m1", payload={"tags": ["exception"]}),
    ]
    c = classify_events(events)
    assert "exception" in c.tags
    assert c.regime == RegimeCategory.STABILITY.value


def test_classify_events_deck_no_basic():
    events = [
        new_event(EventType.DeckLoaded, match_id="m1",
                  payload={"basic_count": 0, "valid": True}),
    ]
    c = classify_events(events)
    assert "no_basic" in c.tags
    assert c.regime == RegimeCategory.DECK_CONSTRUCTION.value


def test_patch_plan_seams_match_regime():
    plan = new_patch_plan(RegimeCategory.PRIZE_RACE, ["missed_knockout"],
                          hypothesis="bump knockout weight")
    assert plan.target_regime == RegimeCategory.PRIZE_RACE.value
    assert "heuristic_weights" in plan.allowed_patch_seams
    assert plan.allows("heuristic_weights")
    assert not plan.allows("deck_list")
    assert plan.validation_protocol["games"] >= 1
    assert plan.status == "proposed"
