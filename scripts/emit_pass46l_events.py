#!/usr/bin/env python3
"""PASS 46L (Part K) — emit LOCAL ActiveGraph events for the Diamond reference-gap planner
v1 CLEAN-NEGATIVE pass.

Data-driven from the Part A/E/F/G/J artifacts. This is a LOCAL-ONLY pass (production keeps
soaking; NOTHING is redeployed). It builds ONE owned candidate
``cg_typed_diamond_specialist_planner_v1`` from the existing v0 via a narrow visible-only diff,
proves it is well-formed (validation + fixtures), measures its v1-vs-v0 non-inertness on REAL
trace frames (the PRE-REGISTERED stage-2 BLOCKING GATE), and — because v1 is DEFINITIVELY INERT
(0 changed decisions) — records the clean ``diamond_v1_not_promising`` decision WITHOUT running
any eval panel. It therefore emits only LOCAL build / evaluation / decision events.

HARD: NOTHING is uploaded / submitted / pushed / promoted / registered / queued / ticked. There
is NO SubmissionQueued, NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted, NO
*Registered/*Promoted, NO TournamentTick*/PublicBenchmarkTick* of any kind. Every event carries
forced ``no_upload=true``. The shared report SITE is never regenerated.

Public references are BENCHMARK-ONLY and EXCLUDED from the decision: no reference panel was run
(the stage-2 gate blocked it), so no reference event is emitted and the ActiveGraph benchmark
ledger is left UNTOUCHED (only scanned for assurance).

Idempotent (unique-sub-step-marker rule): a re-run strips ONLY events carrying the marker tag
``pass46l_eventset`` before re-emitting; events from any other pass are preserved untouched.

Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score, NEVER a strength claim. The
decision ``diamond_v1_not_promising`` is a LOCAL signal — NOT a promotion, NOT a prod change.

Outputs: data/experiments/pass46l_events.{json,md}
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
TAG = "pass46l"
MARK = "pass46l_eventset"  # idempotency marker: ONLY this script's logical events

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
    build = _load("pass46l_candidate_build.json")
    valid = _load("pass46l_candidate_validation.json")
    fixture = _load("pass46l_planner_fixture_validation.json")
    ni = _load("pass46l_non_inertness.json")
    dec = _load("pass46l_strategy_decision.json")

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
                f"refusing to emit forbidden event type for pass46l: {_et_name(et)}")

    def _main(et: EventType, sub: str, payload: dict,
              parents: "list[str] | None" = None) -> str:
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

    # 1) Owned candidate built (LOCAL; narrow visible-only diff from v0; NOT registered).
    build_id = None
    if build:
        build_id = _main(EventType.LocalEvaluationFinished, "candidate_build", {
            "logical_event": "DiamondV1CandidateBuilt",
            "evaluation": "owned_candidate_build",
            "candidate_id": build.get("candidate_id"),
            "planner_parent_candidate_id": build.get("planner_parent_candidate_id"),
            "planner_variant": build.get("planner_variant"),
            "deck_parent_id": build.get("parent_candidate_id"),
            "deck_unchanged": build.get("deck_unchanged"),
            "deck_rows": build.get("deck_rows"),
            "tarball": build.get("tarball"),
            "tarball_sha256": build.get("tarball_sha256"),
            "inline_region_byte_identical": build.get("inline_region_byte_identical"),
            "behavioral_parity_ok": (build.get("parity") or {}).get("behavioral_parity_ok"),
            "owned_candidate": build.get("owned_candidate"),
            "public_reference": build.get("public_reference"),
            "registered": False, "promoted": False, "queued": False, "uploaded": False,
            "caveat": ("OWNED local cg_typed candidate built from the v0 planner via a narrow "
                       "visible-only structural diff; deck byte-identical to the diamond "
                       "parent; NOT registered / promoted / queued / uploaded; NOT a Kaggle "
                       "or strength claim."),
            "source_artifacts": ["data/experiments/pass46l_candidate_build.json"]})

    # 2) Candidate validation + lane separation (cg accepts / stdlib rejects / no ref copy).
    if valid:
        lane = valid.get("lane_separation") or {}
        root = valid.get("root_unchanged") or {}
        deck = valid.get("deck_vs_parent") or {}
        _main(EventType.LocalEvaluationFinished, "validation", {
            "logical_event": "DiamondV1CandidateValidation",
            "evaluation": "validation_and_lane_separation",
            "all_ok": valid.get("all_ok"),
            "cg_typed_lane_accepts": (valid.get("cg_typed_lane_accepts") or {}).get("accepts"),
            "stdlib_lane_rejects": (valid.get("stdlib_lane_rejects") or {}).get("rejects"),
            "no_public_reference_hash_match": lane.get("no_ref_hash_match"),
            "distinct_from_46h_diamond_scorers":
                lane.get("distinct_from_46h_diamond_scorers"),
            "deck_byte_identical_to_parent": deck.get("deck_byte_identical_to_parent"),
            "root_main_unchanged": root.get("root_main_unchanged"),
            "root_deck_unchanged": root.get("root_deck_unchanged"),
            "caveat": ("LOCAL/read-only: the candidate is accepted by the cg_typed lane, "
                       "rejected (byte-unchanged) by the stdlib lane, copies NO public-reference "
                       "code, ships the unchanged parent deck, and leaves root main.py/deck.csv "
                       "untouched."),
            "source_artifacts": ["data/experiments/pass46l_candidate_validation.json"]},
            parents=[build_id] if build_id else None)

    # 3) Planner fixtures (per-context legality + honesty + hidden-zone invariance).
    if fixture:
        _main(EventType.LocalEvaluationFinished, "fixtures", {
            "logical_event": "DiamondV1PlannerFixtures",
            "evaluation": "fixture_validation",
            "all_ok": fixture.get("all_ok"),
            "n_fixtures": fixture.get("n_fixtures"),
            "all_indices_legal": fixture.get("all_indices_legal"),
            "contexts_covered": fixture.get("contexts_covered"),
            "unsupported_claims_all_categories":
                (fixture.get("claims_honesty") or {}).get("all_categories_covered"),
            "no_claimy_field_names":
                (fixture.get("claims_honesty") or {}).get("no_claimy_field_names"),
            "decisions_invariant_to_hidden_zones":
                (fixture.get("hidden_zone") or {}).get(
                    "all_decisions_invariant_to_hidden_zones"),
            "caveat": ("Crafted fixtures only; proves the v1 planner returns legal indices, "
                       "dispatches every context, keeps unsupported claims unsupported (no "
                       "exact-damage / lethal / KO / Boss-gust / spread / best-action), and is "
                       "invariant to hidden-opponent-zone contents."),
            "source_artifacts": ["data/experiments/pass46l_planner_fixture_validation.json"]},
            parents=[build_id] if build_id else None)

    # 4) Non-inertness — the PRE-REGISTERED stage-2 BLOCKING GATE (v1-vs-v0 on REAL frames).
    ni_id = None
    if ni:
        ni_id = _main(EventType.LocalEvaluationFinished, "non_inertness", {
            "logical_event": "DiamondV1NonInertnessGate",
            "evaluation": "v1_vs_v0_changed_decision_rate_on_real_frames",
            "blocking_gate": True,
            "complete": ni.get("complete"),
            "frames": ni.get("frames"),
            "changed_decisions": ni.get("changed_decisions"),
            "changed_decision_rate": ni.get("changed_decision_rate"),
            "non_inert_min_rate": ni.get("non_inert_min_rate"),
            "changes_in_relevant_context": ni.get("changes_in_relevant_context"),
            "v1_illegal_decisions": ni.get("v1_illegal_decisions"),
            "v1_fallback_empty": ni.get("v1_fallback_empty"),
            "attach_multi_frames": ni.get("attach_multi_frames"),
            "attach_multi_changed": ni.get("attach_multi_changed"),
            "non_inert_gate_pass": ni.get("non_inert_gate_pass"),
            "reference_benchmark_only": ni.get("reference_benchmark_only"),
            "gate_interpretation": ni.get("gate_interpretation"),
            "caveat": ("v1 is DEFINITIVELY INERT vs v0 on real trace frames (0 changed "
                       "decisions): the narrow visible-only structural levers move the attach "
                       "active-vs-bench crossover only fractionally and the active-preference "
                       "already dominates in v0, so the argmax is unchanged. The gate therefore "
                       "BLOCKS all eval panels. Reference frames are benchmark-only and were "
                       "NOT used to gate."),
            "source_artifacts": ["data/experiments/pass46l_non_inertness.json"]},
            parents=[build_id] if build_id else None)

    # 5) Decision -> StrategyDecisionRecorded (LOCAL-ONLY; explicitly NOT a promotion).
    if dec:
        ev = dec.get("evidence") or {}
        _main(EventType.StrategyDecisionRecorded, "decision", {
            "pass": "46L", "decision_label": dec.get("decision"),
            "subject_under_test": dec.get("subject_under_test"),
            "planner_parent_id": dec.get("planner_parent_id"),
            "deck_parent_id": dec.get("deck_parent_id"),
            "reference_gap_improved": dec.get("reference_gap_improved"),
            "reasons": dec.get("reasons"),
            "allowed_decisions": dec.get("allowed_decisions"),
            "blocking_gate": dec.get("blocking_gate"),
            "changed_decisions": ev.get("changed_decisions"),
            "non_inertness_frames": ev.get("non_inertness_frames"),
            "changed_decision_rate": ev.get("changed_decision_rate"),
            "references_excluded": ev.get("references_excluded"),
            "decision_independent_of_references":
                dec.get("decision_independent_of_references"),
            "references_benchmark_only": dec.get("references_benchmark_only"),
            "panels_run": dec.get("panels_run"),
            "inertness_finding": dec.get("inertness_finding"),
            "next_step_note": dec.get("next_step_note"),
            # explicit negative invariants — this LOCAL decision changes nothing in prod:
            "promote": False, "queue": False, "upload": False, "submit": False,
            "register": False, "github_push": False, "auto_submit": False,
            "redeploy": False, "prod_mutated": False, "tick_executed": False,
            "candidate_generation_for_prod": False,
            "human_approval_required_for_prod": True,
            "local_only": True, "no_upload": True,
            "source_artifacts": ["data/experiments/pass46l_strategy_decision.json"]},
            parents=[x for x in [ni_id, build_id] if x])

    # 6) Report doc (only if the Part-M report already exists). Shared SITE NOT regenerated.
    report_md = RPT / "pass46l_diamond_reference_gap_planner_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46L", "reports": [str(report_md.relative_to(REPO))],
            "shared_site_regenerated": False,
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)  # untouched; scanned for assurance
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46l_events_v1", "pass": "46L", "part": "K",
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False, "candidate_registered": False,
        "redeploy": False, "prod_mutated": False, "tick_executed": False,
        "shared_report_site_regenerated": False,
        "decision_label": dec.get("decision"),
        "panels_run": dec.get("panels_run", False),
        "references_benchmark_only": True,
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
            "main_historical_forbidden_pre_pass46l": main_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46l_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46L (Part K) — ActiveGraph Events", "",
        f"- decision: **`{dec.get('decision')}`** (LOCAL-ONLY signal — NOT a promotion)",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on the main lab ledger",
        f"- report-doc event emitted: **{report_emitted}** "
        "(re-run after the Part-M report exists to add it)",
        "- shared report SITE regenerated: **false** (event references the local report "
        ".md only)",
        "- NO registration / promotion / redeploy / tick / queue / upload events (production "
        "keeps soaking untouched)",
        "- NO eval-panel or reference events: the stage-2 non-inertness gate BLOCKED panels; "
        "public references stayed benchmark-only and the ActiveGraph benchmark ledger is "
        "untouched (only scanned for assurance)",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · redeploy: false "
        "· tick_executed: false · candidate_promoted: false · candidate_registered: false",
        f"- **verification clean (no forbidden / no_upload=false this pass): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: owned candidate build, candidate validation, planner fixtures, "
        "non-inertness blocking gate, decision" + (", report doc" if report_emitted else "")
        + ".",
        f"- Events from other passes (lacking the `{MARK}` marker) are preserved untouched "
        "on re-run.", "",
        "_Win/loss is LOCAL cabt feasibility context, NOT a Kaggle score. "
        "`diamond_v1_not_promising` is a clean negative justified by the inert stage-2 gate; "
        "it is NOT a promotion, NOT a prod change, and requires human approval before any prod "
        "candidate work. Public-reference distance is benchmark-only and never gated._", ""]
    (EXP / "pass46l_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} {MARK} events on main lab ledger")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"CandidateRegistered=0 redeploy=0 tick=0 report_doc_emitted={report_emitted}")
    if not clean:
        print("FATAL: ledger scan NOT clean for pass46l — forbidden type or "
              "no_upload=false detected; treat as a safety failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
