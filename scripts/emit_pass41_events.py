#!/usr/bin/env python3
"""Pass 41 (Part K) — emit ActiveGraph events for the owned cg_typed candidate spike.

Data-driven from the Pass-41 artifacts. Emits the Part-K logical event set; every
event carries ``no_upload=true`` and the tags ``["pass41", "pass41_eventset"]``.

NOTHING is uploaded/submitted/pushed: there is NO SubmissionQueued, NO
SubmissionUploaded, NO KaggleScoreUpdated, and NO CandidatePromoted event. The
only side effect is appending to two LOCAL ledgers.

Routing (zero reference leakage onto the main lab ledger):
  * MAIN lab ledger (``data/activegraph/lab_events.jsonl``) — events about the
    OWNED candidate and its internal lineage only (registration, build,
    validation, smoke, parent/child H2H, non-inertness, noise control, internal
    anchors, decision, optional report site).
  * SEPARATE benchmark ledger (``data/tournament/benchmark/benchmark_events.jsonl``)
    — summary events that reference the public references (calibration batch,
    public-reference eval, the dragapult reference anchor). The references stay on
    the benchmark ledger exactly as in Pass 40.

Idempotent: a re-run strips only previously-emitted events carrying the marker tag
``pass41_eventset`` from BOTH ledgers before re-emitting. Per-game benchmark/
tournament events (tagged ``pass41``+``benchmark`` but NOT ``pass41_eventset``)
are preserved untouched.

Honest enum mapping (NO invented values beyond the two declared Pass-41 types).
Logical event kinds without a dedicated EventType map to the closest existing real
type and record their intended name in ``payload.logical_event``.

Outputs:
  data/experiments/pass41_events.{json,md}
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
TAG = "pass41"
MARK = "pass41_eventset"  # idempotency marker: ONLY this script's logical events

FORBIDDEN_TYPES = {
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted",
}


def _load(name: str, base: Path = EXP) -> dict:
    try:
        return json.loads((base / name).read_text(encoding="utf-8"))
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
    """Audit a ledger for forbidden / no_upload=false events.

    The Pass-41 guardrail is scoped to THIS pass: it must emit no forbidden type
    and no ``no_upload=false`` event. Events from earlier passes that pre-date
    Pass 41 (lacking the ``pass41`` base tag) are reported separately as
    informational history, NOT counted as a Pass-41 violation.
    """
    p41_forbidden, p41_no_upload_false = [], 0
    hist_forbidden = {}
    if not path.exists():
        return {"pass41_forbidden_types": [], "pass41_no_upload_false": 0,
                "historical_forbidden_by_type": {}}
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
        is_p41 = base_tag in tags
        if et in FORBIDDEN_TYPES:
            if is_p41:
                p41_forbidden.append(et)
            else:
                hist_forbidden[et] = hist_forbidden.get(et, 0) + 1
        if is_p41 and pl.get("no_upload") is False:
            p41_no_upload_false += 1
    return {"pass41_forbidden_types": sorted(set(p41_forbidden)),
            "pass41_no_upload_false": p41_no_upload_false,
            "historical_forbidden_by_type": hist_forbidden}


def main() -> int:
    build = _load("pass41_candidate_build.json")
    val = _load("pass41_cg_candidate_validation.json")
    smoke = _load("pass41_cg_candidate_smoke.json")
    parent = _load("pass41_parent_child_eval.json")
    refs = _load("pass41_public_reference_eval.json")
    anchor = _load("pass41_anchor_eval.json")
    trace = _load("pass41_non_inertness_trace.json")
    noise = _load("pass41_h2h_noise_control.json")
    decision = _load("pass41_strategy_decision.json")
    calib = _load("pass41_public_benchmark_calibration.json")
    target = _load("pass41_target_family_selection.json")

    cand_id = build.get("candidate_id")
    parent_id = parent.get("parent_id") or build.get("mutation_parent")

    # idempotent: remove only our own marker-tagged logical events from BOTH ledgers
    removed_main = _strip(LAB_EVENTS_PATH)
    removed_bench = _strip(BENCHMARK_EVENTS_PATH)
    if removed_main or removed_bench:
        print(f"removed {removed_main} main + {removed_bench} benchmark stale "
              f"{MARK} events (idempotent re-run)")

    store = EventStore(LAB_EVENTS_PATH)
    bench = benchmark_ledger()
    main_n = 0
    bench_n = 0

    def _main(et: EventType, sub: str, payload: dict) -> None:
        nonlocal main_n
        body = dict(payload)
        body.setdefault("no_upload", True)
        body.setdefault("is_kaggle_leaderboard", False)
        store.append(new_event(et, tags=[TAG, MARK, sub], payload=body))
        main_n += 1

    def _bench(et: EventType, sub: str, payload: dict) -> None:
        nonlocal bench_n
        # TournamentLedger.emit forces no_upload=true and refuses forbidden types.
        bench.emit(et, dict(payload), tags=[TAG, MARK, sub, "benchmark"])
        bench_n += 1

    # ---- MAIN LEDGER: owned candidate + internal lineage -----------------
    # 1) OwnedCgCandidateRegistered — local-only registration (NOT promotion).
    _main(EventType.OwnedCgCandidateRegistered, "registration", {
        "candidate_id": cand_id, "parent_id": parent_id, "lane": "cg_typed",
        "owned_candidate": True, "public_reference": False,
        "local_registration": decision.get("local_registration", "benchmark_local_only"),
        "decision": decision.get("decision"),
        "prod_scheduler_changed": False, "republish_required": False,
        "promote": False, "queued": False, "active_cap_changed": False,
        "tarball_sha256": build.get("tarball_sha256"),
        "deck_unchanged": build.get("deck_unchanged"),
        "source_artifacts": ["data/experiments/pass41_candidate_build.json",
                             "data/experiments/pass41_strategy_decision.json"]})

    # 2) CandidateBuilt -> StrategyIterationCreated.
    _main(EventType.StrategyIterationCreated, "build", {
        "logical_event": "CandidateBuilt", "candidate_id": cand_id,
        "parent_id": parent_id, "lane": build.get("lane"),
        "mutation_parent": build.get("mutation_parent"),
        "parent_family": build.get("parent_family"),
        "deck_unchanged": build.get("deck_unchanged"),
        "deck_rows": build.get("deck_rows"),
        "cg_files": build.get("cg_files"),
        "tarball": build.get("tarball"), "tarball_sha256": build.get("tarball_sha256"),
        "owned_candidate": True, "public_reference": False, "is_clone": False,
        "invented_card_ids": False,
        "source_artifacts": ["data/experiments/pass41_candidate_build.json"]})

    # 3) cg_typed validation -> CgTypedLaneValidated (reused Pass-40 type).
    _main(EventType.CgTypedLaneValidated, "validation", {
        "logical_event": "OwnedCgCandidateValidated", "candidate_id": cand_id,
        "ok": val.get("ok"), "cg_typed_lane": val.get("cg_typed_lane"),
        "stdlib_lane_rejects": val.get("stdlib_lane_rejects"),
        "validators_unchanged": val.get("validators_unchanged"),
        "stdlib_validators_byte_unchanged": val.get("stdlib_validators_byte_unchanged"),
        "lanes_separated": val.get("lanes_separated"),
        "candidate_sha256": val.get("candidate_sha256"),
        "source_artifacts": ["data/experiments/pass41_cg_candidate_validation.json"]})

    # 4) Smoke -> LocalEvaluationFinished.
    _main(EventType.LocalEvaluationFinished, "smoke", {
        "logical_event": "OwnedCgCandidateSmoke", "evaluation": "candidate_smoke",
        "candidate_id": cand_id, "ok": smoke.get("ok"),
        "hard_fail": smoke.get("hard_fail"),
        "games_total": smoke.get("games_total"),
        "games_completed": smoke.get("games_completed"),
        "games_error": smoke.get("games_error"),
        "games_timeout": smoke.get("games_timeout"),
        "import_or_deck_failures": smoke.get("import_or_deck_failures"),
        "root_main_deck_unchanged": smoke.get("root_main_deck_unchanged"),
        "references_not_in_pool": smoke.get("references_not_in_pool"),
        "caveat": "subprocess-isolated smoke; cg_typed-vs-reference via dedicated cg child",
        "source_artifacts": ["data/experiments/pass41_cg_candidate_smoke.json"]})

    # 5) Parent/child H2H -> ParentChildComparisonStarted + Finished (Pass-19).
    po = parent.get("overall", {})
    started = new_event(EventType.ParentChildComparisonStarted,
                        tags=[TAG, MARK, "parent_child"],
                        payload={"candidate_id": cand_id, "parent_id": parent_id,
                                 "lane": parent.get("lane"), "no_upload": True,
                                 "is_kaggle_leaderboard": False})
    store.append(started)
    main_n += 1
    store.append(new_event(
        EventType.ParentChildComparisonFinished,
        tags=[TAG, MARK, "parent_child"], parent_event_ids=[started.event_id],
        payload={"logical_event": "ParentChildEval", "candidate_id": cand_id,
                 "parent_id": parent_id, "verdict": parent.get("verdict"),
                 "decisive_win_rate": po.get("decisive_win_rate"),
                 "wilson95": po.get("wilson95"),
                 "record": f"{po.get('wins')}W/{po.get('losses')}L/{po.get('draws')}D",
                 "by_seat": parent.get("by_seat"),
                 "noise_control": parent.get("noise_control"),
                 "root_main_deck_unchanged": parent.get("root_main_deck_unchanged"),
                 "superiority_claim_caveat": ("CI above 0.50 only with the self-mirror "
                                              "noise control corroborating; NOT Kaggle"),
                 "no_upload": True, "is_kaggle_leaderboard": False,
                 "source_artifacts": ["data/experiments/pass41_parent_child_eval.json"]}))
    main_n += 1

    # 6) Non-inertness -> CandidateNonInertnessMeasured (Pass-36).
    _main(EventType.CandidateNonInertnessMeasured, "non_inertness", {
        "candidate_id": cand_id, "parent_id": parent_id,
        "non_inert": trace.get("non_inert"),
        "total_decisions": trace.get("total_decisions"),
        "changed_decisions": trace.get("changed_decisions"),
        "changed_rate": trace.get("changed_rate"),
        "illegal_refinements": trace.get("illegal_refinements"),
        "fallback_rate": trace.get("fallback_rate"),
        "candidate_uncaught_exceptions": trace.get("candidate_uncaught_exceptions"),
        "contexts_changed": trace.get("contexts_changed"),
        "hard_fail": trace.get("hard_fail"), "ok": trace.get("ok"),
        "source_artifacts": ["data/experiments/pass41_non_inertness_trace.json"]})

    # 7) Self-mirror noise control -> LocalEvaluationFinished.
    _main(EventType.LocalEvaluationFinished, "noise_control", {
        "logical_event": "SelfMirrorNoiseControl", "evaluation": "h2h_noise_control",
        "candidate_id": cand_id, "parent_id": parent_id,
        "controls_clean": noise.get("controls_clean"),
        "noise_control_corroborates": noise.get("noise_control_corroborates"),
        "fisher_h2h_vs_mirror_p": noise.get("fisher_h2h_vs_mirror_p"),
        "parent_mirror": noise.get("parent_mirror"),
        "candidate_mirror": noise.get("candidate_mirror"),
        "seat0_first_mover_pooled": noise.get("seat0_first_mover_pooled"),
        "noise_floor_upper_bound": noise.get("noise_floor_upper_bound"),
        "caveat": "self-mirror nulls calibrate the cabt noise floor; Fisher exact",
        "source_artifacts": ["data/experiments/pass41_h2h_noise_control.json"]})

    # 8) Internal anchors only (water_control + internal_leader) -> main ledger.
    internal_anchors = [a for a in anchor.get("anchors", [])
                        if "reference" not in str(a.get("role", "")).lower()]
    _main(EventType.LocalEvaluationFinished, "anchor_internal", {
        "logical_event": "InternalAnchorEval", "evaluation": "internal_anchor_eval",
        "candidate_id": cand_id,
        "anchors": {a.get("role"): a.get("verdict") for a in internal_anchors},
        "root_main_deck_unchanged": anchor.get("root_main_deck_unchanged"),
        "caveat": "internal anchors only; reference anchor lives on benchmark ledger",
        "source_artifacts": ["data/experiments/pass41_anchor_eval.json"]})

    # 9) Strategy decision -> StrategyDecisionRecorded.
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": 41, "decision_label": decision.get("decision"),
        "reason": decision.get("reason"),
        "local_registration": decision.get("local_registration"),
        "republish_required": decision.get("republish_required"),
        "prod_scheduler_changed": decision.get("prod_scheduler_changed"),
        "gates": decision.get("gates"),
        "promote": False, "queue": False, "upload": False, "submit": False,
        "github_push": False, "auto_submit": False, "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "source_artifacts": ["data/experiments/pass41_strategy_decision.json"]})

    # 10) ReportSiteGenerated — only if the Pass-41 report already exists (T-M).
    report_md = RPT / "pass41_reference_calibrated_cg_candidate_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": 41, "reports": [
                "data/reports/pass41_reference_calibrated_cg_candidate_report.md",
                "data/reports/activegraph_strategy_report.md",
                "data/site/index.html"],
            "decision_label": decision.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    # ---- BENCHMARK LEDGER: reference-involving summaries ------------------
    # A) ReferenceCalibrationFinished — larger calibrated reference batch (NEW).
    ct = calib.get("totals", {})
    _bench(EventType.ReferenceCalibrationFinished, "calibration", {
        "logical_event": "ReferenceCalibrationFinished",
        "subjects": len(calib.get("subjects", []) or []),
        "references": calib.get("references"),
        "all_done": calib.get("all_done"), "remaining": calib.get("remaining"),
        "totals": ct, "selected_target_family": target.get("selected_target_family"),
        "selection_rule": target.get("selection_rule"),
        "evidence_tied": target.get("evidence_tied"),
        "selected_parent_is_stdlib": target.get("selected_parent_is_stdlib"),
        "caveat": ("benchmark-only calibration; references never enter our pool/"
                   "ranking/active-cap/queue/promotion/lineage"),
        "source_artifacts": [
            "data/experiments/pass41_public_benchmark_calibration.json",
            "data/experiments/pass41_target_family_selection.json"]})

    # B) Public-reference eval summary -> LocalEvaluationFinished (benchmark).
    _bench(EventType.LocalEvaluationFinished, "public_ref_eval", {
        "logical_event": "PublicReferenceEval", "evaluation": "candidate_vs_references",
        "candidate_id": cand_id,
        "overall_vs_all_refs": refs.get("overall_vs_all_refs"),
        "per_reference": refs.get("per_reference"),
        "root_main_deck_unchanged": refs.get("root_main_deck_unchanged"),
        "caveat": ("owned candidate measured AGAINST public references as benchmark "
                   "opponents; honest below-reference result; references stay "
                   "benchmark-only"),
        "source_artifacts": ["data/experiments/pass41_public_reference_eval.json"]})

    # C) Dragapult reference anchor -> LocalEvaluationFinished (benchmark).
    ref_anchors = [a for a in anchor.get("anchors", [])
                   if "reference" in str(a.get("role", "")).lower()]
    if ref_anchors:
        _bench(EventType.LocalEvaluationFinished, "anchor_reference", {
            "logical_event": "ReferenceAnchorEval", "evaluation": "reference_anchor",
            "candidate_id": cand_id,
            "anchors": {a.get("role"): a.get("verdict") for a in ref_anchors},
            "caveat": "reference anchor (benchmark-only); honest below-reference",
            "source_artifacts": ["data/experiments/pass41_anchor_eval.json"]})

    # ---- verification scan: no forbidden / no_upload=false anywhere -------
    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)

    summary = {
        "schema": "pass41_events_v1", "pass": "41", "part": "K",
        "candidate_id": cand_id, "parent_id": parent_id,
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False,
        "new_event_types": ["OwnedCgCandidateRegistered", "ReferenceCalibrationFinished"],
        "forbidden_types_never_emitted": sorted(FORBIDDEN_TYPES),
        "main_ledger": str(LAB_EVENTS_PATH.relative_to(REPO)),
        "benchmark_ledger": str(BENCHMARK_EVENTS_PATH.relative_to(REPO)),
        "emitted_main": main_n, "emitted_benchmark": bench_n,
        "report_site_emitted": report_emitted,
        "stripped_on_rerun": {"main": removed_main, "benchmark": removed_bench},
        "verification": {
            "main_ledger_pass41_forbidden": main_scan["pass41_forbidden_types"],
            "benchmark_ledger_pass41_forbidden": bench_scan["pass41_forbidden_types"],
            "main_ledger_pass41_no_upload_false": main_scan["pass41_no_upload_false"],
            "benchmark_ledger_pass41_no_upload_false": bench_scan["pass41_no_upload_false"],
            "main_ledger_historical_forbidden_pre_pass41":
                main_scan["historical_forbidden_by_type"],
            "benchmark_ledger_historical_forbidden_pre_pass41":
                bench_scan["historical_forbidden_by_type"],
            "clean": (not main_scan["pass41_forbidden_types"]
                      and not bench_scan["pass41_forbidden_types"]
                      and main_scan["pass41_no_upload_false"] == 0
                      and bench_scan["pass41_no_upload_false"] == 0),
        },
    }
    (EXP / "pass41_events.json").write_text(json.dumps(summary, indent=2),
                                            encoding="utf-8")

    lines = [
        "# Pass 41 (Part K) — ActiveGraph Events", "",
        f"- candidate: `{cand_id}` (parent `{parent_id}`)",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on main lab ledger, **{bench_n}** on benchmark ledger",
        f"- report-site event emitted: **{report_emitted}** "
        f"(re-run after the report exists to add it)",
        f"- new Pass-41 event types: {', '.join(summary['new_event_types'])}",
        f"- forbidden types never emitted: {', '.join(summary['forbidden_types_never_emitted'])}",
        f"- no_upload: true · upload_performed: false · github_push: false · "
        f"candidate_promoted: false",
        f"- **verification clean (no forbidden / no_upload=false on either "
        f"ledger): {summary['verification']['clean']}**", "",
        "## Routing", "",
        "- MAIN lab ledger: registration, build, validation, smoke, parent/child "
        "H2H, non-inertness, noise control, internal anchors, decision"
        + (", report site" if report_emitted else "") + ".",
        "- BENCHMARK ledger (references stay here): reference calibration, "
        "public-reference eval, dragapult reference anchor.",
        "",
        "Per-game benchmark/tournament events (tagged `pass41`+`benchmark` but not "
        "`pass41_eventset`) are preserved untouched on re-run.",
    ]
    (EXP / "pass41_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} main + {bench_n} benchmark {MARK} events")
    print(f"  main -> {LAB_EVENTS_PATH}")
    print(f"  benchmark -> {BENCHMARK_EVENTS_PATH}")
    print(f"verification clean={summary['verification']['clean']} "
          f"pass41_forbidden_main={main_scan['pass41_forbidden_types']} "
          f"pass41_forbidden_bench={bench_scan['pass41_forbidden_types']} "
          f"(historical_main={main_scan['historical_forbidden_by_type']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"report_site_emitted={report_emitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
