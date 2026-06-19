#!/usr/bin/env python3
"""Pass 28 (Part J) — implementation roadmap. LOCAL/READ-ONLY.

Organizes the evidence-gated gaps into roadmap categories A/B/C with scope, risk,
tests and a validation deck per item. Writes docs/CORE_GAMEPLAY_BACKLOG.md and
data/experiments/pass28_implementation_roadmap.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PRIO = EXP / "pass28_core_gap_priority.json"
OUT_JSON = EXP / "pass28_implementation_roadmap.json"
OUT_MD = EXP / "pass28_implementation_roadmap.md"
DOC = REPO / "docs" / "CORE_GAMEPLAY_BACKLOG.md"


def main() -> int:
    prio = json.loads(PRIO.read_text(encoding="utf-8"))

    roadmap = {
        "A_immediate_core_rules_if_evidence_supports": [
            {"item": "color-matched energy attachment",
             "evidence": "REJECTED — 0 off-deck-plan attaches across all decks",
             "implementation_scope": "none (already correct)",
             "risk": "n/a", "tests_needed": "regression: assert on-plan attach holds",
             "candidate_deck": "league_raging_bolt_ogerpon (positive control)",
             "no_upload": True, "recommended": False},
            {"item": "attack pressure",
             "evidence": "REJECTED — 0 attack-available-not-taken across all decks",
             "implementation_scope": "none (already correct)",
             "risk": "n/a", "tests_needed": "regression: assert attack-when-able holds",
             "candidate_deck": "all league decks (positive control)",
             "no_upload": True, "recommended": False},
            {"item": "evolution sequencing",
             "evidence": ("MEDIUM — charizard first attack median step 6 / min 4 "
                          "(on tempo in most games, long tail of stalled Mega-line games)"),
             "implementation_scope": ("evolution-path planning + Rare Candy use; blocked "
                                      "on play_from_hand identity observability"),
             "risk": "medium", "tests_needed": "fx_evolution_sequencing_speed",
             "candidate_deck": "league_mega_charizard_x_burst",
             "no_upload": True, "recommended": False},
            {"item": "search target planning",
             "evidence": "UNKNOWN — search choices not surfaced in option schema",
             "implementation_scope": "needs observability first",
             "risk": "low", "tests_needed": "observability harness",
             "candidate_deck": "any",
             "no_upload": True, "recommended": False},
            {"item": "discard safety",
             "evidence": "UNKNOWN — discard choices not surfaced",
             "implementation_scope": "needs observability first",
             "risk": "low", "tests_needed": "observability harness",
             "candidate_deck": "any",
             "no_upload": True, "recommended": False},
        ],
        "B_requires_more_observability": [
            {"item": "spread targeting", "evidence": "dragapult targets not surfaced",
             "implementation_scope": "extend trace to capture attack sub-targets",
             "risk": "low", "tests_needed": "observability assertion",
             "candidate_deck": "league_dragapult_spread", "no_upload": True,
             "recommended": True},
            {"item": "retreat/switch", "evidence": "switch choice not surfaced",
             "implementation_scope": "capture in_play_action sub-type",
             "risk": "low", "tests_needed": "observability assertion",
             "candidate_deck": "any", "no_upload": True, "recommended": True},
            {"item": "prize race", "evidence": "prize_count present; no policy observed",
             "implementation_scope": "derive prize-race features",
             "risk": "low", "tests_needed": "observability assertion",
             "candidate_deck": "any", "no_upload": True, "recommended": True},
            {"item": "lethal counting", "evidence": "all-in timing not surfaced",
             "implementation_scope": "capture damage/HP state in trace",
             "risk": "medium", "tests_needed": "observability assertion",
             "candidate_deck": "league_raging_bolt_ogerpon", "no_upload": True,
             "recommended": True},
        ],
        "C_requires_deck_specific_or_special_pilot": [
            {"item": "Raging Bolt all-in energy-discard attack",
             "evidence": ("attacks fire every turn but energy-discard scaling not "
                          "surfaced; loss is structural, not pilot color/attack"),
             "implementation_scope": "deck-specific pilot IF a generic rule is infeasible",
             "risk": "medium", "tests_needed": "fx (blocked on observability)",
             "candidate_deck": "league_raging_bolt_ogerpon", "no_upload": True,
             "recommended": False},
            {"item": "Charizard all-in energy-discard attack",
             "evidence": ("high-variance setup (first attack median step 6 / min 4, "
                          "long tail of stalled games); combo engine not accelerated"),
             "implementation_scope": "deck-specific pilot",
             "risk": "medium", "tests_needed": "fx_evolution_sequencing_speed",
             "candidate_deck": "league_mega_charizard_x_burst", "no_upload": True,
             "recommended": False},
            {"item": "Gardevoir ramp", "evidence": "ramp ability under-used",
             "implementation_scope": "ramp-aware deck-specific pilot",
             "risk": "medium", "tests_needed": "fx_ramp_sequencing",
             "candidate_deck": "league_mega_gardevoir_psychic_ramp", "no_upload": True,
             "recommended": False},
            {"item": "Venusaur effect-loop termination",
             "evidence": "~1957-iteration forced-effect loop; near-zero attacks",
             "implementation_scope": ("generic effect-loop termination policy "
                                      "(highest-evidence proven gap)"),
             "risk": "medium", "tests_needed": "fx_effect_loop_termination",
             "candidate_deck": "league_mega_venusaur_tank", "no_upload": True,
             "recommended": True},
            {"item": "Durant deckout/chaos",
             "evidence": "INVALID at engine init; never reaches turn 1",
             "implementation_scope": "init-legality fix + special deckout pilot",
             "risk": "high", "tests_needed": "fx_mill_deckout_init_legality",
             "candidate_deck": "league_durant_deckout_carousel", "no_upload": True,
             "recommended": False},
        ],
    }

    out = {
        "pass": "28", "part": "J",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "top_gap": prio["top_gap"],
        "rejected_gaps": prio["rejected_gaps"],
        "headline": prio["headline"],
        "roadmap": roadmap,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    def section(title, items):
        rows = [f"### {title}", "",
                "| item | evidence | scope | risk | tests | validation deck | "
                "recommended |", "|---|---|---|---|---|---|---|"]
        for it in items:
            rows.append(f"| {it['item']} | {it['evidence']} | "
                        f"{it['implementation_scope']} | {it['risk']} | "
                        f"{it['tests_needed']} | {it['candidate_deck']} | "
                        f"{it['recommended']} |")
        rows.append("")
        return rows

    body = ["# Core Gameplay Backlog (Pass 28)", "",
            "> Evidence-gated roadmap. **No upload** is the default for every item. "
            "Internal-league evidence is our-vs-our, NOT the Kaggle leaderboard.", "",
            f"- **top proven gap:** `{out['top_gap']}`",
            f"- **rejected (refuted by trace):** {', '.join(out['rejected_gaps'])}",
            f"- {out['headline']}", ""]
    body += section("A. Immediate core rules (if evidence supports)",
                    roadmap["A_immediate_core_rules_if_evidence_supports"])
    body += section("B. Requires more observability",
                    roadmap["B_requires_more_observability"])
    body += section("C. Requires deck-specific / special pilot",
                    roadmap["C_requires_deck_specific_or_special_pilot"])
    OUT_MD.write_text("\n".join(body), encoding="utf-8")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(body), encoding="utf-8")

    print(f"roadmap -> {OUT_JSON.relative_to(REPO)} and {DOC.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
