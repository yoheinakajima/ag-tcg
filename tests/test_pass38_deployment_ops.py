"""Pass 38 — production scheduled-deployment OPS / soak / monitoring tests.

These tests verify the Pass 38 operational deliverables WITHOUT weakening any
prior safety guarantee: root immutability, the deploy config, the read-only
health checker's hard safety invariants, scheduler determinism/safety/progress,
the candidate-lifecycle status partition, projection purity, and the operator
runbook + incident addendum. No upload, no submit, no candidate generation.
"""
from __future__ import annotations

import filecmp
import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament import projections  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402

BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
DOCS = REPO / "docs"


# --------------------------------------------------------------------------- #
# load the health checker as a module (it is a script, not a package)
# --------------------------------------------------------------------------- #
def _load_health():
    path = REPO / "scripts" / "check_tournament_health.py"
    spec = importlib.util.spec_from_file_location("check_tournament_health", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve __module__ via sys.modules
    spec.loader.exec_module(mod)
    return mod


health = _load_health()


def _bundle(events, *, manifest=None, game_keys=None, queue=None, config_text=None,
            source="test", data=None):
    data = data or {}
    return health.StateBundle(source, events, manifest or {}, game_keys or [],
                              queue or {}, config_text, lambda k: data.get(k))


def _check(res, name):
    return next(c for c in res.checks if c.name == name)


def _real_events():
    return TournamentLedger().load()


def _real_pool():
    pool = CandidatePool.from_events(_real_events())
    return pool if pool.candidates else CandidatePool.load()


def _real_event_dicts():
    """Raw dict events as the health checker consumes them (not Event objects)."""
    p = REPO / "data" / "tournament" / "events.jsonl"
    return sync.parse_events_text(p.read_text(encoding="utf-8")) if p.is_file() else []


# --------------------------------------------------------------------------- #
# 1–2. root immutability
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fn", ["main.py", "deck.csv"])
def test_root_byte_identical_to_baseline(fn):
    assert (REPO / fn).is_file() and (BASELINE / fn).is_file()
    assert filecmp.cmp(REPO / fn, BASELINE / fn, shallow=False)


# --------------------------------------------------------------------------- #
# 3–6. deploy config invariants (.replit + pyproject)
# --------------------------------------------------------------------------- #
def _deployment():
    return tomllib.loads((REPO / ".replit").read_text(encoding="utf-8")).get(
        "deployment", {})


def test_replit_deployment_target_is_scheduled():
    assert _deployment().get("deploymentTarget") == "scheduled"


def test_replit_run_command_is_bounded_and_never_uploads():
    run = [str(x) for x in _deployment().get("run", [])]
    assert "scripts/tournament_deployment_tick.py" in run
    assert run[run.index("--max-games") + 1] == "20"
    assert run[run.index("--max-seconds") + 1] == "900"
    assert "--production" in run and "replit_app_storage" in run
    # never an upload/submit/auto-submit deployment
    for forbidden in ("--auto-submit", "--submit", "--upload"):
        assert forbidden not in run


def test_replit_build_command_pins_engine_deps():
    build = " ".join(str(x) for x in _deployment().get("build", []))
    assert "--user" in build and "--break-system-packages" in build
    assert "replit-object-storage" in build and "pyyaml" in build
    assert "kaggle-environments==1.30.1" in build


def test_pyproject_uv_package_false():
    cfg = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg.get("tool", {}).get("uv", {}).get("package") is False


# --------------------------------------------------------------------------- #
# 7–12. health checker — hard safety invariants
# --------------------------------------------------------------------------- #
def test_health_local_state_has_no_hard_failures():
    res = health.run_checks(health._local_bundle(), config_path_text=None)
    assert res.hard_failures == [], [c.name for c in res.hard_failures]


def test_health_flags_forbidden_upload_event():
    res = health.run_checks(
        _bundle([{"event_type": "SubmissionUploaded", "payload": {"no_upload": True}}]),
        config_path_text=None)
    assert _check(res, "no_forbidden_events").passed is False


def test_health_flags_event_missing_no_upload():
    res = health.run_checks(
        _bundle([{"event_type": "GameFinished",
                  "payload": {"game_id": "g1", "no_upload": False}}]),
        config_path_text=None)
    assert _check(res, "all_events_no_upload").passed is False


def test_health_flags_duplicate_finished_game_id():
    ev = [{"event_type": "GameFinished",
           "payload": {"game_id": "dup", "artifact_sha256": "a", "no_upload": True}},
          {"event_type": "GameFinished",
           "payload": {"game_id": "dup", "artifact_sha256": "a", "no_upload": True}}]
    res = health.run_checks(_bundle(ev), config_path_text=None)
    assert _check(res, "no_duplicate_finished_game_ids").passed is False


def test_health_flags_never_schedule_candidate_in_queue():
    pool = _real_pool()
    never = sorted(c.candidate_id for c in pool.candidates
                   if c.status in poolmod.NEVER_SCHEDULE)
    assert never, "ledger is expected to contain never-schedule candidates"
    queue = {"queue": [{"game_id": "x", "candidate_a": never[0],
                        "candidate_b": never[0]}]}
    res = health.run_checks(_bundle(_real_event_dicts(), queue=queue),
                            config_path_text=None)
    assert _check(res, "no_never_schedule_in_queue").passed is False


def test_health_flags_auto_submit_env(monkeypatch):
    monkeypatch.setenv("TOURNAMENT_AUTO_SUBMIT", "1")
    res = health.run_checks(_bundle([]), config_path_text=None)
    assert _check(res, "auto_submit_off").passed is False


# --------------------------------------------------------------------------- #
# 13–15. scheduler determinism / safety / progress
# --------------------------------------------------------------------------- #
def _worklist():
    cfg = load_config()
    events = _real_events()
    pool = _real_pool()
    agg = projections.fold_games(events)
    ranked = [r["candidate_id"] for r in projections.compute_rankings(pool, agg)]
    state = projections.build_scheduler_state(events, ranking=ranked)
    return pool, cfg, build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)


def test_scheduler_worklist_is_deterministic():
    _, _, wl1 = _worklist()
    _, _, wl2 = _worklist()
    assert [g.game_id for g in wl1] == [g.game_id for g in wl2]
    assert wl1, "worklist should be non-empty while candidates are below quota"


def test_scheduler_worklist_excludes_never_schedule():
    pool, _, wl = _worklist()
    blocked = {c.candidate_id for c in pool.candidates if not c.schedulable}
    for g in wl:
        assert g.candidate_a not in blocked and g.candidate_b not in blocked


def test_scheduler_worklist_excludes_finished_games():
    _, _, wl = _worklist()
    finished = set(TournamentLedger().finished_game_ids())
    assert wl, "worklist should propose new (unplayed) games"
    assert all(g.game_id not in finished for g in wl)


# --------------------------------------------------------------------------- #
# 16. candidate lifecycle status partition
# --------------------------------------------------------------------------- #
def test_candidate_lifecycle_status_partition_invariants():
    pool = _real_pool()
    assert not (poolmod.SCHEDULABLE_STATUSES & poolmod.NEVER_SCHEDULE)
    for c in pool.candidates:
        assert c.status in poolmod.VALID_STATUSES
        assert c.schedulable == (c.status in poolmod.SCHEDULABLE_STATUSES)
        if c.status in poolmod.NEVER_SCHEDULE:
            assert not c.schedulable
    # held probe must remain schedulable (retention not silently dropped)
    for c in pool.candidates:
        if c.status == poolmod.HELD_PROBE:
            assert c.schedulable


# --------------------------------------------------------------------------- #
# 17. projection purity (event-sourced, deterministic)
# --------------------------------------------------------------------------- #
def test_projection_fold_is_pure():
    events = _real_events()
    a = projections.fold_games(events)
    b = projections.fold_games(events)
    assert a["totals"] == b["totals"]
    assert a["per"] == b["per"] and a["matchup"] == b["matchup"]
    assert a["directed"] == b["directed"]


# --------------------------------------------------------------------------- #
# 18. operator runbook + incident addendum present
# --------------------------------------------------------------------------- #
def test_runbook_and_incident_addendum_present():
    runbook = (DOCS / "REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md")
    assert runbook.is_file()
    text = runbook.read_text(encoding="utf-8")
    for needed in ("Scheduled Deployment", "Concurrency invariant",
                   "package = false", "kaggle-environments==1.30.1",
                   "check_tournament_health.py", "NOT a Kaggle leaderboard"):
        assert needed in text, needed
    # the EXACT live .replit run/build commands must appear verbatim — the runbook
    # may never silently drift from what the deployment actually executes.
    dep = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))["deployment"]
    norm = " ".join(text.split())
    assert " ".join(str(x) for x in dep["run"]) in norm
    assert " ".join(str(x) for x in dep["build"]) in norm
    for doc in ("PERSISTENT_TOURNAMENT_DAEMON.md", "PTCG_STRATEGY_CANVAS.md"):
        body = (DOCS / doc).read_text(encoding="utf-8")
        assert body.count("PASS38_ADDENDUM_START") == 1, doc
        assert "PASS38_ADDENDUM_END" in body
