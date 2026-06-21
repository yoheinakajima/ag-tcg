"""PASS 46C — frame-persisting diagnostic lane (READ-ONLY / LOCAL).

Validates the bounded local trace runner + the honest diagnostic artifacts it feeds.
HARD invariants asserted: root main.py/deck.csv byte-identical to baseline; the trace
runner/worker/builder sources never push prod state, upload, promote, or write a
tournament ledger; the persisted traces are decodable by the Pass-46B extractor with NO
extension; steps integrity hashes round-trip; behavior metrics are observable-only with
unsupported damage/lethal/Boss-gust/spread claims always flagged; references stay
benchmark-only opponents; and the strategy decision is the expected read-only outcome.
"""
from __future__ import annotations

import filecmp
import gzip
import json
import re
from pathlib import Path

import pytest

from ptcg_activegraph.analysis import turn_planning as tp

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
RUNNER = REPO / "scripts" / "run_pass46c_trace_games.py"
WORKER = REPO / "scripts" / "_pass46c_trace_worker.py"
BUILDER = REPO / "scripts" / "build_pass46c_diagnostic.py"
REPORT = REPO / "data" / "reports" / "pass46c_frame_persisting_diagnostic_report.md"

ALLOWED_DECISIONS = {
    "reference_trace_diagnostic_ready_soak_continue",
    "reference_trace_diagnostic_incomplete_hold",
}
EXPECTED_PARENTS = {
    "generated_lightning_monolightningm_dsratio_v1": "mono_lightning_miraidon_easy",
    "generated_diamond_diamondtoolbox_eratio_v1": "diamond_toolbox_diancie",
}


def _j(name: str) -> dict:
    return json.loads((EXP / f"{name}.json").read_text(encoding="utf-8"))


def _trace_files() -> list[Path]:
    return sorted(TRACES.glob("*.json.gz"))


def _load_gz(p: Path) -> dict:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- safety (HARD)
def test_root_main_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


def test_safety_preflight_all_ok():
    assert _j("pass46c_safety_preflight")["all_ok"] is True


def test_safety_references_absent_from_pool_and_worklist():
    pf = _j("pass46c_safety_preflight")
    assert pf["refs_in_pool"] == []
    assert pf["refs_in_worklist"] == []


def test_safety_no_forbidden_events_in_prod_ledger():
    assert _j("pass46c_safety_preflight")["forbidden_events_in_prod_ledger"] == []


def test_safety_flags_read_only_local_no_upload():
    pf = _j("pass46c_safety_preflight")
    assert pf["read_only"] and pf["local_only"] and pf["no_upload"]
    assert pf["production_mutated"] is False and pf["tick_executed"] is False


@pytest.mark.parametrize("script", [RUNNER, WORKER, BUILDER])
def test_source_never_pushes_promotes_or_uploads(script):
    src = script.read_text(encoding="utf-8")
    assert "push_state" not in src
    assert not re.search(r"promote\w*\s*\(", src)
    assert not re.search(r"\.put_text\s*\(", src)
    assert not re.search(r"upload_submission|republish|kaggle_submit", src)


def test_runner_never_writes_local_or_prod_event_ledger():
    src = RUNNER.read_text(encoding="utf-8")
    # the only ledger touch is a read (LOCAL_EVENTS.read_text / prod .read_text)
    assert ".read_text" in src
    assert not re.search(r"LOCAL_EVENTS\.write_text|EVENTS_KEY[^)]*write", src)


# --------------------------------------------------- manifest / persistence
def test_manifest_no_upload_and_no_mutation_flags():
    m = _j("pass46c_trace_manifest")
    assert m["no_upload"] is True
    assert m["production_mutated"] is False
    assert m["events_written"] is False
    assert m["object_storage_mutated"] is False
    assert m["tick_executed"] is False


def test_manifest_panel_complete_twelve_ok():
    m = _j("pass46c_trace_manifest")
    assert m["n_games_planned"] == 12
    assert m["n_ok"] == 12
    assert m["complete"] is True


def test_manifest_parents_resolved_correctly():
    assert _j("pass46c_trace_manifest")["panel_parents_resolved"] == EXPECTED_PARENTS


def test_panel_tarballs_all_present():
    # imported from the runner module to avoid drift
    import importlib.util
    spec = importlib.util.spec_from_file_location("p46c_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    for rel in mod.TARBALLS.values():
        assert (REPO / rel).exists(), rel


def test_twelve_trace_files_present():
    assert len(_trace_files()) == 12


def test_every_trace_has_safety_metadata():
    for p in _trace_files():
        t = _load_gz(p)
        assert t["no_upload"] is True
        assert t["local_only"] is True
        assert t["production_mutated"] is False


def test_candidate_a_always_seat0_invariant():
    for p in _trace_files():
        t = _load_gz(p)
        assert t["a_seat"] == 0


def test_references_only_appear_as_opponents_not_as_candidate_under_test():
    # every game that includes a reference is a benchmark game; references are never
    # promoted/generated — assert their role is public_reference wherever they appear.
    for p in _trace_files():
        t = _load_gz(p)
        for cid, role in ((t["candidate_a"], t["role_a"]), (t["candidate_b"], t["role_b"])):
            if "public_ref" in cid:
                assert role == "public_reference"


# ----------------------------------------------------- extractor compatibility
def test_every_ok_trace_detects_as_kaggle_replay():
    for p in _trace_files():
        t = _load_gz(p)
        if t["ok"]:
            assert tp.detect_format(t) == tp.FMT_KAGGLE_REPLAY


def test_every_ok_trace_yields_decision_frames():
    for p in _trace_files():
        t = _load_gz(p)
        if t["ok"]:
            assert len(tp.iter_decision_frames(t)) > 0


def test_steps_sha256_roundtrips_for_every_trace():
    import hashlib
    for p in _trace_files():
        t = _load_gz(p)
        recomputed = hashlib.sha256(
            json.dumps(t.get("steps", []), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        assert recomputed == t["steps_sha256"]


def test_part_d_no_extractor_extension_needed():
    d = _j("pass46c_trace_extractor_validation")
    assert d["extractor_extension_needed"] is False
    assert d["all_ok_traces_decodable"] is True
    assert d["all_steps_sha256_roundtrip_ok"] is True
    assert d["all_ok_traces_have_frames"] is True


# --------------------------------------------------------- behavior metrics
def test_part_e_candidates_have_aggregate_and_per_game():
    e = _j("pass46c_behavior_metrics")
    assert e["candidates"]
    for c in e["candidates"].values():
        assert "aggregate" in c and "per_game_seat" in c
        assert c["aggregate"]["n_game_seats"] >= 1


def test_part_e_unsupported_claims_flagged():
    e = _j("pass46c_behavior_metrics")
    flags = e["unsupported_claims"]
    for claim in tp.UNSUPPORTED_CLAIMS:
        assert flags[claim] == tp.UNSUPPORTED_SENTINEL


def test_part_e_metric_basis_is_observable_only():
    assert "observable" in _j("pass46c_behavior_metrics")["metric_basis"]


# ------------------------------------------------------- reference comparison
def test_part_f_has_internal_and_reference_groups():
    f = _j("pass46c_reference_comparison")
    assert f["internal"]["aggregate"]["n_game_seats"] >= 1
    assert f["public_reference"]["aggregate"]["n_game_seats"] >= 1


def test_part_f_carries_interpretation_caveat_and_unsupported():
    f = _j("pass46c_reference_comparison")
    assert "not" in f["interpretation_caveat"].lower()
    for claim in tp.UNSUPPORTED_CLAIMS:
        assert f["unsupported_claims"][claim] == tp.UNSUPPORTED_SENTINEL


# --------------------------------------------------------------- decision
def test_decision_is_expected_ready_outcome():
    g = _j("pass46c_strategy_decision")
    assert g["decision"] in ALLOWED_DECISIONS
    assert g["decision"] == "reference_trace_diagnostic_ready_soak_continue"
    assert g["ready"] is True


def test_decision_flags_no_mutation():
    g = _j("pass46c_strategy_decision")
    assert g["production_mutated"] is False
    assert g["tick_executed"] is False
    assert g["events_written"] is False


# --------------------------------------------------------------- report
def test_report_has_exactly_ten_sections():
    body = REPORT.read_text(encoding="utf-8")
    assert len(re.findall(r"^## ", body, flags=re.MULTILINE)) == 10


def test_report_surfaces_unsupported_and_not_a_kaggle_claim():
    body = REPORT.read_text(encoding="utf-8").lower()
    assert "not a kaggle" in body or "not kaggle" in body
    assert "unsupported" in body
    for token in ("damage", "lethal", "boss"):
        assert token in body
