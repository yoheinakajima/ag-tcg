"""Pass 7B Part B: fast cabt import stub wired into the durable child runner.

These tests never play a real cabt game. They drive the child's import-mode
helpers directly and stub out ``subprocess.Popen`` to assert the parent passes
the opt-in env var through and persists the import-optimization metadata into
the durable per-game result.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from ptcg_activegraph.ag import ActiveGraphLedger
from ptcg_activegraph.experiments import _game_subprocess as child
from ptcg_activegraph.experiments import durable_runner as dr
from ptcg_activegraph.experiments import run_state as rs
from ptcg_activegraph.experiments.durable_runner import DurableRunner
from ptcg_activegraph.sim.kaggle_import_optimization import disable_fast_cabt_import_stub

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _runner(tmp_path, fast_import_stub):
    ledger = ActiveGraphLedger(
        events_path=tmp_path / "events.jsonl",
        runs_path=tmp_path / "runs.json",
        artifacts_root=tmp_path / "artifacts",
        warn=False,
    )
    return DurableRunner(
        ledger=ledger,
        artifacts_root=tmp_path / "artifacts",
        fast_import_stub=fast_import_stub,
    )


class _FakePopen:
    """Stand-in for the cabt child: writes the out.json the parent expects."""

    captured_env: dict = {}

    def __init__(self, cmd, stdout=None, stderr=None, start_new_session=True, env=None):
        type(self).captured_env = dict(env or {})
        self.pid = 999999
        self.returncode = 0
        fast = (env or {}).get("PTCG_FAST_CABT_IMPORT_STUB") == "1"
        out_path = Path(cmd[3])
        out_path.write_text(
            json.dumps(
                {
                    "completed": True,
                    "candidate_won": True,
                    "candidate_seat": 0,
                    "fast_import_stub_enabled": fast,
                    "import_optimization_mode": "fast_stub" if fast else "normal",
                    "import_optimization_validated": None,
                    "import_optimization_fallback": False,
                }
            ),
            encoding="utf-8",
        )

    def wait(self, timeout=None):
        return 0


# -- child import-mode helpers ------------------------------------------------
def test_child_meta_defaults_are_safe_normal():
    meta = child._import_meta_defaults()
    assert meta["fast_import_stub_enabled"] is False
    assert meta["import_optimization_mode"] == "normal"
    assert meta["import_optimization_fallback"] is False


def test_child_no_stub_when_env_absent(monkeypatch):
    monkeypatch.delenv("PTCG_FAST_CABT_IMPORT_STUB", raising=False)
    meta = child._import_meta_defaults()
    state = child._maybe_enable_fast_stub(meta)
    assert state is None
    assert meta["import_optimization_mode"] == "normal"
    assert meta["fast_import_stub_enabled"] is False


def test_child_enables_stub_when_env_set(monkeypatch):
    monkeypatch.setenv("PTCG_FAST_CABT_IMPORT_STUB", "1")
    meta = child._import_meta_defaults()
    state = child._maybe_enable_fast_stub(meta)
    try:
        assert meta["fast_import_stub_enabled"] is True
        assert meta["import_optimization_mode"] == "fast_stub"
    finally:
        if state is not None:
            disable_fast_cabt_import_stub(state)


def test_child_fallback_recorded_on_import_failure(monkeypatch):
    """A cabt import failure under the stub is recorded as a normal fallback."""
    monkeypatch.setenv("PTCG_FAST_CABT_IMPORT_STUB", "1")
    meta = child._import_meta_defaults()
    state = child._maybe_enable_fast_stub(meta)
    assert meta["fast_import_stub_enabled"] is True
    # Simulate the self-heal path the child runs when the cabt import fails.
    child._fall_back_to_normal_import(meta, state)
    assert meta["import_optimization_fallback"] is True
    assert meta["fast_import_stub_enabled"] is False
    assert meta["import_optimization_mode"] == "normal"


def test_import_failed_detects_unavailable():
    assert child._import_failed({"error": "kaggle_environments unavailable: X"}) is True
    assert child._import_failed({"error": "some other error"}) is False
    assert child._import_failed({"completed": True}) is False


# -- parent (durable runner) wiring ------------------------------------------
def test_runner_passes_fast_import_env_and_records_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(dr.subprocess, "Popen", _FakePopen)
    runner = _runner(tmp_path, fast_import_stub=True)
    root = tmp_path / "runs"
    _make_candidate(root, "cand_a")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "wiring", games_per_seat=1, seats=(0,))
    runner.execute(run_id, max_games=1)  # real executor + fake Popen
    assert _FakePopen.captured_env.get("PTCG_FAST_CABT_IMPORT_STUB") == "1"
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    done = [g for g in games if g.status == "completed"][0]
    result = json.loads(Path(done.result_json_path).read_text(encoding="utf-8"))
    assert result["fast_import_stub_enabled"] is True
    assert result["import_optimization_mode"] == "fast_stub"


def test_runner_normal_mode_has_no_fast_env(tmp_path, monkeypatch):
    monkeypatch.setattr(dr.subprocess, "Popen", _FakePopen)
    runner = _runner(tmp_path, fast_import_stub=False)
    root = tmp_path / "runs"
    _make_candidate(root, "cand_a")
    ctrl = _make_control(tmp_path)
    run_id = runner.plan(root, ctrl, "wiring", games_per_seat=1, seats=(0,))
    runner.execute(run_id, max_games=1)
    assert "PTCG_FAST_CABT_IMPORT_STUB" not in _FakePopen.captured_env
    games = rs.load_game_states(run_id, tmp_path / "artifacts")
    done = [g for g in games if g.status == "completed"][0]
    result = json.loads(Path(done.result_json_path).read_text(encoding="utf-8"))
    assert result["fast_import_stub_enabled"] is False
    assert result["import_optimization_mode"] == "normal"


def test_fast_stub_does_not_touch_root_submission(tmp_path, monkeypatch):
    """Enabling/disabling the stub must never modify root main.py / deck.csv."""
    def _digest(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    before = {f: _digest(REPO_ROOT / f) for f in ("main.py", "deck.csv")}
    monkeypatch.setenv("PTCG_FAST_CABT_IMPORT_STUB", "1")
    meta = child._import_meta_defaults()
    state = child._maybe_enable_fast_stub(meta)
    if state is not None:
        disable_fast_cabt_import_stub(state)
    after = {f: _digest(REPO_ROOT / f) for f in ("main.py", "deck.csv")}
    assert before == after
