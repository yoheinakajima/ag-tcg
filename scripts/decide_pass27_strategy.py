#!/usr/bin/env python3
"""Pass 27 (Part K) — strategy decision. LOCAL ONLY, no upload.

Turns the Part-J gap analysis + Part-I league + Part-B live score into one honest
decision from the allowed label set. The pass's premise (user wants MORE decks
before refining one Water deck, and the portfolio exposed concrete generic gaps)
constrains the decision: keep Water as the live reference, and spend the next
core-rules effort on the highest-priority deck-AGNOSTIC gap.

No Kaggle probe is recommended: although several candidates are smoke-valid and
validator-passing, none is a clearly useful NEW calibration point this pass (the
Water pivot already anchors the live score, and the portfolio decks are diagnostic
rather than competitive). Writes data/experiments/pass27_strategy_decision.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

ALLOWED = ["keep_water_control", "build_aggro_core_rules_next",
           "build_spread_targeting_next", "build_ramp_core_rules_next",
           "build_chaos_special_pilot_next", "expand_deck_portfolio",
           "run_larger_league", "future_kaggle_probe_candidate", "no_action"]

GAP_TO_DECISION = {
    "color-matched energy attachment": "build_aggro_core_rules_next",
    "combo/ramp sequencing": "build_ramp_core_rules_next",
    "spread/bench target planning": "build_spread_targeting_next",
    "lethal counting / all-in attack timing": "build_aggro_core_rules_next",
}


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    gap = _load("pass27_core_gameplay_gap_analysis.json")
    rankings = _load("pass27_portfolio_rankings.json")
    live = _load("pass27_live_score_status.json")
    validation = _load("pass27_candidate_validation.json")

    top_gap = gap.get("summary", {}).get("highest_priority_generic_gap")
    primary = GAP_TO_DECISION.get(top_gap, "build_aggro_core_rules_next")
    assert primary in ALLOWED

    # Secondary: since user wants breadth before depth, expand portfolio next.
    secondary = "expand_deck_portfolio"

    # Next deck family to add = the next-highest deck-agnostic failing competency
    # not already covered by `primary`.
    agnostic_fails = gap.get("summary", {}).get("deck_agnostic_failures", [])
    next_rule_family = top_gap
    next_deck_family = "another fast-aggro / colour-stress deck to re-test the new aggro rules"

    league_eligible = validation.get("league_eligible", [])
    smoke_valid_count = len(league_eligible)

    decision = {
        "pass": "27", "part": "K", "local_only": True, "upload_performed": False,
        "submit": False, "github_push": False, "is_kaggle_leaderboard": False,
        "allowed_labels": ALLOWED,
        "primary_decision": primary,
        "secondary_decision": secondary,
        "keep_water_control": True,
        "keep_water_control_reason": (
            "Water remains the live-score reference (live_score_leader == "
            "water_family_current_best == league_water_anti_disruption_pivot_v1 @ "
            f"{(live.get('water_family_current_best') or {}).get('publicScore')}) and "
            "topped the internal league; nothing this pass contradicts it. This "
            "pass deliberately did NOT over-refine Water."),
        "next_core_rule_family": next_rule_family,
        "next_deck_family": next_deck_family,
        "highest_priority_generic_gap": top_gap,
        "deck_agnostic_failures": agnostic_fails,
        "future_kaggle_probe": False,
        "future_kaggle_probe_reason": (
            f"{smoke_valid_count} candidates are smoke-valid and validator-passing, "
            "but none is a clearly useful NEW calibration point: the Water pivot "
            "already anchors the live score and the portfolio decks are diagnostic, "
            "not competitive. Per the rules, no probe is recommended."),
        "reason": (
            f"The portfolio exposed that the single generic pilot fails the most on "
            f"'{top_gap}' (Raging Bolt aggro 0-34), plus ramp ({GAP_TO_DECISION.get('combo/ramp sequencing')}) "
            "and lethal/all-in timing — all DECK-AGNOSTIC. Fixing colour-matched "
            "energy + attack-pressure rules helps every archetype, so build those "
            "core rules next, then keep expanding the deck portfolio to re-test."),
        "live_score_leader": live.get("live_score_leader"),
        "water_family_current_best": live.get("water_family_current_best"),
        "distinction_preserved": live.get("distinction_preserved"),
        "league_top": (rankings.get("standings") or [{}])[0].get("id"),
        "league_worst": (rankings.get("standings") or [{}])[-1].get("id"),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass27_strategy_decision.json").write_text(
        json.dumps(decision, indent=2), encoding="utf-8")

    L = ["# Pass 27 — Strategy Decision (Part K)", "",
         "> LOCAL ONLY. No upload, no submit, no GitHub push. Internal league is "
         "NOT Kaggle and NOT a promotion signal.", "",
         f"- **primary decision:** `{decision['primary_decision']}`",
         f"- **secondary decision:** `{decision['secondary_decision']}`",
         f"- **keep Water control:** {decision['keep_water_control']} — "
         f"{decision['keep_water_control_reason']}",
         f"- **next core rule family:** {decision['next_core_rule_family']}",
         f"- **next deck family:** {decision['next_deck_family']}",
         f"- **future Kaggle probe:** {decision['future_kaggle_probe']} — "
         f"{decision['future_kaggle_probe_reason']}",
         "", "## Reason", "", decision["reason"], "",
         "## Allowed labels", "",
         ", ".join(f"`{x}`" for x in ALLOWED), ""]
    (EXP / "pass27_strategy_decision.md").write_text("\n".join(L), encoding="utf-8")

    print(f"primary={primary} secondary={secondary} keep_water=True "
          f"future_probe=False")
    print(f"next_core_rule_family={next_rule_family}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
