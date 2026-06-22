#!/usr/bin/env python3
"""PASS 46I (Part H) — emit LOCAL ActiveGraph events for the water option-value
CONFIRMATION pass.

Data-driven from the Part-A..G artifacts. This pass builds NO new candidates and registers
NOTHING (it replays EXISTING 46H tarballs), so it emits only CONFIRMATION-evaluation events:
per-panel local evaluations, the parent-edge attribution decomposition, the decision, and
(separately) the benchmark-only reference context.

HARD: NOTHING is uploaded / submitted / pushed / promoted / registered / queued. There is NO
SubmissionQueued, NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted, NO
*Registered/*Promoted of any kind. Every event carries forced ``no_upload=true``. The only
side effect is appending to LOCAL ledgers; the shared report SITE is never regenerated (an
optional ``ReportSiteGenerated`` event references the LOCAL report .md and sets
``shared_site_regenerated=false``).

Routing (zero public-reference leakage onto the main lab ledger):
  * MAIN lab ledger (``data/activegraph/lab_events.jsonl``) — gating + context panels,
    parent-edge attribution decomposition, decision, optional report doc.
  * SEPARATE benchmark ledger (``data/tournament/benchmark/benchmark_events.jsonl``) — the
    public-reference context summary (references stay benchmark-only, excluded from decision).

Idempotent (unique-sub-step-marker rule): a re-run strips ONLY events carrying the marker tag
``pass46i_eventset`` from BOTH ledgers before re-emitting; events from any other pass (or
per-game benchmark events lacking this marker) are preserved untouched.

Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score, NEVER a strength claim. A
directional parent edge that is NOT attributable to the option-value layer (Fisher increment
non-significant vs the family-only floor) is reported as inherited, never as a success.

Outputs: data/experiments/pass46i_events.{json,md}
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
from ptcg_activegraph.tournament.benchmark import (  # noqa: E402
    benchmark_ledger, BENCHMARK_EVENTS_PATH,
)

EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
TAG = "pass46i"
MARK = "pass46i_eventset"  # idempotency marker: ONLY this script's logical events

FORBIDDEN_TYPES = {
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted",
    "StrategyPromotionDecision",
}

PANEL_ORDER = ["ov_vs_floor", "ov_vs_parent", "floor_vs_parent",
               "conservative_vs_ov", "parent_vs_parent", "ov_vs_ov"]


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
    edge = _load("pass46i_edge_analysis.json")
    dec = _load("pass46i_strategy_decision.json")
    refctx = _load("pass46i_reference_context.json")

    panels = edge.get("panels") or {}
    increment = edge.get("attribution_increment_fisher")

    removed_main = _strip(LAB_EVENTS_PATH)
    removed_bench = _strip(BENCHMARK_EVENTS_PATH)
    if removed_main or removed_bench:
        print(f"removed {removed_main} main + {removed_bench} benchmark stale "
              f"{MARK} events (idempotent re-run)")

    store = EventStore(LAB_EVENTS_PATH)
    bench = benchmark_ledger()
    main_n = bench_n = 0

    def _et_name(et: EventType) -> str:
        return getattr(et, "value", None) or getattr(et, "name", None) or str(et)

    def _guard(et: EventType) -> None:
        if _et_name(et) in FORBIDDEN_TYPES:
            raise RuntimeError(
                f"refusing to emit forbidden event type for pass46i: {_et_name(et)}")

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

    def _bench(et: EventType, sub: str, payload: dict) -> None:
        nonlocal bench_n
        _guard(et)
        body = dict(payload)
        body["no_upload"] = True            # forced invariant
        bench.emit(et, body, tags=[TAG, MARK, sub, "benchmark"])
        bench_n += 1

    # 1) Per-panel confirmation evaluations (gating arms first, then context, then noise).
    for pid in PANEL_ORDER:
        a = panels.get(pid)
        if not a:
            continue
        is_gating = pid in ("ov_vs_floor", "ov_vs_parent")
        is_noise = pid in ("parent_vs_parent", "ov_vs_ov")
        _main(EventType.LocalEvaluationFinished, "panel_eval", {
            "logical_event": "WaterOptionValueConfirmationPanel",
            "evaluation": "confirmation_panel", "panel_id": pid,
            "arm": ("attribution" if pid == "ov_vs_floor"
                    else "practical" if pid == "ov_vs_parent"
                    else "noise_control" if is_noise else "context"),
            "gating": is_gating,
            "subject": a.get("subject_id"), "opponent": a.get("opponent_id"),
            "n_decisive": a.get("n_decisive"), "subject_wins": a.get("subject_wins"),
            "n_invalid": a.get("n_invalid"), "n_draws": a.get("n_draws"),
            "win_rate_decisive": a.get("point"),
            "wilson95": [a.get("wilson_low"), a.get("wilson_high")],
            "seat0_win_rate": (a.get("seat0") or {}).get("win_rate"),
            "seat1_win_rate": (a.get("seat1") or {}).get("win_rate"),
            "seat_confounded": a.get("seat_confounded"),
            "noise_clean": a.get("noise_clean"),
            "edge_label": a.get("edge_label"),
            "caveat": ("LOCAL cabt decisive win rate vs a single named opponent; an edge is "
                       "claimed only if Wilson lower > 0.50. Win/loss is feasibility "
                       "context, NOT a Kaggle score or strength claim."),
            "source_artifacts": ["data/experiments/pass46i_edge_analysis.json"]})

    # 2) Parent-edge attribution decomposition (the crux: is the parent edge the option-
    #    value layer's, or the family-only floor's?).
    if increment:
        _main(EventType.LocalEvaluationFinished, "attribution_decomposition", {
            "logical_event": "WaterOptionValueParentEdgeDecomposition",
            "evaluation": "attribution_increment_fisher",
            "test": increment.get("test"),
            "ov_vs_parent": increment.get("ov_vs_parent"),
            "floor_vs_parent": increment.get("floor_vs_parent"),
            "ov_parent_rate": increment.get("ov_parent_rate"),
            "floor_parent_rate": increment.get("floor_parent_rate"),
            "fisher_two_sided_p": increment.get("p_value"),
            "significant_at_0_05": increment.get("significant_at_0_05"),
            "parent_edge_attributable_to_option_value":
                dec.get("parent_edge_attributable_to_option_value"),
            "interpretation": dec.get("parent_edge_attribution_note"),
            "caveat": ("a non-significant increment means any parent edge is INHERITED from "
                       "the family-only floor, NOT added by the per-option value layer"),
            "source_artifacts": ["data/experiments/pass46i_edge_analysis.json"]})

    # 3) Decision -> StrategyDecisionRecorded.
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46i", "decision_label": dec.get("decision"),
        "attribution_label": dec.get("attribution_label"),
        "practical_label": dec.get("practical_label"),
        "noise_required": dec.get("noise_required"),
        "noise_clean": dec.get("noise_clean"),
        "gates": dec.get("gates"),
        "parent_edge_attributable_to_option_value":
            dec.get("parent_edge_attributable_to_option_value"),
        "parent_edge_attribution_note": dec.get("parent_edge_attribution_note"),
        "next_iteration_levers": dec.get("next_iteration_levers"),
        "promote": False, "queue": False, "upload": False, "submit": False,
        "register": False, "github_push": False, "auto_submit": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "safety_invariants_ok": dec.get("safety_invariants_ok"),
        "source_artifacts": ["data/experiments/pass46i_strategy_decision.json"]})

    # 4) Report doc (only if the Part-J report already exists). Shared SITE NOT regenerated.
    report_md = RPT / "pass46i_water_option_value_confirmation_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46i", "reports": [str(report_md.relative_to(REPO))],
            "shared_site_regenerated": False,
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    # ---- BENCHMARK LEDGER: public-reference context (refs stay here, EXCLUDED) ----
    if refctx:
        per_opp = refctx.get("per_opponent") or {}
        combined = refctx.get("combined") or {}
        _bench(EventType.LocalEvaluationFinished, "public_ref_context", {
            "logical_event": "WaterOptionValueReferenceContext",
            "evaluation": "subject_vs_references_benchmark_only",
            "subject": refctx.get("subject"),
            "benchmark_only": True, "promotion_relevant": False,
            "excluded_from_decision": True,
            "references_as_source_parent_candidate": False,
            "reference_ids_excluded_from_lineage": refctx.get("safe_opponents", []),
            "per_reference": [
                {"reference": opp, "decisive": o.get("decisive"),
                 "subject_wins": o.get("wins"), "win_rate": o.get("win_rate"),
                 "wilson95": [o.get("wilson_low"), o.get("wilson_high")]}
                for opp, o in per_opp.items()],
            "combined_win_rate": combined.get("win_rate"),
            "combined_wilson95": [combined.get("wilson_low"), combined.get("wilson_high")],
            "combined_decisive": combined.get("decisive"),
            "caveat": ("the owned candidate measured AGAINST public references as benchmark "
                       "opponents ONLY (cross-deck, small n); never a 'beats reference' or "
                       "promotion claim; references never enter pool/queue/lifecycle/"
                       "rankings/lineage and are EXCLUDED from the decision"),
            "source_artifacts": ["data/experiments/pass46i_reference_context.json"]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46i_events_v1", "pass": "46i", "part": "H",
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False, "candidate_registered": False,
        "shared_report_site_regenerated": False,
        "decision_label": dec.get("decision"),
        "forbidden_types_never_emitted": sorted(FORBIDDEN_TYPES),
        "main_ledger": str(LAB_EVENTS_PATH.relative_to(REPO)),
        "benchmark_ledger": str(BENCHMARK_EVENTS_PATH.relative_to(REPO)),
        "emitted_main": main_n, "emitted_benchmark": bench_n,
        "report_doc_emitted": report_emitted,
        "stripped_on_rerun": {"main": removed_main, "benchmark": removed_bench},
        "verification": {
            "main_forbidden": main_scan["forbidden_types"],
            "benchmark_forbidden": bench_scan["forbidden_types"],
            "main_no_upload_false": main_scan["no_upload_false"],
            "benchmark_no_upload_false": bench_scan["no_upload_false"],
            "main_historical_forbidden_pre_pass46i": main_scan["historical"],
            "benchmark_historical_forbidden_pre_pass46i": bench_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46i_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46I (Part H) — ActiveGraph Events", "",
        f"- decision: **`{dec.get('decision')}`**",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on main lab ledger, **{bench_n}** on benchmark ledger",
        f"- report-doc event emitted: **{report_emitted}** "
        "(re-run after the Part-J report exists to add it)",
        "- shared report SITE regenerated: **false** (event references the local report "
        ".md only)",
        "- NO build / registration / promotion events (this pass replays EXISTING 46H "
        "tarballs)",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · "
        "candidate_promoted: false · candidate_registered: false",
        f"- **verification clean (no forbidden / no_upload=false this pass on either "
        f"ledger): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: gating + context panels, parent-edge attribution "
        "decomposition, decision"
        + (", report doc" if report_emitted else "") + ".",
        "- BENCHMARK ledger (public references stay here): reference context summary only "
        "(excluded from the decision).", "",
        f"Events from other passes and per-game benchmark events (lacking the `{MARK}` "
        "marker) are preserved untouched on re-run.", "",
        "_Win/loss is LOCAL feasibility context, NOT a Kaggle score. A directional parent "
        "edge NOT attributable to the option-value layer (Fisher increment non-significant "
        "vs the family-only floor) is reported as inherited, never as a success._", ""]
    (EXP / "pass46i_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} main + {bench_n} benchmark {MARK} events")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"CandidateRegistered=0 report_doc_emitted={report_emitted}")
    if not clean:
        print("FATAL: ledger scan NOT clean for pass46i — forbidden type or "
              "no_upload=false detected; treat as a safety failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
