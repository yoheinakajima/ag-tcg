#!/usr/bin/env python3
"""Pass 25 (Part K) — emit ActiveGraph eval/decision-phase events for the Water
live-control hardening sprint.

Data-driven: reads the Pass-25 artifacts and emits one StrategyIterationEvaluated
per candidate, one LocalEvaluationFinished for the focused surrogate eval, and the
StrategyDecisionRecorded + StrategyPromotionDecision pair for the overall decision.
Every event carries no_upload=true. The only side effect is appending to the local
lab event store; nothing is uploaded to Kaggle and nothing is pushed to GitHub.

Idempotency: re-running strips ONLY previously-emitted Pass-25 *eval/decision-phase*
events (tag "pass25" without tag "build"); the Part-E/F build-phase events
(StrategyIterationCreated / StrategyFixtureAdded, tagged "pass25"+"build") are
preserved. The canonical ReportSiteGenerated event is emitted separately by
scripts/build_report_site.py during Part L.
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
FAMILY = "water_live_control_hardening"
CONTROL = "league_water_anti_disruption_pivot_v1"
CONTROL_PARTICIPANT = "control_pass22_pivot"
CANDIDATES = ["deckout_guard_v1", "prize_liability_guard_v1", "hybrid_guard_v1"]


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _strip_pass25_eval_phase(path) -> int:
    """Drop prior Pass-25 eval/decision-phase events (tag pass25, NOT build)."""
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
        if "pass25" in tags and "build" not in tags:
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def main() -> int:
    val = {c.get("candidate_id"): c for c in _load(
        "pass25_candidate_validation.json").get("candidates", [])}
    replay = _load("pass25_decision_replay.json").get("per_candidate", {})
    focused = _load("pass25_focused_eval.json")
    h2h = focused.get("h2h_vs_control", {})
    seam_delta = focused.get("seam_delta_vs_control", {})
    seam_agg = focused.get("seam_aggregate", {})
    control_seam_wr = (seam_agg.get(CONTROL_PARTICIPANT) or {}).get("win_rate")
    decision = _load("pass25_strategy_decision.json")
    dmap = {d["candidate_id"]: d for d in decision.get("candidate_decisions", [])}

    removed = _strip_pass25_eval_phase(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass25 eval/decision events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    emitted = 0

    # 1) Per-candidate iteration evaluation (gates + replay + surrogate, combined).
    for cid in CANDIDATES:
        v = val.get(cid, {})
        r = replay.get(cid, {})
        d = dmap.get(cid, {})
        store.append(new_event(
            EventType.StrategyIterationEvaluated,
            tags=["pass25", "evaluation"],
            payload={
                "candidate_id": cid, "family": FAMILY, "parent_control": CONTROL,
                "eligible": v.get("eligible"),
                "gates": {"core_gate_ok": v.get("core_gate_ok"),
                          "board_safety_ok": v.get("board_safety_ok"),
                          "hardening_gate_ok": v.get("hardening_gate_ok"),
                          "smoke_clean": v.get("smoke_clean")},
                "decision_replay": {
                    "decisions_examined": r.get("decisions_examined"),
                    "changed_total": r.get("changed_total"),
                    "on_seam": r.get("on_seam"),
                    "illegal": r.get("illegal"),
                    "positive_control_preserved": r.get("positive_control_preserved")},
                "focused_eval": {
                    "h2h_vs_control_winrate": (h2h.get(cid) or {}).get("win_rate"),
                    "h2h_wilson": [(h2h.get(cid) or {}).get("wilson_low"),
                                   (h2h.get(cid) or {}).get("wilson_high")],
                    "seam_delta_vs_control": seam_delta.get(cid)},
                "verdict": f"{d.get('label')} ({d.get('secondary_label')})",
                "surrogate_based": True, "directional_only": True,
                "deep_board_metrics": "NOT_MEASURED (opaque cabt board blob)",
                "source": "data/experiments/pass25_focused_eval.json",
                "no_upload": True,
            },
        ))
        emitted += 1

    # 2) Focused surrogate eval summary (directional only).
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=["pass25", "focused_eval", "directional_only"],
        payload={
            "family": FAMILY, "participants": ["control"] + CANDIDATES,
            "h2h_games_per_seat": 10, "seam_games_per_seat": 5, "seat_swapped": True,
            "control_seam_winrate": control_seam_wr,
            "candidates": {cid: {"h2h_winrate": (h2h.get(cid) or {}).get("win_rate"),
                                 "seam_delta_vs_control": seam_delta.get(cid)}
                           for cid in CANDIDATES},
            "no_candidate_clears_promotion_bar": True,
            "surrogate_based": True, "directional_only": True,
            "note": "surrogate opponents do not reproduce the real Fighting-tempo / "
                    "mirror-deckout seams; differences are noise. The Part-H decision "
                    "replay (0 behaviour deltas over 262 real decisions) is the "
                    "authoritative behavioural evidence.",
            "source": "data/experiments/pass25_focused_eval.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    # 3) Decision: keep current control, do NOT promote / upload / push.
    rec = decision.get("recommendation", {})
    drift = decision.get("drift_context", {})
    decision_payload = {
        "family": FAMILY,
        "primary_decision": rec.get("primary_decision", "keep_current_control"),
        "current_best": rec.get("current_best", CONTROL),
        "per_candidate": {cid: dmap.get(cid, {}).get("label") for cid in CANDIDATES},
        "promote": False, "upload": False, "github_push": False,
        "promote_live_control_change": False,
        "live_active_control": (
            f"{(drift.get('live_best') or {}).get('file')} @ "
            f"{(drift.get('live_best') or {}).get('public_score')} "
            f"(water control under hardening "
            f"{(drift.get('water_control_under_hardening') or {}).get('public_score')}, "
            f"within noise)"),
        "rationale": rec.get("explicit_caveat"),
        "source": "data/experiments/pass25_strategy_decision.json",
        "no_upload": True,
    }
    for et in (EventType.StrategyDecisionRecorded, EventType.StrategyPromotionDecision):
        store.append(new_event(et, tags=["pass25", "decision"], payload=decision_payload))
        emitted += 1

    print(f"emitted {emitted} pass25 eval/decision events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
