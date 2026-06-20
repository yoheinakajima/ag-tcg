"""Pass 32 — Dragapult Kaggle result + replay postmortem tests.

READ-ONLY guarantees and honest, evidence-gated findings. These tests read the
committed Pass-32 artifacts and the lab event store. Nothing here uploads,
submits, or pushes; the tests only verify on-disk state.

Checklist (from the spec):
- root main.py / deck.csv byte-unchanged vs the v1 baseline
- Kaggle status is read-only: no_upload true, upload_performed false
- the Dragapult probe resolved to a real publicScore (was pending) and is below control
- new raw replays are gitignored, untracked, structurally valid; self-mirror 80374966 untouched
- attribution uses exact deck fingerprints; Water fingerprint ambiguity is reported honestly
- the postmortem makes NO spread-targeting claim (numeric attackIds only); no invented card ids
- loss conditions are classified honestly (prize_race_loss / no_pokemon_loss)
- the dry-run queue holds at most 1 entry and is empty (Dragapult below control)
- the decision is keep_water_control
- every pass32 event carries no_upload=true and NO SubmissionUploaded happened
- the 10-section report exists with all ten numbered sections
"""

from __future__ import annotations

import filecmp
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
REPORT = REPO / "data" / "reports" / "pass32_dragapult_result_and_replay_postmortem_report.md"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
QUEUE = REPO / "data" / "submission_queue.json"
RAW = REPO / "data" / "meta_replays" / "raw"

NEW_EPISODES = ["80760752", "80760852", "80761535"]


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _gitignored(rel: str) -> bool:
    return subprocess.run(["git", "--no-optional-locks", "check-ignore", rel],
                          cwd=REPO, capture_output=True).returncode == 0


def _tracked(rel: str) -> bool:
    out = subprocess.run(["git", "--no-optional-locks", "ls-files", rel],
                         cwd=REPO, capture_output=True, text=True).stdout.strip()
    return bool(out)


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def status():
    return _load("pass32_kaggle_status.json")


@pytest.fixture(scope="module")
def safety():
    return _load("pass32_raw_replay_safety.json")


@pytest.fixture(scope="module")
def attribution():
    return _load("pass32_replay_attribution.json")


@pytest.fixture(scope="module")
def postmortem():
    return _load("pass32_dragapult_postmortem.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass32_strategy_decision.json")


@pytest.fixture(scope="module")
def comparison():
    return _load("pass32_live_probe_comparison.json")


@pytest.fixture(scope="module")
def events():
    evs = []
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass32" in (ev.get("tags") or []):
            evs.append(ev)
    return evs


# ----------------------------- root safety ---------------------------------

def test_root_files_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# ----------------------------- Kaggle status -------------------------------

def test_kaggle_status_read_only(status):
    assert status["no_upload"] is True
    assert status["upload_performed"] is False


def test_dragapult_resolved_and_below_control(status):
    drag = status["dragapult"]
    assert drag["status"] == "complete"
    assert isinstance(drag["public_score"], (int, float))
    assert drag["public_score"] == pytest.approx(309.2, abs=0.05)
    water = status["water_family_current_best"]
    assert drag["public_score"] < water["public_score"]


def test_live_leader_and_water_best_present(status):
    assert status["live_score_leader"]["filename"]
    assert status["water_family_current_best"]["filename"]
    assert status["dragapult_family_best"]["public_score"] == pytest.approx(309.2, abs=0.05)


# ----------------------------- raw replay safety ---------------------------

def test_new_replays_gitignored_untracked_valid(safety):
    assert sorted(safety["new_this_pass"]) == sorted(NEW_EPISODES)
    assert safety["new_all_gitignored"] is True
    assert safety["new_all_untracked"] is True
    assert safety["new_all_valid_structure"] is True
    assert safety["duplicate_filenames"] == []


def test_new_replays_actually_gitignored_on_disk():
    for ep in NEW_EPISODES:
        rel = f"data/meta_replays/raw/{ep}.json"
        assert (RAW / f"{ep}.json").exists()
        assert _gitignored(rel) is True
        assert _tracked(rel) is False


def test_preexisting_self_mirror_reported_only(safety):
    pm = safety["preexisting_self_mirror"]
    assert pm["episode_id"] == "80374966"


# ----------------------------- attribution ---------------------------------

def test_attribution_uses_exact_fingerprints(attribution):
    fps = attribution["candidate_fingerprints"]
    assert "league_dragapult_v1_search_only" in fps
    for a in attribution["attributions"]:
        assert a["belongs_to_dragapult_probe"] is True
        assert a["seat_attribution"]["0"]["deck_match"] == "league_dragapult_v1_search_only"


def test_water_fingerprint_ambiguity_reported(attribution):
    # If multiple water names exist, they must collapse to one fingerprint and
    # be reported as ambiguous (honesty requirement).
    assert "ambiguity_note" in attribution
    fps = attribution["candidate_fingerprints"]
    water = [n for n in fps if "water" in n]
    if len(water) > 1:
        assert len({fps[n] for n in water}) == 1
        assert attribution["fingerprint_ambiguity"]


def test_results_match_rewards(attribution):
    by_ep = {a["episode_id"]: a for a in attribution["attributions"]}
    assert by_ep["80760752"]["self_mirror"] is True
    assert "win" in by_ep["80760752"]["result_from_our_perspective"]
    assert by_ep["80760852"]["result_from_our_perspective"] == "loss"
    assert by_ep["80761535"]["result_from_our_perspective"] == "loss"


# ----------------------------- postmortem ----------------------------------

def test_postmortem_record(postmortem):
    assert postmortem["wins"] == 1
    assert postmortem["losses"] == 2
    assert postmortem["vs_real_opponent_record"] == "0W/2L"


def test_postmortem_no_spread_claim(postmortem):
    obs = postmortem["spread_targeting_observability"].lower()
    assert "not observable" in obs
    for g in postmortem["games"]:
        assert g["spread_target_observable"] is False
        assert g["phantom_dive_or_spread_used"] == "not_observable"
        assert g["dusknoir_line_observable"] is False
        assert g["boss_gust_observable"] is False


def test_postmortem_loss_conditions_honest(postmortem):
    by_ep = {g["episode_id"]: g for g in postmortem["games"]}
    assert by_ep["80760852"]["loss_classification"] == "prize_race_loss"
    assert by_ep["80761535"]["loss_condition"] == "no_pokemon_in_play"
    assert by_ep["80761535"]["loss_classification"] == "no_pokemon_loss"
    # very late first attack flagged as a contributing factor for 80761535
    assert "very_late_first_attack" in by_ep["80761535"]["contributing_factors"]


def test_no_invented_card_ids(postmortem):
    # Attacks expose only numeric attackIds; no card names are fabricated.
    for g in postmortem["games"]:
        for aid in g["attack_ids"]:
            assert isinstance(aid, int)


# ----------------------------- decision / queue ----------------------------

def test_decision_keep_water_control(decision):
    assert decision["decision"] == "keep_water_control"
    assert decision["no_upload"] is True
    assert decision["upload_performed"] is False
    assert decision["dry_run_queue_size"] == 0
    assert decision["queue_max"] == 1


def test_comparison_leader_row_is_self_consistent(comparison, status):
    # The live_score_leader's row in the comparison must match its complete
    # scored status (no duplicate-filename history collapsing to an error row).
    leader_fn = status["live_score_leader"]["filename"]
    leader_score = status["live_score_leader"]["public_score"]
    rows = {r["filename"]: r for r in comparison["candidates"]}
    assert leader_fn in rows
    assert rows[leader_fn]["status"] == "complete"
    assert rows[leader_fn]["public_score"] == pytest.approx(leader_score, abs=0.05)
    # every row that has a score must be a complete row
    for r in comparison["candidates"]:
        if r["public_score"] is not None:
            assert r["status"] == "complete"


def test_submission_queue_empty_no_upload():
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    assert q["schema"] == "ptcg_dry_run_submission_queue_v1"
    assert q["max_queue_size"] == 1
    assert len(q["queue"]) == 0
    assert q["upload_performed"] is False
    assert q["auto_submit_enabled"] is False


# ----------------------------- events --------------------------------------

def test_events_all_no_upload_and_no_upload_event(events):
    assert events, "expected pass32 events"
    types = [e.get("type") or e.get("event_type") for e in events]
    for e in events:
        assert e["payload"]["no_upload"] is True
    assert "SubmissionUploaded" not in types
    assert "KaggleScoreUpdated" in types
    assert types.count("ReplayImported") == 3
    assert types.count("ReplayAnalyzed") == 3
    assert "StrategyDecisionRecorded" in types


def test_no_submission_queued_event(events):
    # Dry-run queue empty -> no SubmissionQueued event.
    assert "SubmissionQueued" not in [e.get("type") or e.get("event_type") for e in events]


# ----------------------------- report --------------------------------------

def test_report_has_ten_sections():
    text = REPORT.read_text(encoding="utf-8")
    for i in range(1, 11):
        assert f"## {i}." in text, f"missing section {i}"
