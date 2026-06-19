#!/usr/bin/env python3
"""Pass 30 (Part L) — emit ActiveGraph events for the existing-portfolio hardening.

Data-driven from the Pass-30 artifacts. Emits:
- StrategyFamilyRegistered      : one per portfolio family (Part C).
- DeckVariantCreated            : the two NEW Raging Bolt structural variants (Part E).
- LocalEvaluationFinished       : the internal tournament run (Part G).
- CandidateRanked               : one per tournament standing (Part G).
- ParentChildComparisonFinished : one per parent/child confirmation (Part H).
- StrategyIterationEvaluated     : one per family hardening diagnosis (Part J).
- StrategyDecisionRecorded      : the gated dry-run decision (Part K).
- SubmissionQueued              : the single HELD dry-run queue entry (Part K).
- ReportSiteGenerated           : the Part-M reports/site.

Every event carries no_upload=true and a "pass30" tag. The only side effect is
appending to the local lab event store — nothing is uploaded to Kaggle or pushed
to GitHub. Idempotent: re-running strips previously-emitted "pass30" events first.
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


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path, tag="pass30") -> int:
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
    registry = _load("pass30_existing_portfolio_registry.json")
    manifest = _load("pass30_candidate_manifest.json")
    rank1 = _load("pass30_portfolio_rankings.json")
    pc = _load("pass30_parent_child_confirmations.json")
    diag = _load("pass30_hardening_diagnosis.json")
    decision = _load("pass30_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass30 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) StrategyFamilyRegistered — one per portfolio family.
    fams = registry.get("families") or []
    for fam in fams:
        fid = fam.get("family_id") or fam.get("family_key")
        store.append(new_event(
            EventType.StrategyFamilyRegistered,
            tags=["pass30", "family", fid],
            payload={"family": fid, "family_key": fam.get("family_key"),
                     "role": fam.get("role"),
                     "candidates": [c.get("candidate_id") for c in
                                    fam.get("candidates", [])],
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass30_existing_portfolio_registry.json",
                     "no_upload": True}))
        n += 1

    # 2) DeckVariantCreated — only the NEW Raging Bolt structural variants.
    built_ids = set(manifest.get("candidates_built") or [])
    results = {r.get("candidate_id"): r for r in (manifest.get("results") or [])}
    for cid in built_ids:
        r = results.get(cid, {})
        store.append(new_event(
            EventType.DeckVariantCreated,
            tags=["pass30", "raging_bolt", "new_build"],
            payload={"candidate_id": cid,
                     "family": r.get("family"), "parent": r.get("parent_id"),
                     "role": r.get("role"),
                     "invented_card_ids": False, "is_clone": False,
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass30_candidate_manifest.json",
                     "no_upload": True}))
        n += 1

    # 3) LocalEvaluationFinished — the internal tournament.
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=["pass30", "internal_tournament"],
        payload={"participants": len(rank1.get("standings", [])),
                 "games_per_seat": 3, "stages": 2,
                 "is_kaggle_leaderboard": False,
                 "caveat": ("internal our-vs-our tournament with one generic pilot; "
                            "NOT Kaggle, NOT a promotion signal"),
                 "source": "data/experiments/pass30_portfolio_rankings.json",
                 "no_upload": True}))
    n += 1

    # 4) CandidateRanked — one per standing.
    for i, r in enumerate(rank1.get("standings", []), 1):
        store.append(new_event(
            EventType.CandidateRanked,
            tags=["pass30", "ranking", r["id"]],
            payload={"rank": i, "candidate_id": r["id"], "family": r.get("family"),
                     "adj_win_rate": r.get("adj_win_rate"), "wilson": r.get("wilson"),
                     "compatibility_label": r.get("compatibility_label"),
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass30_portfolio_rankings.json",
                     "no_upload": True}))
        n += 1

    # 5) ParentChildComparisonFinished — one per pair.
    for p in (pc.get("pairs") or []):
        store.append(new_event(
            EventType.ParentChildComparisonFinished,
            tags=["pass30", "parent_child", p.get("family", "")],
            payload={"pair": p.get("id"), "parent": p.get("parent"),
                     "child": p.get("child"),
                     "parent_win_rate": p.get("a_win_rate"),
                     "interpretation": p.get("interpretation"),
                     "is_kaggle_leaderboard": False,
                     "source":
                         "data/experiments/pass30_parent_child_confirmations.json",
                     "no_upload": True}))
        n += 1

    # 6) StrategyIterationEvaluated — one per family hardening diagnosis.
    for fam, f in (diag.get("families") or {}).items():
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=["pass30", "hardening", fam],
            payload={"family": fam, "best": f.get("best"), "worst": f.get("worst"),
                     "hardening_action": f.get("hardening_action"),
                     "hardening_helped": f.get("hardening_helped"),
                     "stay_active": f.get("stay_active"),
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass30_hardening_diagnosis.json",
                     "no_upload": True}))
        n += 1

    # 7) StrategyDecisionRecorded — the gated decision.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=["pass30", "decision"],
        payload={"pass": 30, "decision": decision.get("decision"),
                 "recommended_probe_candidate":
                     decision.get("recommended_probe_candidate"),
                 "all_gates_passed": decision.get("all_gates_passed"),
                 "queued_candidate_count": decision.get("queued_candidate_count"),
                 "human_approval_required": True, "auto_submit_enabled": False,
                 "promote": False, "upload": False, "submit": False,
                 "github_push": False, "is_kaggle_leaderboard": False,
                 "source": "data/experiments/pass30_strategy_decision.json",
                 "no_upload": True}))
    n += 1

    # 8) SubmissionQueued — the single HELD dry-run entry (if any).
    if decision.get("queued_candidate_count"):
        store.append(new_event(
            EventType.SubmissionQueued,
            tags=["pass30", "dry_run_queue"],
            payload={"candidate_id": decision.get("recommended_probe_candidate"),
                     "queue_max": 1, "held": True, "auto_submit_enabled": False,
                     "require_manual_approval_for_submit": True,
                     "upload_performed": False, "is_kaggle_leaderboard": False,
                     "source": "data/submission_queue.json", "no_upload": True}))
        n += 1

    # 9) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass30", "report"],
        payload={"pass": 30,
                 "reports": [
                     "data/reports/pass30_existing_portfolio_hardening_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md"],
                 "decision": decision.get("decision"), "no_upload": True}))
    n += 1

    print(f"emitted {n} pass30 events -> {LAB_EVENTS_PATH}")
    print(f"families={len(fams)} standings={len(rank1.get('standings', []))} "
          f"parent_child={len(pc.get('pairs', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
