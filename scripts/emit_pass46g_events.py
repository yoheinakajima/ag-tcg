#!/usr/bin/env python3
"""PASS 46G (Part J) — emit LOCAL ActiveGraph events for the multi-profile
turn-planner sprint (4 owned local-only cg_typed candidates).

Data-driven from the Part-A..I artifacts. Every event carries ``no_upload=true``
and the tags ``["pass46g", "pass46g_eventset", <sub-step>]``.

HARD: NOTHING is uploaded/submitted/pushed/promoted. There is NO SubmissionQueued,
NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted. The only side
effect is appending to LOCAL ledgers.

Routing (zero public-reference leakage onto the main lab ledger):
  * MAIN lab ledger (``data/activegraph/lab_events.jsonl``) — owned candidates +
    internal lineage only (per-candidate registration/build, pass-level validation
    + smoke, per-candidate non-inertness, parent-H2H + intra-family phase-vs-role
    eval, decision, optional report site).
  * SEPARATE benchmark ledger (``data/tournament/benchmark/benchmark_events.jsonl``)
    — the public-reference eval summary (references stay benchmark-only).

Idempotent (per the unique-sub-step-marker rule): a re-run strips ONLY events
carrying the marker tag ``pass46g_eventset`` from BOTH ledgers before re-emitting;
events from any other pass (or per-game benchmark events lacking this marker) are
preserved untouched.

No exact-damage / lethal / KO / Boss-gust / spread / best-action claims. All
win/loss numbers are LOCAL cabt outcomes, NOT Kaggle scores. A parent edge that is
indistinguishable from the family-only floor is a FAMILY-WEIGHTED TRANSFER signal,
never a phase/role success.

Outputs: data/experiments/pass46g_events.{json,md}
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
TAG = "pass46g"
MARK = "pass46g_eventset"  # idempotency marker: ONLY this script's logical events

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
    build = _load("pass46g_candidate_build.json")
    val = _load("pass46g_candidate_validation.json")
    smoke = _load("pass46g_smoke_non_inertness.json")
    evalp = _load("pass46g_eval_panel.json")
    dec = _load("pass46g_strategy_decision.json")
    source = _load("pass46g_source_selection.json")

    candidates = build.get("candidates", [])
    cand_ids = [c["candidate_id"] for c in candidates]
    admitted = list(smoke.get("admit_to_part_h") or [])
    ni_by_cand = smoke.get("non_inertness_vs_parent") or {}

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

    # 1) Per-candidate registration (LOCAL-ONLY; NOT a promotion).
    for c in candidates:
        _main(EventType.OwnedCgCandidateRegistered, "registration", {
            "candidate_id": c["candidate_id"], "parent_id": c.get("parent_candidate_id"),
            "parent_family": c.get("parent_family"), "lane": "cg_typed",
            "owned_candidate": True, "public_reference": False,
            "local_registration": "local_only_multi_profile_sprint",
            "pool_registration": False, "lifecycle_registration": False,
            "enters_pool_queue_rankings_lineage": False,
            "local_descriptive_record_only": True,
            "profile_id": c.get("profile_id"), "profile_role": c.get("profile_role"),
            "no_online_search": c.get("no_online_search", True),
            "scorer_source_module": c.get("scorer_source_module"),
            "scorer_schema_version": c.get("scorer_schema_version"),
            "tarball_sha256": c.get("tarball_sha256"),
            "deck_unchanged": c.get("deck_unchanged"),
            "admitted_to_eval_panel": c["candidate_id"] in admitted,
            "promote": False, "queued": False, "republish_required": False,
            "decision": dec.get("decision"),
            "source_artifacts": ["data/experiments/pass46g_candidate_build.json",
                                 "data/experiments/pass46g_strategy_decision.json"]})

    # 2) Per-candidate build -> StrategyIterationCreated.
    for c in candidates:
        _main(EventType.StrategyIterationCreated, "build", {
            "logical_event": "MultiProfileTurnPlannerCandidateBuilt",
            "candidate_id": c["candidate_id"], "lane": c.get("lane"),
            "mutation_parent": c.get("mutation_parent"),
            "parent_family": c.get("parent_family"),
            "parent_archetype": c.get("parent_archetype"),
            "profile_id": c.get("profile_id"), "profile_role": c.get("profile_role"),
            "profile_calibrated": c.get("profile_calibrated"),
            "no_online_search": c.get("no_online_search", True),
            "scorer_schema_version": c.get("scorer_schema_version"),
            "inline_region_byte_identical": c.get("inline_region_byte_identical"),
            "inline_region_sha256": c.get("inline_region_sha256"),
            "deck_unchanged": c.get("deck_unchanged"), "deck_rows": c.get("deck_rows"),
            "tarball": c.get("tarball"), "tarball_sha256": c.get("tarball_sha256"),
            "owned_candidate": True, "public_reference": False,
            "catalog_sha256": build.get("catalog_sha256"),
            "source_artifacts": ["data/experiments/pass46g_candidate_build.json"]})

    # 3) Validation -> CgTypedLaneValidated (pass-level, batch of candidates).
    _main(EventType.CgTypedLaneValidated, "validation", {
        "logical_event": "OwnedCgCandidateBatchValidated",
        "candidate_ids": cand_ids, "n_candidates": val.get("n_candidates"),
        "all_ok": val.get("all_ok"),
        "n_references_checked": val.get("n_references_checked"),
        "cross_candidate": val.get("cross_candidate"),
        "source_artifacts": ["data/experiments/pass46g_candidate_validation.json"]})

    # 4) Smoke -> LocalEvaluationFinished (pass-level).
    sm = smoke.get("smoke") or {}
    _main(EventType.LocalEvaluationFinished, "smoke", {
        "logical_event": "MultiProfileSmoke", "evaluation": "candidate_smoke",
        "candidate_ids": cand_ids, "ok": smoke.get("all_ok"),
        "games_total": sm.get("games_total"),
        "games_completed": sm.get("games_completed"),
        "games_error": sm.get("games_error"), "games_timeout": sm.get("games_timeout"),
        "import_or_deck_failures": sm.get("import_or_deck_failures"),
        "all_non_inert_vs_parent": smoke.get("all_non_inert_vs_parent"),
        "all_safe": smoke.get("all_safe"),
        "admit_to_part_h": admitted,
        "root_main_deck_unchanged": sm.get("root_main_deck_unchanged"),
        "caveat": "subprocess-isolated runnability + decision-trace audit; win/loss is "
                  "feasibility context only, NOT a strength or Kaggle claim",
        "source_artifacts": ["data/experiments/pass46g_smoke_non_inertness.json"]})

    # 5) Per-candidate non-inertness -> CandidateNonInertnessMeasured.
    for cid, ni in ni_by_cand.items():
        _main(EventType.CandidateNonInertnessMeasured, "non_inertness", {
            "candidate_id": cid, "parent_id": ni.get("parent_candidate_id"),
            "non_inert": ni.get("non_inert"), "safe": ni.get("safe"),
            "changed_rate": ni.get("changed_rate"),
            "agreement_with_parent": ni.get("agreement_with_parent"),
            "n_parent_frames": ni.get("n_parent_frames"),
            "distinct_families": ni.get("candidate_distinct_families"),
            "illegal_decisions": ni.get("illegal_decisions"),
            "fallback_used": ni.get("fallback_used"),
            "exceptions": ni.get("exceptions"),
            "caveat": "decision-trace audit on parent ACTIVE replay frames; no game "
                      "execution; non-inertness is SAFETY, not strength",
            "source_artifacts": ["data/experiments/pass46g_smoke_non_inertness.json"]})

    # 6) Internal distinguishability (phase/role vs family-only floor, Part G).
    _main(EventType.LocalEvaluationFinished, "internal_distinguishability", {
        "logical_event": "PhaseRoleInternalDistinguishability",
        "evaluation": "internal_distinguishability",
        "internal_distinguishability": smoke.get("internal_distinguishability"),
        "caveat": "top-1 menu-choice divergence between profiles on parent replay "
                  "frames; role == family-only floor at top-1 (no opponent hidden "
                  "zones used); a coarse interpretability check, not strength",
        "source_artifacts": ["data/experiments/pass46g_smoke_non_inertness.json"]})

    # 7) Parent-H2H + intra-family phase-vs-role eval (per pairing).
    pairings = evalp.get("pairings", [])
    for p in pairings:
        if p["kind"] == "parent_h2h":
            started = _main(EventType.ParentChildComparisonStarted, "parent_h2h", {
                "candidate_id": p["subject"], "parent_id": p["opp_id"],
                "lane": "parent_h2h"})
            _main(EventType.ParentChildComparisonFinished, "parent_h2h", {
                "logical_event": "ParentH2HEval", "candidate_id": p["subject"],
                "parent_id": p["opp_id"], "record":
                f"{p['wins']}W/{p['losses']}L/{p['draws']}D",
                "win_rate_decisive": p.get("win_rate_decisive"),
                "wilson95": [p.get("wilson_low"), p.get("wilson_high")],
                "beats_parent_95": p.get("beats_opp_95"),
                "loses_to_parent_95": p.get("loses_to_opp_95"),
                "superiority_claim_caveat": (
                    "LOCAL-ONLY; an edge is claimed only if Wilson lower > 0.5. An "
                    "edge indistinguishable from the family-only floor is a "
                    "FAMILY-WEIGHTED TRANSFER signal, NOT a phase/role success. "
                    "NOT a Kaggle score."),
                "source_artifacts": ["data/experiments/pass46g_eval_panel.json"]},
                parents=[started])
        elif p["kind"] == "intra_family_phase_vs_role":
            _main(EventType.LocalEvaluationFinished, "intra_family", {
                "logical_event": "IntraFamilyPhaseVsRole",
                "evaluation": "intra_family_phase_vs_role",
                "subject": p["subject"], "opponent": p["opp_id"],
                "record": f"{p['wins']}W/{p['losses']}L/{p['draws']}D",
                "win_rate_decisive": p.get("win_rate_decisive"),
                "wilson95": [p.get("wilson_low"), p.get("wilson_high")],
                "indistinct_spans_half": (not p.get("beats_opp_95")
                                          and not p.get("loses_to_opp_95")),
                "caveat": "phase profile vs its OWN-family role profile (== family-only "
                          "floor at top-1); an indistinct result means the phase layer "
                          "adds no separable gameplay signal",
                "source_artifacts": ["data/experiments/pass46g_eval_panel.json"]})

    # 8) Decision -> StrategyDecisionRecorded.
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46g", "decision_label": dec.get("decision"),
        "gates": dec.get("gates"),
        "parent_h2h_edge_candidates_95": dec.get("parent_h2h_edge_candidates_95"),
        "family_weighted_transfer_signal": dec.get("family_weighted_transfer_signal"),
        "clearer_point_estimate_than_46f": dec.get("clearer_point_estimate_than_46f"),
        "phase_role_layer_inert_top1": dec.get("phase_role_layer_inert_top1"),
        "next_iteration_levers": dec.get("next_iteration_levers"),
        "promote": False, "queue": False, "upload": False, "submit": False,
        "github_push": False, "auto_submit": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "source_artifacts": ["data/experiments/pass46g_strategy_decision.json"]})

    # 9) Report site (only if the Part-L report already exists).
    report_md = RPT / "pass46g_multi_profile_turnplanner_sprint_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46g", "reports": [str(report_md.relative_to(REPO))],
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    # ---- BENCHMARK LEDGER: public-reference eval summary (refs stay here) ----
    ref_rows = [p for p in pairings if p["kind"] == "reference_context"]
    _bench(EventType.LocalEvaluationFinished, "public_ref_eval", {
        "logical_event": "PublicReferenceEval", "evaluation": "candidates_vs_references",
        "candidate_ids": sorted({r["subject"] for r in ref_rows}),
        "benchmark_only": True, "promotion_relevant": False,
        "references_as_source_parent_candidate": False,
        "reference_ids_excluded_from_lineage": source.get("reference_ids_excluded"),
        "per_pairing": [
            {"subject": r["subject"], "reference": r["opp_id"],
             "record": f"{r['wins']}W/{r['losses']}L/{r['draws']}D",
             "loses_to_ref_95": r.get("loses_to_opp_95")} for r in ref_rows],
        "references_not_in_pool": evalp.get("references_not_in_pool"),
        "caveat": ("owned candidates measured AGAINST public references as benchmark "
                   "opponents ONLY; never a 'beats reference' or promotion claim; "
                   "references never enter pool/queue/lifecycle/rankings/lineage"),
        "source_artifacts": ["data/experiments/pass46g_eval_panel.json"]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46g_events_v1", "pass": "46g", "part": "J",
        "candidate_ids": cand_ids, "admitted_to_eval_panel": admitted,
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
            "main_historical_forbidden_pre_pass46g": main_scan["historical"],
            "benchmark_historical_forbidden_pre_pass46g": bench_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46g_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46G (Part J) — ActiveGraph Events", "",
        f"- candidates: {', '.join(f'`{c}`' for c in cand_ids)}",
        f"- admitted to eval panel: {', '.join(f'`{c}`' for c in admitted)}",
        f"- decision: **`{dec.get('decision')}`**",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on main lab ledger, **{bench_n}** on benchmark ledger",
        f"- report-site event emitted: **{report_emitted}** "
        "(re-run after the Part-L report exists to add it)",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · "
        "candidate_promoted: false",
        f"- **verification clean (no forbidden / no_upload=false this pass on either "
        f"ledger): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: per-candidate registration + build, pass-level validation "
        "+ smoke, per-candidate non-inertness, internal distinguishability, parent-H2H "
        "+ intra-family phase-vs-role eval, decision"
        + (", report site" if report_emitted else "") + ".",
        "- BENCHMARK ledger (public references stay here): public-reference eval "
        "summary only.", "",
        "Events from other passes and per-game benchmark events (lacking the "
        f"`{MARK}` marker) are preserved untouched on re-run.",
        "", "_Win/loss is LOCAL feasibility context, NOT a Kaggle score. A parent edge "
        "indistinguishable from the family-only floor is a FAMILY-WEIGHTED TRANSFER "
        "signal, NOT a phase/role success._", ""]
    (EXP / "pass46g_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} main + {bench_n} benchmark {MARK} events")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"report_site_emitted={report_emitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
