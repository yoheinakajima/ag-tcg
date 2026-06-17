"""Validation protocols and promotion rules.

A patch may only be promoted into the runtime after passing the validation
protocol attached to its regime. Protocols and rules are *data*, evaluated by
the lab; nothing here mutates code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .taxonomy import RegimeCategory


@dataclass
class ValidationProtocol:
    name: str
    games: int
    opponent: str = "baseline"  # "self", "baseline", "matrix"
    require_no_crash: bool = True
    max_fallback_rate: float | None = None
    min_winrate_improvement: float | None = None
    max_failure_tag_rate: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "games": self.games,
            "opponent": self.opponent,
            "require_no_crash": self.require_no_crash,
            "max_fallback_rate": self.max_fallback_rate,
            "min_winrate_improvement": self.min_winrate_improvement,
            "max_failure_tag_rate": self.max_failure_tag_rate,
            "description": self.description,
        }


@dataclass
class PromotionRule:
    name: str
    description: str
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "requires": self.requires}


# Reusable protocols keyed by regime.
STANDARD_PROTOCOLS: dict[str, ValidationProtocol] = {
    RegimeCategory.STABILITY.value: ValidationProtocol(
        name="stability_smoke",
        games=100,
        opponent="self",
        require_no_crash=True,
        max_fallback_rate=0.50,
        description="100 self-play games; zero runtime crashes; fallback rate must not increase.",
    ),
    RegimeCategory.DECK_CONSTRUCTION.value: ValidationProtocol(
        name="deck_matrix",
        games=200,
        opponent="matrix",
        require_no_crash=True,
        min_winrate_improvement=0.02,
        description="Held-out deck matrix; +2% win rate vs current deck, no new bricks.",
    ),
    RegimeCategory.SEQUENCING.value: ValidationProtocol(
        name="sequencing_baseline",
        games=300,
        opponent="baseline",
        require_no_crash=True,
        min_winrate_improvement=0.03,
        description="300 games vs baseline; +3% win rate; sequencing failure tags reduced.",
    ),
    RegimeCategory.PRIZE_RACE.value: ValidationProtocol(
        name="prize_race_baseline",
        games=500,
        opponent="baseline",
        require_no_crash=True,
        min_winrate_improvement=0.03,
        max_failure_tag_rate=0.10,
        description="500 games vs baseline; +3% win rate; missed_knockout/low_damage rate < 10%.",
    ),
    RegimeCategory.BELIEF_HIDDEN_INFORMATION.value: ValidationProtocol(
        name="belief_search",
        games=500,
        opponent="baseline",
        require_no_crash=True,
        min_winrate_improvement=0.02,
        description="500 games with belief-sampled search; +2% win rate; within time budget.",
    ),
    RegimeCategory.META_LEADERBOARD.value: ValidationProtocol(
        name="meta_holdout",
        games=500,
        opponent="matrix",
        require_no_crash=True,
        min_winrate_improvement=0.02,
        description="Held-out opponent set; guard against overfitting to a single meta.",
    ),
    RegimeCategory.UNKNOWN.value: ValidationProtocol(
        name="triage",
        games=50,
        opponent="self",
        require_no_crash=True,
        description="Triage run to gather more evidence before classifying.",
    ),
}


STANDARD_PROMOTION_RULES: dict[str, PromotionRule] = {
    RegimeCategory.STABILITY.value: PromotionRule(
        name="stability_gate",
        description="Promote only if zero crashes and fallback rate did not increase.",
        requires=["require_no_crash", "max_fallback_rate"],
    ),
    RegimeCategory.PRIZE_RACE.value: PromotionRule(
        name="winrate_gate",
        description="Promote only if win-rate improvement clears threshold with no regressions.",
        requires=["min_winrate_improvement", "require_no_crash"],
    ),
}


def protocol_for_regime(regime: str) -> ValidationProtocol:
    return STANDARD_PROTOCOLS.get(regime, STANDARD_PROTOCOLS[RegimeCategory.UNKNOWN.value])


def evaluate_validation(protocol: ValidationProtocol, results: dict) -> dict:
    """Compare measured ``results`` against a protocol; return pass/fail report.

    ``results`` may contain: ``crashes``, ``fallback_rate``, ``winrate``,
    ``baseline_winrate``, ``failure_tag_rate``.
    """
    reasons: list[str] = []
    passed = True

    if protocol.require_no_crash and results.get("crashes", 0) > 0:
        passed = False
        reasons.append(f"crashes={results.get('crashes')} (require 0)")

    if protocol.max_fallback_rate is not None:
        fr = results.get("fallback_rate")
        if fr is not None and fr > protocol.max_fallback_rate:
            passed = False
            reasons.append(f"fallback_rate {fr} > {protocol.max_fallback_rate}")

    if protocol.min_winrate_improvement is not None:
        wr = results.get("winrate")
        base = results.get("baseline_winrate")
        if wr is not None and base is not None:
            improvement = wr - base
            if improvement < protocol.min_winrate_improvement:
                passed = False
                reasons.append(
                    f"winrate improvement {improvement:.3f} < {protocol.min_winrate_improvement}"
                )

    if protocol.max_failure_tag_rate is not None:
        ftr = results.get("failure_tag_rate")
        if ftr is not None and ftr > protocol.max_failure_tag_rate:
            passed = False
            reasons.append(f"failure_tag_rate {ftr} > {protocol.max_failure_tag_rate}")

    return {"passed": passed, "protocol": protocol.name, "reasons": reasons}
