#!/usr/bin/env python3
"""Pass 26 — Part N: emit ActiveGraph events for the action-opportunity mining
sprint.

Data-driven: reads the Pass-26 artifacts and emits ReplayAnalyzed /
ReplayWindowTagged for the mined corpus, StrategyHypothesisLogged per opportunity
class, StrategyDecisionRecorded + StrategyPromotionDecision for the honest
decision, and ReportSiteGenerated. NO StrategyFixtureAdded / StrategyIteration
Created / StrategyIterationEvaluated are emitted because no candidate was built
(no hook passed the trigger-coverage gate). Every event carries no_upload=true
and a "pass26" tag. The only side effect is appending to the local lab event
store; nothing is uploaded to Kaggle and nothing is pushed to GitHub.

Idempotent: re-running strips previously-emitted "pass26"-tagged events first.
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
LEDGER = EXP / "pass26_action_opportunities.jsonl"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip_pass26(path) -> int:
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
        if "pass26" in tags:
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def main() -> int:
    rows = [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    classes = _load("pass26_true_opportunity_classes.json").get("classes", [])
    gate = _load("pass26_trigger_coverage.json")
    diag = _load("pass26_pass25_inert_hook_diagnosis.json")
    decision = _load("pass26_strategy_decision.json")
    manifest = json.loads((REPO / "candidates_pass26" / "manifest.json")
                          .read_text(encoding="utf-8"))

    episodes = sorted({r["episode_id"] for r in rows})
    removed = _strip_pass26(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass26 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) ReplayAnalyzed — one per mined episode.
    for ep in episodes:
        ep_rows = [r for r in rows if r["episode_id"] == ep]
        store.append(new_event(
            EventType.ReplayAnalyzed,
            tags=["pass26", "replay_mining"],
            payload={
                "episode_id": ep, "decisions": len(ep_rows),
                "result": ep_rows[0]["result"],
                "source": "data/experiments/pass26_action_opportunities.jsonl",
                "no_upload": True,
            }))
        n += 1

    # 2) ReplayWindowTagged — one per opportunity class with >0 windows,
    #    carrying its evidence episodes.
    for c in classes:
        if c["count"] <= 0:
            continue
        store.append(new_event(
            EventType.ReplayWindowTagged,
            tags=["pass26", "opportunity_window", c["name"]],
            payload={
                "opportunity_class": c["name"], "window_count": c["count"],
                "episodes": c["episodes"], "feasibility": c["feasibility"],
                "confidence": c["confidence"],
                "source": "data/experiments/pass26_true_opportunity_classes.json",
                "no_upload": True,
            }))
        n += 1

    # 3) StrategyHypothesisLogged — one per opportunity class (the hypothesis
    #    "this class justifies a runtime hook") + its gate verdict.
    gmap = {h["class"]: h for h in gate.get("hooks", [])}
    for c in classes:
        gh = gmap.get(c["name"], {})
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=["pass26", "hypothesis", c["name"]],
            payload={
                "opportunity_class": c["name"],
                "hypothesis": f"a runtime hook for {c['name']} is justified",
                "window_count": c["count"], "feasibility": c["feasibility"],
                "build_allowed": gh.get("build_allowed", False),
                "blocking_reasons": gh.get("blocking_reasons", []),
                "verdict": "rejected (no trigger coverage)",
                "source": "data/experiments/pass26_trigger_coverage.json",
                "no_upload": True,
            }))
        n += 1

    # NOTE: no StrategyFixtureAdded / StrategyIterationCreated /
    # StrategyIterationEvaluated — nothing was built (no hook passed Part G).

    # 4) StrategyDecisionRecorded + StrategyPromotionDecision (honest block).
    dpayload = {
        "pass": 26,
        "primary_decision": decision.get("primary_decision"),
        "secondary_decision": decision.get("secondary_decision"),
        "any_build_allowed": gate.get("any_build_allowed", False),
        "candidates_built": manifest.get("candidates_built", []),
        "candidates_blocked": manifest.get("candidates_blocked", []),
        "tarballs": manifest.get("tarballs", []),
        "promote": False, "upload": False, "submit": False,
        "github_push": False, "future_kaggle_probe": False,
        "live_score_leader": decision.get("live_score_leader"),
        "water_family_current_best": decision.get("water_family_current_best"),
        "distinction_preserved": decision.get("distinction_preserved"),
        "inert_hook_lesson": decision.get("lesson"),
        "pass25_inert_hooks": [h["hook"] for h in diag.get("hooks", [])],
        "source": "data/experiments/pass26_strategy_decision.json",
        "no_upload": True,
    }
    for et in (EventType.StrategyDecisionRecorded,
               EventType.StrategyPromotionDecision):
        store.append(new_event(et, tags=["pass26", "decision"], payload=dpayload))
        n += 1

    # 5) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass26", "report"],
        payload={
            "pass": 26,
            "reports": [
                "data/reports/pass26_action_opportunity_mining_report.md",
                "data/reports/activegraph_strategy_report.md",
                "data/site/index.html",
                "docs/PTCG_STRATEGY_CANVAS.md",
            ],
            "decision": decision.get("primary_decision"),
            "no_upload": True,
        }))
    n += 1

    print(f"emitted {n} pass26 events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
