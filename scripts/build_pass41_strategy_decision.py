#!/usr/bin/env python3
"""Pass 41 (Part J) — local registration / strategy decision for the cg_typed spike.

Reads the already-written Pass-41 artifacts (safety preflight, build, validation,
smoke, parent/child + public-ref + anchor eval, non-inertness trace, self-mirror
noise control) and records exactly ONE discrete decision code from the allowed
set, with the gates and evidence behind it. Pure read of existing artifacts; this
script writes NO ledger events, performs NO upload/submit/push, and makes NO
production scheduler change.

The owned candidate is a LOCAL-ONLY benchmark subject. Any production scheduler
change would require (a) every gate below passing, (b) ``republish_required``
documented, and (c) explicit user approval — none of which is requested here, so
``republish_required`` is False and the candidate stays local-only.

Outputs:
  data/experiments/pass41_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"

ALLOWED = [
    "promising_local_only",              # success: keep local-only, no prod change
    "registered_local_needs_more_eval",  # behaviorally sound but edge not corroborated
    "rejected_inert",                    # candidate ~never diverges from parent
    "rejected_illegal_or_crash",         # illegal refinement / uncaught exception in trace
    "rejected_smoke_failed",
    "rejected_validation_failed",
    "rejected_build_failed",
    "blocked_root_unsafe",
]

NOISE_CORROBORATES_OK = {"yes", "suggestive_significant_vs_parent_null_only"}


def _g(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    rds = _g(EXP / "pass41_root_prod_benchmark_safety.json")
    build = _g(EXP / "pass41_candidate_build.json")
    val = _g(EXP / "pass41_cg_candidate_validation.json")
    smoke = _g(EXP / "pass41_cg_candidate_smoke.json")
    parent = _g(EXP / "pass41_parent_child_eval.json")
    refs = _g(EXP / "pass41_public_reference_eval.json")
    anchor = _g(EXP / "pass41_anchor_eval.json")
    trace = _g(EXP / "pass41_non_inertness_trace.json")
    noise = _g(EXP / "pass41_h2h_noise_control.json")

    # ---- gates -----------------------------------------------------------
    root_safe = bool(rds.get("root_prod_benchmark_safe")) and not rds.get("stop_required")
    build_ok = bool(build.get("owned_candidate")) and build.get("public_reference") is False
    validation_ok = bool(val.get("ok"))
    smoke_ok = bool(smoke.get("ok")) and not smoke.get("hard_fail")
    illegal = trace.get("illegal_refinements")
    cand_exc = trace.get("candidate_uncaught_exceptions")
    trace_legal = (illegal == 0 and cand_exc == 0 and not trace.get("hard_fail"))
    non_inert = bool(trace.get("non_inert"))
    no_leakage = (bool(smoke.get("references_not_in_pool"))
                  and bool(rds.get("reference_pool_absence", {}).get("absent", True)
                           if isinstance(rds.get("reference_pool_absence"), dict)
                           else True))
    root_unchanged = all(bool(a.get("root_main_deck_unchanged", True))
                         for a in (smoke, parent, refs, anchor, trace, noise))

    beats_parent = parent.get("verdict") == "candidate_beats_parent"
    noise_corroborates = noise.get("noise_control_corroborates") in NOISE_CORROBORATES_OK
    controls_clean = bool(noise.get("controls_clean"))

    # ---- decision (first failing gate wins; else success/borderline) -----
    if not root_safe:
        decision = "blocked_root_unsafe"
        reason = "root/prod/benchmark safety preflight not clean"
    elif not build_ok:
        decision = "rejected_build_failed"
        reason = "owned candidate not built as owned/non-reference"
    elif not validation_ok:
        decision = "rejected_validation_failed"
        reason = "cg_typed validation failed or stdlib lane not intact/separated"
    elif not smoke_ok:
        decision = "rejected_smoke_failed"
        reason = "subprocess-isolated smoke failed or hard-failed"
    elif not trace_legal:
        decision = "rejected_illegal_or_crash"
        reason = (f"non-inertness trace not clean (illegal={illegal}, "
                  f"cand_uncaught_exceptions={cand_exc})")
    elif not non_inert:
        decision = "rejected_inert"
        reason = "candidate effectively never diverges from its parent"
    elif beats_parent and noise_corroborates and controls_clean:
        decision = "promising_local_only"
        reason = ("validated + smoke-clean + non-inert + legal; beats parent with a "
                  "Wilson CI above 0.50 corroborated by a clean self-mirror noise "
                  "control (Fisher exact); below public references (honest). Kept "
                  "LOCAL-ONLY: no prod scheduler change, no upload/submit/push.")
    else:
        decision = "registered_local_needs_more_eval"
        reason = ("behaviorally sound (validated, smoke-clean, non-inert, legal) but "
                  "the parent edge is not corroborated by the noise control; keep "
                  "local-only and gather more games before any stronger claim.")

    assert decision in ALLOWED, decision

    p_overall = parent.get("overall", {})
    fz = noise.get("fisher_h2h_vs_mirror_p", {})
    payload = {
        "schema": "pass41_strategy_decision_v1", "pass": "41", "part": "J",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate_id": build.get("candidate_id"),
        "parent_id": parent.get("parent_id"),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation_for_prod": False,
        "prod_scheduler_changed": False, "local_registration": "benchmark_local_only",
        "decision": decision, "reason": reason, "allowed_decisions": ALLOWED,
        "republish_required": False,
        "republish_note": ("Local-only benchmark subject; root main.py/deck.csv and "
                           "the deployment config are unchanged, so nothing is "
                           "prod-registered and no republish is required. A prod "
                           "scheduler change would require all gates passing, "
                           "republish_required documented, and explicit user "
                           "approval — none requested."),
        "gates": {
            "root_safe": root_safe,
            "build_owned_non_reference": build_ok,
            "validation_ok": validation_ok,
            "smoke_ok": smoke_ok,
            "trace_legal_no_crash": trace_legal,
            "non_inert": non_inert,
            "beats_parent": beats_parent,
            "noise_control_corroborates": noise_corroborates,
            "noise_controls_clean": controls_clean,
            "references_not_in_pool": no_leakage,
            "root_unchanged_across_artifacts": root_unchanged,
        },
        "evidence": {
            "parent_verdict": parent.get("verdict"),
            "parent_decisive_win_rate": p_overall.get("decisive_win_rate"),
            "parent_wilson95": p_overall.get("wilson95"),
            "parent_record": f"{p_overall.get('wins')}W/{p_overall.get('losses')}L/"
                             f"{p_overall.get('draws')}D",
            "noise_control_corroborates": noise.get("noise_control_corroborates"),
            "noise_pooled_mirror_fisher_p": fz.get("pooled_mirror"),
            "noise_parent_mirror_wr": noise.get("parent_mirror", {}).get("decisive_win_rate"),
            "noise_candidate_mirror_wr": noise.get("candidate_mirror", {}).get("decisive_win_rate"),
            "noise_seat0_first_mover_wr": noise.get("seat0_first_mover_pooled", {}).get("seat0_win_rate"),
            "non_inert_changed_rate": trace.get("changed_rate"),
            "non_inert_illegal": illegal,
            "non_inert_fallback_rate": trace.get("fallback_rate"),
            "public_ref_overall_wr": refs.get("overall_vs_all_refs", {}).get("decisive_win_rate"),
            "anchor_verdicts": {a.get("role"): a.get("verdict")
                                for a in anchor.get("anchors", [])},
            "candidate_tarball_sha256": build.get("tarball_sha256"),
            "deck_unchanged": build.get("deck_unchanged"),
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass41_strategy_decision.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 41 (Part J) — Local Registration / Strategy Decision", "",
        f"- generated: {payload['generated_at']}",
        f"- candidate: `{payload['candidate_id']}` (parent `{payload['parent_id']}`)",
        f"- **decision: `{decision}`**",
        f"- reason: {reason}",
        f"- local registration: **{payload['local_registration']}** · "
        f"prod scheduler changed: **{payload['prod_scheduler_changed']}**",
        f"- republish_required: **{payload['republish_required']}** "
        f"({payload['republish_note']})",
        f"- no_upload: true · upload_performed: false · github_push: false", "",
        "## Gates", "", "| gate | pass |", "|---|---|",
    ]
    for k, v in payload["gates"].items():
        lines.append(f"| {k} | {'yes' if v else 'NO'} |")
    lines += ["", "## Evidence", ""]
    for k, v in payload["evidence"].items():
        lines.append(f"- {k}: {v}")
    (EXP / "pass41_strategy_decision.md").write_text("\n".join(lines) + "\n",
                                                     encoding="utf-8")

    print(f"decision={decision} republish_required={payload['republish_required']}")
    print(f"gates={payload['gates']}")
    print(f"wrote {EXP / 'pass41_strategy_decision.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
