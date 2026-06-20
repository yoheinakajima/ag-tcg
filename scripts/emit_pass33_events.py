#!/usr/bin/env python3
"""Pass 33 (Part L) — emit ActiveGraph events for the deck composition stress test.

Data-driven from the Pass-33 artifacts. Emits:
- StrategyIterationCreated       : the two NEW composition variants (Part E).
- DeckVariantCreated             : same NEW variants, structural view.
- LocalEvaluationFinished        : the internal composition tournament (Part G).
- CandidateRanked                : one per Stage-1 standing (Part G).
- ParentChildComparisonFinished  : one per parent/child confirmation (Part I).
- StrategyIterationEvaluated     : one per meta-sanity subject (Part J).
- StrategyDecisionRecorded       : the gated dry-run decision (Part K).
- SubmissionQueued               : the single HELD dry-run queue entry (Part K, if any).
- ReportSiteGenerated            : the Part-M reports/site.

Every event carries no_upload=true and a "pass33" tag. The only side effect is
appending to the local lab event store — nothing is uploaded to Kaggle or pushed to
GitHub. Idempotent: re-running strips previously-emitted "pass33" events first.
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
TAG = "pass33"


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
    manifest = _load("pass33_composition_variants_manifest.json")
    rank1 = _load("pass33_composition_rankings.json")
    pc = _load("pass33_parent_child_confirmations.json")
    meta = _load("pass33_meta_sanity.json")
    decision = _load("pass33_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale {TAG} events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) StrategyIterationCreated + 2) DeckVariantCreated — the NEW variants only.
    new_ids = []
    for v in (manifest.get("results") or []):
        # only the freshly-built composition variants (not reused/blocked tarballs)
        if v.get("kind") != "built":
            continue
        cid = v.get("candidate_id") or v.get("id")
        if not cid:
            continue
        new_ids.append(cid)
        store.append(new_event(
            EventType.StrategyIterationCreated,
            tags=[TAG, "composition_variant", cid],
            payload={"candidate_id": cid, "family": v.get("family"),
                     "parent": v.get("parent") or v.get("parent_id"),
                     "hypothesis": v.get("rationale") or v.get("hypothesis"),
                     "no_basic_p_before": v.get("no_basic_p_before"),
                     "no_basic_p_after": v.get("no_basic_p_after"),
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False,
                     "source":
                         "data/experiments/pass33_composition_variants_manifest.json",
                     "no_upload": True}))
        n += 1
        store.append(new_event(
            EventType.DeckVariantCreated,
            tags=[TAG, "composition_variant", "new_build", cid],
            payload={"candidate_id": cid, "family": v.get("family"),
                     "parent": v.get("parent") or v.get("parent_id"),
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False,
                     "source":
                         "data/experiments/pass33_composition_variants_manifest.json",
                     "no_upload": True}))
        n += 1

    # 3) LocalEvaluationFinished — the internal composition tournament.
    standings = rank1.get("standings", [])
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "composition_tournament"],
        payload={"participants": len(standings),
                 "games_per_seat_stage1": 3, "games_per_seat_stage2": 10, "stages": 2,
                 "is_kaggle_leaderboard": False,
                 "caveat": ("internal our-vs-our composition tournament with one "
                            "generic pilot; NOT Kaggle, NOT a promotion signal"),
                 "source": "data/experiments/pass33_composition_rankings.json",
                 "no_upload": True}))
    n += 1

    # 4) CandidateRanked — one per Stage-1 standing.
    for i, r in enumerate(standings, 1):
        store.append(new_event(
            EventType.CandidateRanked,
            tags=[TAG, "ranking", r["id"]],
            payload={"rank": i, "candidate_id": r["id"], "family": r.get("family"),
                     "adj_win_rate": r.get("adj_win_rate"), "wilson": r.get("wilson"),
                     "compatibility_label": r.get("compatibility_label"),
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass33_composition_rankings.json",
                     "no_upload": True}))
        n += 1

    # 5) ParentChildComparisonFinished — one per confirmation.
    for c in (pc.get("confirmations") or []):
        store.append(new_event(
            EventType.ParentChildComparisonFinished,
            tags=[TAG, "parent_child", c.get("key", "")],
            payload={"pair": c.get("key"), "parent": c.get("parent"),
                     "child": c.get("child"), "kind": c.get("kind"),
                     "child_adj_win_rate": c.get("child_adj_win_rate"),
                     "child_wilson": c.get("child_wilson"),
                     "verdict": c.get("verdict"),
                     "is_kaggle_leaderboard": False,
                     "source":
                         "data/experiments/pass33_parent_child_confirmations.json",
                     "no_upload": True}))
        n += 1

    # 6) StrategyIterationEvaluated — one per meta-sanity subject.
    for cid, d in (meta.get("per_deck") or {}).items():
        collapses = sorted(
            sf for sf, rr in (d.get("per_archetype") or {}).items()
            if (rr.get("win_rate") or 0.0) < 0.10)
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=[TAG, "meta_sanity", cid],
            payload={"candidate_id": cid, "role": d.get("role"),
                     "weighted_meta_score": d.get("weighted_meta_score"),
                     "collapses": collapses,
                     "surrogate_only": True, "is_kaggle_leaderboard": False,
                     "caveat": ("replay-derived surrogate opponents piloted by a "
                                "generic brain; directional only, NOT Kaggle"),
                     "source": "data/experiments/pass33_meta_sanity.json",
                     "no_upload": True}))
        n += 1

    # 7) StrategyDecisionRecorded — the gated decision.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=[TAG, "decision"],
        payload={"pass": 33, "decision": decision.get("decision"),
                 "recommended_probe_candidate":
                     decision.get("recommended_probe_candidate"),
                 "disposition": decision.get("disposition"),
                 "all_gates_passed": decision.get("all_gates_passed"),
                 "queued_candidate_count": decision.get("queued_candidate_count"),
                 "human_approval_required": True, "auto_submit_enabled": False,
                 "promote": False, "upload": False, "submit": False,
                 "github_push": False, "is_kaggle_leaderboard": False,
                 "source": "data/experiments/pass33_strategy_decision.json",
                 "no_upload": True}))
    n += 1

    # 8) SubmissionQueued — the single HELD dry-run entry (if any).
    if decision.get("queued_candidate_count"):
        store.append(new_event(
            EventType.SubmissionQueued,
            tags=[TAG, "dry_run_queue"],
            payload={"candidate_id": decision.get("recommended_probe_candidate"),
                     "disposition": decision.get("disposition"),
                     "queue_max": 1, "held": True, "auto_submit_enabled": False,
                     "require_manual_approval_for_submit": True,
                     "upload_performed": False, "is_kaggle_leaderboard": False,
                     "source": "data/submission_queue.json", "no_upload": True}))
        n += 1

    # 9) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=[TAG, "report"],
        payload={"pass": 33,
                 "reports": [
                     "data/reports/pass33_deck_composition_stress_test_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md"],
                 "decision": decision.get("decision"), "no_upload": True}))
    n += 1

    print(f"emitted {n} {TAG} events -> {LAB_EVENTS_PATH}")
    print(f"new_variants={len(new_ids)} standings={len(standings)} "
          f"parent_child={len(pc.get('confirmations', []))} "
          f"meta_subjects={len(meta.get('per_deck', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
