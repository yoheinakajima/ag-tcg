"""Tests for the durable resumable evaluator (Pass 7A, Part E).

These use dummy executors so no cabt game is ever played.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ptcg_activegraph.ag import ActiveGraphLedger
from ptcg_activegraph.experiments import run_state as rs
from ptcg_activegraph.experiments.durable_runner import DurableRunner


def _make_candidate(root: Path, branch_id: str) -> Path:
    d = root / f"20260618_000000_{branch_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text("def agent(obs, *a, **k):\n    return []\n")
    (d / "deck.csv").write_text("\n".join(["3"] * 60) + "\n")
    (d / "branch.yaml").write_text(
        f"branch_id: {branch_id}\nseam_id: test_seam\nfamily: test\nkind: policy\n"
    )
    return d


def _make_control(root: Path) -> Path:
    d = root / "control"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text("def agent(obs, *a, **k):\n    return []\n")
    (d / "deck.csv").write_text("\n".join(["3"] * 60) + "\n")
    return d


@pytest.fixture()
def runner(tmp_path):
    ledger = ActiveGraphLedger(
        events_path=tmp_path / "events.jsonl",
        runs_path=tmp_path / "runs.json",
        artifacts_root=tmp_path / "artifacts",
        warn=False,
    )
    return DurableRunner(ledger=ledger, artifacts_root=tmp_path / "artifacts")


@pytest.fixture()
def runs_root(tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "cand_a")
    _make_candidate(root, "cand_b")
    return root


def _completed_executor(game):
    return {"completed": True, "candidate_won": True, "steps": 3, "timeout": False, "error": None}


def _timeout_executor(game):
    return {"completed": False, "timeout": True, "error": "timeout >x (killed)"}


def _crash_executor(game):
    return {"completed": False, "error": "boom"}


def _raise_executor(game):
    raise RuntimeError("native crash")


def _force_running_old(run_id, game_id, artifacts_root, age=10_000):
    """Simulate a hung game whose orchestrator died: running + old updated_at.

    Writes the state file directly so ``save_game_state``'s now-stamp doesn't
    overwrite the deliberately-old timestamp.
    """
    p = rs.game_state_path(run_id, game_id, artifacts_root)
    d = json.loads(p.read_text(encoding="utf-8"))
    old = time.time() - age
    d.update(status="running", started_at=old, updated_at=old)
    p.write_text(json.dumps(d), encoding="utf-8")


def test_plan_creates_game_rows_and_events(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0, 1))
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    # 2 candidates x 2 seats x 1 = 4 games, all planned
    assert len(games) == 4
    assert all(g.status == "planned" for g in games)
    summary = runner.ledger.inspect_run(run_id)
    assert summary["events_by_type"]["GamePlanned"] == 4
    assert summary["events_by_type"]["CandidateRegistered"] == 2


def test_execute_dummy_game_records_completed(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1)
    out = runner.execute(run_id, max_games=1, executor=_completed_executor)
    assert out["ran"]["completed"] == 1
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    done = [g for g in games if g.status == "completed"]
    assert len(done) == 1
    assert done[0].duration_seconds is not None
    summary = runner.ledger.inspect_run(run_id)
    assert summary["events_by_type"]["GameFinished"] == 1
    assert summary["events_by_type"]["GameResultRecorded"] == 1


def test_capped_execute_is_partial_not_completed(runner, runs_root, tmp_path):
    """A run with games still planned must NOT be finalized as completed."""
    ctrl = _make_control(tmp_path)
    # 2 candidates x 2 seats = 4 planned games; run only 1.
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0, 1))
    out = runner.execute(run_id, max_games=1, executor=_completed_executor)
    assert out["status"] == "partial"
    assert out["pending_games"] == 3
    run = rs.load_run_state(run_id, tmp_path / "artifacts")
    assert run.status == "partial"
    summary = runner.ledger.inspect_run(run_id)
    assert summary["status"] == "partial"
    assert "ExperimentRunFinished" not in summary["events_by_type"]
    # Finishing the rest flips the run to completed.
    fin = runner.execute(run_id, executor=_completed_executor)
    assert fin["status"] == "completed"
    assert runner.ledger.inspect_run(run_id)["status"] == "completed"


def test_stale_status_surfaces_in_inspect(runner, runs_root, tmp_path):
    """GameStale must be reflected in the ledger inspect game-status counts."""
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1, cabt_timeout_seconds=10)
    g = rs.load_game_states(run_id, tmp_path / "artifacts")[0]
    _force_running_old(run_id, g.game_id, tmp_path / "artifacts")
    runner.mark_stale(run_id)
    summary = runner.ledger.inspect_run(run_id)
    assert summary["game_status_counts"].get("stale") == 1
    assert summary["events_by_type"]["GameStale"] == 1


def test_timeout_dummy_marks_timeout(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1)
    runner.execute(run_id, max_games=1, executor=_timeout_executor)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    assert any(g.status == "timeout" for g in games)
    assert runner.ledger.inspect_run(run_id)["events_by_type"]["GameTimeout"] == 1


def test_crash_dummy_marks_crashed(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1)
    runner.execute(run_id, max_games=1, executor=_crash_executor)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    assert any(g.status == "crashed" for g in games)
    assert runner.ledger.inspect_run(run_id)["events_by_type"]["GameCrashed"] == 1


def test_executor_exception_marks_crashed(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1)
    runner.execute(run_id, max_games=1, executor=_raise_executor)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    crashed = [g for g in games if g.status == "crashed"]
    assert crashed and "executor raised" in (crashed[0].error_summary or "")


def test_stale_running_game_becomes_stale(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1, cabt_timeout_seconds=10)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    g = games[0]
    _force_running_old(run_id, g.game_id, tmp_path / "artifacts")
    marked = runner.mark_stale(run_id)
    assert g.game_id in marked
    reloaded = rs.load_game_states(run_id, tmp_path / "artifacts")
    assert any(x.status == "stale" for x in reloaded)


def test_resume_skips_completed_games(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0, 1),
                         limit_candidates=1)
    # 2 games planned; run 1
    runner.execute(run_id, max_games=1, executor=_completed_executor)
    after_first = rs.load_game_states(run_id, tmp_path / "artifacts")
    assert sum(1 for g in after_first if g.status == "completed") == 1
    assert sum(1 for g in after_first if g.status == "planned") == 1
    # resume runs only the remaining planned game (completed are skipped)
    out = runner.resume(run_id, executor=_completed_executor)
    assert out["ran"]["completed"] == 1
    final = rs.load_game_states(run_id, tmp_path / "artifacts")
    assert all(g.status == "completed" for g in final)


def test_resume_skips_stale_unless_retry(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1, cabt_timeout_seconds=10)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    _force_running_old(run_id, games[0].game_id, tmp_path / "artifacts")
    # resume without retry_stale: stale game is marked but NOT re-run
    out = runner.resume(run_id, retry_stale=False, executor=_completed_executor)
    assert out["ran"].get("completed", 0) == 0
    assert any(x.status == "stale" for x in rs.load_game_states(run_id, tmp_path / "artifacts"))


def test_resume_retries_stale_when_flagged(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1, cabt_timeout_seconds=10)
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    _force_running_old(run_id, games[0].game_id, tmp_path / "artifacts")
    out = runner.resume(run_id, retry_stale=True, executor=_completed_executor)
    assert out["ran"]["completed"] == 1
    assert all(x.status == "completed" for x in rs.load_game_states(run_id, tmp_path / "artifacts"))


def test_lifecycle_events_emitted(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0,),
                         limit_candidates=1)
    runner.execute(run_id, max_games=1, executor=_completed_executor)
    types = runner.ledger.inspect_run(run_id)["events_by_type"]
    for required in ("ExperimentRunCreated", "ExperimentRunStarted", "GamePlanned",
                     "GameStarted", "GameFinished", "ExperimentRunFinished"):
        assert required in types, f"missing {required}"


def test_status_reports_counts(runner, runs_root, tmp_path):
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(runs_root, ctrl, "smoke", games_per_seat=1, seats=(0, 1),
                         limit_candidates=1)
    runner.execute(run_id, max_games=1, executor=_completed_executor)
    st = runner.status(run_id)
    assert st["games_total"] == 2
    assert st["game_status_counts"].get("completed") == 1
    assert st["game_status_counts"].get("planned") == 1
    assert st["candidates"][0]["games_completed"] == 1
