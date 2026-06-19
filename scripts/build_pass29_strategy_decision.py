#!/usr/bin/env python3
"""Pass 29 (Part M) — evidence-gated strategy decision. LOCAL / READ-ONLY.

Records the decision from the measured evidence (NOT assumptions). Decision enum:
  needs_more_observability | build_effect_loop_exit_next |
  effect_loop_exit_candidate_built | effect_loop_exit_rejected |
  keep_portfolio_reference | expand_trace_coverage | no_action

The decision is driven by the Part F gate + the Part K/L eval verdict.
Outputs data/experiments/pass29_strategy_decision.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
OUT_JSON = EXP / "pass29_strategy_decision.json"
OUT_MD = EXP / "pass29_strategy_decision.md"


def _load(name):
    p = EXP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    feas = _load("pass29_effect_loop_feasibility.json")
    eval_ = _load("pass29_effect_loop_guard_eval.json")
    backlog = _load("pass29_target_observability.json")
    live = _load("pass29_live_score_status.json")

    gate = feas.get("gate_passes")
    verdict = eval_.get("verdict")

    if gate and verdict == "effect_loop_exit_candidate_built":
        decision = "effect_loop_exit_candidate_built"
        rationale = ("Part F gate passed (optional_loop_with_exit; exit observable "
                     "1958/1958 and declined by the base pilot). The built guard was "
                     "MEASURED in Part K/L to break the loop: worst-case static run "
                     f"{eval_.get('baseline',{}).get('max_static_run_observed')} -> "
                     f"{eval_.get('guard',{}).get('max_static_run_observed')} and all "
                     "guarded games terminated.")
    elif gate and verdict == "effect_loop_exit_rejected":
        decision = "effect_loop_exit_rejected"
        rationale = ("gate passed but the built guard was inert/ineffective in the "
                     "decision replay; rejected rather than promoted.")
    elif not gate:
        decision = "needs_more_observability"
        rationale = "Part F gate did not pass; the exit was not observable/selectable."
    else:
        decision = "needs_more_observability"
        rationale = "no decisive eval evidence."

    out = {
        "pass": "29", "part": "M",
        "decision": decision,
        "decision_enum": [
            "needs_more_observability", "build_effect_loop_exit_next",
            "effect_loop_exit_candidate_built", "effect_loop_exit_rejected",
            "keep_portfolio_reference", "expand_trace_coverage", "no_action"],
        "rationale": rationale,
        "feasibility_gate_passed": gate,
        "eval_verdict": verdict,
        "candidate_built": "effect_loop_exit_guard_v1"
        if decision == "effect_loop_exit_candidate_built" else None,
        "candidate_uploaded": False,
        "candidate_submitted": False,
        "github_pushed": False,
        "root_files_modified": False,
        "keep_portfolio_reference": True,
        "portfolio_reference": (live.get("portfolio_reference") or {}).get("fileName"),
        "next_observability_targets": [
            f for f in (
                "single_target_attack (add opponent_active to snapshot)",
                "spread_bench_target (capture opponent bench + damage events)",
                "supporter_effect_sequencing (link play events to state deltas)")
        ],
        "secondary_decision": "expand_trace_coverage",
        "secondary_decision_note": ("the action-resolution dataset + per-option "
                                    "capture are the cheap ratchets that unblock the "
                                    "remaining backlog fixtures; expand them next."),
        "is_kaggle_leaderboard": False,
        "no_upload": True, "local_only": True,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Strategy Decision (Part M)", "",
         f"## DECISION: `{decision}`", "", rationale, "",
         f"- feasibility_gate_passed: **{gate}**.",
         f"- eval_verdict: **{verdict}**.",
         f"- candidate_built: **{out['candidate_built']}** "
         f"(uploaded: {out['candidate_uploaded']}, submitted: "
         f"{out['candidate_submitted']}, github_pushed: {out['github_pushed']}).",
         f"- keep_portfolio_reference: **{out['keep_portfolio_reference']}** "
         f"(`{out['portfolio_reference']}`).",
         f"- secondary_decision: **{out['secondary_decision']}** — "
         f"{out['secondary_decision_note']}", "",
         "## Next observability targets", ""]
    L += [f"- {t}" for t in out["next_observability_targets"]]
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"DECISION: {decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
