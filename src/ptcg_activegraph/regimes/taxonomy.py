"""Regime taxonomy: categories, failure tags, patch seams, and their mapping."""

from __future__ import annotations

from enum import Enum


class RegimeCategory(str, Enum):
    STABILITY = "STABILITY"
    DECK_CONSTRUCTION = "DECK_CONSTRUCTION"
    SEQUENCING = "SEQUENCING"
    PRIZE_RACE = "PRIZE_RACE"
    BELIEF_HIDDEN_INFORMATION = "BELIEF_HIDDEN_INFORMATION"
    META_LEADERBOARD = "META_LEADERBOARD"
    UNKNOWN = "UNKNOWN"


class FailureTag(str, Enum):
    exception = "exception"
    timeout = "timeout"
    invalid_return = "invalid_return"
    empty_select = "empty_select"
    fallback_used = "fallback_used"
    lost_game = "lost_game"
    draw_game = "draw_game"
    missed_attack = "missed_attack"
    missed_knockout = "missed_knockout"
    bad_energy_attachment = "bad_energy_attachment"
    bad_evolution = "bad_evolution"
    bad_retreat = "bad_retreat"
    bad_bench = "bad_bench"
    deck_brick = "deck_brick"
    no_basic = "no_basic"
    low_damage = "low_damage"
    deck_out = "deck_out"
    opponent_threat_missed = "opponent_threat_missed"
    overfit_suspected = "overfit_suspected"
    unknown = "unknown"


class PatchSeam(str, Enum):
    deck_list = "deck_list"
    card_role_tags = "card_role_tags"
    heuristic_weights = "heuristic_weights"
    action_priority_rules = "action_priority_rules"
    belief_sampler_parameters = "belief_sampler_parameters"
    search_depth_budget = "search_depth_budget"
    state_evaluator_formula = "state_evaluator_formula"
    fallback_ordering = "fallback_ordering"


REGIME_CATEGORIES = [c.value for c in RegimeCategory]
FAILURE_TAGS = [t.value for t in FailureTag]
PATCH_SEAMS = [s.value for s in PatchSeam]


# Which failure tags map to which regime. Earlier categories win on ties.
TAG_TO_REGIME: dict[str, RegimeCategory] = {
    FailureTag.exception.value: RegimeCategory.STABILITY,
    FailureTag.timeout.value: RegimeCategory.STABILITY,
    FailureTag.invalid_return.value: RegimeCategory.STABILITY,
    FailureTag.empty_select.value: RegimeCategory.STABILITY,
    FailureTag.fallback_used.value: RegimeCategory.STABILITY,
    FailureTag.deck_brick.value: RegimeCategory.DECK_CONSTRUCTION,
    FailureTag.no_basic.value: RegimeCategory.DECK_CONSTRUCTION,
    FailureTag.deck_out.value: RegimeCategory.DECK_CONSTRUCTION,
    FailureTag.bad_energy_attachment.value: RegimeCategory.SEQUENCING,
    FailureTag.bad_evolution.value: RegimeCategory.SEQUENCING,
    FailureTag.bad_retreat.value: RegimeCategory.SEQUENCING,
    FailureTag.bad_bench.value: RegimeCategory.SEQUENCING,
    FailureTag.missed_attack.value: RegimeCategory.PRIZE_RACE,
    FailureTag.missed_knockout.value: RegimeCategory.PRIZE_RACE,
    FailureTag.low_damage.value: RegimeCategory.PRIZE_RACE,
    FailureTag.lost_game.value: RegimeCategory.PRIZE_RACE,
    FailureTag.opponent_threat_missed.value: RegimeCategory.BELIEF_HIDDEN_INFORMATION,
    FailureTag.overfit_suspected.value: RegimeCategory.META_LEADERBOARD,
    FailureTag.draw_game.value: RegimeCategory.PRIZE_RACE,
    FailureTag.unknown.value: RegimeCategory.UNKNOWN,
}


# Which patch seams a regime is allowed to touch.
ALLOWED_PATCH_SEAMS: dict[RegimeCategory, list[PatchSeam]] = {
    RegimeCategory.STABILITY: [
        PatchSeam.fallback_ordering,
        PatchSeam.action_priority_rules,
    ],
    RegimeCategory.DECK_CONSTRUCTION: [
        PatchSeam.deck_list,
        PatchSeam.card_role_tags,
    ],
    RegimeCategory.SEQUENCING: [
        PatchSeam.action_priority_rules,
        PatchSeam.heuristic_weights,
        PatchSeam.card_role_tags,
    ],
    RegimeCategory.PRIZE_RACE: [
        PatchSeam.heuristic_weights,
        PatchSeam.action_priority_rules,
        PatchSeam.state_evaluator_formula,
    ],
    RegimeCategory.BELIEF_HIDDEN_INFORMATION: [
        PatchSeam.belief_sampler_parameters,
        PatchSeam.search_depth_budget,
        PatchSeam.state_evaluator_formula,
    ],
    RegimeCategory.META_LEADERBOARD: [
        PatchSeam.deck_list,
        PatchSeam.heuristic_weights,
    ],
    RegimeCategory.UNKNOWN: [],
}


# Priority order for resolving a single regime from multiple tags. Stability and
# deck construction are the most foundational, so they win.
_REGIME_PRIORITY = [
    RegimeCategory.STABILITY,
    RegimeCategory.DECK_CONSTRUCTION,
    RegimeCategory.SEQUENCING,
    RegimeCategory.PRIZE_RACE,
    RegimeCategory.BELIEF_HIDDEN_INFORMATION,
    RegimeCategory.META_LEADERBOARD,
    RegimeCategory.UNKNOWN,
]


def regime_for_tags(tags: list[str]) -> RegimeCategory:
    """Resolve the single governing regime for a set of failure tags."""
    found = set()
    for tag in tags or []:
        regime = TAG_TO_REGIME.get(tag)
        if regime is not None:
            found.add(regime)
    if not found:
        return RegimeCategory.UNKNOWN
    for regime in _REGIME_PRIORITY:
        if regime in found:
            return regime
    return RegimeCategory.UNKNOWN
