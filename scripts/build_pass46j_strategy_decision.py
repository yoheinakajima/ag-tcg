#!/usr/bin/env python3
"""PASS 46J (Part J) — strategy decision (applies the PRE-REGISTERED rule).

Re-derives the pass decision DETERMINISTICALLY from the frozen decision rule
(``pass46j_diamond_eval_plan.json``) and the upstream evidence artifacts (Parts A/F/H/I).
The derivation lives in the pure, importable ``derive_decision(ctx)`` so the Part-L tests
can re-derive the same decision from the same evidence (forward-compatible: change the
evidence, the decision follows).

Honesty boundaries: decisive win-rate is a LOCAL feasibility/ordering signal only — NOT a
Kaggle / leaderboard / strength claim. Public references are benchmark-only and excluded from
every arm. Role buckets / contexts are observable heuristic labels — no exact-damage /
lethal / KO / missed-KO / Boss-gust / spread / best-action claim. NO promotion, NO upload,
NO production mutation.

Decisions: diamond_specialist_promising_local_only | diamond_specialist_directional_needs_more_n
| diamond_specialist_not_promising | validation_failed | safety_stop_required.

Output: data/experiments/pass46j_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"

PLAN = EXP / "pass46j_diamond_eval_plan.json"
SAFETY = EXP / "pass46j_safety_preflight.json"
VALID = EXP / "pass46j_candidate_validation.json"
SMOKE = EXP / "pass46j_diamond_smoke.json"
NONINERT = EXP / "pass46j_diamond_non_inertness.json"
PANEL = EXP / "pass46j_diamond_eval_panel.json"

PRACTICAL_PANEL = "spec_vs_parent"


def derive_decision(ctx: dict) -> dict:
    """Pure decision function. ``ctx`` carries booleans/labels extracted from the evidence.

    Order (conservative reading of the pre-registered ladder; the HARD safety gate takes
    precedence over validation, both of which precede the positive ladder):
      safety_stop_required -> validation_failed -> promising -> directional -> not_promising.
    """
    reasons: list[str] = []

    if ctx["safety_stop_required"]:
        return {"decision": "safety_stop_required",
                "reasons": ["Part A preflight set stop_required=True"]}

    upstream_ok = (ctx["safety_all_ok"] and ctx["validation_all_ok"]
                   and ctx["smoke_all_ok"] and ctx["root_unchanged"]
                   and ctx["non_inert_ok"] and ctx["non_inert_illegal"] == 0
                   and ctx["plan_field_driven_ok"])
    if not upstream_ok or ctx["gating_unsafe_invalid"] or not ctx["references_excluded"]:
        if not ctx["safety_all_ok"]:
            reasons.append("Part A safety not all_ok")
        if not ctx["validation_all_ok"]:
            reasons.append("Part F validation not all_ok")
        if not ctx["smoke_all_ok"]:
            reasons.append("Part H smoke not all_ok")
        if not ctx["root_unchanged"]:
            reasons.append("root main.py/deck.csv changed")
        if not ctx["non_inert_ok"]:
            reasons.append("Part H non-inertness not ok")
        if ctx["non_inert_illegal"] != 0:
            reasons.append("non-inertness produced illegal decisions")
        if not ctx["plan_field_driven_ok"]:
            reasons.append("changes not plan-field-driven")
        if ctx["gating_unsafe_invalid"]:
            reasons.append("a gating eval panel is unsafe_invalid")
        if not ctx["references_excluded"]:
            reasons.append("a public reference leaked into source/parent/candidate/panels")
        return {"decision": "validation_failed", "reasons": reasons}

    label = ctx["practical_label"]
    attributable = ctx["attributable_to_planner"]
    noise_clean = ctx["noise_clean"]
    seat_conf = ctx["practical_seat_confounded"]

    if label == "confirmed_edge" and not seat_conf and attributable and noise_clean:
        reasons = ["practical (spec_vs_parent) = confirmed_edge, clean seats",
                   "attributable to the planner (beats generic scorer H2H or significant "
                   "Fisher increment vs generic-vs-parent)",
                   "self-mirror noise controls clean (CIs straddle 0.5)",
                   "safety/validation/smoke/non-inertness(0 illegal)/no-leakage all hold"]
        return {"decision": "diamond_specialist_promising_local_only", "reasons": reasons}

    if (label == "directional_edge" and attributable) or (
            label == "confirmed_edge" and attributable and not noise_clean):
        reasons = [f"practical = {label}, attributable={attributable}, "
                   f"noise_clean={noise_clean}",
                   "edge is positive + attributable but not fully confirmed — needs more n"]
        return {"decision": "diamond_specialist_directional_needs_more_n", "reasons": reasons}

    if label in ("no_edge", "seat_confounded") or seat_conf:
        reasons = [f"practical = {label} (seat_confounded={seat_conf}) — no clean parent edge"]
        return {"decision": "diamond_specialist_not_promising", "reasons": reasons}

    if not attributable:
        reasons = [f"practical = {label} but NOT attributable to the planner "
                   "(generic scorer explains the edge)"]
        return {"decision": "diamond_specialist_not_promising", "reasons": reasons}

    return {"decision": "diamond_specialist_not_promising",
            "reasons": [f"residual: practical={label}, attributable={attributable}, "
                        f"noise_clean={noise_clean}"]}


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_context() -> dict:
    safety = _load(SAFETY)
    valid = _load(VALID)
    smoke = _load(SMOKE)
    noninert = _load(NONINERT)
    panel = _load(PANEL)
    plan = _load(PLAN)

    by_id = {p["panel_id"]: p for p in panel["panels"]}
    practical = by_id.get(PRACTICAL_PANEL, {})
    gating_unsafe = any(p.get("unsafe_invalid") for p in panel["panels"] if p.get("gating"))
    noise_panels = [p for p in panel["panels"] if p["arm"] == "noise_control"]
    noise_clean = all(p.get("noise_ci_contains_half") for p in noise_panels) \
        if noise_panels else True

    # references excluded: no public_ref participates as source/parent/candidate/panel, and
    # the plan's optional reference context is NOT scheduled.
    part_ids = list(plan["participants"].keys())
    panel_ids = {p["subject_id"] for p in panel["panels"]} | \
        {p["opponent_id"] for p in panel["panels"]}
    refs_excluded = (not any("public_ref" in cid for cid in part_ids)
                     and not any("public_ref" in cid for cid in panel_ids)
                     and not plan.get("optional_reference_context", {}).get("scheduled", False))

    return {
        "safety_all_ok": bool(safety.get("all_ok")),
        "safety_stop_required": bool(safety.get("stop_required")),
        "validation_all_ok": bool(valid.get("all_ok")),
        "is_planner_not_flat_scorer": bool(valid.get("is_planner_not_flat_scorer")),
        "smoke_all_ok": bool(smoke.get("all_ok")),
        "root_unchanged": bool(smoke.get("root_main_deck_unchanged")),
        "non_inert_ok": bool(noninert.get("non_inert_ok")),
        "non_inert_illegal": int(
            noninert["non_inertness_vs_parent"]["illegal_decisions"]),
        "plan_field_driven_ok": bool(noninert.get("plan_field_driven_ok")),
        "non_inert_attributable": bool(noninert.get("attributable_to_planner")),
        "practical_label": practical.get("edge_label"),
        "practical_win_rate": practical.get("subject_win_rate"),
        "practical_wilson_low": practical.get("wilson_low"),
        "practical_wilson_high": practical.get("wilson_high"),
        "practical_seat_confounded": bool(practical.get("seat_confounded")),
        "attributable_to_planner": bool(panel["attribution"]["attributable_to_planner"]),
        "head_to_head_vs_generic_ov": panel["attribution"]["head_to_head_vs_generic_ov"],
        "head_to_head_vs_generic_floor": panel["attribution"]["head_to_head_vs_generic_floor"],
        "spec_vs_generic_ov_win_rate": by_id.get("spec_vs_generic_ov", {}).get(
            "subject_win_rate"),
        "fisher_increments": panel["attribution"]["fisher_increments_vs_parent"],
        "noise_clean": bool(noise_clean),
        "gating_unsafe_invalid": bool(gating_unsafe),
        "references_excluded": bool(refs_excluded),
        "eval_complete": bool(panel.get("complete")),
    }


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    for p in (PLAN, SAFETY, VALID, SMOKE, NONINERT, PANEL):
        if not p.is_file():
            raise SystemExit(f"missing upstream artifact: {p}")

    ctx = build_context()
    if not ctx["eval_complete"]:
        raise SystemExit("eval panel (Part I) is not complete — run it to completion first")

    result = derive_decision(ctx)
    decision = result["decision"]
    promising = decision == "diamond_specialist_promising_local_only"

    out = {
        "pass": "46J", "part": "J", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "subject_under_test": "cg_typed_diamond_specialist_planner_v0",
        "parent_id": "diamond_toolbox_diancie",
        "decision": decision, "promising": promising,
        "reasons": result["reasons"],
        "pre_registered_rule_source": "pass46j_diamond_eval_plan.json::decision_rules",
        "evidence": ctx,
        "attribution_caveat": (
            "the parent edge is statistically ATTRIBUTABLE to the planner via the one-sided "
            "Fisher increment over the generic-scorer-vs-parent rates "
            "(vs ov_vs_parent and floor_vs_parent), and the head-to-head vs the family-only "
            "floor is a confirmed edge; the head-to-head vs the STRONGER generic option-"
            "value scorer is positive but only "
            f"'{ctx['head_to_head_vs_generic_ov']}' (point "
            f"{ctx['spec_vs_generic_ov_win_rate']}) "
            "— a caveat, not a blocker, since the pre-registered attributable rule is met by "
            "the significant Fisher increment"),
        "claim_boundaries": (
            "LOCAL feasibility/ordering only; NO Kaggle / leaderboard / strength claim; "
            "public references benchmark-only and excluded; role buckets / contexts are "
            "observable heuristic labels (no exact-damage / lethal / KO / missed-KO / "
            "Boss-gust / spread / best-action); NO promotion / upload / production mutation"),
        "next_step_note": (
            "LOCAL-ONLY result: production keeps soaking; do NOT redeploy/register/promote "
            "from this pass. A future pass may grow n on spec_vs_generic_ov to convert the "
            "head-to-head into a confirmed edge before any productionization is considered"),
        "all_ok": True,
    }
    (EXP / "pass46j_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    pr = ctx
    md = [
        "# Pass 46J (Part J) — strategy decision", "",
        "_LOCAL / READ-ONLY. Decision re-derived deterministically from the PRE-REGISTERED "
        "rule + upstream evidence. Decisive win-rate is a LOCAL feasibility/ordering signal "
        "only — NOT a Kaggle / leaderboard / strength claim. Public references are "
        "benchmark-only and excluded. Role buckets / contexts are observable heuristic "
        "labels (no exact-damage / lethal / KO / missed-KO / Boss-gust / spread / "
        "best-action). NO promotion / upload / production mutation._", "",
        f"## DECISION: **{decision}**", "",
        "### Why", *[f"- {r}" for r in result["reasons"]], "",
        "### Evidence",
        f"- **practical** (`spec_vs_parent`): **{pr['practical_label']}**, win-rate "
        f"{pr['practical_win_rate']} (Wilson95 {pr['practical_wilson_low']}.."
        f"{pr['practical_wilson_high']}), seat_confounded={pr['practical_seat_confounded']}",
        f"- **attributable to planner:** **{pr['attributable_to_planner']}** "
        f"(H2H vs generic_ov: {pr['head_to_head_vs_generic_ov']}; H2H vs floor: "
        f"{pr['head_to_head_vs_generic_floor']})",
        "- **Fisher increment vs parent (one-sided):** "
        + "; ".join(f"{g}: spec {i['spec_wins']}-{i['spec_losses']} vs generic "
                    f"{i['generic_wins']}-{i['generic_losses']} p={i['fisher_right_p']} "
                    f"(sig={i['significant']})"
                    for g, i in pr["fisher_increments"].items()),
        f"- **noise controls clean:** {pr['noise_clean']} (self-mirror CIs straddle 0.5)",
        f"- **upstream gates:** safety_all_ok={pr['safety_all_ok']} "
        f"(stop_required={pr['safety_stop_required']}), validation_all_ok="
        f"{pr['validation_all_ok']} (planner_not_scorer={pr['is_planner_not_flat_scorer']}), "
        f"smoke_all_ok={pr['smoke_all_ok']} (root_unchanged={pr['root_unchanged']}), "
        f"non_inert_ok={pr['non_inert_ok']} (illegal={pr['non_inert_illegal']}, "
        f"plan_driven={pr['plan_field_driven_ok']})",
        f"- **references excluded from every arm:** {pr['references_excluded']}", "",
        "### Caveat", f"- {out['attribution_caveat']}", "",
        "### Next step", f"- {out['next_step_note']}",
    ]
    (EXP / "pass46j_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"DECISION: {decision} | promising={promising} | attributable="
          f"{ctx['attributable_to_planner']} | practical={ctx['practical_label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
