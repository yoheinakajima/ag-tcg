#!/usr/bin/env python3
"""PASS 46J (Part I) — PRE-REGISTERED diamond specialist eval plan (NO games here).

Freezes the panel design, targets, thresholds, edge-label rules and the decision rule
BEFORE a single game is played (``games_played = 0``). The panel runner
(``run_pass46j_diamond_eval_panel.py``) consumes this plan; the strategy decision (Part J)
applies the frozen decision rule. LOCAL / READ-ONLY: no Object Storage, no Kaggle, no
events, no tarball mutation.

Arms (the only two that GATE the decision):
  * practical   = ``spec_vs_parent``      — does the owned SPECIALIST PLANNER beat the REAL
                                            internal diamond parent?
  * attribution = ``spec_vs_generic_ov``  — does it beat the 46H GENERIC flat option/family
                                            scorer head-to-head (so any edge is the
                                            PLANNER's per-context policies, not the
                                            previously-shipped generic scorer)?

Context panels (non-gating) supply the generic-scorer-vs-parent rates so the specialist's
edge-over-parent can be compared to the generic scorers' edge-over-parent via a Fisher-exact
INCREMENT, and a weaker-baseline attribution panel (vs the family-only floor).

Public references are benchmark-only and are NEVER scheduled here and NEVER gate the
decision. NO exact-damage / lethal / KO / missed-KO / Boss-gust / spread / best-action /
Kaggle-strength claim is made anywhere; decisive win-rate is a LOCAL feasibility/ordering
signal only.

Output: data/experiments/pass46j_diamond_eval_plan.{json,md}
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"

PARTICIPANTS = {
    "cg_typed_diamond_specialist_planner_v0": {
        "tarball": "data/submissions/candidates_pass46j/cg_typed_diamond_specialist_planner_v0.tar.gz",
        "kind": "owned_cg_typed_specialist_planner", "role": "subject_under_test"},
    "diamond_toolbox_diancie": {
        "tarball": "data/submissions/candidates_pass34/diamond_toolbox_diancie.tar.gz",
        "kind": "internal_stdlib_parent", "role": "parent_baseline"},
    "cg_typed_diamond_option_value_v1": {
        "tarball": "data/submissions/candidates_pass46h/cg_typed_diamond_option_value_v1.tar.gz",
        "kind": "cg_typed_generic_scorer", "role": "attribution_baseline_generic"},
    "cg_typed_diamond_family_only_floor_v1": {
        "tarball": "data/submissions/candidates_pass46h/cg_typed_diamond_family_only_floor_v1.tar.gz",
        "kind": "cg_typed_generic_scorer", "role": "attribution_baseline_floor"},
}

SPEC = "cg_typed_diamond_specialist_planner_v0"
PARENT = "diamond_toolbox_diancie"
GEN_OV = "cg_typed_diamond_option_value_v1"
GEN_FLOOR = "cg_typed_diamond_family_only_floor_v1"

PANELS = [
    {"panel_id": "spec_vs_parent", "arm": "practical", "gating": True,
     "subject": SPEC, "opponent": PARENT,
     "target_decisive": 40, "hard_cap_games": 72, "seat_balanced": True,
     "purpose": "Does the owned specialist planner beat the REAL internal diamond parent?"},
    {"panel_id": "spec_vs_generic_ov", "arm": "attribution", "gating": True,
     "subject": SPEC, "opponent": GEN_OV,
     "target_decisive": 36, "hard_cap_games": 64, "seat_balanced": True,
     "purpose": "Does the planner beat the 46H GENERIC option-value scorer head-to-head?"},
    {"panel_id": "spec_vs_generic_floor", "arm": "attribution_context", "gating": False,
     "subject": SPEC, "opponent": GEN_FLOOR,
     "target_decisive": 30, "hard_cap_games": 56, "seat_balanced": True,
     "purpose": "Does the planner beat the weaker family-only FLOOR scorer head-to-head?"},
    {"panel_id": "ov_vs_parent", "arm": "context", "gating": False,
     "subject": GEN_OV, "opponent": PARENT,
     "target_decisive": 30, "hard_cap_games": 56, "seat_balanced": True,
     "purpose": "Generic-scorer-vs-parent rate (Fisher-increment baseline for the planner)."},
    {"panel_id": "floor_vs_parent", "arm": "context", "gating": False,
     "subject": GEN_FLOOR, "opponent": PARENT,
     "target_decisive": 30, "hard_cap_games": 56, "seat_balanced": True,
     "purpose": "Family-only-floor-vs-parent rate (additional Fisher-increment baseline)."},
]

CONDITIONAL_NOISE = [
    {"panel_id": "parent_vs_parent", "arm": "noise_control", "gating": False,
     "subject": PARENT, "opponent": PARENT,
     "target_decisive": 20, "hard_cap_games": 40, "seat_balanced": True,
     "trigger": "only if spec_vs_parent appears to clear parent (confirmed/directional)",
     "purpose": "Self-mirror noise floor: decisive win rate must straddle 0.50."},
    {"panel_id": "spec_vs_spec", "arm": "noise_control", "gating": False,
     "subject": SPEC, "opponent": SPEC,
     "target_decisive": 20, "hard_cap_games": 40, "seat_balanced": True,
     "trigger": "only if spec_vs_parent appears to clear parent (confirmed/directional)",
     "purpose": "Self-mirror noise floor: decisive win rate must straddle 0.50."},
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    participants = {}
    all_present = True
    for cid, meta in PARTICIPANTS.items():
        p = ROOT / meta["tarball"]
        present = p.is_file()
        all_present = all_present and present
        participants[cid] = {"candidate_id": cid, **meta,
                             "present": present, "sha256": _sha(p)}

    plan = {
        "pass": "46J", "part": "I", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "games_played": 0, "pre_registered": True,
        "subject_under_test": SPEC,
        "participants": participants,
        "panels": PANELS,
        "conditional_noise_controls": CONDITIONAL_NOISE,
        "optional_reference_context": {
            "refs": ["public_ref_kiyotah_dragapult", "public_ref_kiyotah_iono"],
            "scheduled": False,
            "policy": ("benchmark-only; NOT scheduled in this panel (already exercised for "
                       "runnability in Part H); NEVER gates or changes the decision."),
        },
        "seat_balancing": ("each panel alternates subject seat 0/1 by game index and plays "
                           "until target_decisive decisive games or hard_cap_games is hit"),
        "thresholds": {
            "wilson_z": 1.96, "confirm_wilson_low": 0.5,
            "directional_point": 0.6, "seat_confound_hi": 0.6, "seat_confound_lo": 0.4,
            "invalid_abs_tol": 2, "invalid_rate_tol": 0.05,
            "noise_ci_must_contain": 0.5, "fisher_alpha": 0.05,
        },
        "edge_label_rules": {
            "metric": "decisive win rate (winner != None) of subject over opponent",
            "wilson_z": 1.96,
            "unsafe_invalid": "invalid games > 2 AND invalid_rate > 0.05",
            "seat_confounded": ("one seat decisive win rate >= 0.6 while the other <= 0.4 "
                                "(edge reverses with seat)"),
            "confirmed_edge": "Wilson_low > 0.5 AND NOT seat_confounded AND NOT unsafe_invalid",
            "directional_edge": ("point estimate >= 0.6 AND Wilson_low <= 0.5 AND NOT "
                                 "seat_confounded AND NOT unsafe_invalid"),
            "no_edge": ("residual: NOT confirmed_edge AND NOT directional_edge AND NOT "
                        "seat_confounded AND NOT unsafe_invalid"),
            "noise_clean": "self-mirror Wilson CI for decisive win rate CONTAINS 0.50",
        },
        "attribution_rules": {
            "head_to_head": ("spec_vs_generic_ov edge label (the planner must out-play the "
                             "generic scorer directly), with spec_vs_generic_floor as a "
                             "weaker-baseline corroborator"),
            "fisher_increment": ("one-sided Fisher-exact on the 2x2 "
                                 "[[spec_wins_vs_parent, spec_losses_vs_parent], "
                                 "[generic_wins_vs_parent, generic_losses_vs_parent]] for "
                                 "generic in {ov_vs_parent, floor_vs_parent}; the planner is "
                                 "'incrementally attributable' if it beats the parent at a "
                                 "higher rate than the generic scorer does (p < fisher_alpha)"),
            "attributable_to_planner": ("spec_vs_generic_ov is confirmed_edge OR "
                                        "directional_edge, OR the Fisher increment vs "
                                        "ov_vs_parent is significant (p < fisher_alpha)"),
        },
        "decision_rules": {
            "arms": {"practical": "spec_vs_parent", "attribution": "spec_vs_generic_ov"},
            "order": [
                {"decision": "validation_failed",
                 "when": ("either gating arm is unsafe_invalid, OR Parts A/B/F not all_ok, "
                          "OR Part H non-inert/smoke not ok")},
                {"decision": "safety_stop_required",
                 "when": "Part A preflight stop_required (handled upstream)"},
                {"decision": "diamond_specialist_promising_local_only",
                 "when": ("practical == confirmed_edge AND attributable_to_planner AND "
                          "noise controls clean (or not required) AND safety/validation/"
                          "smoke/non-inert(0 illegal)/no-leakage all hold")},
                {"decision": "diamond_specialist_directional_needs_more_n",
                 "when": ("practical == directional_edge AND attributable_to_planner; OR "
                          "practical == confirmed_edge but attribution only directional / a "
                          "triggered noise control not clean")},
                {"decision": "diamond_specialist_not_promising",
                 "when": ("practical in {no_edge, seat_confounded}, OR practical positive "
                          "but NOT attributable_to_planner (the generic scorer explains it)")},
            ],
            "reference_policy": "public references are benchmark-only and NEVER gate the decision",
            "noise_control_trigger": ("run parent_vs_parent and spec_vs_spec ONLY if "
                                      "spec_vs_parent is confirmed_edge or directional_edge"),
        },
        "claim_boundaries": ("decisive win-rate is a LOCAL feasibility/ordering signal only; "
                             "NO Kaggle-strength / leaderboard claim; references excluded; "
                             "role buckets / contexts are observable heuristic labels — no "
                             "exact-damage / lethal / KO / missed-KO / Boss-gust / spread / "
                             "best-action claim"),
        "all_participants_present": all_present,
        "all_ok": all_present,
    }

    (EXP / "pass46j_diamond_eval_plan.json").write_text(
        json.dumps(plan, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46J (Part I) — PRE-REGISTERED diamond specialist eval plan", "",
        "_LOCAL / READ-ONLY. Frozen BEFORE any game (games_played=0). Decisive win-rate is "
        "a local feasibility/ordering signal only — NOT a Kaggle / leaderboard / strength "
        "claim. Public references are benchmark-only and excluded from every decision. Role "
        "buckets / contexts are observable heuristic labels (no exact-damage / lethal / KO "
        "/ missed-KO / Boss-gust / spread / best-action)._", "",
        f"- **subject under test:** `{SPEC}`",
        f"- **all participants present:** {all_present}",
        f"- **gating arms:** practical=`spec_vs_parent`, attribution=`spec_vs_generic_ov`", "",
        "## Panels",
        "| panel | arm | gating | subject | opponent | target | cap |",
        "|---|---|:---:|---|---|---:|---:|",
    ]
    for p in PANELS:
        md.append(f"| `{p['panel_id']}` | {p['arm']} | {p['gating']} | `{p['subject']}` | "
                  f"`{p['opponent']}` | {p['target_decisive']} | {p['hard_cap_games']} |")
    md += ["", "## Conditional noise controls (only if practical clears parent)",
           "| panel | subject | opponent | target | cap |", "|---|---|---|---:|---:|"]
    for p in CONDITIONAL_NOISE:
        md.append(f"| `{p['panel_id']}` | `{p['subject']}` | `{p['opponent']}` | "
                  f"{p['target_decisive']} | {p['hard_cap_games']} |")
    md += ["", "## Decision rule (pre-registered)",
           "- **promising_local_only:** practical confirmed_edge AND attributable to the "
           "planner (beats generic scorer H2H or significant Fisher increment) AND noise "
           "clean AND safety/validation/smoke/non-inert all hold.",
           "- **directional_needs_more_n:** practical directional (or attribution only "
           "directional / noise not clean), still attributable.",
           "- **not_promising:** practical no-edge/seat-confounded, OR positive but the "
           "generic scorer already explains it (not attributable).",
           "- **validation_failed / safety_stop_required:** gating-arm unsafe-invalid / "
           "upstream parts not ok / preflight stop."]
    (EXP / "pass46j_diamond_eval_plan.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"PRE-REGISTERED: all_present={all_present} panels={len(PANELS)} "
          f"conditional={len(CONDITIONAL_NOISE)}")
    return 0 if all_present else 1


if __name__ == "__main__":
    raise SystemExit(main())
