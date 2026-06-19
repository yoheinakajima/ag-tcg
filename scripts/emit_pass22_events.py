#!/usr/bin/env python3
"""Pass 22 — emit ActiveGraph events for the water anti-disruption + emergency
backup-bench implementation pass.

Every event carries no_upload=true. The only side effect is appending to the
local lab event store; nothing is uploaded to Kaggle and nothing is pushed.
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

CANDIDATE = "league_water_anti_disruption_pivot_v1"
REFERENCE = "league_water_core_reference"

# No-Pokemon / empty-bench loss episodes analysed this pass (raw gitignored).
LOSS_EPISODES = [
    "80503804", "80504288", "80505567", "80506042", "80591511",
    "80592831", "80593320", "80594489", "80595014",
]

FIXTURES = [
    "ebb_01", "ebb_02", "ebb_03", "ebb_04", "ebb_05",
    "adp_01", "adp_02", "pbd_01", "pbd_02",
]

HOOKS = [
    {"context": 0, "name": "emergency_backup_bench",
     "flag": "emergency_backup_bench"},
    {"context": 7, "name": "anti_disruption_search_pivot",
     "flag": "anti_disruption_search_pivot"},
    {"context": 8, "name": "preserve_backup_basic_on_discard",
     "flag": "preserve_backup_basic_on_discard"},
]


def _strip_existing_pass22(path) -> int:
    """Idempotency: drop any previously-emitted pass22 events so re-runs don't
    duplicate. Returns the number of lines removed."""
    from pathlib import Path as _P
    p = _P(path)
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
        payload = ev.get("payload", {}) if isinstance(ev, dict) else {}
        is_p22 = "pass22" in (ev.get("tags") or []) or payload.get("pass") in (22, "22")
        if is_p22:
            removed += 1
        else:
            kept.append(line)
    p.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
    return removed


def main() -> int:
    removed = _strip_existing_pass22(LAB_EVENTS_PATH)
    if removed:
        print(f"removed {removed} stale pass22 events (idempotent re-run)")
    store = EventStore(LAB_EVENTS_PATH)
    emitted = 0

    # Replay inputs analysed for the no-Pokemon-loss / energy-denial study.
    for ep in LOSS_EPISODES:
        store.append(new_event(
            EventType.ReplayAnalyzed,
            match_id=ep,
            tags=["pass22", "no_pokemon_loss"],
            payload={
                "episode_id": ep, "reference_candidate": REFERENCE,
                "study": "no_pokemon_in_play / empty-bench loss",
                "source": "data/experiments/pass22_no_pokemon_loss_windows.jsonl",
                "raw": f"data/meta_replays/raw/{ep}.json (gitignored)",
                "no_upload": True,
            },
        ))
        emitted += 1

    # Strategy family + iteration for the new candidate.
    store.append(new_event(
        EventType.StrategyFamilyRegistered,
        tags=["pass22"],
        payload={
            "family": "water_anti_disruption_pivot",
            "parent_reference": REFERENCE,
            "motivation": "convert held-but-never-benched backup basics into "
                          "bench plays; survive energy denial",
            "no_upload": True,
        },
    ))
    emitted += 1

    store.append(new_event(
        EventType.StrategyIterationCreated,
        tags=["pass22"],
        payload={
            "candidate_id": CANDIDATE, "family": "water_anti_disruption_pivot",
            "hooks": [h["name"] for h in HOOKS],
            "deck": "byte-identical to core_pilot_water_v2 (no deck change)",
            "no_upload": True,
        },
    ))
    emitted += 1

    for h in HOOKS:
        store.append(new_event(
            EventType.StrategyHypothesisLogged,
            tags=["pass22", "hook"],
            payload={
                "candidate_id": CANDIDATE,
                "context": h["context"], "hook": h["name"],
                "flag": h["flag"], "flag_gated": True, "narrow": True,
                "hypothesis": "narrow flag-gated sub-action hook reduces "
                              "no-Pokemon-in-play losses without overriding Main",
                "no_upload": True,
            },
        ))
        emitted += 1

    for fx in FIXTURES:
        store.append(new_event(
            EventType.StrategyFixtureAdded,
            tags=["pass22", "fixture"],
            payload={
                "fixture_id": fx, "candidate_id": CANDIDATE, "implemented": True,
                "suite": "data/fixtures/pass22_water_board_safety/index.yaml",
                "no_upload": True,
            },
        ))
        emitted += 1

    # Build + packaging.
    store.append(new_event(
        EventType.SubmissionPackaged,
        tags=["pass22", "build"],
        payload={
            "candidate_id": CANDIDATE,
            "tarball": "data/submissions/candidates_pass22/"
                       "league_water_anti_disruption_pivot_v1.tar.gz",
            "top_level_only": ["main.py", "deck.csv"],
            "queued_for_upload": False, "no_upload": True,
        },
    ))
    emitted += 1

    # Validation results.
    store.append(new_event(
        EventType.ValidationRunFinished,
        tags=["pass22", "validation"],
        payload={
            "candidate_id": CANDIDATE,
            "tarball_validator": "PASS", "entrypoint_validator": "PASS",
            "live_smoke": "PASS",
            "pass22_fixture_gate": "9/9 PASS",
            "default_core_competency_gate": "13 pass / 1 advisory / 0 hard-fail",
            "source": "data/reports/pass22_candidate_validation.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    # Focused surrogate eval (directional only).
    store.append(new_event(
        EventType.LocalEvaluationFinished,
        tags=["pass22", "focused_eval", "directional_only"],
        payload={
            "candidate_id": CANDIDATE,
            "weighted_pool_winrate": 0.65,
            "reference_weighted_pool": 0.775,
            "base_lineage_weighted_pool": 0.82,
            "surrogate_based": True, "directional_only": True,
            "note": "surrogate opponents do not reproduce real energy-denial; "
                    "result is inconclusive and does NOT justify promotion",
            "source": "data/reports/pass22_focused_eval.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    # Decision replay on the real loss windows.
    store.append(new_event(
        EventType.ReplayAnalyzed,
        tags=["pass22", "decision_replay"],
        payload={
            "candidate_id": CANDIDATE, "reference": REFERENCE,
            "empty_bench_benchable_windows": 75,
            "windows_pivot_benched_backup_where_reference_did_not": 5,
            "all_pivot_choices_legal_single_option": True,
            "source": "data/reports/pass22_decision_replay.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    # Iteration evaluation summary (replay + surrogate evidence combined).
    store.append(new_event(
        EventType.StrategyIterationEvaluated,
        tags=["pass22", "evaluation"],
        payload={
            "candidate_id": CANDIDATE, "parent_reference": REFERENCE,
            "fixture_gate": "9/9 PASS",
            "decision_replay_legal_fixes": 5,
            "surrogate_weighted_pool": 0.65,
            "surrogate_reference_weighted_pool": 0.775,
            "verdict": "legal+narrow on real windows; surrogate inconclusive",
            "no_upload": True,
        },
    ))
    emitted += 1

    # Promotion + strategy decision: do NOT promote / do NOT upload.
    for et in (EventType.StrategyPromotionDecision, EventType.StrategyDecisionRecorded):
        store.append(new_event(
            et,
            tags=["pass22", "decision"],
            payload={
                "candidate_id": CANDIDATE,
                "decision": "do_not_promote_do_not_upload",
                "promote": False, "upload": False,
                "promote_live_control_change": False,
                "live_active_control": f"{REFERENCE} @ 420.8",
                "rationale": "hooks are provably legal & narrow on real loss "
                             "windows, but surrogate eval cannot confirm net gain; "
                             "keep local until real-opponent evidence exists",
                "no_upload": True,
            },
        ))
        emitted += 1

    # Report site / markdown regenerated this pass.
    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass22", "report"],
        payload={
            "candidate_id": CANDIDATE,
            "report": "data/reports/pass22_water_anti_disruption_report.md",
            "strategy_report": "data/reports/activegraph_strategy_report.md",
            "canvas": "docs/PTCG_STRATEGY_CANVAS.md",
            "site": "data/site/index.html",
            "no_upload": True,
        },
    ))
    emitted += 1

    print(f"emitted {emitted} events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
