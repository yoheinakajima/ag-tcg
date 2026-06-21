#!/usr/bin/env python3
"""PASS 46F (Part J) — emit LOCAL ActiveGraph events for the search-calibrated
fast turn-planner candidate pilot.

Data-driven from the Part-A..I artifacts. Every event carries ``no_upload=true``
and the tags ``["pass46f", "pass46f_eventset", <sub-step>]``.

HARD: NOTHING is uploaded/submitted/pushed/promoted. There is NO SubmissionQueued,
NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted. The only side
effect is appending to LOCAL ledgers.

Routing (zero public-reference leakage onto the main lab ledger):
  * MAIN lab ledger (``data/activegraph/lab_events.jsonl``) — owned candidate +
    internal lineage only (registration, build, validation, smoke, parent H2H,
    non-inertness, noise control, internal anchor, decision, optional report).
  * SEPARATE benchmark ledger (``data/tournament/benchmark/benchmark_events.jsonl``)
    — the public-reference eval summary (references stay benchmark-only).

Idempotent (per the unique-sub-step-marker rule): a re-run strips ONLY events
carrying the marker tag ``pass46f_eventset`` from BOTH ledgers before re-emitting;
events from any other pass (or per-game benchmark events lacking this marker) are
preserved untouched.

No exact-damage/lethal/missed-KO/Boss-gust/spread/best-action claims. All win/loss
numbers are local cabt outcomes, NOT Kaggle scores.

Outputs: data/experiments/pass46f_events.{json,md}
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
TAG = "pass46f"
MARK = "pass46f_eventset"  # idempotency marker: ONLY this script's logical events

FORBIDDEN_TYPES = {
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted",
}


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
    """Audit a ledger; THIS pass must emit no forbidden type and no no_upload=false."""
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
    build = _load("pass46f_candidate_build.json")
    val = _load("pass46f_candidate_validation.json")
    smoke = _load("pass46f_candidate_smoke.json")
    ni = _load("pass46f_non_inertness.json")
    h = _load("pass46f_parent_h2h.json")
    nc = _load("pass46f_noise_control.json")
    anc = _load("pass46f_internal_anchor_eval.json")
    rf = _load("pass46f_public_reference_eval.json")
    dec = _load("pass46f_strategy_decision.json")

    cand_id = build.get("candidate_id") or dec.get("candidate_id")
    parent_id = h.get("parent_id") or build.get("mutation_parent")

    removed_main = _strip(LAB_EVENTS_PATH)
    removed_bench = _strip(BENCHMARK_EVENTS_PATH)
    if removed_main or removed_bench:
        print(f"removed {removed_main} main + {removed_bench} benchmark stale "
              f"{MARK} events (idempotent re-run)")

    store = EventStore(LAB_EVENTS_PATH)
    bench = benchmark_ledger()
    main_n = bench_n = 0

    def _main(et: EventType, sub: str, payload: dict,
              parents: list[str] | None = None) -> str:
        nonlocal main_n
        body = dict(payload)
        body.setdefault("no_upload", True)
        body.setdefault("is_kaggle_leaderboard", False)
        ev = new_event(et, tags=[TAG, MARK, sub], payload=body,
                       parent_event_ids=parents or [])
        store.append(ev)
        main_n += 1
        return ev.event_id

    def _bench(et: EventType, sub: str, payload: dict) -> None:
        nonlocal bench_n
        bench.emit(et, dict(payload), tags=[TAG, MARK, sub, "benchmark"])
        bench_n += 1

    # 1) Registration (LOCAL-ONLY; NOT a promotion).
    _main(EventType.OwnedCgCandidateRegistered, "registration", {
        "candidate_id": cand_id, "parent_id": parent_id, "lane": "cg_typed",
        "owned_candidate": True, "public_reference": False,
        "local_registration": "local_only_pilot",
        "decision": dec.get("decision"),
        "no_online_search": build.get("no_online_search", True),
        "scorer_source_module": build.get("scorer_source_module"),
        "profile_id": build.get("profile_id"),
        "tarball_sha256": build.get("tarball_sha256"),
        "deck_unchanged": build.get("deck_unchanged"),
        "promote": False, "queued": False, "republish_required": False,
        "prod_scheduler_changed": False, "active_cap_changed": False,
        "source_artifacts": ["data/experiments/pass46f_candidate_build.json",
                             "data/experiments/pass46f_strategy_decision.json"]})

    # 2) Build -> StrategyIterationCreated.
    _main(EventType.StrategyIterationCreated, "build", {
        "logical_event": "SearchCalibratedTurnPlannerCandidateBuilt",
        "candidate_id": cand_id, "parent_id": parent_id, "lane": build.get("lane"),
        "mutation_parent": build.get("mutation_parent"),
        "parent_family": build.get("parent_family"),
        "profile_calibrated": build.get("profile_calibrated"),
        "profile_id": build.get("profile_id"),
        "no_online_search": build.get("no_online_search", True),
        "scorer_schema_version": build.get("scorer_schema_version"),
        "inline_region_byte_identical": build.get("inline_region_byte_identical"),
        "parity": build.get("parity"),
        "deck_unchanged": build.get("deck_unchanged"), "deck_rows": build.get("deck_rows"),
        "cg_files": build.get("cg_files"), "tarball": build.get("tarball"),
        "tarball_sha256": build.get("tarball_sha256"),
        "owned_candidate": True, "public_reference": False,
        "source_artifacts": ["data/experiments/pass46f_candidate_build.json"]})

    # 3) Validation -> CgTypedLaneValidated.
    _main(EventType.CgTypedLaneValidated, "validation", {
        "logical_event": "OwnedCgCandidateValidated", "candidate_id": cand_id,
        "all_ok": val.get("all_ok"),
        "cg_typed_lane_accepts": val.get("cg_typed_lane_accepts"),
        "stdlib_lane_rejects": val.get("stdlib_lane_rejects"),
        "lane_separation": val.get("lane_separation"),
        "source_artifacts": ["data/experiments/pass46f_candidate_validation.json"]})

    # 4) Smoke -> LocalEvaluationFinished.
    _main(EventType.LocalEvaluationFinished, "smoke", {
        "logical_event": "OwnedCgCandidateSmoke", "evaluation": "candidate_smoke",
        "candidate_id": cand_id, "ok": smoke.get("ok"),
        "hard_fail": smoke.get("hard_fail"), "games_total": smoke.get("games_total"),
        "games_completed": smoke.get("games_completed"),
        "import_or_deck_failures": smoke.get("import_or_deck_failures"),
        "root_main_deck_unchanged": smoke.get("root_main_deck_unchanged"),
        "references_not_in_pool": smoke.get("references_not_in_pool"),
        "caveat": "subprocess-isolated runnability smoke; win/loss is feasibility "
                  "context only, NOT a strength or Kaggle claim",
        "source_artifacts": ["data/experiments/pass46f_candidate_smoke.json"]})

    # 5) Parent H2H -> ParentChildComparisonStarted + Finished.
    po = h.get("overall", {})
    started = _main(EventType.ParentChildComparisonStarted, "parent_h2h", {
        "candidate_id": cand_id, "parent_id": parent_id, "lane": "parent_h2h"})
    _main(EventType.ParentChildComparisonFinished, "parent_h2h", {
        "logical_event": "ParentH2HEval", "candidate_id": cand_id,
        "parent_id": parent_id, "decisive_win_rate": po.get("decisive_win_rate"),
        "wilson95": po.get("wilson95"), "decisive_n": po.get("decisive"),
        "record": f"{po.get('wins')}W/{po.get('losses')}L/{po.get('draws')}D",
        "by_seat": h.get("by_seat"), "both_seats_winning": h.get("both_seats_winning"),
        "edges_parent_local_only": h.get("edges_parent_local_only"),
        "superiority_claim_caveat": ("LOCAL-ONLY; an edge is claimed only if Wilson "
                                     "lower > 0.5 on BOTH seats AND the self-mirror "
                                     "null corroborates (Fisher). NOT a Kaggle score."),
        "source_artifacts": ["data/experiments/pass46f_parent_h2h.json"]},
        parents=[started])

    # 6) Non-inertness -> CandidateNonInertnessMeasured.
    _main(EventType.CandidateNonInertnessMeasured, "non_inertness", {
        "candidate_id": cand_id, "parent_id": parent_id,
        "non_inert": ni.get("non_inert"), "safe": ni.get("safe"),
        "verdict": ni.get("verdict"), "changed_rate": ni.get("changed_rate"),
        "n_parent_frames": ni.get("n_parent_frames"),
        "distinct_families": ni.get("candidate_distinct_families"),
        "illegal_decisions": ni.get("illegal_decisions"),
        "fallback_used": ni.get("fallback_used"), "exceptions": ni.get("exceptions"),
        "caveat": "decision-trace audit on parent ACTIVE replay frames; no game "
                  "execution; non-inertness is SAFETY, not strength",
        "source_artifacts": ["data/experiments/pass46f_non_inertness.json"]})

    # 7) Self-mirror noise control -> LocalEvaluationFinished.
    _main(EventType.LocalEvaluationFinished, "noise_control", {
        "logical_event": "SelfMirrorNoiseControl", "evaluation": "noise_control",
        "candidate_id": cand_id, "parent_id": parent_id,
        "controls_clean": nc.get("controls_clean"),
        "noise_control_corroborates": nc.get("noise_control_corroborates"),
        "fisher_h2h_vs_mirror_p": nc.get("fisher_h2h_vs_mirror_p"),
        "parent_mirror": nc.get("parent_mirror"),
        "candidate_mirror": nc.get("candidate_mirror"),
        "caveat": "self-mirror nulls calibrate the cabt noise floor; Fisher exact",
        "source_artifacts": ["data/experiments/pass46f_noise_control.json"]})

    # 8) Internal anchor (NOT a public reference) -> LocalEvaluationFinished.
    _main(EventType.LocalEvaluationFinished, "internal_anchor", {
        "logical_event": "InternalAnchorEval", "evaluation": "internal_anchor_eval",
        "candidate_id": cand_id, "anchor_id": anc.get("anchor_id"),
        "is_public_reference": False,
        "decisive_win_rate": (anc.get("overall") or {}).get("decisive_win_rate"),
        "wilson95": (anc.get("overall") or {}).get("wilson95"),
        "caveat": "internal water baseline only; supportive context, not gating",
        "source_artifacts": ["data/experiments/pass46f_internal_anchor_eval.json"]})

    # 9) Decision -> StrategyDecisionRecorded.
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46f", "decision_label": dec.get("decision"),
        "rationale": dec.get("rationale"), "gates": dec.get("gates"),
        "promote": False, "queue": False, "upload": False, "submit": False,
        "github_push": False, "auto_submit": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "source_artifacts": ["data/experiments/pass46f_strategy_decision.json"]})

    # 10) Report site (only if the Part-L report already exists).
    report_md = RPT / "pass46f_search_calibrated_turnplanner_candidate_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46f", "reports": [str(report_md.relative_to(REPO))],
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    # ---- BENCHMARK LEDGER: public-reference eval summary (refs stay here) ---
    _bench(EventType.LocalEvaluationFinished, "public_ref_eval", {
        "logical_event": "PublicReferenceEval", "evaluation": "candidate_vs_references",
        "candidate_id": cand_id, "benchmark_only": True, "promotion_relevant": False,
        "public_refs": rf.get("public_refs"),
        "pooled": rf.get("pooled"), "per_reference": rf.get("per_reference"),
        "references_not_in_pool": rf.get("references_not_in_pool"),
        "references_as_source_parent_candidate": False,
        "caveat": ("owned candidate measured AGAINST public references as benchmark "
                   "opponents ONLY; never a 'beats reference' or promotion claim; "
                   "references never enter pool/queue/lifecycle/rankings"),
        "source_artifacts": ["data/experiments/pass46f_public_reference_eval.json"]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46f_events_v1", "pass": "46f", "part": "J",
        "candidate_id": cand_id, "parent_id": parent_id,
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False,
        "decision_label": dec.get("decision"),
        "forbidden_types_never_emitted": sorted(FORBIDDEN_TYPES),
        "main_ledger": str(LAB_EVENTS_PATH.relative_to(REPO)),
        "benchmark_ledger": str(BENCHMARK_EVENTS_PATH.relative_to(REPO)),
        "emitted_main": main_n, "emitted_benchmark": bench_n,
        "report_site_emitted": report_emitted,
        "stripped_on_rerun": {"main": removed_main, "benchmark": removed_bench},
        "verification": {
            "main_forbidden": main_scan["forbidden_types"],
            "benchmark_forbidden": bench_scan["forbidden_types"],
            "main_no_upload_false": main_scan["no_upload_false"],
            "benchmark_no_upload_false": bench_scan["no_upload_false"],
            "main_historical_forbidden_pre_pass46f": main_scan["historical"],
            "benchmark_historical_forbidden_pre_pass46f": bench_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46f_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46F (Part J) — ActiveGraph Events", "",
        f"- candidate: `{cand_id}` (internal parent `{parent_id}`)",
        f"- decision: **`{dec.get('decision')}`**",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on main lab ledger, **{bench_n}** on benchmark ledger",
        f"- report-site event emitted: **{report_emitted}** "
        "(re-run after the Part-L report exists to add it)",
        f"- forbidden types never emitted: {', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · "
        "candidate_promoted: false",
        f"- **verification clean (no forbidden / no_upload=false this pass on either "
        f"ledger): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: registration, build, validation, smoke, parent H2H, "
        "non-inertness, noise control, internal anchor, decision"
        + (", report site" if report_emitted else "") + ".",
        "- BENCHMARK ledger (public references stay here): public-reference eval "
        "summary only.", "",
        "Events from other passes and per-game benchmark events (lacking the "
        f"`{MARK}` marker) are preserved untouched on re-run.", ""]
    (EXP / "pass46f_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} main + {bench_n} benchmark {MARK} events")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"report_site_emitted={report_emitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
