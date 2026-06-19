#!/usr/bin/env python3
"""Pass 27 (Part L) — emit ActiveGraph events for the multi-archetype portfolio.

Data-driven from the Pass-27 artifacts:
- StrategyFamilyRegistered  : one per portfolio deck family (registry).
- StrategyHypothesisLogged  : one per gap-analysis competency (the hypothesis
                              "the generic pilot supports competency X").
- StrategyFixtureAdded      : one per Part-H fixture family.
- StrategyIterationCreated  : one per built+packaged candidate.
- InternalLeagueStarted /
  LocalEvaluationStarted/Finished / InternalLeagueFinished : the internal league.
- StrategyIterationEvaluated: one per league participant (its standing).
- StrategyDecisionRecorded /
  StrategyPromotionDecision  : the honest Part-K decision (promote=False).
- StrategyBlocked           : one per blocked deck (e.g. Durant).
- ReportSiteGenerated       : the Part-M reports/site.

Every event carries no_upload=true and a "pass27" tag; the only side effect is
appending to the local lab event store. Nothing is uploaded to Kaggle or pushed
to GitHub. Idempotent: re-running strips previously-emitted "pass27" events.
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
FIXDIR = REPO / "data" / "fixtures" / "pass27_portfolio_core"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip(path, tag="pass27") -> int:
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
    registry = _load("pass27_portfolio_registry.json")
    gap = _load("pass27_core_gameplay_gap_analysis.json")
    rankings = _load("pass27_portfolio_rankings.json")
    validation = _load("pass27_candidate_validation.json")
    manifest = _load("pass27_candidate_manifest.json")
    decision = _load("pass27_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass27 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) StrategyFamilyRegistered — one per deck family.
    families = registry.get("decks") or registry.get("families") or []
    for fam in families:
        fid = fam.get("candidate_id") or fam.get("key") or fam.get("name")
        store.append(new_event(
            EventType.StrategyFamilyRegistered,
            tags=["pass27", "portfolio", "family"],
            payload={"family": fid, "archetype": fam.get("archetype"),
                     "legal": fam.get("valid"),
                     "card_count": fam.get("total"),
                     "blocked_from_league": fam.get("blocked_from_league", False),
                     "source": "data/experiments/pass27_portfolio_registry.json",
                     "no_upload": True}))
        n += 1

    # 2) StrategyHypothesisLogged — one per competency in the gap analysis.
    for c in gap.get("competencies", []):
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=["pass27", "competency", c["name"]],
            payload={"competency": c["name"], "exposed_by": c["deck"],
                     "hypothesis": f"the generic core pilot supports '{c['name']}'",
                     "verdict": c["status"], "priority": c["priority"],
                     "scope": c["scope"], "evidence": c["evidence"],
                     "source": "data/experiments/pass27_core_gameplay_gap_analysis.json",
                     "no_upload": True}))
        n += 1

    # 3) StrategyFixtureAdded — one per Part-H fixture family.
    try:
        import yaml  # noqa: PLC0415
        idx = yaml.safe_load((FIXDIR / "index.yaml").read_text(encoding="utf-8"))
        for fam in idx.get("families", []):
            store.append(new_event(
                EventType.StrategyFixtureAdded,
                tags=["pass27", "fixture", fam["id"]],
                payload={"fixture_family": fam["id"], "deck": fam["deck"],
                         "competencies": fam.get("competencies", []),
                         "blocked_from_league": fam.get("blocked_from_league", False),
                         "source": "data/fixtures/pass27_portfolio_core/index.yaml",
                         "no_upload": True}))
            n += 1
    except Exception as e:  # noqa: BLE001
        print(f"warn: fixtures not enumerated: {e}")

    # 4) StrategyIterationCreated — one per built+packaged candidate.
    built = manifest.get("candidates_built", [])
    for c in built:
        cid = c["candidate_id"]
        store.append(new_event(
            EventType.StrategyIterationCreated,
            tags=["pass27", "candidate", cid],
            payload={"candidate": cid, "packaged": True,
                     "archetype": c.get("archetype"), "role": c.get("role"),
                     "tarball": c.get("tarball"),
                     "blocked_from_league": c.get("blocked_from_league", False),
                     "source": "data/experiments/pass27_candidate_manifest.json",
                     "no_upload": True}))
        n += 1

    # 5) StrategyBlocked — decks excluded from the league (e.g. Durant chaos) and
    #    any deck that could not be built at all.
    blocked_ids = set(manifest.get("league_blocked", []))
    block_reasons = {c["candidate_id"]: c.get("block_reason")
                     for c in built if c.get("blocked_from_league")}
    for c in manifest.get("candidates_not_built", []):
        bid = c["candidate_id"] if isinstance(c, dict) else c
        blocked_ids.add(bid)
        if isinstance(c, dict):
            block_reasons.setdefault(bid, c.get("block_reason"))
    for bid in sorted(blocked_ids):
        store.append(new_event(
            EventType.StrategyBlocked,
            tags=["pass27", "blocked", bid],
            payload={"candidate": bid, "reason": block_reasons.get(bid),
                     "source": "data/experiments/pass27_candidate_manifest.json",
                     "no_upload": True}))
        n += 1

    # 6) Internal league lifecycle + per-participant evaluation.
    standings = rankings.get("standings", [])
    store.append(new_event(
        EventType.InternalLeagueStarted,
        tags=["pass27", "league"],
        payload={"participants": [s["id"] for s in standings],
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1
    store.append(new_event(
        EventType.LocalEvaluationStarted,
        tags=["pass27", "league"],
        payload={"participants": len(standings), "no_upload": True}))
    n += 1
    for s in standings:
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=["pass27", "league", s["id"]],
            payload={"candidate": s["id"], "rank": s.get("rank"),
                     "adj_win_rate": s.get("adj_win_rate"),
                     "record": f"{s.get('wins')}-{s.get('losses')}-{s.get('draws')}",
                     "wilson": s.get("wilson"), "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass27_portfolio_rankings.json",
                     "no_upload": True}))
        n += 1
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=["pass27", "league"],
        payload={"participants": len(standings),
                 "top": standings[0]["id"] if standings else None,
                 "worst": standings[-1]["id"] if standings else None,
                 "is_kaggle_leaderboard": False, "no_upload": True}))
    n += 1
    store.append(new_event(
        EventType.InternalLeagueFinished,
        tags=["pass27", "league"],
        payload={"top": standings[0]["id"] if standings else None,
                 "is_kaggle_leaderboard": False,
                 "caveat": "internal surrogate league, NOT Kaggle, NOT a promotion signal",
                 "no_upload": True}))
    n += 1

    # 7) Decision (honest: promote=False, no probe).
    dpayload = {
        "pass": 27,
        "primary_decision": decision.get("primary_decision"),
        "secondary_decision": decision.get("secondary_decision"),
        "keep_water_control": decision.get("keep_water_control"),
        "next_core_rule_family": decision.get("next_core_rule_family"),
        "highest_priority_generic_gap": decision.get("highest_priority_generic_gap"),
        "promote": False, "upload": False, "submit": False,
        "github_push": False, "future_kaggle_probe": decision.get("future_kaggle_probe", False),
        "live_score_leader": decision.get("live_score_leader"),
        "water_family_current_best": decision.get("water_family_current_best"),
        "is_kaggle_leaderboard": False,
        "source": "data/experiments/pass27_strategy_decision.json",
        "no_upload": True}
    for et in (EventType.StrategyDecisionRecorded,
               EventType.StrategyPromotionDecision):
        store.append(new_event(et, tags=["pass27", "decision"], payload=dpayload))
        n += 1

    # 8) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass27", "report"],
        payload={"pass": 27,
                 "reports": [
                     "data/reports/pass27_multi_archetype_portfolio_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                     "docs/CORE_PILOT_ROLE_TAXONOMY.md"],
                 "decision": decision.get("primary_decision"),
                 "no_upload": True}))
    n += 1

    print(f"emitted {n} pass27 events -> {LAB_EVENTS_PATH}")
    print(f"families={len(families)} competencies={len(gap.get('competencies', []))} "
          f"standings={len(standings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
