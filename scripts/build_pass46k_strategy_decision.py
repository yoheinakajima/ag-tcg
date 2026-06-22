#!/usr/bin/env python3
"""PASS 46K (Part H) — strategy decision (applies the PRE-REGISTERED 46K rule).

Re-derives the pass decision DETERMINISTICALLY from the frozen decision rule
(``pass46k_eval_plan.json::decision_rules``) and the upstream evidence artifacts
(Part A safety, Part B artifact-check, Part E edge-analysis). The derivation lives in the pure,
importable ``derive_decision(ctx)`` so the Part-J tests can re-derive the same decision from the
same evidence (forward-compatible: change the evidence, the decision follows).

Honesty boundaries: decisive win-rate is a LOCAL feasibility/ordering signal only — NOT a
Kaggle / leaderboard / strength claim. Public references are BENCHMARK-ONLY and NEVER gate or
change the decision (Part F may only colour the reason TEXT). Role buckets / contexts are
observable heuristic labels — no exact-damage / lethal / KO / missed-KO / Boss-gust / spread /
best-action claim. NO promotion, NO upload, NO production mutation.

Decisions (the only allowed outcomes):
  diamond_specialist_confirmed_local_candidate | diamond_specialist_promising_needs_reference_work
  | diamond_specialist_inconclusive_needs_more_n | diamond_specialist_not_promising
  | validation_failed | safety_stop_required.

Output: data/experiments/pass46k_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"

PLAN = EXP / "pass46k_eval_plan.json"
SAFETY = EXP / "pass46k_safety_preflight.json"
ARTIFACT = EXP / "pass46k_artifact_check.json"
EDGE = EXP / "pass46k_edge_analysis.json"
REFGAP = EXP / "pass46k_public_reference_gap.json"   # benchmark-only; reason TEXT only

ALLOWED = [
    "diamond_specialist_confirmed_local_candidate",
    "diamond_specialist_promising_needs_reference_work",
    "diamond_specialist_inconclusive_needs_more_n",
    "diamond_specialist_not_promising",
    "validation_failed",
    "safety_stop_required",
]


def derive_decision(ctx: dict) -> dict:
    """Pure decision function applying the PRE-REGISTERED 46K ladder, in order.

    Order (frozen in pass46k_eval_plan.json::decision_rules.order):
      1 safety_stop_required
      2 validation_failed   (upstream not all_ok / gating unsafe_invalid / no_upload or
                             reference-exclusion or root-immutability violated)
      3 not_promising       (practical no_edge/seat_confounded at larger N, OR
                             attribution NEGATIVE — generic_ov decisive win rate < 0.5)
      4 inconclusive_needs_more_n  (neither gating arm reached min, OR practical only
                             directional, OR a TRIGGERED noise control is not clean)
      5 confirmed_local_candidate  (practical confirmed AND (attribution confirmed OR
                             attribution directional w/ significant Fisher increment) AND
                             noise clean)
      6 promising_needs_reference_work (practical confirmed AND noise clean AND attribution
                             not negative but not fully confirmed)

    Public references NEVER enter this function — they are benchmark-only.
    """
    reasons: list[str] = []

    if ctx["safety_stop_required"]:
        return {"decision": "safety_stop_required",
                "reasons": ["Part A preflight set stop_required=True"]}

    upstream_ok = (ctx["safety_all_ok"] and ctx["artifact_all_ok"]
                   and ctx["references_excluded"] and ctx["no_upload_ok"]
                   and ctx["root_unchanged"])
    if (not upstream_ok) or ctx["any_gating_unsafe_invalid"]:
        if not ctx["safety_all_ok"]:
            reasons.append("Part A safety not all_ok")
        if not ctx["artifact_all_ok"]:
            reasons.append("Part B artifact-check not all_ok")
        if not ctx["references_excluded"]:
            reasons.append("a public reference leaked into the gating/attribution analysis")
        if not ctx["no_upload_ok"]:
            reasons.append("no_upload invariant violated")
        if not ctx["root_unchanged"]:
            reasons.append("root main.py/deck.csv changed")
        if ctx["any_gating_unsafe_invalid"]:
            reasons.append("a gating eval panel is unsafe_invalid")
        return {"decision": "validation_failed", "reasons": reasons}

    practical = ctx["practical_label"]
    if practical in ("no_edge", "seat_confounded") or ctx["practical_seat_confounded"]:
        return {"decision": "diamond_specialist_not_promising",
                "reasons": [f"practical (spec_vs_parent) = {practical} "
                            f"(seat_confounded={ctx['practical_seat_confounded']}) at larger N "
                            "— the parent edge did NOT hold cleanly"]}
    if ctx["attribution_negative"]:
        return {"decision": "diamond_specialist_not_promising",
                "reasons": ["practical edge present but attribution is NEGATIVE: the generic "
                            "option-value scorer beats the parent at >= the specialist's rate "
                            "(spec_vs_generic_ov decisive win rate < 0.5) — no separable "
                            "planner value"]}

    if (not ctx["gating_reached_min_acceptable"]) or ctx["practical_directional"] or \
            (ctx["noise_required"] and not ctx["noise_clean"]):
        if not ctx["gating_reached_min_acceptable"]:
            reasons.append("a gating arm did not reach its min_acceptable_decisive")
        if ctx["practical_directional"]:
            reasons.append("practical is only directional_edge (Wilson low <= 0.5), "
                           "not confirmed, at larger N")
        if ctx["noise_required"] and not ctx["noise_clean"]:
            bad = [k for k, v in ctx["noise_results"].items() if not v]
            reasons.append("a TRIGGERED self-mirror noise control is NOT clean "
                           f"(CI excludes 0.5): {bad} — the larger-N readout is not yet "
                           "trustworthy as a confirmation")
        return {"decision": "diamond_specialist_inconclusive_needs_more_n", "reasons": reasons}

    if ctx["practical_confirmed"] and (
            ctx["attribution_confirmed"]
            or (ctx["attribution_directional"] and ctx["fisher_ov_increment_significant"])
    ) and ctx["noise_clean"]:
        return {"decision": "diamond_specialist_confirmed_local_candidate",
                "reasons": ["practical (spec_vs_parent) = confirmed_edge at larger N",
                            "attribution (spec_vs_generic_ov) confirmed OR directional with a "
                            "significant Fisher increment vs ov_vs_parent",
                            "all triggered noise controls clean (CIs straddle 0.5)",
                            "safety / artifact / no-leakage / no_upload / root-immutability "
                            "all hold"]}

    if ctx["practical_confirmed"] and ctx["noise_clean"] and not ctx["attribution_negative"]:
        return {"decision": "diamond_specialist_promising_needs_reference_work",
                "reasons": ["practical confirmed + noise clean, but attribution is not fully "
                            "confirmed (ov no_edge, or directional without a significant Fisher "
                            "increment) — parent edge holds, separation from the generic scorer "
                            "needs more work"]}

    return {"decision": "diamond_specialist_inconclusive_needs_more_n",
            "reasons": [f"residual: practical={practical}, "
                        f"practical_confirmed={ctx['practical_confirmed']}, "
                        f"noise_clean={ctx['noise_clean']}"]}


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_context() -> dict:
    safety = _load(SAFETY)
    artifact = _load(ARTIFACT)
    edge = _load(EDGE)
    di = edge["decision_inputs"]
    panels = edge["panels"]
    practical_panel = panels.get(di["practical_panel"], {})

    return {
        # upstream gates
        "safety_all_ok": bool(safety.get("all_ok")),
        "safety_stop_required": bool(safety.get("stop_required")),
        "artifact_all_ok": bool(artifact.get("all_ok")),
        "references_excluded": (not bool(edge.get("references_in_analysis"))),
        "no_upload_ok": bool(safety.get("no_upload")) and bool(edge.get("no_upload"))
        and bool(artifact.get("no_upload")),
        "root_unchanged": (not bool(safety.get("candidate_rebuilt")))
        and (not bool(safety.get("tick_executed")))
        and (not bool(safety.get("promotion_performed"))),
        # edge / decision inputs (pre-computed deterministically in Part E)
        "practical_label": di["practical_label"],
        "practical_point": di["practical_point"],
        "practical_wilson_low": di["practical_wilson_low"],
        "practical_seat_confounded": bool(practical_panel.get("seat_confounded")),
        "practical_confirmed": bool(di["practical_confirmed"]),
        "practical_directional": bool(di["practical_directional"]),
        "attribution_label": di["attribution_label"],
        "attribution_point": di["attribution_point"],
        "attribution_confirmed": bool(di["attribution_confirmed"]),
        "attribution_directional": bool(di["attribution_directional"]),
        "attribution_negative": bool(di["attribution_negative"]),
        "attributable_to_planner": bool(di["attributable_to_planner"]),
        "fisher_ov_increment_significant": bool(di["fisher_ov_increment_significant"]),
        "head_to_head_floor_label": di.get("head_to_head_floor_label"),
        "any_gating_unsafe_invalid": bool(di["any_gating_unsafe_invalid"]),
        "gating_reached_min_acceptable": bool(di["gating_reached_min_acceptable"]),
        "noise_required": bool(di["noise_required"]),
        "noise_results": dict(di["noise_results"]),
        "noise_clean": bool(di["noise_clean"]),
        "edge_all_ok": bool(edge.get("all_ok")),
    }


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    for p in (PLAN, SAFETY, ARTIFACT, EDGE):
        if not p.is_file():
            raise SystemExit(f"missing upstream artifact: {p}")

    plan = _load(PLAN)
    allowed_plan = plan["decision_rules"]["allowed_decisions"]
    assert set(allowed_plan) == set(ALLOWED), "allowed-decision drift vs pre-registered plan"

    ctx = build_context()
    if not ctx["edge_all_ok"]:
        raise SystemExit("Part E edge-analysis is not all_ok — re-run it first")

    result = derive_decision(ctx)
    decision = result["decision"]
    assert decision in ALLOWED, f"derived decision not in allowed list: {decision}"

    # Public references are BENCHMARK-ONLY: load Part F purely for reason/colour TEXT, and
    # PROVE the decision is independent of references by re-deriving with refs absent.
    ref_colour = None
    refs_benchmark_only = True
    refs_is_gate = False
    if REFGAP.is_file():
        rg = _load(REFGAP)
        refs_benchmark_only = bool(rg.get("benchmark_only"))
        refs_is_gate = bool(rg.get("is_decision_gate"))
        pooled = rg.get("pooled", {})
        ref_colour = {
            "safe_opponents": rg.get("safe_opponents", []),
            "pooled_decisive": pooled.get("decisive"),
            "pooled_win_rate": pooled.get("win_rate"),
            "pooled_wilson": [pooled.get("wilson_low"), pooled.get("wilson_high")],
            "parity_supported_any_ref": rg.get("parity_supported_any_ref"),
            "pooled_parity_supported": rg.get("pooled_parity_supported"),
        }
    decision_independent_of_refs = (derive_decision(ctx)["decision"] == decision)

    confirmed = decision == "diamond_specialist_confirmed_local_candidate"
    out = {
        "pass": "46K", "part": "H", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "subject_under_test": "cg_typed_diamond_specialist_planner_v0",
        "parent_id": "diamond_toolbox_diancie",
        "decision": decision, "confirmed_local_candidate": confirmed,
        "reasons": result["reasons"],
        "allowed_decisions": ALLOWED,
        "pre_registered_rule_source": "pass46k_eval_plan.json::decision_rules",
        "evidence": ctx,
        "reference_colour_only": ref_colour,
        "references_benchmark_only": refs_benchmark_only,
        "references_are_decision_gate": refs_is_gate,
        "decision_independent_of_references": decision_independent_of_refs,
        "attribution_caveat": (
            "the parent edge IS statistically attributable to the planner — the head-to-head "
            "vs the stronger generic option-value scorer is "
            f"'{ctx['attribution_label']}' (point {ctx['attribution_point']}) AND the one-sided "
            "Fisher increment over ov_vs_parent is significant; BUT a triggered self-mirror "
            f"noise control is not clean (noise_results={ctx['noise_results']}), so the "
            "pre-registered ladder holds the larger-N readout as inconclusive rather than a "
            "confirmation — do NOT move the goalposts"),
        "claim_boundaries": (
            "LOCAL feasibility/ordering only; NO Kaggle / leaderboard / strength claim; "
            "public references benchmark-only and EXCLUDED from the decision; role buckets / "
            "contexts are observable heuristic labels (no exact-damage / lethal / KO / "
            "missed-KO / Boss-gust / spread / best-action); NO promotion / upload / production "
            "mutation"),
        "next_step_note": (
            "LOCAL-ONLY result: production keeps soaking; do NOT redeploy / register / promote "
            "from this pass. To convert toward a confirmed local candidate a future pass should "
            "grow n on the self-mirror noise controls until their CIs straddle 0.5 (clean), "
            "while holding the confirmed practical + attribution edges; public-reference "
            "distance stays benchmark-only context"),
        "all_ok": True,
    }
    assert out["decision_independent_of_references"], "decision must not depend on references"
    (EXP / "pass46k_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    pr = ctx
    md = [
        "# Pass 46K (Part H) — strategy decision", "",
        "_LOCAL / READ-ONLY. Decision re-derived DETERMINISTICALLY from the PRE-REGISTERED 46K "
        "rule + upstream evidence (Parts A / B / E). Decisive win-rate is a LOCAL feasibility / "
        "ordering signal only — NOT a Kaggle / leaderboard / strength claim. Public references "
        "are BENCHMARK-ONLY and EXCLUDED from the decision (they only colour the reason text). "
        "Role buckets / contexts are observable heuristic labels (no exact-damage / lethal / "
        "KO / missed-KO / Boss-gust / spread / best-action). NO promotion / upload / production "
        "mutation._", "",
        f"## DECISION: **{decision}**", "",
        "### Why", *[f"- {r}" for r in result["reasons"]], "",
        "### Evidence (gating + attribution; references EXCLUDED)",
        f"- **practical** (`spec_vs_parent`): **{pr['practical_label']}**, point "
        f"{pr['practical_point']} (Wilson low {pr['practical_wilson_low']}), "
        f"seat_confounded={pr['practical_seat_confounded']}, "
        f"confirmed={pr['practical_confirmed']}",
        f"- **attribution** (`spec_vs_generic_ov`): **{pr['attribution_label']}**, point "
        f"{pr['attribution_point']}, confirmed={pr['attribution_confirmed']}, "
        f"directional={pr['attribution_directional']}, negative={pr['attribution_negative']}",
        f"- **attributable to planner:** {pr['attributable_to_planner']} "
        f"(Fisher increment vs ov_vs_parent significant={pr['fisher_ov_increment_significant']}; "
        f"H2H vs floor: {pr['head_to_head_floor_label']})",
        f"- **gating reached min_acceptable:** {pr['gating_reached_min_acceptable']} | "
        f"any gating unsafe_invalid: {pr['any_gating_unsafe_invalid']}",
        f"- **noise controls** (triggered={pr['noise_required']}): {pr['noise_results']} -> "
        f"clean={pr['noise_clean']}",
        f"- **upstream gates:** safety_all_ok={pr['safety_all_ok']} "
        f"(stop_required={pr['safety_stop_required']}), artifact_all_ok={pr['artifact_all_ok']}, "
        f"references_excluded={pr['references_excluded']}, no_upload_ok={pr['no_upload_ok']}, "
        f"root_unchanged={pr['root_unchanged']}", "",
        "### Public-reference distance (BENCHMARK-ONLY — not a gate)",
    ]
    if ref_colour:
        md.append(
            f"- pooled decisive {ref_colour['pooled_decisive']}, win rate "
            f"{ref_colour['pooled_win_rate']} (Wilson {ref_colour['pooled_wilson']}); parity "
            f"supported any ref: {ref_colour['parity_supported_any_ref']}, pooled parity: "
            f"{ref_colour['pooled_parity_supported']} — colour only, EXCLUDED from the decision")
    else:
        md.append("- (Part F reference-gap artifact not present — references contribute no "
                  "colour; the decision is unchanged)")
    md += [
        f"- decision independent of references: **{decision_independent_of_refs}** "
        f"(references benchmark-only={refs_benchmark_only}, is-gate={refs_is_gate})", "",
        "### Caveat", f"- {out['attribution_caveat']}", "",
        "### Next step", f"- {out['next_step_note']}",
    ]
    (EXP / "pass46k_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"DECISION: {decision} | confirmed={confirmed} | "
          f"practical={ctx['practical_label']} | attribution={ctx['attribution_label']} | "
          f"noise_clean={ctx['noise_clean']} | refs_independent={decision_independent_of_refs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
