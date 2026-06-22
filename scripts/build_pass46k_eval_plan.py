#!/usr/bin/env python3
"""PASS 46K (Part C) — PRE-REGISTERED larger-N confirmation eval plan (NO games here).

Freezes the larger-N panel design, COMBINED decisive targets, carry-forward accounting policy,
edge-label rules and the decision rule BEFORE a single NEW game is played. Pass 46K re-evaluates
the EXISTING Pass-46J specialist candidate ``cg_typed_diamond_specialist_planner_v0`` at larger
N; it CARRIES the 46J decisive evidence forward (auditable, never silently mixed) and runs only
the incremental games needed to reach the larger targets.

Gating arms (the ONLY two that gate the decision):
  * practical   = ``spec_vs_parent``     — does the specialist planner still beat the REAL
                                            internal diamond parent at larger N?
  * attribution = ``spec_vs_generic_ov`` — does it separate from the stronger 46H GENERIC
                                            option-value scorer head-to-head at larger N (so any
                                            edge is the planner's policy, not the generic scorer)?

Context panels (non-gating): the floor head-to-head and the two generic-vs-parent rates (the
Fisher-increment baselines). Conditional self-mirror noise controls run only if the practical
arm clears the parent.

Public references are BENCHMARK-ONLY: registered here as ``optional_reference_context`` with
``gating=false`` / ``benchmark_only=true`` / ``decision_excluded=true``. They are NEVER a
source/parent/candidate and NEVER gate or change the decision (Part F plays them in their own
no_upload ledger). NO exact-damage / lethal / KO / missed-KO / Boss-gust / spread / best-action /
Kaggle-strength claim is made anywhere; decisive win-rate is a LOCAL feasibility/ordering signal.

LOCAL / READ-ONLY: no Object Storage, no Kaggle, no events, no tarball mutation.
Output: data/experiments/pass46k_eval_plan.{json,md}
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PANEL_46J = EXP / "pass46j_diamond_eval_panel.json"

SPEC = "cg_typed_diamond_specialist_planner_v0"
PARENT = "diamond_toolbox_diancie"
GEN_OV = "cg_typed_diamond_option_value_v1"
GEN_FLOOR = "cg_typed_diamond_family_only_floor_v1"

PARTICIPANTS = {
    SPEC: {
        "tarball": "data/submissions/candidates_pass46j/cg_typed_diamond_specialist_planner_v0.tar.gz",
        "kind": "owned_cg_typed_specialist_planner", "role": "subject_under_test"},
    PARENT: {
        "tarball": "data/submissions/candidates_pass34/diamond_toolbox_diancie.tar.gz",
        "kind": "internal_stdlib_parent", "role": "parent_baseline"},
    GEN_OV: {
        "tarball": "data/submissions/candidates_pass46h/cg_typed_diamond_option_value_v1.tar.gz",
        "kind": "cg_typed_generic_scorer", "role": "attribution_baseline_generic_strongest"},
    GEN_FLOOR: {
        "tarball": "data/submissions/candidates_pass46h/cg_typed_diamond_family_only_floor_v1.tar.gz",
        "kind": "cg_typed_generic_scorer", "role": "attribution_baseline_floor"},
}

# COMBINED decisive targets (carried 46J + new 46K) and the NEW-game cap per panel.
# new_cap stubs are generated on top of the carried rows; completion = combined decisive
# target reached OR all new stubs exhausted.
PANELS = [
    {"panel_id": "spec_vs_parent", "arm": "practical", "gating": True,
     "subject": SPEC, "opponent": PARENT,
     "target_decisive": 80, "min_acceptable_decisive": 60, "new_cap": 64, "seat_balanced": True,
     "purpose": "Larger-N: does the specialist planner still beat the REAL internal parent?"},
    {"panel_id": "spec_vs_generic_ov", "arm": "attribution", "gating": True,
     "subject": SPEC, "opponent": GEN_OV,
     "target_decisive": 80, "min_acceptable_decisive": 60, "new_cap": 68, "seat_balanced": True,
     "purpose": "Larger-N: does the planner separate from the 46H GENERIC option-value scorer?"},
    {"panel_id": "spec_vs_generic_floor", "arm": "attribution_context", "gating": False,
     "subject": SPEC, "opponent": GEN_FLOOR,
     "target_decisive": 60, "min_acceptable_decisive": 40, "new_cap": 48, "seat_balanced": True,
     "purpose": "Larger-N corroborator: planner vs the weaker family-only FLOOR scorer."},
    {"panel_id": "ov_vs_parent", "arm": "context", "gating": False,
     "subject": GEN_OV, "opponent": PARENT,
     "target_decisive": 44, "min_acceptable_decisive": 30, "new_cap": 24, "seat_balanced": True,
     "purpose": "Generic-ov-vs-parent rate (Fisher-increment baseline for the planner)."},
    {"panel_id": "floor_vs_parent", "arm": "context", "gating": False,
     "subject": GEN_FLOOR, "opponent": PARENT,
     "target_decisive": 44, "min_acceptable_decisive": 30, "new_cap": 24, "seat_balanced": True,
     "purpose": "Family-only-floor-vs-parent rate (additional Fisher-increment baseline)."},
]

CONDITIONAL_NOISE = [
    {"panel_id": "parent_vs_parent", "arm": "noise_control", "gating": False,
     "subject": PARENT, "opponent": PARENT,
     "target_decisive": 30, "min_acceptable_decisive": 20, "new_cap": 16, "seat_balanced": True,
     "trigger": "only if spec_vs_parent clears parent (confirmed/directional)",
     "purpose": "Self-mirror noise floor: decisive win rate Wilson CI must contain 0.50."},
    {"panel_id": "spec_vs_spec", "arm": "noise_control", "gating": False,
     "subject": SPEC, "opponent": SPEC,
     "target_decisive": 30, "min_acceptable_decisive": 20, "new_cap": 16, "seat_balanced": True,
     "trigger": "only if spec_vs_parent clears parent (confirmed/directional)",
     "purpose": "Self-mirror noise floor: decisive win rate Wilson CI must contain 0.50."},
]

REFERENCES = [
    "public_ref_kiyotah_dragapult",
    "public_ref_kiyotah_iono",
    "public_ref_kiyotah_mega_abomasnow",
    "public_ref_kiyotah_mega_lucario",
    "public_ref_ryotasueyoshi_alakazam",
]


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _carried_counts() -> dict:
    """Per-panel carried 46J counts (decisive/wins/results) for the pre-registration record."""
    out: dict[str, dict] = {}
    if not PANEL_46J.exists():
        return out
    d = json.loads(PANEL_46J.read_text(encoding="utf-8"))
    for p in d.get("panels", []):
        out[p["panel_id"]] = {"carried_results": p["n_results"],
                              "carried_decisive": p["n_decisive"],
                              "carried_subject_wins": p["subject_wins"],
                              "carried_edge_label_46j": p["edge_label"]}
    return out


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    participants = {}
    all_present = True
    for cid, meta in PARTICIPANTS.items():
        p = ROOT / meta["tarball"]
        present = p.is_file()
        all_present = all_present and present
        participants[cid] = {"candidate_id": cid, **meta, "present": present, "sha256": _sha(p)}

    references_available = []
    for ref_id in REFERENCES:
        tb = ROOT / "data" / "reference_agents" / "raw_outputs" / ref_id / "submission.tar.gz"
        references_available.append({
            "ref_id": ref_id, "tarball": str(tb.relative_to(ROOT)),
            "kind": "public_reference_benchmark_only", "present": tb.is_file()})

    carried = _carried_counts()
    panels = []
    for p in PANELS:
        panels.append({**p, **carried.get(p["panel_id"], {})})
    noise = [{**p, **carried.get(p["panel_id"], {})} for p in CONDITIONAL_NOISE]

    plan = {
        "pass": "46K", "part": "C", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "new_games_played": 0, "pre_registered": True,
        "subject_under_test": SPEC,
        "evaluates_existing_candidate": True, "rebuilds_candidate": False,
        "participants": participants,
        "panels": panels,
        "conditional_noise_controls": noise,
        "carry_forward": {
            "enabled": True,
            "source_pass": "46j",
            "source_panel_json": str(PANEL_46J.relative_to(ROOT)),
            "source_games_jsonl": "data/experiments/pass46j_diamond_eval_games.jsonl",
            "target_games_jsonl": "data/experiments/pass46k_diamond_confirmation_games.jsonl",
            "policy": ("46J decisive/result rows are copied ONCE into the 46K ledger with "
                       "game_id renamed to 'carry46j:<old_game_id>' and tagged carried=true, "
                       "source_pass='46j', source_game_id=<old_game_id>. New 46K games use "
                       "fresh ids '<panel>#g<NNN>'. The batch worker does NOT seed by game_id "
                       "(each game is an independent env.run), so renamed-and-new ids are "
                       "genuinely independent plays; the rename only prevents id collision. "
                       "Every panel summary MUST expose carried_results, new_results, "
                       "carried_decisive, new_decisive and the combined totals — carried and "
                       "new are NEVER silently mixed."),
            "carried_panels": sorted(carried.keys()),
        },
        "references_available": references_available,
        "optional_reference_context": [{
            "panel_id": "spec_vs_public_refs", "arm": "reference_benchmark",
            "gating": False, "benchmark_only": True, "decision_excluded": True,
            "subject": SPEC, "opponents": REFERENCES,
            "target_decisive_per_ref": 4, "min_games_per_seat_per_ref": 2,
            "hard_cap_games_per_ref": 12, "seat_balanced": True,
            "ledger": "data/experiments/pass46k_reference_games.jsonl",
            "work_dir": "data/tournament/benchmark/_pass46k_ref_work",
            "policy": ("benchmark-only; played in Part F in a SEPARATE no_upload ledger so "
                       "reference games can NEVER leak into the gating/attribution statistics; "
                       "untrusted ref tarballs are member-validated BEFORE extraction; NEVER "
                       "gates or changes the decision — distance-from-parity is colour only."),
        }],
        "seat_balancing": ("each panel alternates subject seat 0/1 by NEW-game index; carried "
                           "rows keep their original recorded seat; play continues until the "
                           "combined decisive target or the new-game cap is hit"),
        "thresholds": {
            "wilson_z": 1.96, "confirm_wilson_low": 0.5,
            "directional_point": 0.6, "seat_confound_hi": 0.6, "seat_confound_lo": 0.4,
            "invalid_abs_tol": 2, "invalid_rate_tol": 0.05,
            "noise_ci_must_contain": 0.5, "fisher_alpha": 0.05,
            "attribution_negative_point_lt": 0.5,
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
            "head_to_head": "spec_vs_generic_ov edge label at larger N (planner must out-play "
                            "the generic scorer directly); spec_vs_generic_floor corroborates",
            "fisher_increment": ("one-sided Fisher-exact on [[spec_wins_vs_parent, "
                                 "spec_losses_vs_parent], [generic_wins_vs_parent, "
                                 "generic_losses_vs_parent]] for generic in {ov_vs_parent, "
                                 "floor_vs_parent}; planner is 'incrementally attributable' if "
                                 "it beats the parent at a HIGHER rate than the generic scorer "
                                 "does (p < fisher_alpha)"),
            "attribution_negative": ("spec_vs_generic_ov decisive win rate < 0.5 at/above "
                                     "min_acceptable_decisive — the generic scorer is as good or "
                                     "better, so the planner adds no separable value"),
        },
        "decision_rules": {
            "arms": {"practical": "spec_vs_parent", "attribution": "spec_vs_generic_ov"},
            "allowed_decisions": [
                "diamond_specialist_confirmed_local_candidate",
                "diamond_specialist_promising_needs_reference_work",
                "diamond_specialist_inconclusive_needs_more_n",
                "diamond_specialist_not_promising",
                "validation_failed", "safety_stop_required",
            ],
            "order": [
                {"decision": "safety_stop_required",
                 "when": "Part A preflight stop_required"},
                {"decision": "validation_failed",
                 "when": ("Parts A/B not all_ok, OR a gating arm is unsafe_invalid, OR "
                          "no_upload / reference-exclusion / root-immutability violated")},
                {"decision": "diamond_specialist_not_promising",
                 "when": ("practical (spec_vs_parent) is no_edge or seat_confounded at larger N "
                          "(the parent edge did NOT hold), OR practical positive but attribution "
                          "is NEGATIVE (generic_ov decisive win rate < 0.5 — the generic scorer "
                          "explains/exceeds it)")},
                {"decision": "diamond_specialist_inconclusive_needs_more_n",
                 "when": ("neither gating arm reached its min_acceptable_decisive, OR practical "
                          "is only directional_edge (not confirmed) at larger N, OR a triggered "
                          "noise control is not clean")},
                {"decision": "diamond_specialist_confirmed_local_candidate",
                 "when": ("practical == confirmed_edge at larger N AND (attribution == "
                          "confirmed_edge OR (attribution == directional_edge AND the Fisher "
                          "increment vs ov_vs_parent is significant)) AND noise controls clean")},
                {"decision": "diamond_specialist_promising_needs_reference_work",
                 "when": ("practical == confirmed_edge at larger N AND noise clean AND "
                          "attribution is NOT negative but NOT fully confirmed (ov no_edge, or "
                          "directional without a significant Fisher increment) — the parent edge "
                          "holds but separation from the generic scorer needs more work; "
                          "reference distance is reported as context only")},
            ],
            "reference_policy": ("public references are benchmark-only and NEVER gate or change "
                                 "the decision; they may only affect the reason TEXT"),
            "noise_control_trigger": ("run parent_vs_parent and spec_vs_spec ONLY if "
                                      "spec_vs_parent is confirmed_edge or directional_edge"),
        },
        "claim_boundaries": ("decisive win-rate is a LOCAL feasibility/ordering signal only; NO "
                             "Kaggle-strength / leaderboard / parity claim; references excluded "
                             "from decisions; role buckets / contexts are observable heuristic "
                             "labels — no exact-damage / lethal / KO / missed-KO / Boss-gust / "
                             "spread / best-action claim"),
        "all_participants_present": all_present,
        "all_references_present": all(r["present"] for r in references_available),
        "all_ok": all_present,
    }

    (EXP / "pass46k_eval_plan.json").write_text(
        json.dumps(plan, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46K (Part C) — PRE-REGISTERED larger-N confirmation eval plan", "",
        "_LOCAL / READ-ONLY. Frozen BEFORE any NEW game (new_games_played=0). Re-evaluates the "
        "EXISTING Pass-46J specialist (rebuilds nothing). 46J decisive evidence is CARRIED "
        "forward with explicit carried-vs-new accounting (never silently mixed). Decisive "
        "win-rate is a LOCAL feasibility/ordering signal only — NOT a Kaggle / leaderboard / "
        "parity claim. Public references are benchmark-only and excluded from every decision. "
        "Role buckets / contexts are observable heuristic labels (no exact-damage / lethal / KO "
        "/ missed-KO / Boss-gust / spread / best-action)._", "",
        f"- **subject under test:** `{SPEC}` (evaluated, not rebuilt)",
        f"- **all participants present:** {all_present}",
        f"- **references available (benchmark-only):** "
        f"{sum(r['present'] for r in references_available)}/{len(references_available)}",
        f"- **gating arms:** practical=`spec_vs_parent`, attribution=`spec_vs_generic_ov`", "",
        "## Panels (combined carried+new targets)",
        "| panel | arm | gating | subject | opponent | target | min | new cap | carried dec |",
        "|---|---|:---:|---|---|---:|---:|---:|---:|",
    ]
    for p in panels:
        md.append(f"| `{p['panel_id']}` | {p['arm']} | {p['gating']} | `{p['subject']}` | "
                  f"`{p['opponent']}` | {p['target_decisive']} | "
                  f"{p['min_acceptable_decisive']} | {p['new_cap']} | "
                  f"{p.get('carried_decisive', 0)} |")
    md += ["", "## Conditional noise controls (only if practical clears parent)",
           "| panel | subject | opponent | target | new cap | carried dec |",
           "|---|---|---|---:|---:|---:|"]
    for p in noise:
        md.append(f"| `{p['panel_id']}` | `{p['subject']}` | `{p['opponent']}` | "
                  f"{p['target_decisive']} | {p['new_cap']} | {p.get('carried_decisive', 0)} |")
    md += ["", "## Public references (benchmark-only — NEVER gate)",
           "| ref | present |", "|---|:---:|"]
    for r in references_available:
        md.append(f"| `{r['ref_id']}` | {r['present']} |")
    md += ["", "## Decision rule (pre-registered, refs NEVER gate)",
           "- **confirmed_local_candidate:** practical confirmed_edge at larger N AND "
           "(attribution confirmed_edge OR directional+significant-Fisher) AND noise clean.",
           "- **promising_needs_reference_work:** practical confirmed_edge AND noise clean AND "
           "attribution not negative but not fully confirmed (needs more separation work).",
           "- **inconclusive_needs_more_n:** gating arms below min_acceptable_decisive, or "
           "practical only directional, or a triggered noise control not clean.",
           "- **not_promising:** practical no_edge/seat_confounded, OR attribution negative "
           "(generic scorer explains/exceeds it).",
           "- **validation_failed / safety_stop_required:** upstream parts not ok / gating "
           "unsafe-invalid / no-upload or reference-exclusion or root-immutability violated / "
           "Part A stop."]
    (EXP / "pass46k_eval_plan.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_present,
                      "all_references_present": plan["all_references_present"],
                      "panels": len(panels), "conditional": len(noise),
                      "carried_panels": sorted(carried.keys())}, indent=2))
    return 0 if all_present else 1


if __name__ == "__main__":
    raise SystemExit(main())
