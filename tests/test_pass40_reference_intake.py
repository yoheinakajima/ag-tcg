"""Pass 40 — public reference agent intake + cg_typed lane + benchmark lane.

Pure in-memory tests plus committed-artifact integrity checks. No network, no Kaggle,
no native ``libcg.so`` import, no real game execution. Ledger-writing tests use a
``tmp_path`` benchmark ledger; the projection test monkeypatches the output dir.

Coverage (18 items):
  1. load_opponents: built-only, external_reference status, sorted, optional toggle
  2. BenchmarkOpponent.no_upload defaults True
  3. classify_result inverts the reference's outcome to our perspective
  4. classify_result maps incomplete/error/timeout -> invalid, draw -> draw
  5. build_benchmark_worklist: only references as opponents, only ours as subjects
  6. build_benchmark_worklist: bounded by max_games + seat balancing
  7. build_benchmark_worklist: resumes least-played-first from prior counts
  8. register_opponents idempotent (tmp ledger) + writes reference_pool.json
  9. benchmark_ledger writes a SEPARATE file and stamps no_upload on every event
 10. fold_benchmark_games totals/per_pair/per_our from synthetic events
 11. write_benchmark_projection structure (tmp dir)
 12. assert_zero_leakage passes clean, fails on poisoned pool / poisoned main ledger
 13. Part M EventTypes exist, are unique, and folding ignores them (additive)
 14. CandidatePool.from_events never folds a reference registration into the pool
 15. committed manifest integrity: built, hashes present + tarball hash matches
 16. attribution: ATTRIBUTION.md + source.json per agent
 17. cg_typed + smoke artifacts: references pass typed lane, stdlib lane intact, runnable
 18. LIVE guardrails: no external_reference in real pool; no benchmark events in main ledger
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ptcg_activegraph.graph.events import EventType, new_event
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.ledger import TournamentLedger
from ptcg_activegraph.tournament.pool import Candidate, CandidatePool
from ptcg_activegraph.tournament.projections import fold_games

REPO = Path(__file__).resolve().parents[1]
REF = REPO / "data" / "reference_agents"
EXP = REPO / "data" / "experiments"
MANIFEST = REF / "reference_agent_manifest.json"


def _gf(our, ref, result, seat=0):
    return new_event(EventType.PublicBenchmarkGameFinished, payload={
        "our_candidate": our, "reference_id": ref, "result": result, "our_seat": seat})


# --------------------------------------------------------------------------- #
# opponents
# --------------------------------------------------------------------------- #
def test_load_opponents_built_only_and_sorted():
    opps = B.load_opponents()
    assert opps, "expected built reference agents"
    assert opps == sorted(opps, key=lambda o: o.agent_id)
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)


def test_load_opponents_optional_toggle():
    with_opt = B.load_opponents(include_optional=True)
    without_opt = B.load_opponents(include_optional=False)
    assert len(without_opt) <= len(with_opt)
    assert all(not o.optional for o in without_opt)


def test_opponent_no_upload_default():
    o = B.BenchmarkOpponent(agent_id="x", label="x", deck_archetype="y")
    assert o.no_upload is True
    assert o.status == B.EXTERNAL_REFERENCE_STATUS


# --------------------------------------------------------------------------- #
# classify_result (inversion)
# --------------------------------------------------------------------------- #
def test_classify_result_inverts_reference_outcome():
    assert B.classify_result({"completed": True, "candidate_won": True}) == B.REFERENCE_WIN
    assert B.classify_result({"completed": True, "candidate_won": False}) == B.OUR_WIN


def test_classify_result_draw_and_invalid():
    assert B.classify_result({"completed": True, "draw": True}) == B.DRAW
    assert B.classify_result({"completed": False}) == B.INVALID
    assert B.classify_result({"completed": True, "error": "boom"}) == B.INVALID
    assert B.classify_result({"completed": True, "timeout": True}) == B.INVALID
    assert B.classify_result({"completed": True, "candidate_won": None}) == B.DRAW


# --------------------------------------------------------------------------- #
# worklist
# --------------------------------------------------------------------------- #
def _opps(n=2):
    return [B.BenchmarkOpponent(agent_id=f"ref_{i}", label=f"R{i}",
                                deck_archetype="a") for i in range(n)]


def test_worklist_only_refs_as_opponents_and_ours_as_subjects():
    opps = _opps(2)
    wl = B.build_benchmark_worklist(["c1", "c2"], opps, [], max_games=8)
    assert {g.reference_id for g in wl} == {"ref_0", "ref_1"}
    assert {g.our_candidate for g in wl} == {"c1", "c2"}
    assert all(g.our_seat in (0, 1) for g in wl)


def test_worklist_bounded_and_seat_balanced():
    opps = _opps(2)
    wl = B.build_benchmark_worklist(["c1"], opps, [], max_games=4)
    assert len(wl) == 4
    # each (our, ref) pair gets both seats once across the 4 games
    by_pair: dict[str, set] = {}
    for g in wl:
        by_pair.setdefault(g.reference_id, set()).add(g.our_seat)
    assert all(seats == {0, 1} for seats in by_pair.values())


def test_worklist_resumes_least_played_first():
    opps = _opps(2)
    prior = [_gf("c1", "ref_0", B.OUR_WIN, 0), _gf("c1", "ref_0", B.OUR_WIN, 1)]
    wl = B.build_benchmark_worklist(["c1"], opps, prior, max_games=1)
    # ref_0 already has 2 games; the single next game must go to under-played ref_1
    assert [g.reference_id for g in wl] == ["ref_1"]


def test_worklist_even_cap_seat_balanced_when_truncated():
    # 4 candidates x 3 refs = 12 pairs; an even cap below 2*pairs must STILL be
    # seat-balanced (each scheduled pair contributes both seats before expanding).
    opps = _opps(3)
    wl = B.build_benchmark_worklist(["c1", "c2", "c3", "c4"], opps, [], max_games=8)
    assert len(wl) == 8
    seats = [g.our_seat for g in wl]
    assert seats.count(0) == seats.count(1) == 4
    by_pair: dict = {}
    for g in wl:
        by_pair.setdefault((g.our_candidate, g.reference_id), set()).add(g.our_seat)
    assert all(s == {0, 1} for s in by_pair.values())


def test_safe_extract_all_extracts_normal_tar(tmp_path):
    import io
    import tarfile
    from ptcg_activegraph.tournament.artifacts import safe_extract_all
    good = tmp_path / "good.tar.gz"
    with tarfile.open(good, "w:gz") as tf:
        data = b"print('ok')\n"
        info = tarfile.TarInfo(name="main.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    dest = tmp_path / "g"
    with tarfile.open(good, "r:gz") as tf:
        safe_extract_all(tf, dest)
    assert (dest / "main.py").read_text() == "print('ok')\n"


def test_safe_extract_all_rejects_path_traversal(tmp_path):
    import io
    import tarfile
    import pytest
    from ptcg_activegraph.tournament.artifacts import safe_extract_all
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tf:
        data = b"pwned"
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    dest = tmp_path / "out"
    with tarfile.open(evil, "r:gz") as tf:
        with pytest.raises(ValueError):
            safe_extract_all(tf, dest)
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_all_rejects_symlink(tmp_path):
    import tarfile
    import pytest
    from ptcg_activegraph.tournament.artifacts import safe_extract_all
    evil = tmp_path / "lnk.tar.gz"
    with tarfile.open(evil, "w:gz") as tf:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    dest = tmp_path / "out2"
    with tarfile.open(evil, "r:gz") as tf:
        with pytest.raises(ValueError):
            safe_extract_all(tf, dest)


# --------------------------------------------------------------------------- #
# registration + separate ledger
# --------------------------------------------------------------------------- #
def test_register_opponents_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BENCHMARK_DIR", tmp_path)
    monkeypatch.setattr(B, "REFERENCE_POOL_PATH", tmp_path / "reference_pool.json")
    led = B.benchmark_ledger(tmp_path / "bench.jsonl")
    opps = _opps(3)
    r1 = B.register_opponents(opps, led)
    assert len(r1["newly_registered"]) == 3
    r2 = B.register_opponents(opps, led)
    assert r2["newly_registered"] == []
    assert (tmp_path / "reference_pool.json").is_file()
    snap = json.loads((tmp_path / "reference_pool.json").read_text())
    assert snap["status"] == B.EXTERNAL_REFERENCE_STATUS
    assert len(snap["opponents"]) == 3


def test_benchmark_ledger_separate_and_no_upload(tmp_path):
    led = B.benchmark_ledger(tmp_path / "bench.jsonl")
    assert str(led.store.path) != str(TournamentLedger().store.path)
    led.emit(EventType.PublicBenchmarkTickStarted, {"tick_id": "t"})
    ev = led.load()
    assert ev and all(e.payload.get("no_upload") is True for e in ev)


# --------------------------------------------------------------------------- #
# folding + projection
# --------------------------------------------------------------------------- #
def test_fold_benchmark_games_counts():
    events = [_gf("c1", "ref_0", B.OUR_WIN), _gf("c1", "ref_0", B.REFERENCE_WIN),
              _gf("c1", "ref_1", B.REFERENCE_WIN), _gf("c2", "ref_0", B.DRAW)]
    agg = B.fold_benchmark_games(events)
    assert agg["totals"]["games"] == 4
    assert agg["totals"][B.OUR_WIN] == 1
    assert agg["totals"][B.REFERENCE_WIN] == 2
    assert agg["per_pair"]["c1~ref_0"]["games"] == 2
    assert agg["per_our"]["c1"]["games"] == 3


def test_write_benchmark_projection_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "PROJ_DIR", tmp_path)
    events = [_gf("c1", "ref_0", B.OUR_WIN), _gf("c1", "ref_0", B.REFERENCE_WIN)]
    out = B.write_benchmark_projection(events, _opps(1))
    assert out["totals"]["games"] == 2
    data = json.loads((tmp_path / "benchmark_results.json").read_text())
    assert data["no_upload"] is True
    assert "NOT a Kaggle" in data["caveat"]
    assert (tmp_path / "benchmark_results.md").is_file()


# --------------------------------------------------------------------------- #
# zero leakage
# --------------------------------------------------------------------------- #
def _pool(ids):
    return CandidatePool([Candidate(candidate_id=i, family_id="f") for i in ids])


def test_assert_zero_leakage_clean():
    opps = _opps(2)
    res = B.assert_zero_leakage(_pool(["c1", "c2"]), [], opps)
    assert res["zero_leakage"] is True
    assert all(res["checks"].values())


def test_assert_zero_leakage_detects_poisoned_pool():
    opps = _opps(2)
    res = B.assert_zero_leakage(_pool(["c1", "ref_0"]), [], opps)
    assert res["zero_leakage"] is False
    assert res["checks"]["no_reference_in_pool_ids"] is False


def test_assert_zero_leakage_detects_benchmark_event_in_main():
    opps = _opps(1)
    poisoned = [_gf("c1", "ref_0", B.OUR_WIN)]  # bench event in the MAIN stream
    res = B.assert_zero_leakage(_pool(["c1"]), poisoned, opps)
    assert res["zero_leakage"] is False
    assert res["checks"]["no_benchmark_events_in_main_ledger"] is False


# --------------------------------------------------------------------------- #
# Part M additivity
# --------------------------------------------------------------------------- #
def test_pass40_event_types_exist_and_unique():
    names = ["PublicReferenceAgentRegistered", "CgTypedLaneValidated",
             "PublicBenchmarkTickStarted", "PublicBenchmarkGameScheduled",
             "PublicBenchmarkGameStarted", "PublicBenchmarkGameFinished",
             "PublicBenchmarkProjectionUpdated", "PublicBenchmarkTickFinished"]
    values = [getattr(EventType, n).value for n in names]
    assert len(set(values)) == len(values)


def test_folding_ignores_benchmark_events():
    # a benchmark game must NOT be counted by the normal game fold
    events = [_gf("c1", "ref_0", B.OUR_WIN)]
    agg = fold_games(events)
    assert agg["totals"]["games"] == 0


def test_pool_from_events_ignores_reference_registration():
    ev = new_event(EventType.PublicReferenceAgentRegistered,
                   payload={"agent_id": "ref_0", "status": B.EXTERNAL_REFERENCE_STATUS})
    pool = CandidatePool.from_events([ev])
    assert pool.candidates == []


# --------------------------------------------------------------------------- #
# committed artifact integrity
# --------------------------------------------------------------------------- #
def test_manifest_integrity_and_hashes():
    man = json.loads(MANIFEST.read_text())
    agents = man["agents"]
    assert len(agents) >= 4
    for a in agents:
        if not a.get("built"):
            continue
        assert a["tarball_sha256"] and a["content_sha256"]
        tar = Path(a["tarball"])
        if not tar.is_absolute():
            tar = REPO / a["tarball"]  # manifest stores repo-relative paths
        assert tar.is_file(), f"missing tarball {tar}"
        h = hashlib.sha256(tar.read_bytes()).hexdigest()
        assert h == a["tarball_sha256"], f"hash drift for {a['agent_id']}"


def test_attribution_present_per_agent():
    man = json.loads(MANIFEST.read_text())
    for a in man["agents"]:
        if not a.get("built"):
            continue
        adir = REF / "materialized" / a["agent_id"]
        assert (adir / "ATTRIBUTION.md").is_file(), f"no ATTRIBUTION.md for {a['agent_id']}"
        assert (adir / "source.json").is_file(), f"no source.json for {a['agent_id']}"


def test_cg_typed_and_smoke_artifacts():
    cg = json.loads((EXP / "pass40_cg_typed_lane_validation.json").read_text())
    assert cg["all_reference_cg_typed_pass"] is True
    assert cg["stdlib_lane_rejects_cg_typed_count"] >= 4
    assert cg["lanes_separate_and_intact"] is True
    smoke = json.loads((EXP / "pass40_reference_agent_smoke.json").read_text())
    assert smoke["all_runnable"] is True
    assert smoke["agents_runnable"] >= 4


def test_integration_and_gap_artifacts_honest():
    integ = json.loads((EXP / "pass40_tournament_benchmark_integration.json").read_text())
    assert integ["integration_ok"] is True
    assert integ["zero_leakage"] is True
    assert integ["no_upload"] is True
    gap = json.loads((EXP / "pass40_public_reference_gap_report.json").read_text())
    assert gap["no_upload"] is True
    assert "NOT a Kaggle" in gap["caveat"]


# --------------------------------------------------------------------------- #
# LIVE guardrails on the real repo state
# --------------------------------------------------------------------------- #
def test_live_pool_has_no_external_reference():
    pool = CandidatePool.load()
    assert all(c.status != B.EXTERNAL_REFERENCE_STATUS for c in pool.candidates)
    ref_ids = {o.agent_id for o in B.load_opponents()}
    assert not (ref_ids & {c.candidate_id for c in pool.candidates})


def test_live_main_ledger_has_no_benchmark_events():
    main = TournamentLedger().load()
    bench_types = {
        EventType.PublicReferenceAgentRegistered.value,
        EventType.PublicBenchmarkGameFinished.value,
        EventType.PublicBenchmarkTickStarted.value,
    }
    assert not [e for e in main if e.event_type in bench_types]
