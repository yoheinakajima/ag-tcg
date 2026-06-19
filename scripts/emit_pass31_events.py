#!/usr/bin/env python3
"""Pass 31 (Part 9) — emit ActiveGraph events for the human-approved single
Kaggle calibration probe of league_dragapult_v1_search_only.

Data-driven from data/experiments/pass31_kaggle_probe.json. Emits:
- StrategyPromotionDecision : promotion_claimed=false, human_approved=true,
                              calibration_probe=true. no_upload=false (this is
                              the human-approved upload event).
- SubmissionQueued          : the single calibration probe entry.
- SubmissionUploaded        : the exactly-once upload (no_upload=false).
- ReportSiteGenerated       : the Pass-31 reports/site.

KaggleScoreUpdated is emitted ONLY when a real publicScore is present. The probe
is pending at emit time, so no scored event is fabricated.

Every event carries a "pass31" tag and the required calibration payload fields.
Idempotent: re-running strips previously-emitted "pass31" events first.
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


def _strip(path, tag="pass31") -> int:
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
    facts = _load("pass31_kaggle_probe.json")
    cid = facts["candidate_id"]
    tarball = facts["tarball"]
    kaggle = facts["kaggle"]
    post = kaggle["post_upload"]

    base = {
        "candidate_id": cid,
        "tarball": tarball,
        "pass30_source_evidence": facts["pass30_source_evidence"],
        "upload_mode": facts["upload_mode"],
        "promotion_claimed": False,
        "no_auto_submit": True,
        "no_github_push": True,
    }

    removed = _strip(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass31 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    n = 0

    # 1) StrategyPromotionDecision — the human-approved upload decision.
    store.append(new_event(
        EventType.StrategyPromotionDecision,
        tags=["pass31", "calibration_probe", cid],
        payload={**base,
                 "human_approved": True,
                 "calibration_probe": True,
                 "no_upload": False,
                 "decision": "human_approved_single_calibration_probe_upload",
                 "rationale": ("strongest non-Water candidate from Pass30 "
                               "(top meta sanity + held dry-run); calibration "
                               "only, NOT a promotion claim"),
                 "source": "data/experiments/pass31_kaggle_probe.json"}))
    n += 1

    # 2) SubmissionQueued — the single probe entry.
    store.append(new_event(
        EventType.SubmissionQueued,
        tags=["pass31", "queue", cid],
        payload={**base,
                 "human_approved": True,
                 "calibration_probe": True,
                 "no_upload": True,
                 "queue_size": 1,
                 "kaggle_message": facts["kaggle_message"],
                 "source": "data/experiments/pass31_kaggle_probe.json"}))
    n += 1

    # 3) SubmissionUploaded — the exactly-once upload (real upload event).
    store.append(new_event(
        EventType.SubmissionUploaded,
        tags=["pass31", "upload", cid],
        payload={**base,
                 "human_approved": True,
                 "calibration_probe": True,
                 "no_upload": False,
                 "upload_count": 1,
                 "competition": kaggle["competition"],
                 "kaggle_message": facts["kaggle_message"],
                 "status_after_upload": post["status"],
                 "filename": post["fileName"],
                 "submitted_at": post["date"],
                 "upload_result": kaggle["upload_result"],
                 "status_logs": kaggle["status_logs"],
                 "source": "data/experiments/pass31_kaggle_probe.json"}))
    n += 1

    # 4) KaggleScoreUpdated — ONLY if a real publicScore exists (pending => skip).
    if post.get("publicScore") is not None:
        store.append(new_event(
            EventType.KaggleScoreUpdated,
            tags=["pass31", "score", cid],
            payload={**base,
                     "human_approved": True,
                     "calibration_probe": True,
                     "no_upload": False,
                     "public_score": post["publicScore"],
                     "status": post["status"],
                     "source": "data/experiments/pass31_kaggle_probe.json"}))
        n += 1
    else:
        print("publicScore pending -> KaggleScoreUpdated NOT emitted (no fabrication)")

    # 5) ReportSiteGenerated — the Pass-31 reports/site.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass31", "report"],
        payload={**base,
                 "no_upload": True,
                 "reports": [
                     "data/reports/pass31_dragapult_search_only_kaggle_probe_report.md",
                     "data/reports/activegraph_strategy_report.md",
                     "data/site/index.html",
                     "docs/PTCG_STRATEGY_CANVAS.md",
                 ],
                 "source": "data/experiments/pass31_kaggle_probe.json"}))
    n += 1

    print(f"emitted {n} pass31 events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
