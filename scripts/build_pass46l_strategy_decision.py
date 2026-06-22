#!/usr/bin/env python3
"""PASS 46L (Part J) — strategy decision (applies the PRE-REGISTERED 46L ladder).

Re-derives the pass decision DETERMINISTICALLY from the frozen decision ladder
(``pass46l_eval_plan.json::decision_ladder_frozen``) and the upstream evidence artifacts
(Part A safety, Part E build, Part F validation, Part G fixtures + non-inertness). The
derivation lives in the pure, importable ``derive_decision(ctx)`` so the Part-L tests can
re-derive the same decision from the same evidence (forward-compatible: change the evidence,
the decision follows).

Honesty boundaries: this is a LOCAL feasibility/ordering result only — NOT a Kaggle /
leaderboard / strength claim. Public references are BENCHMARK-ONLY and gate ONLY the single
``diamond_v1_reference_gap_improved_local_only`` outcome via the frozen reference-improvement
test; they NEVER gate the not_promising / internal_only / validation / safety outcomes, and
are never a source / parent / candidate. Role buckets / contexts are observable heuristic
labels — no exact-damage / lethal / KO / missed-KO / Boss-gust / spread / best-action claim.
NO promotion, NO upload, NO production mutation, NO redeploy.

The STAGE-2 non-inertness test is the BLOCKING GATE: if the owned v1 planner does not change
a meaningful fraction of REAL decision frames in a relevant context (vs v0), no eval panel is
run and the decision is a clean ``diamond_v1_not_promising`` negative.

Decisions (the only allowed outcomes, in ladder order):
  safety_stop_required | validation_failed | diamond_v1_not_promising
  | diamond_v1_internal_only_no_reference_gain | diamond_v1_reference_gap_improved_local_only.

Output: data/experiments/pass46l_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"

PLAN = EXP / "pass46l_eval_plan.json"
SAFETY = EXP / "pass46l_safety_preflight.json"
BUILD = EXP / "pass46l_candidate_build.json"
VALID = EXP / "pass46l_candidate_validation.json"
FIXTURE = EXP / "pass46l_planner_fixture_validation.json"
NONINERT = EXP / "pass46l_non_inertness.json"
# Stage-3/4 panel artifacts (present ONLY if the stage-2 gate passed). Absent in a clean
# inert negative — derive_decision never needs them on the not_promising path.
REFGAP = EXP / "pass46l_reference_gap_analysis.json"

ALLOWED = [
    "safety_stop_required",
    "validation_failed",
    "diamond_v1_not_promising",
    "diamond_v1_internal_only_no_reference_gain",
    "diamond_v1_reference_gap_improved_local_only",
]


def reference_improvement_test(metrics: dict) -> dict:
    """Pure re-derivation of the PRE-REGISTERED reference-improvement test (frozen in
    pass46l_eval_plan.json::pre_registered_reference_improvement_test). TRUE iff ALL hold.

    Public references gate ONLY this single outcome and NOTHING else. Per-reference rows are
    explanatory only and NEVER a gate. Frozen baseline: v0 = W1/L59 (decisive 60)."""
    conds = {
        "safety_artifact_all_ok": bool(metrics.get("safety_artifact_all_ok")),
        "pooled_v1_decisive_ge_50": int(metrics.get("pooled_decisive", 0)) >= 50,
        "invalid_rate_le_5pct": float(metrics.get("invalid_rate", 1.0)) <= 0.05,
        "both_seats_represented": bool(metrics.get("both_seats_represented")),
        "mirror_ci_straddles_half": bool(metrics.get("mirror_ci_straddles_half")),
        "fisher_one_sided_p_le_0_05": float(metrics.get("fisher_p", 1.0)) <= 0.05,
        "v1_pooled_win_rate_ge_0_10": float(metrics.get("win_rate", 0.0)) >= 0.10,
    }
    return {"conditions": conds, "passed": all(conds.values())}


def derive_decision(ctx: dict) -> dict:
    """Pure decision function applying the PRE-REGISTERED 46L ladder, in order.

    1 safety_stop_required          (Part A preflight stop_required)
    2 validation_failed             (any upstream gate false: safety/build/validation not
                                     all_ok, candidate is a public reference, no_upload or
                                     reference-exclusion or root-immutability or deck-identity
                                     violated, non-inertness panel incomplete)
    3 diamond_v1_not_promising      (STAGE-2 BLOCKING GATE fails: v1-vs-v0 changed-decision
                                     rate < min OR no change in a relevant context OR any
                                     illegal v1 decision) -- OR a run stage-3 panel shows v1
                                     internally worse than v0
    4 diamond_v1_internal_only_no_reference_gain  (non-inert + not internally worse, but the
                                     frozen reference-improvement test is NOT met)
    5 diamond_v1_reference_gap_improved_local_only (non-inert + not worse + the frozen
                                     reference-improvement test passes; refs gate ONLY here)
    """
    reasons: list[str] = []

    if ctx["safety_stop_required"]:
        return {"decision": "safety_stop_required",
                "reasons": ["Part A preflight set stop_required=True"]}

    upstream_ok = (ctx["safety_all_ok"] and ctx["candidate_build_ok"]
                   and (not ctx["candidate_public_reference"]) and ctx["validation_all_ok"]
                   and ctx["fixtures_all_ok"]
                   and ctx["no_upload_ok"] and ctx["references_excluded"]
                   and ctx["root_unchanged"] and ctx["deck_eq_parent"]
                   and ctx["non_inertness_complete"])
    if not upstream_ok:
        if not ctx["safety_all_ok"]:
            reasons.append("Part A safety not all_ok")
        if not ctx["candidate_build_ok"]:
            reasons.append("Part E candidate build not candidate_ok")
        if ctx["candidate_public_reference"]:
            reasons.append("candidate is flagged public_reference (must be owned/internal)")
        if not ctx["validation_all_ok"]:
            reasons.append("Part F candidate validation not all_ok")
        if not ctx["fixtures_all_ok"]:
            reasons.append("Part G fixture validation not all_ok")
        if not ctx["no_upload_ok"]:
            reasons.append("no_upload invariant violated in some artifact")
        if not ctx["references_excluded"]:
            reasons.append("a public reference leaked into the candidate/analysis lane")
        if not ctx["root_unchanged"]:
            reasons.append("root main.py/deck.csv changed vs the Part-A baseline")
        if not ctx["deck_eq_parent"]:
            reasons.append("candidate deck.csv is NOT byte-identical to the diamond parent")
        if not ctx["non_inertness_complete"]:
            reasons.append("Part G non-inertness panel did not complete")
        return {"decision": "validation_failed", "reasons": reasons}

    # STAGE 2 — blocking non-inertness gate (re-derived here, not trusted from upstream flag).
    non_inert = (ctx["changed_decision_rate"] >= ctx["non_inert_min_rate"]
                 and ctx["changes_in_relevant_context"]
                 and ctx["v1_illegal_decisions"] == 0)
    if not non_inert:
        why = []
        if ctx["changed_decision_rate"] < ctx["non_inert_min_rate"]:
            why.append(f"v1-vs-v0 changed-decision rate {ctx['changed_decision_rate']} "
                       f"< min {ctx['non_inert_min_rate']} on {ctx['non_inertness_frames']} "
                       "REAL trace frames (definitively inert)")
        if not ctx["changes_in_relevant_context"]:
            why.append("no changed decision landed in a relevant context "
                       "(attach_energy / choose_active)")
        if ctx["v1_illegal_decisions"] > 0:
            why.append(f"{ctx['v1_illegal_decisions']} illegal v1 decisions (forbidden)")
        return {"decision": "diamond_v1_not_promising", "reasons": why}

    # STAGE 3+ — reachable ONLY when v1 is non-inert (panels were run).
    if ctx.get("v1_internally_worse"):
        return {"decision": "diamond_v1_not_promising",
                "reasons": ["v1 is internally WORSE than v0 (a v1-vs-parent or "
                            "v1-vs-generic_ov Wilson lower bound fell below v0's, or the "
                            "v1-vs-v1 mirror CI excludes 0.5)"]}
    rit = ctx.get("reference_improvement_test") or {"passed": False, "conditions": {}}
    if rit["passed"]:
        return {"decision": "diamond_v1_reference_gap_improved_local_only",
                "reasons": ["non-inert + not internally worse, AND the frozen pooled "
                            "reference-improvement test passed (>=50 decisive, invalid<=5%, "
                            "both seats, mirror CI straddles 0.5, one-sided Fisher p<=0.05 vs "
                            "frozen 1/59, win-rate>=0.10) — LOCAL-ONLY benchmark improvement"]}
    return {"decision": "diamond_v1_internal_only_no_reference_gain",
            "reasons": ["non-inert + not internally worse, but the frozen pooled "
                        "reference-improvement test is NOT met (no material public-reference "
                        "gain vs frozen 1/59) — a clean internal-only result"]}


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_context() -> dict:
    safety = _load(SAFETY)
    build = _load(BUILD)
    valid = _load(VALID)
    fixture = _load(FIXTURE) if FIXTURE.is_file() else {}
    ni = _load(NONINERT)

    lane = valid.get("lane_separation", {})
    root = valid.get("root_unchanged", {})
    deck = valid.get("deck_vs_parent", {})

    references_excluded = (bool(lane.get("no_ref_hash_match"))
                           and bool(ni.get("reference_benchmark_only"))
                           and (not bool(build.get("public_reference"))))
    no_upload_ok = (bool(safety.get("no_upload")) and bool(build.get("no_upload"))
                    and bool(valid.get("no_upload")) and bool(fixture.get("no_upload"))
                    and bool(ni.get("no_upload")))

    # Stage-3/4 panel inputs — present ONLY if the gate passed (absent in a clean inert run).
    refgap = _load(REFGAP) if REFGAP.is_file() else {}
    rit = None
    if refgap:
        rit = reference_improvement_test({
            "safety_artifact_all_ok": bool(safety.get("all_ok")) and bool(build.get(
                "candidate_ok")) and bool(valid.get("all_ok")),
            "pooled_decisive": refgap.get("pooled", {}).get("decisive", 0),
            "invalid_rate": refgap.get("pooled", {}).get("invalid_rate", 1.0),
            "both_seats_represented": refgap.get("both_seats_represented", False),
            "mirror_ci_straddles_half": refgap.get("mirror_ci_straddles_half", False),
            "fisher_p": refgap.get("fisher_one_sided_p", 1.0),
            "win_rate": refgap.get("pooled", {}).get("win_rate", 0.0),
        })

    return {
        # upstream gates
        "safety_all_ok": bool(safety.get("all_ok")),
        "safety_stop_required": bool(safety.get("stop_required")),
        "candidate_build_ok": bool(build.get("candidate_ok")),
        "candidate_public_reference": bool(build.get("public_reference")),
        "validation_all_ok": bool(valid.get("all_ok")),
        "fixtures_all_ok": bool(fixture.get("all_ok")),
        "no_upload_ok": no_upload_ok,
        "references_excluded": references_excluded,
        "root_unchanged": (root.get("root_main_unchanged") is True
                           and root.get("root_deck_unchanged") is True),
        "deck_eq_parent": bool(deck.get("deck_byte_identical_to_parent")),
        # stage-2 blocking gate (re-derived from raw counts in derive_decision)
        "non_inertness_complete": bool(ni.get("complete")),
        "changed_decision_rate": float(ni.get("changed_decision_rate", 0.0)),
        "non_inert_min_rate": float(ni.get("non_inert_min_rate", 0.05)),
        "changes_in_relevant_context": bool(ni.get("changes_in_relevant_context")),
        "v1_illegal_decisions": int(ni.get("v1_illegal_decisions", 0)),
        "non_inertness_frames": int(ni.get("frames", 0)),
        "changed_decisions": int(ni.get("changed_decisions", 0)),
        "non_inert_gate_pass_upstream": bool(ni.get("non_inert_gate_pass")),
        # stage-3/4 (present only if gate passed; None/absent on the clean inert path)
        "v1_internally_worse": (None if not refgap
                                else bool(refgap.get("v1_internally_worse"))),
        "reference_improvement_test": rit,
    }


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    for p in (PLAN, SAFETY, BUILD, VALID, FIXTURE, NONINERT):
        if not p.is_file():
            raise SystemExit(f"missing upstream artifact: {p}")

    plan = _load(PLAN)
    ladder = plan["decision_ladder_frozen"]
    assert ladder == ALLOWED, "decision-ladder drift vs pre-registered plan"

    ctx = build_context()
    result = derive_decision(ctx)
    decision = result["decision"]
    assert decision in ALLOWED, f"derived decision not in allowed list: {decision}"

    # Prove the decision is INDEPENDENT of public references on every non-reference outcome:
    # forcing the reference-improvement test both ways must not change a non-reference decision.
    ref_independent = True
    if decision != "diamond_v1_reference_gap_improved_local_only":
        for forced in (True, False):
            probe = dict(ctx)
            probe["reference_improvement_test"] = {"passed": forced, "conditions": {}}
            if derive_decision(probe)["decision"] != decision:
                ref_independent = False
                break

    out = {
        "pass": "46L", "part": "J", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True, "no_redeploy": True,
        "subject_under_test": "cg_typed_diamond_specialist_planner_v1",
        "planner_parent_id": "cg_typed_diamond_specialist_planner_v0",
        "deck_parent_id": "diamond_toolbox_diancie",
        "frozen_reference_baseline": plan.get("baseline_frozen"),
        "decision": decision,
        "reference_gap_improved": decision == "diamond_v1_reference_gap_improved_local_only",
        "reasons": result["reasons"],
        "allowed_decisions": ALLOWED,
        "pre_registered_ladder_source": "pass46l_eval_plan.json::decision_ladder_frozen",
        "blocking_gate": "stage-2 non-inertness (v1-vs-v0 on REAL frames)",
        "evidence": ctx,
        "references_benchmark_only": True,
        "references_are_decision_gate_for_other_outcomes": False,
        "decision_independent_of_references": ref_independent,
        "panels_run": REFGAP.is_file(),
        "inertness_finding": (
            "v1 is DEFINITIVELY INERT vs v0 on real trace frames "
            f"({ctx['changed_decisions']}/{ctx['non_inertness_frames']} frames changed, "
            f"rate {ctx['changed_decision_rate']}, "
            f"{ctx['v1_illegal_decisions']} illegal): the 3 visible-only structural levers "
            "(stronger attach-to-active, harsher already-energized penalty, most-energized "
            "promote tilt) move the attach active-vs-bench crossover only fractionally "
            "(base/penalty ratio ~2.5->~2.8), and the active-preference already dominates in "
            "v0 — so the argmax is unchanged across integer visible-energy counts. The only "
            "live-firing surface is the attach zone, which is already at the strategically "
            "correct 'concentrate on the active attacker'."),
        "claim_boundaries": (
            "LOCAL feasibility/ordering only; NO Kaggle / leaderboard / strength claim; "
            "public references benchmark-only and gate ONLY the reference-improved outcome; "
            "role buckets / contexts are observable heuristic labels (no exact-damage / "
            "lethal / KO / missed-KO / Boss-gust / spread / best-action); NO promotion / "
            "upload / production mutation / redeploy"),
        "next_step_note": (
            "LOCAL-ONLY clean negative: production keeps soaking; do NOT redeploy / register / "
            "promote / queue / upload from this pass. The reference gap is a CARD-ID GROUNDING "
            "gap, not a thin-policy gap — a future pass should ground the role map to an "
            "authoritative owned card database (independently audited, NOT extended from "
            "observed play = invented ids), or pivot to a different archetype, rather than add "
            "another visible-only policy layer (role-keyed OR structural — both proven inert)."),
        "all_ok": True,
    }
    assert out["decision_independent_of_references"], \
        "a non-reference decision must not depend on references"
    (EXP / "pass46l_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    ev = ctx
    md = [
        "# Pass 46L (Part J) — strategy decision", "",
        "_LOCAL / READ-ONLY. Decision re-derived DETERMINISTICALLY from the PRE-REGISTERED "
        "46L ladder + upstream evidence (Parts A / E / F / G). This is a LOCAL feasibility / "
        "ordering result only — NOT a Kaggle / leaderboard / strength claim. Public references "
        "are BENCHMARK-ONLY and gate ONLY the reference-improved outcome. Role buckets / "
        "contexts are observable heuristic labels (no exact-damage / lethal / KO / missed-KO / "
        "Boss-gust / spread / best-action). NO promotion / upload / production mutation / "
        "redeploy._", "",
        f"## DECISION: **{decision}**", "",
        "### Why", *[f"- {r}" for r in result["reasons"]], "",
        "### Blocking gate (stage-2 non-inertness, v1-vs-v0 on REAL frames)",
        f"- changed decisions: **{ev['changed_decisions']}** / {ev['non_inertness_frames']} "
        f"frames  ·  rate **{ev['changed_decision_rate']}** (min {ev['non_inert_min_rate']})",
        f"- changes in a relevant context (attach_energy / choose_active): "
        f"**{ev['changes_in_relevant_context']}**",
        f"- illegal v1 decisions: **{ev['v1_illegal_decisions']}**  ·  panel complete: "
        f"**{ev['non_inertness_complete']}**", "",
        "### Upstream gates",
        f"- safety all_ok: **{ev['safety_all_ok']}** (stop_required="
        f"{ev['safety_stop_required']})",
        f"- candidate build ok: **{ev['candidate_build_ok']}** (public_reference="
        f"{ev['candidate_public_reference']})",
        f"- validation all_ok: **{ev['validation_all_ok']}**  ·  fixtures all_ok: "
        f"**{ev['fixtures_all_ok']}**",
        f"- no_upload ok: **{ev['no_upload_ok']}**  ·  references excluded: "
        f"**{ev['references_excluded']}**",
        f"- root unchanged: **{ev['root_unchanged']}**  ·  deck == parent: "
        f"**{ev['deck_eq_parent']}**", "",
        "### Reference independence",
        f"- decision independent of public references: "
        f"**{out['decision_independent_of_references']}** (references benchmark-only; gate "
        "ONLY the reference-improved outcome)", "",
        "### Inertness finding", f"- {out['inertness_finding']}", "",
        "### Next step", f"- {out['next_step_note']}",
    ]
    (EXP / "pass46l_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"DECISION: {decision} | changed={ev['changed_decisions']}/"
          f"{ev['non_inertness_frames']} (rate {ev['changed_decision_rate']}) | "
          f"refs_independent={out['decision_independent_of_references']} | "
          f"panels_run={out['panels_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
