#!/usr/bin/env python3
"""Pass 32 — emit ActiveGraph events for the Dragapult Kaggle result + replay
postmortem. READ-ONLY wrt Kaggle: NO upload happened this pass.

Data-driven from the Pass-32 experiment artifacts. Emits (all tagged "pass32",
no_upload=true, and NO SubmissionUploaded event):
- KaggleScoreUpdated      : the now-resolved Dragapult publicScore (was pending).
- ReplayImported (x3)     : the new gitignored replays.
- ReplayAnalyzed (x3)     : per-replay postmortem result.
- StrategyIterationEvaluated : Dragapult live calibration result.
- StrategyDecisionRecorded : keep_water_control decision.
- ReportSiteGenerated     : the Pass-32 reports/site.

SubmissionQueued is emitted ONLY if the dry-run queue is non-empty (it is empty
this pass -> not emitted). Idempotent: strips previously-emitted "pass32" events.
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
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _strip(path, tag="pass32") -> int:
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
    status = _load("pass32_kaggle_status.json")
    attribution = _load("pass32_replay_attribution.json")
    postmortem = _load("pass32_dragapult_postmortem.json")
    decision = _load("pass32_strategy_decision.json")
    ingestion = _load("pass32_replay_ingestion.json")

    cid = "league_dragapult_v1_search_only"
    base = {
        "candidate_id": cid,
        "no_upload": True,
        "upload_performed": False,
        "no_auto_submit": True,
        "no_github_push": True,
        "read_only_kaggle": True,
    }

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass32 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) KaggleScoreUpdated — the resolved Dragapult score (was pending in Pass 31).
    drag = status["dragapult"]
    if drag.get("public_score") is not None:
        store.append(new_event(
            EventType.KaggleScoreUpdated,
            tags=["pass32", "score", cid],
            payload={**base,
                     "public_score": drag["public_score"],
                     "status": drag["status"],
                     "resolved_from": "pass31_pending",
                     "live_score_leader": status["live_score_leader"],
                     "water_family_current_best": status["water_family_current_best"],
                     "below_current_control": decision["dragapult_result"]["below_current_control"],
                     "source": "data/experiments/pass32_kaggle_status.json"}))
        n += 1

    # 2) ReplayImported (x3) + 3) ReplayAnalyzed (x3).
    pm_by_ep = {g["episode_id"]: g for g in postmortem["games"]}
    for a in attribution["attributions"]:
        ep = a["episode_id"]
        store.append(new_event(
            EventType.ReplayImported,
            tags=["pass32", "replay_import", str(ep)],
            payload={**base,
                     "episode_id": ep, "file": a["file"],
                     "gitignored": True, "tracked": False,
                     "self_mirror": a["self_mirror"],
                     "source": "data/experiments/pass32_replay_attribution.json"}))
        n += 1
        g = pm_by_ep.get(ep, {})
        store.append(new_event(
            EventType.ReplayAnalyzed,
            tags=["pass32", "replay_analyzed", str(ep)],
            payload={**base,
                     "episode_id": ep,
                     "result": a["result_from_our_perspective"],
                     "opponent_seat_match": a["seat_attribution"]["1"]["deck_match"]
                     if "1" in a["seat_attribution"] else None,
                     "belongs_to_dragapult_probe": a["belongs_to_dragapult_probe"],
                     "loss_condition": g.get("loss_condition"),
                     "loss_classification": g.get("loss_classification"),
                     "contributing_factors": g.get("contributing_factors", []),
                     "first_attack_step": g.get("first_attack_step"),
                     "attack_ids": g.get("attack_ids"),
                     "spread_target_observable": False,
                     "source": "data/experiments/pass32_dragapult_postmortem.json"}))
        n += 1

    # 4) StrategyIterationEvaluated — Dragapult live calibration result.
    store.append(new_event(
        EventType.StrategyIterationEvaluated,
        tags=["pass32", "iteration_eval", cid],
        payload={**base,
                 "iteration": "dragapult_v1_search_only_live_calibration",
                 "public_score": drag["public_score"],
                 "vs_real_opponent_record": postmortem["vs_real_opponent_record"],
                 "primary_loss_modes": postmortem["primary_loss_modes"],
                 "contributing_factors": postmortem["contributing_factors"],
                 "calibration_only": True, "promotion_claimed": False,
                 "source": "data/experiments/pass32_dragapult_postmortem.json"}))
    n += 1

    # 5) StrategyDecisionRecorded — keep_water_control.
    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=["pass32", "decision", cid],
        payload={**base,
                 "decision": decision["decision"],
                 "secondary_label": decision["secondary_label"],
                 "next_candidate_family": decision["next_candidate_family"],
                 "dry_run_queue_size": decision["dry_run_queue_size"],
                 "queue_max": decision["queue_max"],
                 "human_approval_required": True,
                 "reason": decision["reason"],
                 "source": "data/experiments/pass32_strategy_decision.json"}))
    n += 1

    # 6) SubmissionQueued — ONLY if the dry-run queue is non-empty (it is empty).
    if decision["dry_run_queue_size"] > 0:
        store.append(new_event(
            EventType.SubmissionQueued,
            tags=["pass32", "queue"],
            payload={**base, "queue_size": decision["dry_run_queue_size"],
                     "source": "data/submission_queue.json"}))
        n += 1
    else:
        print("dry-run queue empty -> SubmissionQueued NOT emitted; "
              "NO SubmissionUploaded emitted (read-only Kaggle pass)")

    # 7) ReportSiteGenerated — the Pass-32 reports/site.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass32", "report"],
        payload={**base,
                 "reports": [
                     "data/reports/pass32_dragapult_result_and_replay_postmortem_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                 ],
                 "corpus_record": ingestion["corpus_record"],
                 "source": "data/experiments/pass32_kaggle_status.json"}))
    n += 1

    print(f"emitted {n} pass32 events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
