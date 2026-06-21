"""Pass 41 — reference-calibrated owned cg_typed candidate spike.

Committed-artifact integrity + live-repo guardrail checks. No network, no Kaggle,
no native ``libcg.so`` execution, no real game runs here. The owned cg_typed
candidate is a LOCAL-ONLY benchmark subject; these tests assert that nothing was
uploaded/submitted/promoted, that the public references stayed benchmark-only,
and that root/prod config is untouched.

Required coverage (20 items, mirroring the Part-L spec):
 1. root main.py/deck.csv unchanged (byte-identical to the frozen baseline)
 2. pass40 references remain benchmark-only
 3. public references not in the candidate pool
 4. stdlib validators byte-unchanged + still reject the cg_typed candidate
 5. cg_typed validator accepts the owned candidate
 6. cg_typed validator rejects bad shapes
 7. candidate tarball has main.py/deck.csv/cg only
 8. candidate deck matches the selected internal parent deck
 9. no public-reference lineage parent
10. no public-reference code path in the mutation lineage
11. no upload/submit/auto-submit
12. candidate smoke has no invalid/error/timeout above threshold
13. parent/child eval artifact exists
14. public-reference eval artifact exists
15. non-inertness artifact exists and has zero illegal actions
16. strategy decision is one of the allowed states
17. reports include benchmark caveats
18. all pass41 events carry no_upload=true
19. production scheduled deployment config unchanged unless republish_required true
20. if build/eval blocked, the blocked artifact is honest and the blocked path is validated
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tarfile
import tomllib
from pathlib import Path

import pytest

from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
CAND = (REPO / "data" / "submissions" / "candidates_pass41"
        / "cg_typed_mono_lightning_miraidon_policy_v1.tar.gz")
PARENT_DECK = (REPO / "data" / "tournament" / "benchmark" / "_our_extracted"
               / "mono_lightning_miraidon_easy" / "deck.csv")
REF_TARBALL_DIR = REPO / "data" / "reference_agents" / "tarballs"
LAB_LEDGER = REPO / "data" / "activegraph" / "lab_events.jsonl"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"

ALLOWED_DECISIONS = {
    "promising_local_only", "registered_local_needs_more_eval", "rejected_inert",
    "rejected_illegal_or_crash", "rejected_smoke_failed",
    "rejected_validation_failed", "rejected_build_failed", "blocked_root_unsafe",
}
SUCCESS_DECISIONS = {"promising_local_only", "registered_local_needs_more_eval"}
# Map a non-success decision to the gate that must be honestly False for it.
DECISION_TO_FALSE_GATE = {
    "blocked_root_unsafe": "root_safe",
    "rejected_build_failed": "build_owned_non_reference",
    "rejected_validation_failed": "validation_ok",
    "rejected_smoke_failed": "smoke_ok",
    "rejected_illegal_or_crash": "trace_legal_no_crash",
    "rejected_inert": "non_inert",
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load(name: str, base: Path = EXP) -> dict:
    return json.loads((base / name).read_text(encoding="utf-8"))


def _tar_member_bytes(tar: Path, suffix: str) -> bytes:
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name == suffix or m.name.endswith("/" + suffix):
                f = tf.extractfile(m)
                assert f is not None
                return f.read()
    raise KeyError(f"{suffix} not in {tar}")


# --------------------------------------------------------------------------- #
# 1. root unchanged
# --------------------------------------------------------------------------- #
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


# --------------------------------------------------------------------------- #
# 2. references benchmark-only
# --------------------------------------------------------------------------- #
def test_02_references_remain_benchmark_only():
    opps = B.load_opponents(include_optional=True)
    assert opps, "expected built public reference agents"
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)
    assert all(o.no_upload is True for o in opps)


# --------------------------------------------------------------------------- #
# 3. references not in candidate pool
# --------------------------------------------------------------------------- #
def test_03_references_not_in_candidate_pool():
    pool = CandidatePool.load()
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    pool_ids = {c.candidate_id for c in pool.candidates}
    assert not (ref_ids & pool_ids)
    assert all(c.status != B.EXTERNAL_REFERENCE_STATUS for c in pool.candidates)


# --------------------------------------------------------------------------- #
# 4. stdlib validators byte-unchanged + still reject the cg_typed candidate
# --------------------------------------------------------------------------- #
def test_04_stdlib_validators_unchanged_and_reject():
    val = _load("pass41_cg_candidate_validation.json")
    assert val["stdlib_validators_byte_unchanged"] is True
    vu = val["validators_unchanged"]
    for name in ("validate_candidate_tarball.py", "validate_candidate_entrypoint.py"):
        assert vu[name]["git_clean"] is True
    rej = val["stdlib_lane_rejects"]
    assert rej["validate_candidate_tarball"]["rejected"] is True
    assert rej["validate_candidate_entrypoint"]["rejected"] is True


# --------------------------------------------------------------------------- #
# 5. cg_typed validator accepts the owned candidate
# --------------------------------------------------------------------------- #
def test_05_cg_typed_validator_accepts():
    val = _load("pass41_cg_candidate_validation.json")
    assert val["ok"] is True
    assert val["lanes_separated"] is True
    assert val["cg_typed_lane"]["static_pass"] is True
    assert val["cg_typed_lane"]["static_returncode"] == 0


# --------------------------------------------------------------------------- #
# 6. cg_typed validator rejects bad shapes
# --------------------------------------------------------------------------- #
def _load_cg_validator():
    path = REPO / "scripts" / "validate_cg_typed_tarball.py"
    spec = importlib.util.spec_from_file_location("_v_cg_typed", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_06_cg_typed_validator_rejects_bad_shapes(tmp_path):
    mod = _load_cg_validator()
    # the real candidate validates clean
    assert mod.validate(str(CAND)) == 0
    # a tarball missing cg/ + deck.csv and not importing cg is rejected
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        data = b"x = 1\n"
        info = tarfile.TarInfo(name="main.py")
        info.size = len(data)
        import io
        tf.addfile(info, io.BytesIO(data))
    assert mod.validate(str(bad)) != 0


# --------------------------------------------------------------------------- #
# 7. tarball has main.py/deck.csv/cg only
# --------------------------------------------------------------------------- #
def test_07_tarball_contents_main_deck_cg_only():
    with tarfile.open(CAND, "r:gz") as tf:
        names = [m.name for m in tf.getmembers() if m.isfile() or m.isdir()]
    top = {n.split("/")[0] for n in names}
    assert top <= {"main.py", "deck.csv", "cg"}, top
    for n in names:
        assert n in ("main.py", "deck.csv", "cg") or n.startswith("cg/"), n
    assert "main.py" in names
    assert "deck.csv" in names
    assert any(n.startswith("cg/") for n in names)


# --------------------------------------------------------------------------- #
# 8. candidate deck matches the selected internal parent deck
# --------------------------------------------------------------------------- #
def test_08_candidate_deck_matches_parent():
    build = _load("pass41_candidate_build.json")
    assert build["deck_unchanged"] is True
    cand_deck = _tar_member_bytes(CAND, "deck.csv")
    assert hashlib.sha256(cand_deck).hexdigest() == _sha(PARENT_DECK)


# --------------------------------------------------------------------------- #
# 9. no public-reference lineage parent
# --------------------------------------------------------------------------- #
def test_09_no_public_reference_lineage_parent():
    build = _load("pass41_candidate_build.json")
    assert build["owned_candidate"] is True
    assert build["public_reference"] is False
    assert build["mutation_parent"] == "internal"
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    assert build["parent_family"] not in ref_ids


# --------------------------------------------------------------------------- #
# 10. no public-reference code path in the mutation lineage
# --------------------------------------------------------------------------- #
def test_10_no_reference_code_in_lineage():
    build = _load("pass41_candidate_build.json")
    assert build["mutation_parent"] == "internal"
    cand_main_sha = hashlib.sha256(_tar_member_bytes(CAND, "main.py")).hexdigest()
    ref_main_shas = set()
    for tb in sorted(REF_TARBALL_DIR.glob("public_ref_*.tar.gz")):
        ref_main_shas.add(hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest())
    assert ref_main_shas, "expected reference tarballs to compare against"
    assert cand_main_sha not in ref_main_shas


# --------------------------------------------------------------------------- #
# 11. no upload/submit/auto-submit
# --------------------------------------------------------------------------- #
def test_11_no_upload_submit_autosubmit():
    ev = _load("pass41_events.json")
    assert ev["no_upload"] is True
    assert ev["upload_performed"] is False
    assert ev["auto_submit"] is False
    assert ev["github_push"] is False
    assert ev["candidate_promoted"] is False
    assert ev["verification"]["clean"] is True
    assert ev["verification"]["main_ledger_pass41_forbidden"] == []
    assert ev["verification"]["benchmark_ledger_pass41_forbidden"] == []
    dec = _load("pass41_strategy_decision.json")
    assert dec["upload_performed"] is False
    assert dec["auto_submit"] is False
    assert dec["github_push"] is False


# --------------------------------------------------------------------------- #
# 12. smoke has no invalid/error/timeout above threshold
# --------------------------------------------------------------------------- #
def test_12_smoke_clean():
    s = _load("pass41_cg_candidate_smoke.json")
    assert s["ok"] is True
    assert s["hard_fail"] is False
    assert s["import_or_deck_failures"] == 0
    total = s["games_total"]
    bad = s["games_error"] + s["games_timeout"]
    assert bad <= max(1, total // 10), (bad, total)


# --------------------------------------------------------------------------- #
# 13. parent/child eval artifact exists
# --------------------------------------------------------------------------- #
def test_13_parent_child_eval_exists():
    pc = _load("pass41_parent_child_eval.json")
    assert pc.get("verdict")
    assert pc.get("overall", {}).get("games") is not None or pc.get("games")


# --------------------------------------------------------------------------- #
# 14. public-reference eval artifact exists
# --------------------------------------------------------------------------- #
def test_14_public_reference_eval_exists():
    pr = _load("pass41_public_reference_eval.json")
    assert "overall_vs_all_refs" in pr
    assert pr["root_main_deck_unchanged"] is True


# --------------------------------------------------------------------------- #
# 15. non-inertness artifact exists with zero illegal actions
# --------------------------------------------------------------------------- #
def test_15_non_inertness_zero_illegal():
    t = _load("pass41_non_inertness_trace.json")
    assert t["illegal_refinements"] == 0
    assert t["candidate_uncaught_exceptions"] == 0
    assert t["non_inert"] is True


# --------------------------------------------------------------------------- #
# 16. strategy decision is one of the allowed states
# --------------------------------------------------------------------------- #
def test_16_decision_allowed():
    dec = _load("pass41_strategy_decision.json")
    assert dec["decision"] in ALLOWED_DECISIONS
    assert dec["decision"] in set(dec["allowed_decisions"])


# --------------------------------------------------------------------------- #
# 17. reports include benchmark caveats
# --------------------------------------------------------------------------- #
def test_17_reports_include_benchmark_caveats():
    report = RPT / "pass41_reference_calibrated_cg_candidate_report.md"
    assert report.is_file(), f"missing report {report}"
    text = report.read_text(encoding="utf-8").lower()
    assert "benchmark" in text
    assert "local-only" in text or "local only" in text
    assert "not a kaggle" in text or "no upload" in text or "no_upload" in text


# --------------------------------------------------------------------------- #
# 18. all pass41 events carry no_upload=true
# --------------------------------------------------------------------------- #
def test_18_all_pass41_events_no_upload():
    for path in (LAB_LEDGER, BENCH_LEDGER):
        for ev in EventStore(path).load():
            if "pass41" in ev.tags:
                assert ev.payload.get("no_upload") is True, (path, ev.event_type)


# --------------------------------------------------------------------------- #
# 19. prod deployment config unchanged unless republish_required true
# --------------------------------------------------------------------------- #
def test_19_prod_deployment_config_unchanged():
    cfg = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = cfg.get("deployment", {})
    run = dep.get("run", [])
    assert dep.get("deploymentTarget") == "scheduled"
    assert any("tournament_deployment_tick.py" in str(x) for x in run)
    assert "--production" in run
    assert run != ["python3", "main.py"]
    dec = _load("pass41_strategy_decision.json")
    assert dec["republish_required"] is False
    assert dec["prod_scheduler_changed"] is False


# --------------------------------------------------------------------------- #
# 20. blocked path honesty (validates BOTH branches of the decision)
# --------------------------------------------------------------------------- #
def test_20_blocked_path_honesty():
    dec = _load("pass41_strategy_decision.json")
    gates = dec["gates"]
    decision = dec["decision"]
    if decision in SUCCESS_DECISIONS:
        # a success/registered decision must have its core safety+behavior gates true
        for g in ("root_safe", "build_owned_non_reference", "validation_ok",
                  "smoke_ok", "trace_legal_no_crash", "non_inert"):
            assert gates[g] is True, g
    else:
        # a rejected/blocked decision must honestly reflect a failed gate
        assert decision in ALLOWED_DECISIONS
        false_gate = DECISION_TO_FALSE_GATE.get(decision)
        assert false_gate is not None, decision
        assert gates[false_gate] is False, (decision, false_gate)
