#!/usr/bin/env python3
"""Pass 21 — emit ActiveGraph events for the replay-ingestion / water post-mortem.

All events carry no_upload=true. Read-only with respect to Kaggle; the only side
effect is appending to the lab event store.
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

CANDIDATE = "league_water_core_reference"

NEW = ["80590776", "80591511", "80592173", "80592831", "80593320"]

# Per-episode facts (opponent, result, archetype) from Part E/F.
GAMES = {
    "80590776": {"opponent": None, "result": "self_mirror", "archetype": "water_kyogre_abomasnow_passive_mirror"},
    "80591511": {"opponent": "Latitu", "result": "loss", "archetype": "grass_crustle_energy_denial_control"},
    "80592173": {"opponent": "Roman Tamrazov", "result": "win", "archetype": "fighting_lucario_hariyama_ex"},
    "80592831": {"opponent": "Leopard Jaguar", "result": "loss", "archetype": "grass_fire_crustle_typhlosion_control"},
    "80593320": {"opponent": "Kazato Takahashi", "result": "loss", "archetype": "grass_water_dipplin_toolbox"},
}

FIXTURES = [
    "anti_energy_denial_backup_plan",
    "evolve_snover_when_kyogre_plan_stalls",
    "preserve_snover_line_after_secret_box",
    "backup_bench_before_no_bench_loss",
    "choose_pivot_search_target",
    "anti_crushing_hammer_energy_spread",
]


def main() -> int:
    store = EventStore(LAB_EVENTS_PATH)
    emitted = 0

    for ep in NEW:
        g = GAMES[ep]
        store.append(new_event(
            EventType.ReplayImported,
            match_id=ep,
            tags=["pass21", "replay_ingestion"],
            payload={
                "episode_id": ep, "candidate_id": CANDIDATE,
                "opponent": g["opponent"], "result": g["result"],
                "archetype": g["archetype"],
                "source": f"data/meta_replays/raw/{ep}.json (gitignored)",
                "no_upload": True,
            },
        ))
        emitted += 1
        store.append(new_event(
            EventType.ReplayAnalyzed,
            match_id=ep,
            tags=["pass21", "water_postmortem"],
            payload={
                "episode_id": ep, "candidate_id": CANDIDATE,
                "opponent": g["opponent"], "result": g["result"],
                "archetype": g["archetype"],
                "source": "data/experiments/pass21_water_replay_analysis.json",
                "no_upload": True,
            },
        ))
        emitted += 1

    store.append(new_event(
        EventType.KaggleScoreUpdated,
        tags=["pass21", "read_only"],
        payload={
            "candidate_id": CANDIDATE, "status": "complete",
            "public_score": 420.8, "previous_control": "combo_full_safety_v3_fixed",
            "previous_control_score": 391.1,
            "source": "data/kaggle_uploads/live_score_registry.json",
            "read_only": True, "no_upload": True,
        },
    ))
    emitted += 1

    store.append(new_event(
        EventType.StrategyIterationEvaluated,
        tags=["pass21"],
        payload={
            "candidate_id": CANDIDATE,
            "record_excluding_mirror": {"wins": 1, "losses": 3, "draws": 0},
            "main_failure": "lack of anti-disruption pivot",
            "source": "data/experiments/pass21_strategy_interpretation.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    store.append(new_event(
        EventType.StrategyDecisionRecorded,
        tags=["pass21", "decision"],
        payload={
            "candidate_id": CANDIDATE,
            "decision": "build_water_anti_disruption",
            "promote_live_control": False,
            "next_candidate_family": "water_anti_disruption_pivot",
            "source": "data/experiments/pass21_strategy_interpretation.json",
            "no_upload": True,
        },
    ))
    emitted += 1

    for fx in FIXTURES:
        store.append(new_event(
            EventType.StrategyFixtureAdded,
            tags=["pass21", "planned_fixture"],
            payload={
                "fixture_id": fx, "candidate_id": CANDIDATE,
                "implemented": False,
                "source": "data/fixtures/pass21_planned_water_fixtures.yaml",
                "no_upload": True,
            },
        ))
        emitted += 1

    store.append(new_event(
        EventType.ReportSiteGenerated,
        tags=["pass21", "report"],
        payload={
            "candidate_id": CANDIDATE,
            "report": "data/reports/pass21_water_reference_replay_analysis_report.md",
            "site": "data/site/index.html",
            "no_upload": True,
        },
    ))
    emitted += 1

    print(f"emitted {emitted} events -> {LAB_EVENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
