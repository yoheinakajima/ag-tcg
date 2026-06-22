#!/usr/bin/env python3
"""PASS 46K (Part I) — emit LOCAL ActiveGraph events for the Diamond cg_typed SPECIALIST
PLANNER larger-N confirmation + reference-gap audit pass.

Data-driven from the Part-A..H artifacts. This is a LOCAL-ONLY re-evaluation pass (production
keeps soaking; NOTHING is redeployed). It re-evaluates the EXISTING 46J candidate
``cg_typed_diamond_specialist_planner_v0`` at larger N against the internal parent
``diamond_toolbox_diancie`` and the 46H generic diamond scorers, audits its distance from
public-reference parity (benchmark-only), and records the pre-registered decision. It therefore
emits only LOCAL evaluation / decision events.

HARD: NOTHING is uploaded / submitted / pushed / promoted / registered / queued / ticked. There
is NO SubmissionQueued, NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted, NO
*Registered/*Promoted, NO TournamentTick*/PublicBenchmarkTick* of any kind. Every event carries
forced ``no_upload=true``. The shared report SITE is never regenerated.

Public references are BENCHMARK-ONLY: the reference-gap context event is flagged
``benchmark_only=true`` / ``excluded_from_decision=true`` / ``is_decision_gate=false`` and the
ActiveGraph benchmark ledger is left UNTOUCHED (only scanned for assurance) — the Part-F
reference games live in their own no_upload experiment ledger, never in ActiveGraph.

Idempotent (unique-sub-step-marker rule): a re-run strips ONLY events carrying the marker tag
``pass46k_eventset`` before re-emitting; events from any other pass are preserved untouched.

Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score, NEVER a strength claim. The
decision ``diamond_specialist_inconclusive_needs_more_n`` is a LOCAL signal — NOT a promotion,
NOT a prod change.

Outputs: data/experiments/pass46k_events.{json,md}
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
TAG = "pass46k"
MARK = "pass46k_eventset"  # idempotency marker: ONLY this script's logical events

FORBIDDEN_TYPES = {
    # upload / submit / score
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    # promotion / lifecycle
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted", "StrategyPromotionDecision",
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
               "ov_vs_parent", "floor_vs_parent", "parent_vs_parent", "spec_vs_spec"]


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _arm_gating_map(plan: dict) -> dict:
    out: dict[str, dict] = {}
    for pan in plan.get("panels", []):
        out[pan["panel_id"]] = {"arm": pan.get("arm"), "gating": bool(pan.get("gating"))}
    for pan in plan.get("conditional_noise_controls", []):
        out[pan["panel_id"]] = {"arm": pan.get("arm"), "gating": bool(pan.get("gating"))}
    return out


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
    plan = _load("pass46k_eval_plan.json")
    edge = _load("pass46k_edge_analysis.json")
    dec = _load("pass46k_strategy_decision.json")
    refgap = _load("pass46k_public_reference_gap.json")
    trace = _load("pass46k_planner_trace_diagnostic.json")

    ev_panels = edge.get("panels") or {}
    increments = edge.get("attribution_increments_fisher") or {}
    di = edge.get("decision_inputs") or {}
    evidence = dec.get("evidence") or {}
    am = _arm_gating_map(plan)

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
                f"refusing to emit forbidden event type for pass46k: {_et_name(et)}")

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
        meta = am.get(pid, {})
        arm = meta.get("arm")
        _main(EventType.LocalEvaluationFinished, "panel_eval", {
            "logical_event": "DiamondSpecialistLargerNPanel",
            "evaluation": "local_eval_panel", "panel_id": pid, "arm": arm,
            "gating": meta.get("gating"),
            "subject": a.get("subject_id"), "opponent": a.get("opponent_id"),
            "n_decisive": a.get("n_decisive"), "subject_wins": a.get("subject_wins"),
            "n_invalid": a.get("n_invalid"), "n_draws": a.get("n_draws"),
            "n_total": a.get("n_total"), "invalid_rate": a.get("invalid_rate"),
            "win_rate_decisive": a.get("point"),
            "wilson95": [a.get("wilson_low"), a.get("wilson_high")],
            "carried_decisive": a.get("carried_decisive"),
            "new_decisive": a.get("new_decisive"),
            "seat0_win_rate": (a.get("seat0") or {}).get("win_rate"),
            "seat1_win_rate": (a.get("seat1") or {}).get("win_rate"),
            "seat_confounded": a.get("seat_confounded"),
            "noise_ci_contains_half": a.get("noise_clean"),
            "edge_label": a.get("edge_label"),
            "unsafe_invalid": a.get("unsafe_invalid"),
            "caveat": ("LOCAL cabt decisive win rate vs a single named opponent; an edge is "
                       "claimed only if Wilson lower > 0.50. Carried (46J) and NEW 46K rows are "
                       "reported separately, never silently mixed. Win/loss is feasibility "
                       "context, NOT a Kaggle score or strength claim. Public references were "
                       "EXCLUDED from this panel (benchmark-only)."),
            "source_artifacts": ["data/experiments/pass46k_edge_analysis.json"]})

    # 2) Parent-edge attribution decomposition (is the parent edge the planner's, or inherited
    #    from the 46H generic diamond scorers?).
    if increments:
        _main(EventType.LocalEvaluationFinished, "attribution_decomposition", {
            "logical_event": "DiamondSpecialistParentEdgeAttribution",
            "evaluation": "attribution_fisher_increment_plus_h2h",
            "test": "one_sided_fisher_increment_vs_generic_scorer_parent_rates",
            "increment_vs_generic_option_value": increments.get("ov_vs_parent"),
            "increment_vs_generic_family_floor": increments.get("floor_vs_parent"),
            "attribution_label": di.get("attribution_label"),
            "attribution_point": di.get("attribution_point"),
            "head_to_head_floor_label": di.get("head_to_head_floor_label"),
            "attributable_to_planner": di.get("attributable_to_planner"),
            "fisher_ov_increment_significant": di.get("fisher_ov_increment_significant"),
            "interpretation": dec.get("attribution_caveat"),
            "caveat": ("attribution holds when the planner BEATS a generic scorer head-to-head "
                       "OR adds a significant one-sided Fisher increment over the "
                       "generic-scorer-vs-parent rate. Here both the H2H vs the stronger generic "
                       "option-value scorer AND the Fisher increment are positive — the parent "
                       "edge IS the planner's — but a triggered self-mirror noise control is "
                       "NOT clean, so the larger-N readout stays inconclusive."),
            "source_artifacts": ["data/experiments/pass46k_edge_analysis.json"]})

    # 3) Public-reference GAP context (BENCHMARK-ONLY; excluded from the decision; ActiveGraph
    #    benchmark ledger left untouched — Part-F games live in their own experiment ledger).
    if refgap:
        pooled = refgap.get("pooled") or {}
        _main(EventType.LocalEvaluationFinished, "reference_gap_context", {
            "logical_event": "DiamondSpecialistPublicReferenceGap",
            "evaluation": "benchmark_only_reference_gap",
            "benchmark_only": True, "excluded_from_decision": True, "is_decision_gate": False,
            "parity_claim": False,
            "safe_opponents": refgap.get("safe_opponents"),
            "pooled_decisive": pooled.get("decisive"),
            "pooled_win_rate": pooled.get("win_rate"),
            "pooled_wilson95": [pooled.get("wilson_low"), pooled.get("wilson_high")],
            "parity_supported_any_ref": refgap.get("parity_supported_any_ref"),
            "pooled_parity_supported": refgap.get("pooled_parity_supported"),
            "caveat": ("Cross-deck, small-n distance-from-parity vs public references playing "
                       "their OWN decks; NOT a parity / 'beats the field' claim; EXCLUDED from "
                       "every gating/attribution statistic and from the decision. The Part-F "
                       "games live in a SEPARATE no_upload experiment ledger; the ActiveGraph "
                       "benchmark ledger is untouched."),
            "source_artifacts": ["data/experiments/pass46k_public_reference_gap.json"]})

    # 4) Planner trace diagnostic (visible-only plan fields, replayed on real states).
    if trace:
        co = trace.get("cooccurrence_descriptive") or {}
        _main(EventType.LocalEvaluationFinished, "planner_trace_diagnostic", {
            "logical_event": "DiamondSpecialistPlannerTrace",
            "evaluation": "visible_plan_field_replay_cooccurrence",
            "n_games": trace.get("n_games_played"),
            "n_decision_frames": trace.get("n_decision_frames"),
            "replay_faithful_rate": trace.get("replay_faithful_rate"),
            "outcomes": trace.get("outcomes"),
            "win_frames_internal_n": (co.get("win_frames_internal") or {}).get("n"),
            "loss_frames_internal_n": (co.get("loss_frames_internal") or {}).get("n"),
            "benchmark_ref_frames_n": (co.get("benchmark_ref_frames") or {}).get("n"),
            "planner_unsupported_claims": trace.get("planner_unsupported_claims"),
            "caveat": ("Visible plan fields only, REPLAYED deterministically on real recorded "
                       "states; win/loss links are DESCRIPTIVE co-occurrence at small n, never "
                       "causal. Every field is an observable heuristic LABEL — NOT a lethal / "
                       "KO / missed-KO / exact-damage / Boss-gust / spread / best-action claim. "
                       "Public-reference frames are benchmark-only (cross-deck) and excluded "
                       "from win/loss attribution cohorts."),
            "source_artifacts": ["data/experiments/pass46k_planner_trace_diagnostic.json"]})

    # 5) Decision -> StrategyDecisionRecorded (LOCAL-ONLY; explicitly NOT a promotion).
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46K", "decision_label": dec.get("decision"),
        "subject_under_test": dec.get("subject_under_test"),
        "parent_id": dec.get("parent_id"),
        "confirmed_local_candidate": dec.get("confirmed_local_candidate"),
        "reasons": dec.get("reasons"),
        "allowed_decisions": dec.get("allowed_decisions"),
        "practical_label": di.get("practical_label"),
        "practical_point": di.get("practical_point"),
        "practical_wilson_low": di.get("practical_wilson_low"),
        "attribution_label": di.get("attribution_label"),
        "attribution_point": di.get("attribution_point"),
        "attributable_to_planner": di.get("attributable_to_planner"),
        "fisher_ov_increment_significant": di.get("fisher_ov_increment_significant"),
        "gating_reached_min_acceptable": di.get("gating_reached_min_acceptable"),
        "noise_required": di.get("noise_required"),
        "noise_results": di.get("noise_results"),
        "noise_clean": di.get("noise_clean"),
        "references_excluded": evidence.get("references_excluded"),
        "decision_independent_of_references": dec.get("decision_independent_of_references"),
        "attribution_caveat": dec.get("attribution_caveat"),
        # explicit negative invariants — this LOCAL decision changes nothing in prod:
        "promote": False, "queue": False, "upload": False, "submit": False,
        "register": False, "github_push": False, "auto_submit": False,
        "redeploy": False, "prod_mutated": False, "tick_executed": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "local_only": True, "no_upload": True,
        "source_artifacts": ["data/experiments/pass46k_strategy_decision.json"]})

    # 6) Report doc (only if the Part-K report already exists). Shared SITE NOT regenerated.
    report_md = RPT / "pass46k_diamond_specialist_confirmation_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46K", "reports": [str(report_md.relative_to(REPO))],
            "shared_site_regenerated": False,
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)  # untouched; scanned for assurance
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46k_events_v1", "pass": "46K", "part": "I",
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False, "candidate_registered": False,
        "redeploy": False, "prod_mutated": False, "tick_executed": False,
        "shared_report_site_regenerated": False,
        "decision_label": dec.get("decision"),
        "references_benchmark_only": bool(refgap.get("benchmark_only", True)) if refgap else True,
        "references_emitted_to_benchmark_ledger": False,
        "references_excluded_from_decision": True,
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
            "main_historical_forbidden_pre_pass46k": main_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46k_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46K (Part I) — ActiveGraph Events", "",
        f"- decision: **`{dec.get('decision')}`** (LOCAL-ONLY signal — NOT a promotion)",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on the main lab ledger",
        f"- report-doc event emitted: **{report_emitted}** "
        "(re-run after the Part-K report exists to add it)",
        "- shared report SITE regenerated: **false** (event references the local report "
        ".md only)",
        "- NO build / registration / promotion / redeploy / tick events (production keeps "
        "soaking untouched)",
        "- public references BENCHMARK-ONLY and EXCLUDED from the decision; the ActiveGraph "
        "benchmark ledger is left untouched (Part-F games live in their own no_upload "
        "experiment ledger) and only scanned for assurance",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · redeploy: false "
        "· tick_executed: false · candidate_promoted: false · candidate_registered: false",
        f"- **verification clean (no forbidden / no_upload=false this pass): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: per-panel local evaluations, parent-edge attribution "
        "decomposition, benchmark-only reference-gap context, planner trace diagnostic, "
        "decision" + (", report doc" if report_emitted else "") + ".",
        f"- Events from other passes (lacking the `{MARK}` marker) are preserved untouched "
        "on re-run.", "",
        "_Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score. "
        "`diamond_specialist_inconclusive_needs_more_n` justifies more iteration on the noise "
        "controls; it is NOT a promotion, NOT a prod change, and requires human approval before "
        "any prod candidate work. Public-reference distance is benchmark-only and never gates._",
        ""]
    (EXP / "pass46k_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} {MARK} events on main lab ledger")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"CandidateRegistered=0 redeploy=0 tick=0 report_doc_emitted={report_emitted}")
    if not clean:
        print("FATAL: ledger scan NOT clean for pass46k — forbidden type or "
              "no_upload=false detected; treat as a safety failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
