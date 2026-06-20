"""Pass 37 — deployment-readiness + persistent-storage guardrail tests.

These tests assert the storage abstraction, state sync/merge, lease, and the
scheduled worker wrapper behave honestly and fail closed in production. They also
re-assert the Pass 36 safety invariants the deployment must preserve: root files
byte-identical, no upload/submit events, special pilots never scheduled, held
probe still held.
"""
from __future__ import annotations

import filecmp
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402
from ptcg_activegraph.tournament import storage as st  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.config import TournamentConfig, load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402

BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
TOURNAMENT_DIR = REPO / "data" / "tournament"
WRAPPER = REPO / "scripts" / "tournament_deployment_tick.py"
CONFIG_GEN = REPO / "scripts" / "print_replit_scheduled_deployment_config.py"


# --------------------------------------------------------------------------- #
# Root safety
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fn", ["main.py", "deck.csv"])
def test_root_byte_identical_to_baseline(fn):
    assert filecmp.cmp(REPO / fn, BASELINE / fn, shallow=False), (
        f"root {fn} drifted from frozen baseline"
    )


# --------------------------------------------------------------------------- #
# Storage backend: round-trip + fail-closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("make", [
    lambda root: st.InMemoryStorageBackend(prefix="tournament/v0"),
    lambda root: st.LocalFileStorageBackend(root=root, prefix="tournament/v0"),
])
def test_backend_roundtrip(make, tmp_path):
    be = make(tmp_path / "store")
    be.write_text("events.jsonl", "a\nb\n")
    be.write_bytes("games/g.json.gz", b"\x1f\x8bdata")
    be.put_json("candidate_pool.json", {"x": 1})
    assert be.exists("events.jsonl") and not be.exists("missing")
    assert be.read_text("events.jsonl") == "a\nb\n"
    assert be.read_bytes("games/g.json.gz") == b"\x1f\x8bdata"
    assert be.get_json("candidate_pool.json") == {"x": 1}
    assert set(be.list()) == {"events.jsonl", "games/g.json.gz", "candidate_pool.json"}
    assert be.list("games") == ["games/g.json.gz"]
    import hashlib
    assert be.sha256("events.jsonl") == hashlib.sha256(b"a\nb\n").hexdigest()
    assert be.sha256("missing") is None
    be.delete("events.jsonl")
    assert not be.exists("events.jsonl")


def test_production_refuses_non_durable_backends():
    with pytest.raises(st.ProductionStorageError):
        st.get_storage_backend(env="production", backend="local")
    with pytest.raises(st.ProductionStorageError):
        st.get_storage_backend(env="production", backend="memory")


def test_object_storage_fails_closed_when_unreachable():
    # Fail closed (never silently fall back to local) if the client is unusable.
    class _Broken:
        def list(self, *a, **k):
            raise RuntimeError("bucket unreachable")

    be = st.ObjectStorageBackend(prefix="tournament/v0", client=_Broken())
    with pytest.raises(st.StorageUnavailableError):
        be.ensure_available()


@pytest.mark.skipif(
    not __import__("os").environ.get("DEFAULT_OBJECT_STORAGE_BUCKET_ID"),
    reason="no Object Storage bucket provisioned in this environment",
)
def test_production_object_storage_available_when_provisioned():
    be = st.get_storage_backend(env="production", backend="replit_app_storage")
    assert isinstance(be, st.ObjectStorageBackend)
    be.ensure_available()  # live round-trip; raises if not reachable


def test_dev_defaults_to_local():
    be = st.get_storage_backend(env="dev")
    assert isinstance(be, st.LocalFileStorageBackend)


def test_auto_submit_refused_by_env(monkeypatch):
    monkeypatch.setenv("TOURNAMENT_AUTO_SUBMIT", "true")
    with pytest.raises(st.AutoSubmitRefusedError):
        st.assert_no_auto_submit()


def test_auto_submit_refused_by_config():
    with pytest.raises(st.AutoSubmitRefusedError):
        st.assert_no_auto_submit(TournamentConfig(auto_submit=True))


def test_kaggle_upload_refused(monkeypatch):
    monkeypatch.setenv("KAGGLE_SUBMIT", "1")
    with pytest.raises(st.AutoSubmitRefusedError):
        st.assert_no_kaggle_upload()


# --------------------------------------------------------------------------- #
# Sync: events, manifest, pull/push idempotence, reconcile
# --------------------------------------------------------------------------- #
def _ev(eid, etype, ts, game_id=None, sha=None):
    p = {"no_upload": True}
    if game_id is not None:
        p["game_id"] = game_id
    if sha is not None:
        p["artifact_sha256"] = sha
    return {"event_type": etype, "event_id": eid, "timestamp": ts, "payload": p}


def test_reconcile_merges_disjoint_by_event_id():
    local = [_ev("e1", "GameFinished", 1.0, "gA", "sha_a")]
    remote = [_ev("e2", "GameFinished", 2.0, "gB", "sha_b")]
    merged, rep = sync.reconcile_events(local, remote)
    gids = sorted((e["payload"]["game_id"] for e in merged))
    assert gids == ["gA", "gB"]
    assert rep["merged_count"] == 2


def test_reconcile_dedupes_idempotent_duplicate():
    local = [_ev("e1", "GameFinished", 1.0, "gA", "same")]
    remote = [_ev("e2", "GameFinished", 2.0, "gA", "same")]
    merged, rep = sync.reconcile_events(local, remote)
    finishes = [e for e in merged if e["event_type"] == "GameFinished"]
    assert len(finishes) == 1
    assert rep["deduped_lifecycle"] >= 1


def test_reconcile_raises_on_conflicting_finish():
    local = [_ev("e1", "GameFinished", 1.0, "gA", "sha_local")]
    remote = [_ev("e2", "GameFinished", 2.0, "gA", "sha_remote")]
    with pytest.raises(sync.ConflictError):
        sync.reconcile_events(local, remote)


def test_dump_events_is_canonical_jsonl():
    text = sync.dump_events([_ev("e1", "GameScheduled", 1.0, "gA")])
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == "e1" and parsed["payload"]["game_id"] == "gA"


def _seed_workdir(d: Path):
    (d / "projections").mkdir(parents=True, exist_ok=True)
    (d / "games").mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text(
        sync.dump_events([
            _ev("e1", "GameScheduled", 1.0, "gA"),
            _ev("e2", "GameFinished", 2.0, "gA", "sha_a"),
        ]),
        encoding="utf-8",
    )
    (d / "candidate_pool.json").write_text('{"tournament_id": "t"}', encoding="utf-8")
    (d / "config.yaml").write_text("auto_submit: false\n", encoding="utf-8")
    (d / "projections" / "rankings.json").write_text('{"r": []}', encoding="utf-8")
    (d / "games" / "gA.json.gz").write_bytes(b"\x1f\x8bsidecar")


def test_pull_push_roundtrip_and_manifest(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _seed_workdir(work)
    be = st.InMemoryStorageBackend(prefix="tournament/v0")

    res = sync.push_state(be, work, base_remote_hash=None, tick_id="t1")
    assert res["status"] == "clean"
    assert res["verify"]["ok"] and res["verify"]["mismatches"] == []
    # manifest sha entries match stored bytes
    manifest = be.get_json(sync.MANIFEST_KEY)
    assert manifest["no_upload"] is True and manifest["auto_submit"] is False
    for f in manifest["files"]:
        assert be.sha256(f["key"]) == f["sha256"]

    # pull into a fresh dir; events identical
    dest = tmp_path / "dest"
    summary = sync.pull_state(be, dest)
    assert "events.jsonl" in summary["keys"]
    assert (dest / "events.jsonl").read_text() == (work / "events.jsonl").read_text()

    # idempotent re-push (base = current remote hash) stays clean
    base = sync.remote_events_hash(be)
    res2 = sync.push_state(be, work, base_remote_hash=base, tick_id="t2")
    assert res2["status"] == "clean" and res2["drift"] is False


def test_push_dry_run_uploads_nothing(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _seed_workdir(work)
    be = st.InMemoryStorageBackend(prefix="tournament/v0")
    res = sync.push_state(be, work, base_remote_hash=None, tick_id="t", dry_run=True)
    assert res["status"] == "dry_run" and res["uploaded"] == []
    assert not be.exists("events.jsonl")


def test_push_detects_remote_drift_and_merges(tmp_path):
    """Simulate a concurrent worker that pushed a disjoint game meanwhile."""
    work = tmp_path / "work"
    work.mkdir()
    _seed_workdir(work)
    shared = {}
    be = st.InMemoryStorageBackend(prefix="tournament/v0", store=shared)

    # initial remote ledger has only gA; record its hash as our base.
    be.write_text("events.jsonl", (work / "events.jsonl").read_text())
    base = sync.remote_events_hash(be)

    # a concurrent worker appends gB to the remote ledger.
    remote_events = sync.parse_events_text(be.read_text("events.jsonl"))
    remote_events.append(_ev("e9", "GameFinished", 3.0, "gB", "sha_b"))
    be.write_text("events.jsonl", sync.dump_events(remote_events))

    res = sync.push_state(be, work, base_remote_hash=base, tick_id="t3")
    assert res["status"] == "merged" and res["drift"] is True
    merged = sync.parse_events_text(be.read_text("events.jsonl"))
    gids = sorted({e["payload"].get("game_id") for e in merged
                   if e["event_type"] == "GameFinished"})
    assert gids == ["gA", "gB"]  # neither side's game was lost


def test_push_reconciles_against_empty_base_remote_hash(tmp_path):
    """Regression: we pulled an EMPTY backend (base_remote_hash=None) but another
    worker pushed first. The late push must MERGE, never overwrite — otherwise the
    other worker's events are silently lost."""
    work = tmp_path / "work"
    work.mkdir()
    _seed_workdir(work)  # local ledger has gA scheduled + finished
    be = st.InMemoryStorageBackend(prefix="tournament/v0")

    base = sync.remote_events_hash(be)
    assert base is None  # we pulled an empty prefix

    # A concurrent worker writes a disjoint game gB into the (was-empty) remote.
    be.write_text("events.jsonl", sync.dump_events([
        _ev("e8", "GameScheduled", 2.5, "gB"),
        _ev("e9", "GameFinished", 3.0, "gB", "sha_b"),
    ]))

    res = sync.push_state(be, work, base_remote_hash=base, tick_id="t_race")
    assert res["drift"] is True and res["status"] == "merged"
    merged = sync.parse_events_text(be.read_text("events.jsonl"))
    gids = sorted({e["payload"].get("game_id") for e in merged
                   if e["event_type"] == "GameFinished"})
    assert gids == ["gA", "gB"]  # the other worker's game was NOT discarded


def test_pull_clears_stale_local_only_keys(tmp_path):
    """Regression: a file present locally but absent from the backend must not
    survive a pull (so it can never be pushed back). Bootstrap config/pool are
    kept so a brand-new tournament can still seed when the backend is empty."""
    work = tmp_path / "work"
    work.mkdir()
    _seed_workdir(work)  # creates events.jsonl, games/gA.json.gz, projections/, pool, config
    stale_proj = work / "projections" / "old_rankings.json"
    stale_proj.write_text("{}", encoding="utf-8")
    stale_game = work / "games" / "gA.json.gz"
    assert stale_game.is_file() and stale_proj.is_file()

    # Backend holds ONLY a single events.jsonl — no games/projections.
    be = st.InMemoryStorageBackend(prefix="tournament/v0")
    be.write_text("events.jsonl", sync.dump_events([_ev("e1", "GameScheduled", 1.0, "gZ")]))

    summary = sync.pull_state(be, work)
    assert "events.jsonl" in summary["cleared"] and "games/" in summary["cleared"]
    assert not stale_game.exists()  # local-only derived file removed
    assert not stale_proj.exists()
    assert (work / "candidate_pool.json").is_file()  # bootstrap preserved
    assert (work / "config.yaml").is_file()           # bootstrap preserved
    keys = sync.collect_local_keys(work)
    assert "games/gA.json.gz" not in keys  # stale derived state is not re-pushed
    assert "events.jsonl" in keys


def test_reconcile_conflicts_on_divergent_lifecycle():
    """Regression: two GameScheduled for the same game_id with different identity
    payloads (different candidates) is a divergence, not a silent drop."""
    a = {"event_type": "GameScheduled", "event_id": "x1", "timestamp": 1.0,
         "payload": {"game_id": "gX", "candidate_a": "deck1", "candidate_b": "deck2",
                     "no_upload": True, "run_id": "r1"}}
    b = {"event_type": "GameScheduled", "event_id": "x2", "timestamp": 2.0,
         "payload": {"game_id": "gX", "candidate_a": "deckZ", "candidate_b": "deck2",
                     "no_upload": True, "run_id": "r2"}}
    with pytest.raises(sync.ConflictError):
        sync.reconcile_events([a], [b])


def test_reconcile_collapses_idempotent_lifecycle_diff_volatile_only():
    """The same game scheduled by two workers differs only in volatile run_id/
    tick_id/priority; that is an idempotent re-emit and collapses cleanly."""
    a = {"event_type": "GameScheduled", "event_id": "y1", "timestamp": 1.0,
         "payload": {"game_id": "gY", "candidate_a": "d1", "candidate_b": "d2",
                     "no_upload": True, "run_id": "rA", "tick_id": "tA", "priority": 1}}
    b = {"event_type": "GameScheduled", "event_id": "y2", "timestamp": 2.0,
         "payload": {"game_id": "gY", "candidate_a": "d1", "candidate_b": "d2",
                     "no_upload": True, "run_id": "rB", "tick_id": "tB", "priority": 5}}
    merged, report = sync.reconcile_events([a], [b])
    sched = [e for e in merged
             if e["event_type"] == "GameScheduled" and e["payload"]["game_id"] == "gY"]
    assert len(sched) == 1 and report["deduped_lifecycle"] == 1


def test_reconcile_collapses_duplicate_finish_same_sha_diff_runtime():
    """Regression: two GameFinished for the same game_id with the SAME
    artifact_sha256 but different runtime metadata (elapsed_s/run_id/tick_id) are
    idempotent duplicates and must collapse, not raise (locked-design rule)."""
    a = {"event_type": "GameFinished", "event_id": "f1", "timestamp": 5.0,
         "payload": {"game_id": "gF", "artifact_sha256": "shaX", "a_outcome": "win",
                     "no_upload": True, "run_id": "rA", "tick_id": "tA",
                     "elapsed_s": 12.3, "steps": 40}}
    b = {"event_type": "GameFinished", "event_id": "f2", "timestamp": 6.0,
         "payload": {"game_id": "gF", "artifact_sha256": "shaX", "a_outcome": "win",
                     "no_upload": True, "run_id": "rB", "tick_id": "tB",
                     "elapsed_s": 14.9, "steps": 41}}
    merged, report = sync.reconcile_events([a], [b])
    fin = [e for e in merged
           if e["event_type"] == "GameFinished" and e["payload"]["game_id"] == "gF"]
    assert len(fin) == 1 and report["deduped_lifecycle"] == 1


# --------------------------------------------------------------------------- #
# Lease
# --------------------------------------------------------------------------- #
def test_lease_acquire_block_expire_release():
    be = st.InMemoryStorageBackend(prefix="tournament/v0")
    l1 = lease_mod.acquire_lease(be, ttl_seconds=100, owner="A", tick_id="t1", now=1000.0)
    assert be.exists(lease_mod.LOCK_KEY)
    # a different worker cannot acquire while active
    with pytest.raises(lease_mod.LeaseHeldError):
        lease_mod.acquire_lease(be, ttl_seconds=100, owner="B", tick_id="t2", now=1050.0)
    # after expiry another worker may recover it
    l2 = lease_mod.acquire_lease(be, ttl_seconds=100, owner="B", tick_id="t2", now=1200.0)
    assert l2.owner == "B"
    # only the owner releases
    assert lease_mod.release_lease(be, l2) is True
    assert not be.exists(lease_mod.LOCK_KEY)
    assert lease_mod.release_lease(be, l1) is False


# --------------------------------------------------------------------------- #
# Pass 36 invariants the deployment must preserve
# --------------------------------------------------------------------------- #
def test_ledger_refuses_upload_events(tmp_path):
    led = TournamentLedger(tmp_path / "events.jsonl")
    for forbidden in (EventType.SubmissionUploaded, EventType.KaggleScoreUpdated):
        with pytest.raises(PermissionError):
            led.emit(forbidden, {"x": 1})
    ev = led.emit(EventType.GameScheduled, {"game_id": "g"})
    assert ev.payload["no_upload"] is True


def test_live_ledger_has_no_upload_or_submit_events():
    led = TournamentLedger()
    types = {e.event_type for e in led.load()}
    assert "SubmissionUploaded" not in types
    assert "KaggleScoreUpdated" not in types
    # every event carries no_upload=true
    assert all(e.payload.get("no_upload") is True for e in led.load())


def test_special_pilots_never_scheduled_and_held_probe_held():
    from ptcg_activegraph.tournament import projections
    from ptcg_activegraph.tournament.pool import CandidatePool, SPECIAL_PILOT_ONLY, HELD_PROBE
    from ptcg_activegraph.tournament.scheduler import build_worklist

    pool = CandidatePool.load()
    special = {c.candidate_id for c in pool.candidates if c.status == SPECIAL_PILOT_ONLY}
    assert special, "expected Toxic/Durant special pilots in the pool"
    sched_ids = {c.candidate_id for c in pool.schedulable()}
    assert not (special & sched_ids)

    cfg = load_config()
    events = TournamentLedger().load()
    state = projections.build_scheduler_state(events)
    worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    for g in worklist:
        assert g.candidate_a not in special and g.candidate_b not in special

    held = [c for c in pool.candidates if c.status == HELD_PROBE]
    assert held, "expected the held probe to still exist and remain held"


def test_sidecar_codec_fallback_is_gzip():
    cfg = load_config()
    assert cfg.sidecar_codec_fallback == "gzip"
    sidecars = list((TOURNAMENT_DIR / "games").glob("*.json.gz"))
    assert sidecars, "expected at least one gzip sidecar"
    led = TournamentLedger()
    finishes = [e for e in led.load() if e.event_type == "GameFinished"]
    if finishes:
        assert finishes[0].payload.get("artifact_codec") in ("zstd", "gzip")


def test_no_raw_replays_or_card_dumps_in_synced_state():
    keys = sync.collect_local_keys(TOURNAMENT_DIR)
    for k in keys:
        assert not k.lower().endswith(".pdf")
        assert "cards.csv" not in k.lower()
        # game artifacts must be gzipped sidecars, not raw replay json
        if k.startswith("games/"):
            assert k.endswith(".json.gz")


# --------------------------------------------------------------------------- #
# Scripts import + run cleanly
# --------------------------------------------------------------------------- #
def _import_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wrapper_and_config_generator_import_cleanly():
    _import_path("pass37_wrapper", WRAPPER)
    _import_path("pass37_cfg_gen", CONFIG_GEN)


def test_config_generator_documents_scheduled_deployment():
    md = (REPO / "data" / "experiments" / "pass37_scheduled_deployment_config.md")
    out = subprocess.run(
        [sys.executable, str(CONFIG_GEN)], capture_output=True, text=True, cwd=REPO
    )
    assert out.returncode == 0
    text = (out.stdout + (md.read_text() if md.exists() else "")).lower()
    assert "scheduled deployment" in text
    assert "tournament_deployment_tick.py" in text
    assert "auto-submit" in text or "auto_submit" in text
    assert "kaggle" in text


def test_daemon_doc_warns_about_deployment_filesystem():
    doc = (REPO / "docs" / "PERSISTENT_TOURNAMENT_DAEMON.md").read_text().lower()
    assert "persistent storage" in doc
    assert "deployment filesystem" in doc or "deployed filesystem" in doc


def test_wrapper_refuses_auto_submit_via_subprocess():
    out = subprocess.run(
        [sys.executable, str(WRAPPER), "--no-games", "--storage-backend", "memory"],
        capture_output=True, text=True, cwd=REPO,
        env={**__import__("os").environ, "TOURNAMENT_AUTO_SUBMIT": "true"},
    )
    assert out.returncode == 2
    assert "refus" in (out.stdout + out.stderr).lower()
