#!/usr/bin/env python3
"""Pass 28 (Part K) — strategy decision, evidence-gated. LOCAL/READ-ONLY.

Chooses ONE decision label, gated strictly by trace evidence. color-energy and
attack-pressure rules are forbidden (refuted by trace). Because the highest-value
generic suspicions (target/spread/search/supporter selection) are UNOBSERVABLE in
the current option schema, the evidence-gated choice is gather_more_traces.
Writes data/experiments/pass28_strategy_decision.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PRIO = EXP / "pass28_core_gap_priority.json"
OUT_JSON = EXP / "pass28_strategy_decision.json"
OUT_MD = EXP / "pass28_strategy_decision.md"


def main() -> int:
    prio = json.loads(PRIO.read_text(encoding="utf-8"))

    decision = "gather_more_traces"
    out = {
        "pass": "28", "part": "K",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "decision": decision,
        "specific_mechanic_focus": ("action-trace OBSERVABILITY for attack-target / "
                                    "spread-target / search-target / supporter-card "
                                    "selection (resolve play_from_hand + attack "
                                    "sub-target identity)"),
        "evidence_gated": True,
        "forbidden_choices_and_why": {
            "build_color_energy_rules_next": ("FORBIDDEN — trace shows 0 off-deck-plan "
                                              "attaches; color matching is refuted"),
            "build_attack_pressure_rules_next": ("FORBIDDEN — trace shows 0 "
                                                 "attack-available-not-taken; attack "
                                                 "pressure is refuted"),
            "build_aggro_core_rules_next": "FORBIDDEN — vague bucket, not a mechanic",
        },
        "why_this_decision": (
            "No deck-AGNOSTIC high-confidence core-rule gap is proven by the trace. The "
            "two Pass-27 hypotheses (color match, attack pressure) are REFUTED. The "
            "remaining proven gaps are DECK-SPECIFIC (venusaur effect loop, durant "
            "init/mill), and the most valuable generic suspicions "
            "(target/spread/search/supporter selection) are currently UNOBSERVABLE "
            "because the pilot's option schema does not resolve play_from_hand identity "
            "or attack sub-targets. Per the Pass-28 rule, when no high-confidence "
            "generic gap exists, choose gather_more_traces — specifically, extend trace "
            "observability so those mechanics can be measured before any core rule is "
            "built."),
        "secondary_recommendation": (
            "in parallel, prototype the single highest-evidence proven gap "
            "(effect_loop_termination, from venusaur) as a generic termination policy; "
            "validate on league_mega_venusaur_tank. No upload."),
        "keep_water_reference": True,
        "keep_water_reference_reason": (
            "league_water_core_reference remains the internal-league benchmark "
            "(top adj win rate) and the portfolio yardstick; it is NOT a Kaggle signal."),
        "top_gap": prio["top_gap"],
        "rejected_gaps": prio["rejected_gaps"],
        "validation_deck": "league_mega_venusaur_tank",
        "no_candidate_built": True,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 28 — Strategy Decision (Part K, evidence-gated)", "",
         f"## decision: `{decision}`", "",
         f"- **specific mechanic focus:** {out['specific_mechanic_focus']}",
         f"- **why:** {out['why_this_decision']}", "",
         f"- **secondary:** {out['secondary_recommendation']}",
         f"- **keep Water reference:** {out['keep_water_reference']} — "
         f"{out['keep_water_reference_reason']}",
         f"- **validation deck:** {out['validation_deck']}",
         f"- **no candidate built:** {out['no_candidate_built']}", "",
         "## Forbidden choices (refuted by trace)", ""]
    for k, v in out["forbidden_choices_and_why"].items():
        L.append(f"- `{k}` — {v}")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"decision: {decision} validation_deck={out['validation_deck']} "
          f"-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
