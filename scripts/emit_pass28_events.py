#!/usr/bin/env python3
"""Pass 28 (Part L) — emit ActiveGraph events for the cross-deck forensic trace.

Data-driven from the Pass-28 artifacts. Emits:
- StrategyIterationEvaluated : one per deck-family diagnostic (Part F).
- LocalEvaluationFinished    : the forensic trace run (Parts D+E).
- StrategyHypothesisLogged   : one per core gap (Part H), incl. REJECTED ones.
- StrategyFixtureAdded       : one per fixture backlog item (Part I).
- StrategyDecisionRecorded   : the evidence-gated decision (Part K).
- ReportSiteGenerated        : the Part-M reports/site.

Every event carries no_upload=true and a "pass28" tag. The only side effect is
appending to the local lab event store — nothing is uploaded to Kaggle or pushed
to GitHub, and no candidate is built. Idempotent: re-running strips previously-
emitted "pass28" events first.
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
FIX = REPO / "data" / "fixtures" / "pass28_core_gameplay_backlog.yaml"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path, tag="pass28") -> int:
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
    forensics = _load("pass28_deck_forensics.json")
    diag = _load("pass28_diagnostic_trace.json")
    priority = _load("pass28_core_gap_priority.json")
    decision = _load("pass28_strategy_decision.json")
    matrix = _load("pass28_mechanics_coverage_matrix.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass28 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) LocalEvaluationFinished — the forensic trace run itself.
    pairings = diag.get("pairings", {})
    total_decisions = diag.get("total_decisions_traced") or diag.get("decisions_traced")
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=["pass28", "forensic_trace"],
        payload={"pairings": len(pairings),
                 "decisions_traced": total_decisions,
                 "is_kaggle_leaderboard": False,
                 "caveat": ("internal our-vs-our forensic trace, NOT Kaggle, NOT a "
                            "promotion signal"),
                 "source": "data/experiments/pass28_diagnostic_trace.json",
                 "no_upload": True}))
    n += 1

    # 2) StrategyIterationEvaluated — one per deck-family diagnosis.
    for fam, f in (forensics.get("families") or {}).items():
        ev = f.get("evidence", {})
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=["pass28", "forensic", fam],
            payload={"family": fam, "candidate": f.get("candidate_id"),
                     "issue_classification": f.get("issue_classification"),
                     "attacks_taken": ev.get("attacks_taken"),
                     "first_attack_step": ev.get("first_attack_step"),
                     "attach_off_deck_plan": ev.get("attach_off_deck_plan"),
                     "attack_available_not_taken": ev.get("attack_available_not_taken"),
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass28_deck_forensics.json",
                     "no_upload": True}))
        n += 1

    # 3) StrategyHypothesisLogged — one per core gap (incl. rejected).
    for g in priority.get("gaps_ranked", []):
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=["pass28", "gap", g["gap_id"]],
            payload={"gap_id": g["gap_id"], "claimed_issue": g["claimed_issue"],
                     "evidence_for": g["evidence_for"],
                     "evidence_against": g["evidence_against"],
                     "decks_affected": g["decks_affected"],
                     "confidence": g["confidence"],
                     "rejected": g["confidence"].lower().startswith("rejected"),
                     "source": "data/experiments/pass28_core_gap_priority.json",
                     "no_upload": True}))
        n += 1

    # 4) StrategyFixtureAdded — one per fixture backlog item.
    try:
        import yaml  # noqa: PLC0415
        fixdoc = yaml.safe_load(FIX.read_text(encoding="utf-8"))
        for fx in fixdoc.get("fixtures", []):
            store.append(new_event(
                EventType.StrategyFixtureAdded,
                tags=["pass28", "fixture", fx["fixture_id"]],
                payload={"fixture_id": fx["fixture_id"], "gap_id": fx["gap_id"],
                         "deck": fx["candidate_source_deck"],
                         "executable_now": fx["executable_now"],
                         "priority": fx["priority"],
                         "source": "data/fixtures/pass28_core_gameplay_backlog.yaml",
                         "no_upload": True}))
            n += 1
    except Exception as e:  # noqa: BLE001
        print(f"warn: fixtures not enumerated: {e}")

    # 5) StrategyDecisionRecorded — the evidence-gated decision.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=["pass28", "decision"],
        payload={"pass": 28, "decision": decision.get("decision"),
                 "specific_mechanic_focus": decision.get("specific_mechanic_focus"),
                 "top_gap": decision.get("top_gap"),
                 "rejected_gaps": decision.get("rejected_gaps"),
                 "validation_deck": decision.get("validation_deck"),
                 "keep_water_reference": decision.get("keep_water_reference"),
                 "no_candidate_built": True, "promote": False, "upload": False,
                 "submit": False, "github_push": False, "is_kaggle_leaderboard": False,
                 "source": "data/experiments/pass28_strategy_decision.json",
                 "no_upload": True}))
    n += 1

    # 6) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass28", "report"],
        payload={"pass": 28,
                 "reports": [
                     "data/reports/pass28_cross_deck_forensic_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                     "docs/CORE_GAMEPLAY_BACKLOG.md"],
                 "matrix_rows": matrix.get("row_count"),
                 "decision": decision.get("decision"),
                 "no_upload": True}))
    n += 1

    print(f"emitted {n} pass28 events -> {LAB_EVENTS_PATH}")
    print(f"families={len(forensics.get('families', {}))} "
          f"gaps={len(priority.get('gaps_ranked', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
