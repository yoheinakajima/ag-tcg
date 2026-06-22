#!/usr/bin/env python3
"""PASS 46H (Part K) — emit LOCAL ActiveGraph events for the within-family
per-option value sprint (owned local-only ``cg_typed`` candidates).

Data-driven from the Part-A..J artifacts. Every event carries ``no_upload=true``
and the tags ``["pass46h", "pass46h_eventset", <sub-step>]``.

HARD: NOTHING is uploaded/submitted/pushed/promoted. There is NO SubmissionQueued,
NO SubmissionUploaded, NO KaggleScoreUpdated, NO CandidatePromoted. The only side
effect is appending to LOCAL ledgers. The shared report SITE is never regenerated
(an optional ``ReportSiteGenerated`` event only references the LOCAL report .md and
sets ``shared_site_regenerated=false``).

Routing (zero public-reference leakage onto the main lab ledger):
  * MAIN lab ledger (``data/activegraph/lab_events.jsonl``) — owned candidates +
    internal lineage only (per-candidate registration/build, pass-level validation
    + smoke, per-candidate non-inertness, within-family distinguishability,
    parent-H2H + intra-family-vs-floor eval, decision, optional report doc).
  * SEPARATE benchmark ledger (``data/tournament/benchmark/benchmark_events.jsonl``)
    — the public-reference eval summary (references stay benchmark-only).

Idempotent (per the unique-sub-step-marker rule): a re-run strips ONLY events
carrying the marker tag ``pass46h_eventset`` from BOTH ledgers before re-emitting;
events from any other pass (or per-game benchmark events lacking this marker) are
preserved untouched.

No exact-damage / lethal / KO / missed-KO / Boss-gust / spread / best-action
claims. All win/loss numbers are LOCAL cabt outcomes, NOT Kaggle scores. A parent
edge indistinguishable from the within-family floor is reported as such, never a
strength claim; an option-value treatment that is distinguishable from the
family-only floor is the honest signal under test.

Outputs: data/experiments/pass46h_events.{json,md}
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
TAG = "pass46h"
MARK = "pass46h_eventset"  # idempotency marker: ONLY this script's logical events

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
    build = _load("pass46h_candidate_build.json")
    val = _load("pass46h_candidate_validation.json")
    smoke = _load("pass46h_smoke_non_inertness.json")
    evalp = _load("pass46h_eval_panel.json")
    dec = _load("pass46h_strategy_decision.json")

    candidates = build.get("candidates", [])
    cand_ids = [c["candidate_id"] for c in candidates]
    admitted = list(smoke.get("admit_to_part_i") or [])
    ni_by_cand = smoke.get("non_inertness_vs_parent") or {}

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
                f"refusing to emit forbidden event type for pass46h: {_et_name(et)}")

    def _main(et: EventType, sub: str, payload: dict,
              parents: list[str] | None = None) -> str:
        nonlocal main_n
        _guard(et)
        body = dict(payload)
        body["no_upload"] = True  # forced invariant, never overridable by a caller
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
        body["no_upload"] = True  # forced invariant, never overridable by a caller
        bench.emit(et, body, tags=[TAG, MARK, sub, "benchmark"])
        bench_n += 1

    # 1) Per-candidate registration (LOCAL-ONLY; NOT a promotion).
    for c in candidates:
        _main(EventType.OwnedCgCandidateRegistered, "registration", {
            "candidate_id": c["candidate_id"], "parent_id": c.get("parent_candidate_id"),
            "parent_family": c.get("parent_family"), "lane": "cg_typed",
            "owned_candidate": True, "public_reference": False,
            "local_registration": "local_only_within_family_option_value_sprint",
            "pool_registration": False, "lifecycle_registration": False,
            "enters_pool_queue_rankings_lineage": False,
            "local_descriptive_record_only": True,
            "profile_id": c.get("profile_id"), "scoring_mode": c.get("scoring_mode"),
            "no_online_search": c.get("no_online_search", True),
            "scorer_source_module": c.get("scorer_source_module"),
            "scorer_schema_version": c.get("scorer_schema_version"),
            "tarball_sha256": c.get("tarball_sha256"),
            "deck_unchanged": c.get("deck_unchanged"),
            "admitted_to_eval_panel": c["candidate_id"] in admitted,
            "promote": False, "queued": False, "republish_required": False,
            "decision": dec.get("decision"),
            "source_artifacts": ["data/experiments/pass46h_candidate_build.json",
                                 "data/experiments/pass46h_strategy_decision.json"]})

    # 2) Per-candidate build -> StrategyIterationCreated.
    for c in candidates:
        _main(EventType.StrategyIterationCreated, "build", {
            "logical_event": "WithinFamilyOptionValueCandidateBuilt",
            "candidate_id": c["candidate_id"], "lane": c.get("lane"),
            "mutation_parent": c.get("mutation_parent"),
            "parent_family": c.get("parent_family"),
            "parent_archetype": c.get("parent_archetype"),
            "profile_id": c.get("profile_id"), "scoring_mode": c.get("scoring_mode"),
            "profile_calibrated": c.get("profile_calibrated"),
            "no_online_search": c.get("no_online_search", True),
            "scorer_schema_version": c.get("scorer_schema_version"),
            "inline_region_byte_identical": c.get("inline_region_byte_identical"),
            "inline_region_sha256": c.get("inline_region_sha256"),
            "deck_unchanged": c.get("deck_unchanged"), "deck_rows": c.get("deck_rows"),
            "tarball": c.get("tarball"), "tarball_sha256": c.get("tarball_sha256"),
            "owned_candidate": True, "public_reference": False,
            "catalog_sha256": build.get("catalog_sha256"),
            "source_artifacts": ["data/experiments/pass46h_candidate_build.json"]})

    # 3) Validation -> CgTypedLaneValidated (pass-level, batch of candidates).
    _main(EventType.CgTypedLaneValidated, "validation", {
        "logical_event": "OwnedCgCandidateBatchValidated",
        "candidate_ids": cand_ids, "n_candidates": val.get("n_candidates"),
        "all_ok": val.get("all_ok"),
        "n_references_checked": val.get("n_references_checked"),
        "cross_candidate": val.get("cross_candidate"),
        "source_artifacts": ["data/experiments/pass46h_candidate_validation.json"]})

    # 4) Smoke -> LocalEvaluationFinished (pass-level).
    sm = smoke.get("smoke") or {}
    _main(EventType.LocalEvaluationFinished, "smoke", {
        "logical_event": "OptionValueSmoke", "evaluation": "candidate_smoke",
        "candidate_ids": cand_ids, "ok": smoke.get("all_ok"),
        "games_total": sm.get("games_total"),
        "games_completed": sm.get("games_completed"),
        "games_error": sm.get("games_error"), "games_timeout": sm.get("games_timeout"),
        "import_or_deck_failures": sm.get("import_or_deck_failures"),
        "all_non_inert_vs_parent": smoke.get("all_non_inert_vs_parent"),
        "all_safe": smoke.get("all_safe"),
        "option_value_active_on_live_frames_any_family":
            smoke.get("option_value_active_on_live_frames_any_family"),
        "admit_to_eval_panel": admitted,
        "root_main_deck_unchanged": sm.get("root_main_deck_unchanged"),
        "caveat": "subprocess-isolated runnability + decision-trace audit; win/loss is "
                  "feasibility context only, NOT a strength or Kaggle claim",
        "source_artifacts": ["data/experiments/pass46h_smoke_non_inertness.json"]})

    # 5) Per-candidate non-inertness -> CandidateNonInertnessMeasured.
    for cid, ni in ni_by_cand.items():
        _main(EventType.CandidateNonInertnessMeasured, "non_inertness", {
            "candidate_id": cid, "parent_id": ni.get("parent_candidate_id"),
            "parent_family": ni.get("parent_family"), "profile_id": ni.get("profile_id"),
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
            "source_artifacts": ["data/experiments/pass46h_smoke_non_inertness.json"]})

    # 6) Within-family distinguishability (option-value vs family-only floor, Part H).
    _main(EventType.LocalEvaluationFinished, "within_family_distinguishability", {
        "logical_event": "WithinFamilyOptionValueDistinguishability",
        "evaluation": "within_family_distinguishability",
        "within_family_distinguishability": smoke.get("within_family_distinguishability"),
        "option_value_active_on_live_frames_any_family":
            smoke.get("option_value_active_on_live_frames_any_family"),
        "caveat": "top-1 menu-choice divergence between within-family profiles on parent "
                  "replay frames (multi-option frames only; no opponent hidden zones "
                  "used); a coarse interpretability check of whether per-option VISIBLE "
                  "features move the top pick off the family-only floor, not strength",
        "source_artifacts": ["data/experiments/pass46h_smoke_non_inertness.json"]})

    # 7) Parent-H2H + intra-family-vs-floor eval (per pairing).
    pairings = evalp.get("pairings", [])
    for p in pairings:
        if p["kind"] == "parent_h2h":
            started = _main(EventType.ParentChildComparisonStarted, "parent_h2h", {
                "candidate_id": p["subject"], "parent_id": p["opp_id"],
                "lane": "parent_h2h"})
            _main(EventType.ParentChildComparisonFinished, "parent_h2h", {
                "logical_event": "ParentH2HEval", "candidate_id": p["subject"],
                "parent_id": p["opp_id"], "family": p.get("family"),
                "profile": p.get("profile"),
                "record": f"{p['wins']}W/{p['losses']}L/{p['draws']}D",
                "win_rate_decisive": p.get("win_rate_decisive"),
                "wilson95": [p.get("wilson_low"), p.get("wilson_high")],
                "beats_parent_95": p.get("beats_opp_95"),
                "loses_to_parent_95": p.get("loses_to_opp_95"),
                "superiority_claim_caveat": (
                    "LOCAL-ONLY; an edge is claimed only if Wilson lower > 0.5. An "
                    "edge indistinguishable from the within-family floor is NOT an "
                    "option-value success. NOT a Kaggle score."),
                "source_artifacts": ["data/experiments/pass46h_eval_panel.json"]},
                parents=[started])
        elif p["kind"] == "intra_family_vs_floor":
            _main(EventType.LocalEvaluationFinished, "intra_family", {
                "logical_event": "IntraFamilyOptionValueVsFloor",
                "evaluation": "intra_family_vs_floor",
                "subject": p["subject"], "opponent": p["opp_id"],
                "family": p.get("family"), "profile": p.get("profile"),
                "record": f"{p['wins']}W/{p['losses']}L/{p['draws']}D",
                "win_rate_decisive": p.get("win_rate_decisive"),
                "wilson95": [p.get("wilson_low"), p.get("wilson_high")],
                "beats_floor_95": p.get("beats_opp_95"),
                "loses_to_floor_95": p.get("loses_to_opp_95"),
                "indistinct_spans_half": (not p.get("beats_opp_95")
                                          and not p.get("loses_to_opp_95")),
                "caveat": "an option-value treatment vs its OWN-family family-only floor "
                          "sibling; a result distinguishable from the floor is the honest "
                          "signal under test, an indistinct one adds no separable signal",
                "source_artifacts": ["data/experiments/pass46h_eval_panel.json"]})

    # 8) Decision -> StrategyDecisionRecorded.
    _main(EventType.StrategyDecisionRecorded, "decision", {
        "pass": "46h", "decision_label": dec.get("decision"),
        "gates": dec.get("gates"),
        "coherent_escape_candidates": dec.get("coherent_escape_candidates"),
        "live_distinct_only_candidates": dec.get("live_distinct_only_candidates"),
        "gameplay_only_variance_candidates": dec.get("gameplay_only_variance_candidates"),
        "option_value_escapes_46g_top1_inertness":
            dec.get("option_value_escapes_46g_top1_inertness"),
        "parent_h2h_edge_candidates_95": dec.get("parent_h2h_edge_candidates_95"),
        "parent_edge_established": dec.get("parent_edge_established"),
        "treatment_vs_floor_distinct_in_gameplay":
            dec.get("treatment_vs_floor_distinct_in_gameplay"),
        "next_iteration_levers": dec.get("next_iteration_levers"),
        "promote": False, "queue": False, "upload": False, "submit": False,
        "github_push": False, "auto_submit": False,
        "candidate_generation_for_prod": False,
        "human_approval_required_for_prod": True,
        "source_artifacts": ["data/experiments/pass46h_strategy_decision.json"]})

    # 9) Report doc (only if the Part-M report already exists). The shared report
    #    SITE is NOT regenerated — this only references the local report .md.
    report_md = RPT / "pass46h_within_family_option_value_report.md"
    report_emitted = report_md.exists()
    if report_emitted:
        _main(EventType.ReportSiteGenerated, "report", {
            "pass": "46h", "reports": [str(report_md.relative_to(REPO))],
            "shared_site_regenerated": False,
            "decision_label": dec.get("decision"),
            "source_artifacts": [str(report_md.relative_to(REPO))]})

    # ---- BENCHMARK LEDGER: public-reference eval summary (refs stay here) ----
    ref_rows = [p for p in pairings if p["kind"] == "reference_context"]
    ref_ids_excluded = sorted({r["opp_id"] for r in ref_rows})
    _bench(EventType.LocalEvaluationFinished, "public_ref_eval", {
        "logical_event": "PublicReferenceEval", "evaluation": "candidates_vs_references",
        "candidate_ids": sorted({r["subject"] for r in ref_rows}),
        "benchmark_only": True, "promotion_relevant": False,
        "references_as_source_parent_candidate": False,
        "reference_ids_excluded_from_lineage": ref_ids_excluded,
        "per_pairing": [
            {"subject": r["subject"], "reference": r["opp_id"],
             "record": f"{r['wins']}W/{r['losses']}L/{r['draws']}D",
             "loses_to_ref_95": r.get("loses_to_opp_95")} for r in ref_rows],
        "references_not_in_pool": evalp.get("references_not_in_pool"),
        "caveat": ("owned candidates measured AGAINST public references as benchmark "
                   "opponents ONLY; never a 'beats reference' or promotion claim; "
                   "references never enter pool/queue/lifecycle/rankings/lineage"),
        "source_artifacts": ["data/experiments/pass46h_eval_panel.json"]})

    main_scan = _scan_forbidden(LAB_EVENTS_PATH)
    bench_scan = _scan_forbidden(BENCHMARK_EVENTS_PATH)
    clean = (not main_scan["forbidden_types"] and not bench_scan["forbidden_types"]
             and main_scan["no_upload_false"] == 0 and bench_scan["no_upload_false"] == 0)

    summary = {
        "schema": "pass46h_events_v1", "pass": "46h", "part": "K",
        "candidate_ids": cand_ids, "admitted_to_eval_panel": admitted,
        "marker_tag": MARK, "base_tag": TAG,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_promoted": False,
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
            "main_historical_forbidden_pre_pass46h": main_scan["historical"],
            "benchmark_historical_forbidden_pre_pass46h": bench_scan["historical"],
            "clean": clean},
    }
    (EXP / "pass46h_events.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Pass 46H (Part K) — ActiveGraph Events", "",
        f"- candidates: {', '.join(f'`{c}`' for c in cand_ids)}",
        f"- admitted to eval panel: {', '.join(f'`{c}`' for c in admitted)}",
        f"- decision: **`{dec.get('decision')}`**",
        f"- marker tag (idempotency): `{MARK}` · base tag: `{TAG}`",
        f"- emitted: **{main_n}** on main lab ledger, **{bench_n}** on benchmark ledger",
        f"- report-doc event emitted: **{report_emitted}** "
        "(re-run after the Part-M report exists to add it)",
        "- shared report SITE regenerated: **false** (event references the local "
        "report .md only)",
        f"- forbidden types never emitted: "
        f"{', '.join(summary['forbidden_types_never_emitted'])}",
        "- no_upload: true · upload_performed: false · github_push: false · "
        "candidate_promoted: false",
        f"- **verification clean (no forbidden / no_upload=false this pass on either "
        f"ledger): {clean}**", "",
        "## Routing", "",
        "- MAIN lab ledger: per-candidate registration + build, pass-level validation "
        "+ smoke, per-candidate non-inertness, within-family distinguishability, "
        "parent-H2H + intra-family-vs-floor eval, decision"
        + (", report doc" if report_emitted else "") + ".",
        "- BENCHMARK ledger (public references stay here): public-reference eval "
        "summary only.", "",
        "Events from other passes and per-game benchmark events (lacking the "
        f"`{MARK}` marker) are preserved untouched on re-run.",
        "", "_Win/loss is LOCAL feasibility context, NOT a Kaggle score. A parent edge "
        "indistinguishable from the within-family floor is NOT an option-value success; "
        "an option-value treatment distinguishable from the family-only floor is the "
        "honest signal under test._", ""]
    (EXP / "pass46h_events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"emitted {main_n} main + {bench_n} benchmark {MARK} events")
    print(f"verification clean={clean} main_forbidden={main_scan['forbidden_types']} "
          f"bench_forbidden={bench_scan['forbidden_types']} "
          f"(historical_main={main_scan['historical']})")
    print(f"SubmissionQueued=0 SubmissionUploaded=0 CandidatePromoted=0 "
          f"report_doc_emitted={report_emitted}")
    if not clean:
        print("FATAL: ledger scan NOT clean for pass46h — forbidden type or "
              "no_upload=false detected; treat as a safety failure.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
