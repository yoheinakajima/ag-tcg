#!/usr/bin/env python3
"""Pass 35 (T-N) — emit ActiveGraph events for the typed board-aware strategy layer.

Data-driven from the Pass-35 artifacts. Emits the Part-N logical event set; every
event carries no_upload=true and a "pass35" tag. NOTHING is uploaded: there is NO
SubmissionUploaded event and no Kaggle/GitHub side effect. The only side effect is
appending to the local lab event store. Idempotent: a re-run strips previously
emitted "pass35" events first.

Honest enum mapping (NO invented EventType values). Three logical event kinds named
in the plan are not present in the EventType enum, so each maps to the closest
existing real type and records its intended logical name in payload.logical_event:
  StrategyProfileCreated  -> StrategyFamilyRegistered   (one per executable profile)
  CandidateBuilt          -> StrategyIterationCreated    (one per built candidate)
  CandidateValidated      -> ValidationRunFinished       (one per validated candidate)
The rest use their own real types: StrategyFixtureAdded, StrategyIterationEvaluated,
LocalEvaluationFinished, StrategyDecisionRecorded, StrategyPromotionDecision,
ReportSiteGenerated.
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

EXP = REPO / "data" / "experiments"
TAG = "pass35"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path, tag=TAG) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    kept, removed = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            kept.append(line)
            continue
        tags = ev.get("tags") or [] if isinstance(ev, dict) else []
        if tag in tags:
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def main() -> int:
    prof = _load("pass35_strategy_profiles.json")
    gate = _load_report("pass35_typed_strategy_gate.json")
    build = _load("pass35_candidate_build.json")
    valid = _load("pass35_candidate_validation.json")
    replay = _load("pass35_decision_replay.json")
    firing = _load("pass35_typed_firing_probe.json")
    rankings = _load("pass35_rankings.json")
    pc = _load("pass35_parent_child.json")
    meta = _load("pass35_meta_sanity.json")
    decision = _load("pass35_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale {TAG} events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    PROF_SRC = "data/experiments/pass35_strategy_profiles.json"
    GATE_SRC = "data/reports/pass35_typed_strategy_gate.json"
    BUILD_SRC = "data/experiments/pass35_candidate_build.json"
    VAL_SRC = "data/experiments/pass35_candidate_validation.json"
    RANK_SRC = "data/experiments/pass35_rankings.json"
    PC_SRC = "data/experiments/pass35_parent_child.json"
    META_SRC = "data/experiments/pass35_meta_sanity.json"
    DEC_SRC = "data/experiments/pass35_strategy_decision.json"

    profiles = prof.get("profiles", [])
    fire_tot = firing.get("totals", {})
    pairs = {p["child_id"]: p for p in pc.get("pairs", [])}
    meta_pd = (meta.get("sanity", {}) or {}).get("per_deck", {})

    # 1) StrategyProfileCreated -> StrategyFamilyRegistered (executable profiles).
    for p in profiles:
        if not p.get("executable"):
            continue
        store.append(new_event(
            EventType.StrategyFamilyRegistered,
            tags=[TAG, "profile", p["id"]],
            payload={"logical_event": "StrategyProfileCreated",
                     "profile_id": p["id"], "lane": p.get("lane"),
                     "parent": p.get("parent"), "role": p.get("role"),
                     "executable": True,
                     "implemented_contexts": p.get("implemented_contexts"),
                     "unsupported_mechanics": p.get("unsupported_mechanics"),
                     "energy_types": p.get("energy_types"),
                     "refuted": p.get("refuted"),
                     "source_artifacts": [PROF_SRC],
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1
    # special-pilot-only profiles registered but explicitly NOT built/queued.
    for p in profiles:
        if p.get("executable"):
            continue
        store.append(new_event(
            EventType.StrategyBlocked,
            tags=[TAG, "profile", "special_pilot_only", p["id"]],
            payload={"logical_event": "StrategyProfileCreated",
                     "profile_id": p["id"], "executable": False,
                     "special_pilot_required": p.get("special_pilot_required"),
                     "reason": "special-pilot-only; never built, never queued",
                     "source_artifacts": [PROF_SRC],
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 2) StrategyFixtureAdded — one per profile fixture group (gate schema:
    #    profile_id / executable / n_cases / n_passed / ok / path).
    for f in gate.get("fixtures", []) if isinstance(gate.get("fixtures"), list) \
            else []:
        store.append(new_event(
            EventType.StrategyFixtureAdded,
            tags=[TAG, "fixture", f.get("profile_id")],
            payload={"profile_id": f.get("profile_id"),
                     "executable": f.get("executable"),
                     "n_cases": f.get("n_cases"), "n_passed": f.get("n_passed"),
                     "ok": f.get("ok"), "fixture_path": f.get("path"),
                     "source_artifacts": [GATE_SRC],
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 3) CandidateBuilt -> StrategyIterationCreated (built candidates).
    built_ids = []
    for r in build.get("candidates", []):
        if not r.get("built"):
            continue
        cid = r["candidate_id"]
        built_ids.append(cid)
        store.append(new_event(
            EventType.StrategyIterationCreated,
            tags=[TAG, "candidate", cid],
            payload={"logical_event": "CandidateBuilt",
                     "candidate_id": cid, "parent_id": r.get("id"),
                     "parent_tarball": r.get("parent_tarball"),
                     "deck_identical_to_parent": r.get("deck_identical_to_parent"),
                     "deck_count": r.get("deck_count"),
                     "implemented_contexts": r.get("implemented_contexts"),
                     "meta_card_count": r.get("meta_card_count"),
                     "tarball": f"data/submissions/candidates_pass35/{cid}.tar.gz",
                     "source_artifacts": [BUILD_SRC],
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 4) CandidateValidated -> ValidationRunFinished (validated candidates).
    for r in valid.get("records", []):
        store.append(new_event(
            EventType.ValidationRunFinished,
            tags=[TAG, "validation", r["id"]],
            payload={"logical_event": "CandidateValidated",
                     "candidate_id": r["id"], "ok": r.get("ok"),
                     "static": r.get("static"), "import_scan": r.get("import_scan"),
                     "entrypoint_smoke_rc": r.get("entrypoint_smoke_rc"),
                     "self_smoke": r.get("self_smoke"),
                     "control_smoke": r.get("control_smoke"),
                     "parent_child_smoke": r.get("parent_child_smoke"),
                     "source_artifacts": [VAL_SRC],
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 5) StrategyIterationEvaluated — one per tournament participant.
    for i, r in enumerate(rankings.get("overall_ranking", []), 1):
        cid = r["id"]
        md = meta_pd.get(cid, {})
        pcrow = pairs.get(cid, {})
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=[TAG, "tournament", cid],
            payload={"candidate_id": cid, "rank": i,
                     "adj_win_rate": r.get("adj_win_rate"),
                     "wilson": r.get("wilson"), "label": r.get("label"),
                     "games": r.get("games"),
                     "parent_child_classification": pcrow.get("classification"),
                     "superiority_claim": pcrow.get("superiority_claim"),
                     "weighted_meta_score": md.get("weighted_meta_score"),
                     "meta_collapses": md.get("collapses"),
                     "surrogate_only": True,
                     "source_artifacts": [RANK_SRC, PC_SRC, META_SRC],
                     "is_kaggle_leaderboard": False, "no_upload": True}))
        n += 1

    # 6) LocalEvaluationFinished — tournament, parent/child H2H, meta sanity.
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "tournament"],
        payload={"evaluation": "internal_typed_child_tournament",
                 "participants": len(rankings.get("overall_ranking", [])),
                 "caveat": ("internal self-play; every seat is our own typed child "
                            "driven by the same base pilot; NOT Kaggle, NOT a "
                            "promotion signal"),
                 "source_artifacts": [RANK_SRC],
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "parent_child"],
        payload={"evaluation": "control_calibrated_parent_child_h2h",
                 "any_superiority_claim": pc.get("any_superiority_claim"),
                 "classification_counts": pc.get("classification_counts"),
                 "games_done": pc.get("games_done"),
                 "caveat": ("seat-swapped H2H; every child CI required to clear BOTH "
                            "self-mirror noise floors; none did"),
                 "source_artifacts": [PC_SRC],
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1
    san = meta.get("sanity", {})
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "meta_sanity"],
        payload={"evaluation": "replay_derived_meta_sanity",
                 "subjects": len(meta_pd),
                 "sanity_passed": san.get("sanity_passed"),
                 "surrogate_only": True,
                 "caveat": ("replay-derived surrogate opponents; directional only, "
                            "NOT Kaggle"),
                 "source_artifacts": [META_SRC],
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1

    # 7) StrategyDecisionRecorded — the gated dry-run decision.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=[TAG, "decision"],
        payload={"pass": 35, "decision_label": decision.get("decision"),
                 "held_probe": decision.get("held_probe"),
                 "held_probe_reaffirmed": decision.get("held_probe_reaffirmed"),
                 "queued_candidate_count": decision.get("queued_candidate_count"),
                 "any_superiority_claim": decision.get("any_superiority_claim"),
                 "typed_layer_safe": decision.get(
                     "typed_layer_safe_no_illegal_refinements"),
                 "decision_labels": decision.get("decision_labels"),
                 "human_approval_required": True, "auto_submit_enabled": False,
                 "promote": False, "upload": False, "submit": False,
                 "github_push": False, "is_kaggle_leaderboard": False,
                 "source_artifacts": [DEC_SRC], "no_upload": True}))
    n += 1

    # 8) StrategyPromotionDecision — explicit "no typed child promoted" + held queue.
    store.append(new_event(
        EventType.StrategyPromotionDecision,
        tags=[TAG, "promotion"],
        payload={"pass": 35, "promoted": False,
                 "no_typed_child_promoted_to_queue": True,
                 "any_typed_child_displaces_held": decision.get(
                     "any_typed_child_displaces_held"),
                 "held_probe": decision.get("held_probe"),
                 "queued_candidate_count": decision.get("queued_candidate_count"),
                 "queue_max": decision.get("queue_max"),
                 "auto_submit_enabled": False,
                 "require_manual_approval_for_submit": True,
                 "upload_performed": False, "is_kaggle_leaderboard": False,
                 "reason": ("typed layer safe + meta-sane but no control-calibrated "
                            "superiority over any parent; held probe re-affirmed"),
                 "source_artifacts": [DEC_SRC, "data/submission_queue.json"],
                 "no_upload": True}))
    n += 1

    # 9) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=[TAG, "report"],
        payload={"pass": 35,
                 "reports": [
                     "data/reports/pass35_final_report.md",
                     "data/reports/pass35_typed_strategy_portfolio_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/reports/pass35_typed_strategy_gate.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                     "docs/TYPED_AGENT_ARCHITECTURE.md"],
                 "decision_label": decision.get("decision"),
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1

    print(f"emitted {n} {TAG} events -> {LAB_EVENTS_PATH}")
    print(f"profiles={len(profiles)} built={len(built_ids)} "
          f"validated={len(valid.get('records', []))} "
          f"participants={len(rankings.get('overall_ranking', []))} "
          f"queued={decision.get('queued_candidate_count')} "
          f"firing_rate={fire_tot.get('overall_firing_rate_pct')}% "
          "SubmissionUploaded=0")
    return 0


def _load_report(name: str) -> dict:
    try:
        return json.loads((REPO / "data" / "reports" / name).read_text(
            encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    sys.exit(main())
