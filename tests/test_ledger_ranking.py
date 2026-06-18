"""Pass 7B Part G/I: ranking + dry-run queue from durable ledger state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptcg_activegraph.ag import ActiveGraphLedger
from ptcg_activegraph.experiments.dry_run_queue import build_dry_run_queue
from ptcg_activegraph.experiments.durable_runner import DurableRunner
from ptcg_activegraph.experiments.ledger_ranking import (
    rank_run,
    wilson_interval,
    write_ranking,
)


def _make_candidate(root: Path, branch_id: str) -> Path:
    d = root / f"20260618_000000_{branch_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text("def agent(obs, *a, **k):\n    return []\n")
    (d / "deck.csv").write_text("\n".join(["3"] * 60) + "\n")
    (d / "branch.yaml").write_text(
        f"branch_id: {branch_id}\nseam_id: s\nfamily: t\nkind: policy\n"
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


def _win_executor(game):
    return {"completed": True, "candidate_won": True, "draw": False,
            "candidate_seat": game.seat, "fast_import_stub_enabled": True,
            "import_optimization_mode": "fast_stub"}


def _loss_executor(game):
    return {"completed": True, "candidate_won": False, "draw": False,
            "candidate_seat": game.seat}


def test_wilson_interval_basic():
    lo, hi = wilson_interval(6, 6, 95)
    assert 0.0 <= lo <= hi <= 1.0
    assert lo > 0.5  # 6/6 lower bound is well above coin-flip
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_rank_run_reads_ledger_and_excludes_anchor(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_winner")
    _make_candidate(root, "pass6_control_v2_anchor")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=1, seats=(0, 1),
                         candidate_ids=["policy_winner", "pass6_control_v2_anchor"])
    runner.execute(run_id, executor=_win_executor)

    rank = rank_run(run_id, ledger=runner.ledger)
    cand_ids = [c["candidate_id"] for c in rank["candidates"]]
    anchor_ids = [a["candidate_id"] for a in rank["anchors"]]
    assert "policy_winner" in cand_ids
    # The anchor must NOT appear in the top candidate list.
    assert "pass6_control_v2_anchor" not in cand_ids
    assert "pass6_control_v2_anchor" in anchor_ids
    winner = rank["candidates"][0]
    assert winner["adjusted_win_rate"] == 1.0
    assert winner["fast_import_stub_used"] is True
    assert rank["anchors"][0]["promotion_label"] == "anchor_control"


def test_small_clean_sample_is_scout_promising_not_promotable(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_small")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=3, seats=(0, 1),
                         candidate_ids=["policy_small"])
    runner.execute(run_id, executor=_win_executor)  # 6 clean wins
    rank = rank_run(run_id, ledger=runner.ledger)
    c = rank["candidates"][0]
    assert c["games_completed"] == 6
    # < 20 completed games => never promotable
    assert c["promotion_label"] == "scout_promising"


def test_loser_is_rejected(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_loser")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=2, seats=(0, 1),
                         candidate_ids=["policy_loser"])
    runner.execute(run_id, executor=_loss_executor)
    rank = rank_run(run_id, ledger=runner.ledger)
    assert rank["candidates"][0]["promotion_label"] == "rejected"


def test_crash_makes_not_promotable_and_unqueueable(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_flaky")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=1, seats=(0,),
                         candidate_ids=["policy_flaky"])

    def _crash(game):
        return {"completed": False, "error": "boom"}

    runner.execute(run_id, executor=_crash)
    rank = rank_run(run_id, ledger=runner.ledger)
    c = rank["candidates"][0]
    assert c["crashes"] == 1
    assert c["promotion_label"] in ("inconclusive", "blocked")
    doc = build_dry_run_queue(run_id, rank, artifacts_root=runner.artifacts_root,
                              queue_path=tmp_path / "queue.json")
    assert doc["queued_candidate_count"] == 0
    assert doc["auto_submit_enabled"] is False
    assert doc["upload_performed"] is False


def test_dry_run_queue_queues_one_clean_winner(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_winner")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=3, seats=(0, 1),
                         candidate_ids=["policy_winner"])
    runner.execute(run_id, executor=_win_executor)
    rank = rank_run(run_id, ledger=runner.ledger)
    doc = build_dry_run_queue(run_id, rank, artifacts_root=runner.artifacts_root,
                              queue_path=tmp_path / "queue.json")
    assert doc["queued_candidate_count"] == 1
    q = doc["queue"][0]
    assert q["candidate_id"] == "policy_winner"
    assert Path(q["tarball"]).exists()
    assert sorted(q["tarball_members"]) == ["deck.csv", "main.py"]
    assert doc["max_queue_size"] == 1
    assert doc["require_manual_approval_for_submit"] is True


def test_write_ranking_emits_json_and_md(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "policy_winner")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=2, seats=(0, 1),
                         candidate_ids=["policy_winner"])
    runner.execute(run_id, executor=_win_executor)
    j = tmp_path / "rank.json"
    m = tmp_path / "rank.md"
    write_ranking(run_id, j, m, ledger=runner.ledger)
    assert j.exists() and m.exists()
    data = json.loads(j.read_text(encoding="utf-8"))
    assert data["ranking_source"] == "durable_activegraph_ledger"
    assert "Pass 7B Scout Ranking" in m.read_text(encoding="utf-8")


def test_candidate_id_selection_reports_missing(runner, tmp_path):
    root = tmp_path / "runs"
    _make_candidate(root, "exists_a")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "pass7b_scout", games_per_seat=1, seats=(0,),
                         candidate_ids=["exists_a", "does_not_exist"])
    assert runner._missing_candidate_ids == ["does_not_exist"]
    rank = rank_run(run_id, ledger=runner.ledger)
    assert [c["candidate_id"] for c in rank["candidates"]] == ["exists_a"]
