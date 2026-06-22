#!/usr/bin/env python3
"""PASS 46J (Part K) — emit LOCAL ActiveGraph events for the Diamond cg_typed
SPECIALIST PLANNER v0 pass.

Data-driven from the Part-A..J artifacts. This is a LOCAL-ONLY gameplay-improvement pass
(production keeps soaking; nothing is redeployed). It builds ONE owned cg_typed specialist
turn planner for the internal parent ``diamond_toolbox_diancie`` and decides — honestly —
whether it clears a parent edge AND is attributable to the planner (vs the 46H generic
diamond scorers). It therefore emits only LOCAL evaluation / decision events: the per-panel
local evaluations, the parent-edge attribution decomposition, and the decision (plus an
optional report-doc event once the Part-M report exists).

HARD: NOTHING is uploaded / submitted / pushed / promoted / registered / queued. There is NO
SubmissionQueued, NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted, NO
*Registered/*Promoted of any kind. Every event carries forced ``no_upload=true``. The shared
report SITE is never regenerated (an optional ``ReportSiteGenerated`` event references the
LOCAL report .md and sets ``shared_site_regenerated=false``).

Routing: this pass evaluates the owned candidate against the internal parent and the 46H
internal generic-diamond scorers only — public references were EXCLUDED from the eval panel
entirely (benchmark-only), so there is no reference context to emit and the benchmark ledger
is left untouched (only scanned for safety). All logical events go to the MAIN lab ledger
(``data/activegraph/lab_events.jsonl``).

Idempotent (unique-sub-step-marker rule): a re-run strips ONLY events carrying the marker tag
``pass46j_eventset`` before re-emitting; events from any other pass are preserved untouched.

Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score, NEVER a strength claim. A
``promising_local_only`` decision is a LOCAL signal that justifies more iteration — it is NOT
a promotion, NOT a prod change, and requires human approval before any prod candidate work.

Outputs: data/experiments/pass46j_events.{json,md}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType, new_event  # noqa: E402
from ptcg_activegraph.graph.event_store import EventStore  # noqa: E402
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH  # noqa: E402
from ptcg_activegraph.tournament.benchmark import BENCHMARK_EVENTS_PATH  # noqa: E402

EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
TAG = "pass46j"
MARK = "pass46j_eventset"  # idempotency marker: ONLY this script's logical events

FORBIDDEN_TYPES = {
    # upload / submit / score
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    # promotion / lifecycle
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted",
    "StrategyPromotionDecision",
    # registration of ANY kind (contract: NO *Registered)
    "OwnedCgCandidateRegistered", "PublicReferenceAgentRegistered",
    "TournamentParticipantRegistered", "BaselineRegistered",
    "HypothesisRegistered", "StrategyFamilyRegistered",
    # production ticks / republish (no prod tick this pass)
    "TournamentTickStarted", "TournamentTickFinished",
    "PublicBenchmarkTickStarted", "PublicBenchmarkTickFinished",
}

# gating arms first (practical + attribution), then attribution-context, then context,
# then the noise self-mirror controls.
PANEL_ORDER = ["spec_vs_parent", "spec_vs_generic_ov", "spec_vs_generic_floor",
               "floor_vs_parent", "ov_vs_parent", "parent_vs_parent", "spec_vs_spec"]


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path: Path, mark: str = MARK) -> int:
    if not path.exists():
        return 0
    kept, removed = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            kept.append(line)
            continue
        tags = ev.get("tags") or [] if isinstance(ev, dict) else []
        if mark in tags:
            removed += 1
        else:
            kept.append(line)
    path.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def _scan_forbidden(path: Path, base_tag: str = TAG) -> dict:
    pf_forbidden, pf_no_upload_false = [], 0
    hist = {}
    if not path.exists():
        return {"forbidden_types": [], "no_upload_false": 0, "historical": {}}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        et = ev.get("event_type")
        tags = ev.get("tags") or []
        pl = ev.get("payload") or {}
        is_pf = base_tag in tags
        if et in FORBIDDEN_TYPES:
            if is_pf:
                pf_forbidden.append(et)
            else:
                hist[et] = hist.get(et, 0) + 1
        if is_pf and pl.get("no_upload") is False:
            pf_no_upload_false += 1
    return {"forbidden_types": sorted(set(pf_forbidden)),
            "no_upload_false": pf_no_upload_false, "historical": hist}


def main() -> int:
    panel = _load("pass46j_diamond_eval_panel.json")
    dec = _load("pass46j_strategy_decision.json")
    ev_panels = {p["panel_id"]: p for p in (panel.get("panels") or [])}
    evidence = dec.get("evidence") or {}
    increments = evidence.get("fisher_increments") or {}

    removed_main = _strip(LAB_EVENTS_PATH)
    if removed_main:
        print(f"removed {removed_main} stale {MARK} events (idempotent re-run)")

    store = EventStore(LAB_EVENTS_PATH)
    main_n = 0

    def _et_name(et: EventType) -> str:
        return getattr(et, "value", None) or getattr(et, "name", None) or str(et)

    def _guard(et: EventType) -> None:
        if _et_name(et) in FORBIDDEN_TYPES:
            raise RuntimeError(
                f"refusing to emit forbidden event type for pass46j: {_et_name(et)}")

    def _main(et: EventType, sub: str, payload: dict,
              parents: list[str] | None = None) -> str:
        nonlocal main_n
        _guard(et)
        body = dict(payload)
        body["no_upload"] = True            # forced invariant
        body["is_kaggle_leaderboard"] = False
        ev = new_event(et, tags=[TAG, MARK, sub], payload=body,
                       parent_event_ids=parents or [])
        store.append(ev)
        main_n += 1
        return ev.event_id

    # 1) Per-panel local evaluations (gating arms first, then context, then noise controls).
    for pid in PANEL_ORDER:
        a = ev_panels.get(pid)
        if not a:
            continue
        arm = a.get("arm")
        is_noise = arm == "noise_control"
        _main(EventType.LocalEvaluationFinished, "panel_eval", {
            "logical_event": "DiamondSpecialistPlannerPanel",
            "evaluation": "local_eval_panel", "panel_id": pid, "arm": arm,
            "gating": a.get("gating"),
            "subject": a.get("subject_id"), "opponent": a.get("opponent_id"),
            "n_decisive": a.get("n_decisive"), "subject_wins": a.get("subject_wins"),
            "n_invalid": a.get("n_invalid"), "n_draws": a.get("n_draws"),
            "n_results": a.get("n_results"), "invalid_rate": a.get("invalid_rate"),
            "win_rate_decisive": a.get("subject_win_rate"),
            "wilson95": [a.get("wilson_low"), a.get("wilson_high")],
            "seat0_win_rate": a.get("seat0_rate"),
            "seat1_win_rate": a.get("seat1_rate"),
            "seat_confounded": a.get("seat_confounded"),
            "noise_ci_contains_half": a.get("noise_ci_contains_half"),
            "edge_label": a.get("edge_label"),
            "reached_target": a.get("reached_target"),
            "unsafe_invalid": a.get("unsafe_invalid"),
            "caveat": ("LOCAL cabt decisive win rate vs a single named opponent; an edge is "
                       "claimed only if Wilson lower > 0.50. Win/loss is feasibility context, "
                       "NOT a Kaggle score or strength claim. Public references were EXCLUDED "
                       "from this panel (benchmark-only)."),
            "source_artifacts": ["data/experiments/pass46j_diamond_eval_panel.json"]})

    # 2) Parent-edge attribution decomposition (the crux: is the parent edge the planner's,
    #    or inherited from the 46H generic diamond scorers?).
    if increments:
        _main(EventType.LocalEvaluationFinished, "attribution_decomposition", {
            "logical_event": "DiamondSpecialistParentEdgeAttribution",
            "evaluation": "attribution_fisher_increment_plus_h2h",
            "test": "one_sided_fisher_increment_vs_generic_scorer_parent_rates",
            "increment_vs_generic_option_value": increments.get("ov_vs_parent"),
            "increment_vs_generic_family_floor": increments.get("floor_vs_parent"),
            "head_to_head_vs_generic_option_value":
                evidence.get("head_to_head_vs_generic_ov"),
            "head_to_head_vs_generic_floor":
                evidence.get("head_to_head_vs_generic_floor"),
            "spec_vs_generic_ov_win_rate": evidence.get("spec_vs_generic_ov_win_rate"),
            "attributable_to_planner": evidence.get("attributable_to_planner"),
            "interpretation": dec.get("attribution_caveat"),
            "caveat": ("attribution holds when the planner BEATS a generic scorer head-to-head "
                       "OR adds a significant one-sided Fisher increment over the "
                       "generic-scorer-vs-parent rate; a parent edge with neither is INHERITED "
                       "from the generic diamond family, NOT added by the planner. The "
                       "head-to-head vs the STRONGER generic option-value scorer is reported "
                       "honestly (no edge there)."),
            "source_artifacts": ["data/experiments/pass46j_strategy_decision.json"]})

    # 3) Decision -> StrategyDecisionRecorded (LOCAL-ONLY; explicitly NOT a promotion).
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46J", "decision_label": dec.get("decision"),
        "subject_under_test": dec.get("subject_under_test"),
        "parent_id": dec.get("parent_id"),
        "promising": dec.get("promising"),
        "reasons": dec.get("reasons"),
        "practical_label": evidence.get("practical_label"),
        "practical_win_rate": evidence.get("practical_win_rate"),
        "practical_wilson95": [evidence.get("practical_wilson_low"),
                               evidence.get("practical_wilson_high")],
        "attributable_to_planner": evidence.get("attributable_to_planner"),
        "noise_clean": evidence.get("noise_clean"),
        "is_planner_not_flat_scorer": evidence.get("is_planner_not_flat_scorer"),
        "non_inert_illegal": evidence.get("non_inert_illegal"),
        "references_excluded": evidence.get("references_excluded"),
        "attribution_caveat": dec.get("attribution_caveat"),
        # explicit negative invariants — this LOCAL decision changes nothing in prod:
        "promote": False, "queue": False, "upload": False, "submit": False,
        "register": False, "github_push": False, "auto_submit": False,
        "redeploy": False, "prod_mutated": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "local_only": True, "no_upload": True,
        "source_artifacts": ["data/experiments/pass46j_strategy_decision.json"]})

    # 4) Report doc (only if the Part-M report already exists). Shared SITE NOT regenerated.
    report_md = RPT / "pass46j_diamond_specialist_planner_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46J", "reports": [str(report_md.relative_to(REPO))],
            "shared_site_regenerated": False,
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)  # untouched; scanned for assurance
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46j_events_v1", "pass": "46J", "part": "K",
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False, "candidate_registered": False,
        "redeploy": False, "prod_mutated": False,
        "shared_report_site_regenerated": False,
        "decision_label": dec.get("decision"),
        "references_emitted_to_benchmark_ledger": False,
        "references_excluded_from_eval": True,
        "forbidden_types_never_emitted": sorted(FORBIDDEN_TYPES),
        "main_ledger": str(LAB_EVENTS_PATH.relative_to(REPO)),
        "benchmark_ledger_untouched": str(BENCHMARK_EVENTS_PATH.relative_to(REPO)),
        "emitted_main": main_n,
        "report_doc_emitted": report_emitted,
        "stripped_on_rerun": {"main": removed_main},
        "verification": {
            "main_forbidden": main_scan["forbidden_types"],
            "benchmark_forbidden": bench_scan["forbidden_types"],
            "main_no_upload_false": main_scan["no_upload_false"],
            "benchmark_no_upload_false": bench_scan["no_upload_false"],
            "main_historical_forbidden_pre_pass46j": main_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46j_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46J (Part K) — ActiveGraph Events", "",
        f"- decision: **`{dec.get('decision')}`** (LOCAL-ONLY signal — NOT a promotion)",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on the main lab ledger",
        f"- report-doc event emitted: **{report_emitted}** "
        "(re-run after the Part-M report exists to add it)",
        "- shared report SITE regenerated: **false** (event references the local report "
        ".md only)",
        "- NO build / registration / promotion / redeploy events (production keeps soaking "
        "untouched)",
        "- public references EXCLUDED from the eval panel (benchmark-only); the benchmark "
        "ledger is left untouched and only scanned for assurance",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · redeploy: false "
        "· candidate_promoted: false · candidate_registered: false",
        f"- **verification clean (no forbidden / no_upload=false this pass): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: per-panel local evaluations, parent-edge attribution "
        "decomposition, decision"
        + (", report doc" if report_emitted else "") + ".",
        f"- Events from other passes (lacking the `{MARK}` marker) are preserved untouched "
        "on re-run.", "",
        "_Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score. A "
        "`promising_local_only` decision justifies more iteration; it is NOT a promotion, NOT "
        "a prod change, and requires human approval before any prod candidate work. The "
        "head-to-head vs the stronger generic option-value scorer is reported honestly._", ""]
    (EXP / "pass46j_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} {MARK} events on main lab ledger")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"CandidateRegistered=0 redeploy=0 report_doc_emitted={report_emitted}")
    if not clean:
        print("FATAL: ledger scan NOT clean for pass46j — forbidden type or "
              "no_upload=false detected; treat as a safety failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
