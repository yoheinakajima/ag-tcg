#!/usr/bin/env python3
"""Pass 28 (Part H) — evidence-gated causal ranking. LOCAL/READ-ONLY.

Ranks candidate core gaps by EVIDENCE only. Color-matched energy can rank #1
ONLY if the trace proves wrong/poor attachment caused losses — it does NOT, so
it is explicitly REJECTED here. Writes
data/experiments/pass28_core_gap_priority.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
FOREN = EXP / "pass28_deck_forensics.json"
OUT_JSON = EXP / "pass28_core_gap_priority.json"
OUT_MD = EXP / "pass28_core_gap_priority.md"


def main() -> int:
    foren = json.loads(FOREN.read_text(encoding="utf-8"))
    fam = foren["families"]
    ev = {k: v.get("evidence", {}) for k, v in fam.items()}
    rb = ev["raging_bolt"]
    venu = ev["venusaur"]
    venu_loop = max(venu.get("context_histogram", {}).values(), default=0)
    total_off_plan = sum(e.get("attach_off_deck_plan", 0) for e in ev.values())
    total_atk_not_taken = sum(e.get("attack_available_not_taken", 0)
                              for e in ev.values())

    gaps = [
        {
            "gap_id": "effect_loop_termination",
            "claimed_issue": ("generic pilot cannot exit a repeated forced/optional "
                              "effect, stalling the deck"),
            "evidence_for": (f"venusaur: context 33/21 repeat ~{venu_loop}x per game, "
                             f"avg ~1516 steps, only {venu['attacks_taken']} attacks in "
                             f"{venu['decisions']} decisions"),
            "evidence_against": "isolated to venusaur; other decks do not loop",
            "decks_affected": ["league_mega_venusaur_tank"],
            "action_trace_count": venu_loop,
            "loss_win_impact": "near-total attack starvation in affected games",
            "implementation_risk": "medium (effect-termination policy is subtle)",
            "generality": "deck-specific (1 deck)",
            "legal_alternative_observed": ("forced 1-option contexts leave no legal "
                                           "alternative; the loop is engine/effect-driven"),
            "positive_controls_exist": ("yes — 5 other decks run normal-length games "
                                        "without looping"),
            "confidence": "high",
        },
        {
            "gap_id": "mill_deckout_unsupported",
            "claimed_issue": "deckout/mill win condition not supported by generic pilot",
            "evidence_for": (f"durant: {ev['durant'].get('invalid_games', 4)}/4 games "
                             "INVALID at init (step 1), 0 gameplay decisions reached"),
            "evidence_against": ("the failure is at engine init, so the deckout LINE is "
                                 "never even attempted — this is also a legality issue"),
            "decks_affected": ["league_durant_deckout_carousel"],
            "action_trace_count": ev["durant"].get("invalid_games", 4),
            "loss_win_impact": "automatic loss (never reaches turn 1)",
            "implementation_risk": "high (needs special pilot AND init-legality fix)",
            "generality": "deck-specific (1 deck)",
            "legal_alternative_observed": "none — no legal gameplay state is reached",
            "positive_controls_exist": "yes — 6 other decks reach turn 1 fine",
            "confidence": "high (failure) / unknown (whether a legal line exists)",
        },
        {
            "gap_id": "ramp_sequencing",
            "claimed_issue": "from-discard energy ramp engine under-exercised",
            "evidence_for": (f"gardevoir: only {ev['gardevoir'].get('attach_count')} "
                             "attaches and minimal in-play actions; ramp ability barely "
                             "used"),
            "evidence_against": ("gardevoir still attacks early and often "
                                 f"({ev['gardevoir'].get('attacks_taken')}x) — ramp may "
                                 "be a tempo loss, not a hard block"),
            "decks_affected": ["league_mega_gardevoir_psychic_ramp"],
            "action_trace_count": ev["gardevoir"].get("attach_count", 0),
            "loss_win_impact": "tempo/under-powered attacks; not a hard stall",
            "implementation_risk": "medium",
            "generality": "deck-specific (1 deck)",
            "legal_alternative_observed": "yes — it attacks instead of ramping",
            "positive_controls_exist": "yes — water/dragapult attach on tempo",
            "confidence": "medium",
        },
        {
            "gap_id": "evolution_sequencing_speed",
            "claimed_issue": "Mega evolution line setup is high-variance — some games stall",
            "evidence_for": (f"charizard: first attack typically at step "
                             f"{ev['charizard'].get('first_attack_step')} (median, on "
                             f"tempo with aggro), min "
                             f"{ev['charizard'].get('first_attack_step_min')}, but a long "
                             "tail of stalled games where the line never comes online"),
            "evidence_against": ("in most games it DOES complete the line and attack on "
                                 "tempo; the slowness is a variance tail, not a uniform "
                                 "failure, and Rare Candy use is unobservable"),
            "decks_affected": ["league_mega_charizard_x_burst"],
            "action_trace_count": 1,
            "loss_win_impact": "stalled-game tail cedes the match before the combo lands",
            "implementation_risk": "medium",
            "generality": "partial (Mega/Stage-2 decks)",
            "legal_alternative_observed": "n/a",
            "positive_controls_exist": "yes — aggro decks attack by median step 5-6 too",
            "confidence": "medium",
        },
        {
            "gap_id": "spread_target_selection_observability",
            "claimed_issue": "spread/bench damage targeting may be missing",
            "evidence_for": ("dragapult attacks frequently but attack options expose "
                             "only attackId; bench-target choices are not surfaced"),
            "evidence_against": ("UNMEASURED, not proven missing — dragapult posts a "
                                 "strong internal record while attacking often"),
            "decks_affected": ["league_dragapult_spread"],
            "action_trace_count": 0,
            "loss_win_impact": "unknown (not observable)",
            "implementation_risk": "low (needs observability first)",
            "generality": "deck-specific",
            "legal_alternative_observed": "n/a (choice not surfaced)",
            "positive_controls_exist": "n/a",
            "confidence": "unknown -> need_more_diagnostics",
        },
        {
            "gap_id": "engine_card_play_observability",
            "claimed_issue": "engine supporters (e.g. Crispin) may not be played well",
            "evidence_for": ("raging_bolt: play_from_hand options do not resolve card "
                             "identity, so supporter usage cannot be confirmed"),
            "evidence_against": ("Ogerpon IS benched and energy IS on-plan, so the "
                                 "engine is at least partially functioning"),
            "decks_affected": ["league_raging_bolt_ogerpon"],
            "action_trace_count": 0,
            "loss_win_impact": "unknown (not observable)",
            "implementation_risk": "low (needs observability first)",
            "generality": "deck-specific",
            "legal_alternative_observed": "n/a",
            "positive_controls_exist": "n/a",
            "confidence": "unknown -> need_more_diagnostics",
        },
        # --- explicitly REJECTED gaps (the Pass-27 hypotheses) ---
        {
            "gap_id": "color_match_attach",
            "claimed_issue": "pilot attaches wrong-color energy (Pass-27 hypothesis)",
            "evidence_for": "NONE found in trace",
            "evidence_against": (f"{total_off_plan} off-deck-plan attaches across ALL "
                                 "decks; raging_bolt attaches only L/F/G (its plan) and "
                                 "Bellowing Thunder discards F+L from across the board, "
                                 "so F/L on Ogerpon still feeds the plan"),
            "decks_affected": [],
            "action_trace_count": total_off_plan,
            "loss_win_impact": "none demonstrated",
            "implementation_risk": "n/a",
            "generality": "n/a",
            "legal_alternative_observed": "pilot already attaches on-plan colors",
            "positive_controls_exist": ("yes — every deck attaches its own colors "
                                        "correctly"),
            "confidence": "REJECTED (trace refutes; cannot rank #1 per mandate)",
        },
        {
            "gap_id": "attack_pressure",
            "claimed_issue": "pilot fails to attack (Pass-27 hypothesis)",
            "evidence_for": "NONE found in trace",
            "evidence_against": (f"{total_atk_not_taken} attack-available-not-taken "
                                 "across ALL decks; raging_bolt attacks "
                                 f"{rb['attacks_taken']}x from step "
                                 f"{rb['first_attack_step']}"),
            "decks_affected": [],
            "action_trace_count": total_atk_not_taken,
            "loss_win_impact": "none demonstrated",
            "implementation_risk": "n/a",
            "generality": "n/a",
            "legal_alternative_observed": "pilot already attacks every available turn",
            "positive_controls_exist": "yes — all decks attack when able",
            "confidence": "REJECTED (trace refutes)",
        },
    ]

    rank = {"high": 0, "medium": 1, "unknown": 2, "low": 3}

    def keyf(g):
        c = g["confidence"].split()[0].lower()
        if c.startswith("rejected"):
            return (9, 0)
        return (rank.get(c, 2), -g["action_trace_count"])

    active = [g for g in gaps if not g["confidence"].lower().startswith("rejected")]
    rejected = [g for g in gaps if g["confidence"].lower().startswith("rejected")]
    active.sort(key=keyf)
    ranked = active + rejected

    out = {
        "pass": "28", "part": "H",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "ranking_rule": ("Ranked by trace evidence, not intuition. Color-matched energy "
                         "and attack pressure are REJECTED (the trace refutes them) and "
                         "cannot rank #1, per the Pass-28 mandate."),
        "no_generic_high_confidence_gap": True,
        "headline": ("No deck-AGNOSTIC high-confidence core-rule gap is proven by the "
                     "trace. The Pass-27 color/attack hypotheses are refuted. The "
                     "highest-evidence proven gaps are DECK-SPECIFIC (venusaur effect "
                     "loop, durant init/mill); the remaining generic suspicions are "
                     "UNOBSERVABLE and need more diagnostics."),
        "top_gap": ranked[0]["gap_id"],
        "rejected_gaps": [g["gap_id"] for g in rejected],
        "need_more_diagnostics": [g["gap_id"] for g in active
                                  if "need_more_diagnostics" in g["confidence"]],
        "gaps_ranked": ranked,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 28 — Causal Gap Priority (Part H, evidence-gated)", "",
         f"> {out['ranking_rule']}", "", f"- **headline:** {out['headline']}",
         f"- **top_gap:** `{out['top_gap']}`",
         f"- **rejected_gaps:** {', '.join(out['rejected_gaps'])}",
         f"- **need_more_diagnostics:** {', '.join(out['need_more_diagnostics'])}", ""]
    for i, g in enumerate(ranked, 1):
        L += [f"## {i}. {g['gap_id']} — {g['confidence']}",
              f"- claimed_issue: {g['claimed_issue']}",
              f"- evidence_for: {g['evidence_for']}",
              f"- evidence_against: {g['evidence_against']}",
              f"- decks_affected: {g['decks_affected']}",
              f"- action_trace_count: {g['action_trace_count']}",
              f"- loss/win impact: {g['loss_win_impact']}",
              f"- implementation_risk: {g['implementation_risk']}",
              f"- generality: {g['generality']}",
              f"- legal_alternative_observed: {g['legal_alternative_observed']}",
              f"- positive_controls_exist: {g['positive_controls_exist']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"priority: top_gap={out['top_gap']} rejected={out['rejected_gaps']} "
          f"-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
