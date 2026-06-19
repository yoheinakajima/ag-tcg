#!/usr/bin/env python3
"""Pass 29 (Part N) — emit ActiveGraph events for the observability ratchet.

Data-driven from the Pass-29 artifacts. Emits:
- LocalEvaluationFinished : the action-resolution dataset build (Parts C/D).
- StrategyHypothesisLogged : effect-loop anatomy + observability gaps (E/G/H).
- StrategyFixtureAdded : one per backlog item (Part I).
- PolicyVariantCreated : the built guard candidate (Part J), if built.
- ValidationRunFinished : the focused guard eval (Parts K/L), if run.
- StrategyDecisionRecorded : the evidence-gated decision (Part M).
- ReportSiteGenerated : the Part-O reports/site.

Every event carries no_upload=true and a "pass29" tag. Only side effect: appending
to the local lab event store. Nothing uploaded to Kaggle or pushed to GitHub.
Idempotent: re-running strips previously-emitted "pass29" events first.
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
FIX = REPO / "data" / "fixtures" / "pass29_observability_backlog.yaml"
TAG = "pass29"


def _load(name):
    p = EXP / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
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
    resolve = _load("pass29_action_resolution_summary.json")
    valid = _load("pass29_action_resolution_validation.json")
    loops = _load("pass29_effect_loop_analysis.json")
    feas = _load("pass29_effect_loop_feasibility.json")
    tgt = _load("pass29_target_observability.json")
    eng = _load("pass29_engine_card_observability.json")
    eval_ = _load("pass29_effect_loop_guard_eval.json")
    decision = _load("pass29_strategy_decision.json")

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale {TAG} events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) LocalEvaluationFinished — dataset build + validation.
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=[TAG, "action_resolution"],
        payload={"rows": resolve.get("total_rows"),
                 "resolved_fraction": resolve.get("resolved_fraction"),
                 "validation_agreement": valid.get("agreement_among_checkable"),
                 "is_kaggle_leaderboard": False,
                 "caveat": "internal action-resolution dataset, NOT Kaggle",
                 "source": "data/experiments/pass29_action_resolution_dataset.jsonl",
                 "no_upload": True}))
    n += 1

    # 2) StrategyHypothesisLogged — effect-loop anatomy + observability gaps.
    store.append(new_event(
        EventType.StrategyHypothesisLogged,
        tags=[TAG, "effect_loop", "venusaur"],
        payload={"hypothesis": "venusaur_effect_loop",
                 "classification": (
                     max(loops.get("by_classification", {}),
                         key=loops.get("by_classification", {}).get,
                         default="optional_loop_with_exit")),
                 "corrected_finding": ("loop head is ctx0 where pilot is offered an "
                                       "end option but always picks in_play_action; "
                                       "earlier 'forced_engine_loop' read was wrong"),
                 "source": "data/experiments/pass29_effect_loop_analysis.json",
                 "no_upload": True}))
    n += 1
    for part, art, gid in (("G", tgt, "attack_target_observability"),
                           ("H", eng, "engine_card_observability")):
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=[TAG, "observability", gid],
            payload={"gap_id": gid, "part": part,
                     "observable": art.get("observable"),
                     "not_observable_yet": art.get("NOT_observable_yet"),
                     "no_upload": True}))
        n += 1

    # 3) StrategyFixtureAdded — one per backlog item.
    try:
        import yaml
        doc = yaml.safe_load(FIX.read_text(encoding="utf-8"))
        for fx in doc.get("fixtures", []):
            store.append(new_event(
                EventType.StrategyFixtureAdded,
                tags=[TAG, "fixture", fx["fixture_id"]],
                payload={"fixture_id": fx["fixture_id"],
                         "observability": fx["observability"],
                         "executable_now": fx["executable_now"],
                         "status": fx["status"], "priority": fx["priority"],
                         "source": "data/fixtures/pass29_observability_backlog.yaml",
                         "no_upload": True}))
            n += 1
    except Exception as e:  # noqa: BLE001
        print(f"warn: fixtures not enumerated: {e}")

    # 4) Feasibility gate as StrategyBlocked / hypothesis.
    store.append(new_event(
        EventType.StrategyHypothesisLogged,
        tags=[TAG, "feasibility_gate"],
        payload={"gate_passes": feas.get("gate_passes"),
                 "classification": feas.get("loop_classification"),
                 "source": "data/experiments/pass29_effect_loop_feasibility.json",
                 "no_upload": True}))
    n += 1

    # 5) PolicyVariantCreated — the built guard (only if built).
    if decision.get("candidate_built"):
        store.append(new_event(
            EventType.PolicyVariantCreated,
            tags=[TAG, "candidate", decision["candidate_built"]],
            payload={"candidate": decision["candidate_built"],
                     "kind": "runtime_effect_loop_exit_guard",
                     "deck_unchanged": True, "uploaded": False, "submitted": False,
                     "github_pushed": False,
                     "location": "data/submissions/candidates_pass29/",
                     "no_upload": True}))
        n += 1
        # 6) ValidationRunFinished — the focused eval.
        store.append(new_event(
            EventType.ValidationRunFinished,
            tags=[TAG, "guard_eval"],
            payload={"verdict": eval_.get("verdict"),
                     "baseline_max_static_run":
                         (eval_.get("baseline") or {}).get("max_static_run_observed"),
                     "guard_max_static_run":
                         (eval_.get("guard") or {}).get("max_static_run_observed"),
                     "all_games_terminate":
                         (eval_.get("guard") or {}).get("all_games_terminate"),
                     "is_kaggle_leaderboard": False,
                     "source": "data/experiments/pass29_effect_loop_guard_eval.json",
                     "no_upload": True}))
        n += 1

    # 7) StrategyDecisionRecorded.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=[TAG, "decision"],
        payload={"pass": 29, "decision": decision.get("decision"),
                 "feasibility_gate_passed": decision.get("feasibility_gate_passed"),
                 "eval_verdict": decision.get("eval_verdict"),
                 "candidate_built": decision.get("candidate_built"),
                 "uploaded": False, "submitted": False, "github_push": False,
                 "root_files_modified": False, "is_kaggle_leaderboard": False,
                 "source": "data/experiments/pass29_strategy_decision.json",
                 "no_upload": True}))
    n += 1

    # 8) ReportSiteGenerated.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=[TAG, "report"],
        payload={"pass": 29,
                 "reports": [
                     "data/reports/pass29_observability_ratchet_report.md",
                     "data/site/index.html"],
                 "decision": decision.get("decision"),
                 "no_upload": True}))
    n += 1

    print(f"emitted {n} {TAG} events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
