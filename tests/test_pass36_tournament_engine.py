"""Pass 36 — standing tournament engine v0 tests.

Pure-unit where possible: scheduler/projection determinism use a synthetic pool;
the tick path is exercised with a FAKE game runner (monkeypatched subprocess) so
no cabt game actually runs. Internal diagnostics only; asserts NO upload.
"""
from __future__ import annotations

import filecmp
import importlib.util
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import artifacts, pool as poolmod, projections  # noqa: E402
from ptcg_activegraph.tournament.config import TournamentConfig, load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import Candidate, CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import (SchedulerState,  # noqa: E402
                                                   build_worklist)
from ptcg_activegraph.tournament.runner import (TournamentEngine,  # noqa: E402
                                                TickInProgressError, _tick_lock)
from ptcg_activegraph.graph.events import EventType  # noqa: E402

BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def work():
    """Temp dir INSIDE the repo (engine stores artifact paths relative to REPO)."""
    d = REPO / "data" / "tournament" / "_pytest" / uuid.uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _synthetic_pool() -> CandidatePool:
    c = []
    c.append(Candidate("water_ref", "water", 0, None, "t/water_ref.tar.gz",
                       status=poolmod.FAMILY_CHAMPION))
    c.append(Candidate("water_probe", "water", 1, "water_ref", "t/water_probe.tar.gz",
                       status=poolmod.HELD_PROBE))
    c.append(Candidate("drag_ref", "dragapult", 0, None, "t/drag_ref.tar.gz",
                       status=poolmod.PORTFOLIO_ANCHOR))
    c.append(Candidate("drag_child", "dragapult", 1, "drag_ref", "t/drag_child.tar.gz",
                       status=poolmod.ACTIVE))
    c.append(Candidate("lightning_ref", "lightning", 0, None, "t/l.tar.gz",
                       status=poolmod.PORTFOLIO_ANCHOR))
    c.append(Candidate("toxic", "toxic", 0, None, "t/toxic.tar.gz",
                       status=poolmod.SPECIAL_PILOT_ONLY))
    c.append(Candidate("durant", "durant", 0, None, "t/durant.tar.gz",
                       status=poolmod.SPECIAL_PILOT_ONLY))
    c.append(Candidate("old_grandparent", "water", -1, None, "t/old.tar.gz",
                       status=poolmod.RETIRED))
    c.append(Candidate("broken", "x", 0, None, "t/broken.tar.gz",
                       status=poolmod.QUARANTINED))
    return CandidatePool(c, tournament_id="test_tourney")


# --------------------------------------------------------------------------- #
# root safety
# --------------------------------------------------------------------------- #
def test_root_main_deck_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# --------------------------------------------------------------------------- #
# candidate pool seed
# --------------------------------------------------------------------------- #
def test_seeded_pool_has_expected_statuses():
    pool = CandidatePool.load()
    stats = pool.stats()
    assert stats.get(poolmod.HELD_PROBE, 0) >= 1
    assert stats.get(poolmod.SPECIAL_PILOT_ONLY, 0) >= 2
    assert stats.get(poolmod.FAMILY_CHAMPION, 0) >= 1
    assert pool.by_id("water_basic_density_v1").status == poolmod.HELD_PROBE
    assert pool.by_id("toxic_trap_poison_lock").status == poolmod.SPECIAL_PILOT_ONLY
    assert pool.by_id("deckout_carousel_durant_v2").status == poolmod.SPECIAL_PILOT_ONLY


def test_seeded_pool_within_active_caps():
    pool, cfg = CandidatePool.load(), load_config()
    assert pool.active_count() <= cfg.active_hard_cap


def test_pool_tarballs_exist_status_marks_only_no_deletion():
    pool = CandidatePool.load()
    sub = REPO / "data" / "submissions"
    for c in pool.candidates:
        assert (sub / c.tarball_path).exists(), f"tarball vanished: {c.tarball_path}"


# --------------------------------------------------------------------------- #
# scheduler
# --------------------------------------------------------------------------- #
def test_special_and_retired_never_scheduled():
    pool, cfg = _synthetic_pool(), TournamentConfig()
    wl = build_worklist(pool, SchedulerState(), cfg, max_games=40)
    blocked = {"toxic", "durant", "old_grandparent", "broken"}
    for g in wl:
        assert g.candidate_a not in blocked
        assert g.candidate_b not in blocked


def test_scheduler_deterministic():
    pool, cfg = _synthetic_pool(), TournamentConfig()
    st = SchedulerState(games_per_candidate={"water_ref": 30, "drag_ref": 30},
                        ranking=["water_ref", "drag_ref"])
    a = build_worklist(pool, st, cfg, max_games=20)
    b = build_worklist(pool, st, cfg, max_games=20)
    assert [g.game_id for g in a] == [g.game_id for g in b]


def test_scheduler_prioritizes_new_before_top_bracket():
    pool, cfg = _synthetic_pool(), TournamentConfig()
    # Anchors are "well played"; probe/child are new -> must come first.
    st = SchedulerState(
        games_per_candidate={"water_ref": 50, "drag_ref": 50, "lightning_ref": 50},
        ranking=["water_ref", "drag_ref", "lightning_ref"])
    wl = build_worklist(pool, st, cfg, max_games=20)
    assert wl[0].priority <= 2
    first_top = next((i for i, g in enumerate(wl) if g.priority == 4), len(wl))
    first_new = next((i for i, g in enumerate(wl) if g.priority <= 2), len(wl))
    assert first_new < first_top


def test_scheduler_game_ids_unique_within_worklist():
    pool, cfg = _synthetic_pool(), TournamentConfig()
    wl = build_worklist(pool, SchedulerState(), cfg, max_games=40)
    ids = [g.game_id for g in wl]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------- #
# tick path with a FAKE game runner (no cabt)
# --------------------------------------------------------------------------- #
def _install_fake_runner(monkeypatch):
    """Replace subprocess.run so the worker 'plays' instantly: candidate_a wins."""
    def fake_run(cmd, *a, **k):
        spec_path, out_path = Path(cmd[2]), Path(cmd[3])
        games = json.loads(spec_path.read_text())
        with open(out_path, "a") as f:
            for g in games:
                f.write(json.dumps({"ev": "start", "game_id": g["game_id"]}) + "\n")
                f.write(json.dumps({
                    "ev": "result", "game_id": g["game_id"],
                    "candidate_a": g["candidate_a"], "candidate_b": g["candidate_b"],
                    "a_seat": 0, "a_outcome": "win", "ok": True, "timeout": False,
                    "steps": 42, "rewards": [1, -1], "statuses": ["DONE", "DONE"],
                    "elapsed_s": 0.01, "error": None}) + "\n")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()
    monkeypatch.setattr(subprocess, "run", fake_run)


def _isolated_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(projections, "PROJ_DIR", tmp_path / "projections")
    monkeypatch.setattr(artifacts, "GAMES_DIR", tmp_path / "games")
    import ptcg_activegraph.tournament.runner as rn
    monkeypatch.setattr(rn, "RUNS_DIR", tmp_path / "runs")
    ledger = TournamentLedger(tmp_path / "events.jsonl")
    pool = CandidatePool.load()  # real tarballs (engine extracts agent main)
    cfg = TournamentConfig(tick_max_games=4, tick_max_seconds=60,
                           per_game_timeout_seconds=5)
    return TournamentEngine(cfg=cfg, pool=pool, ledger=ledger), ledger


def test_tick_respects_max_games(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    rec = engine.run_tick(max_games=3, max_seconds=60)
    assert rec["games_played"] == 3
    assert len(ledger.by_type(EventType.GameFinished)) == 3


def test_tick_event_chain_links_tick_schedule_start_finish(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=2, max_seconds=60)
    evs = ledger.load()
    by_id = {e.event_id: e for e in evs}
    tick = next(e for e in evs if e.event_type == EventType.TournamentTickStarted.value)
    for fin in (e for e in evs if e.event_type == EventType.GameFinished.value):
        start = by_id[fin.parent_event_ids[0]]
        assert start.event_type == EventType.GameStarted.value
        sched = by_id[start.parent_event_ids[0]]
        assert sched.event_type == EventType.GameScheduled.value
        assert tick.event_id in sched.parent_event_ids


def test_event_ids_unique(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=3, max_seconds=60)
    ids = [e.event_id for e in ledger.load()]
    assert len(ids) == len(set(ids))


def test_game_finished_requires_artifact_path_and_sha(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=2, max_seconds=60)
    for fin in ledger.by_type(EventType.GameFinished):
        assert fin.payload.get("artifact_path")
        assert fin.payload.get("artifact_sha256")
        sidecar = REPO / fin.payload["artifact_path"]
        assert sidecar.exists()
        assert artifacts.sha256_file(sidecar) == fin.payload["artifact_sha256"]


def test_all_events_no_upload_true(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=3, max_seconds=60)
    for e in ledger.load():
        assert e.payload.get("no_upload") is True


def test_tick_emits_no_upload_or_kaggle_events(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=3, max_seconds=60)
    bad = [e for e in ledger.load()
           if e.event_type in (EventType.SubmissionUploaded.value,
                               EventType.KaggleScoreUpdated.value)]
    assert bad == []


def test_ledger_refuses_to_emit_upload_event(tmp_path):
    ledger = TournamentLedger(tmp_path / "ev.jsonl")
    with pytest.raises(PermissionError):
        ledger.emit(EventType.SubmissionUploaded, {"x": 1})


def test_tick_resume_no_duplicate_game_ids(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=4, max_seconds=60)
    first = sorted(ledger.finished_game_ids())
    engine.run_tick(max_games=4, max_seconds=60)
    after = sorted(ledger.finished_game_ids())
    assert len(after) == len(set(after))
    assert len(after) > len(first)  # made progress
    # no id appears twice across the two ticks
    gf = [e.payload["game_id"] for e in ledger.by_type(EventType.GameFinished)]
    assert len(gf) == len(set(gf))


# --------------------------------------------------------------------------- #
# projections rebuild / idempotency
# --------------------------------------------------------------------------- #
def test_projections_rebuild_from_events_idempotent(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, ledger = _isolated_engine(monkeypatch, work)
    engine.run_tick(max_games=3, max_seconds=60)
    pool, cfg = engine.pool, engine.cfg
    evs = ledger.load()
    s1 = projections.write_projections(pool, evs, cfg)
    f1 = (projections.PROJ_DIR / "rankings.json").read_text()
    s2 = projections.write_projections(pool, evs, cfg)
    f2 = (projections.PROJ_DIR / "rankings.json").read_text()
    assert s1["rankings"] == s2["rankings"]
    assert f1 == f2


# --------------------------------------------------------------------------- #
# held probe / safety contract
# --------------------------------------------------------------------------- #
def test_held_probe_remains_held_and_queue_not_auto_submitted():
    q = json.loads((REPO / "data" / "submission_queue.json").read_text())
    assert q["auto_submit_enabled"] is False
    assert q.get("upload_performed") is False
    pool = CandidatePool.load()
    assert pool.by_id("water_basic_density_v1").status == poolmod.HELD_PROBE


def test_config_auto_submit_false_by_default():
    assert load_config().auto_submit is False


def test_pool_rebuilds_from_events_only(tmp_path):
    ledger = TournamentLedger(tmp_path / "ev.jsonl")
    ledger.emit(EventType.TournamentEngineInitialized, {"tournament_id": "tx"})
    src = _synthetic_pool()
    for c in src.candidates:
        ledger.emit(EventType.TournamentParticipantRegistered,
                    {"candidate_id": c.candidate_id, "candidate": c.to_dict()})
    rebuilt = CandidatePool.from_events(ledger.load())
    assert rebuilt.tournament_id == "tx"
    assert {c.candidate_id for c in rebuilt.candidates} == \
           {c.candidate_id for c in src.candidates}
    # full snapshot preserved (generation/parent/status), not just id
    rb = rebuilt.by_id("drag_child")
    assert rb.generation == 1 and rb.parent_candidate_id == "drag_ref"
    assert rebuilt.by_id("water_probe").status == poolmod.HELD_PROBE


def test_tick_lock_blocks_concurrent_run(monkeypatch, work):
    _install_fake_runner(monkeypatch)
    engine, _ = _isolated_engine(monkeypatch, work)
    with _tick_lock():  # simulate another tick already holding the lock
        with pytest.raises(TickInProgressError):
            engine.run_tick(max_games=1, max_seconds=10)


# --------------------------------------------------------------------------- #
# artifacts codec fallback (zstd unavailable -> gzip, recorded honestly)
# --------------------------------------------------------------------------- #
def test_sidecar_codec_is_known_value():
    assert artifacts.sidecar_codec() in ("zstd", "gzip")


def test_sidecar_roundtrip(work, monkeypatch):
    monkeypatch.setattr(artifacts, "GAMES_DIR", work)
    meta = artifacts.write_game_sidecar("g_test", {"a": 1, "result": "win"})
    assert meta["codec"] in ("zstd", "gzip")
    back = artifacts.read_game_sidecar(REPO / meta["path"])
    assert back["result"] == "win" and back["no_upload"] is True


# --------------------------------------------------------------------------- #
# report / scripts hygiene
# --------------------------------------------------------------------------- #
def test_report_has_internal_not_kaggle_caveat():
    rep = (REPO / "data" / "reports" /
           "pass36_standing_tournament_engine_report.md").read_text().lower()
    assert "not a kaggle leaderboard" in rep or "not a kaggle" in rep
    assert "no upload" in rep


@pytest.mark.parametrize("script", [
    "seed_tournament_pool", "tournament_daemon_tick",
    "build_tournament_projections", "run_pass36_engine_smoke",
    "_tournament_game_worker"])
def test_new_scripts_import_cleanly(script):
    path = REPO / "scripts" / f"{script}.py"
    assert path.exists()
    spec = importlib.util.spec_from_file_location(f"_imp_{script}", path)
    mod = importlib.util.module_from_spec(spec)
    # import-only: scripts guard real work behind __main__
    spec.loader.exec_module(mod)
