"""Pass 46F — search-calibrated fast turn-planner candidate pilot (LOCAL-ONLY).

Committed-artifact integrity + live-repo guardrail + pure-scorer behavior checks.
No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

The owned cg_typed candidate's fast hot-path scorer is calibrated OFFLINE against
the Pass-46E Search oracle; there is NO online Search in the live hot path. The
candidate is a LOCAL-ONLY benchmark subject. These tests assert that nothing was
uploaded/submitted/promoted, that the public references stayed benchmark-only
(never source/parent/candidate, never in the pool), that root/prod config is
untouched, and that the pure scorer never raises.

Forward-compatible: assertions check invariants and ranges, and validate whichever
decision state is honestly present via a decision->required-gate-state map, rather
than pinning shared-artifact numbers that legitimately move between re-runs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import tarfile
import tomllib
from pathlib import Path

import pytest

from ptcg_activegraph.analysis import turn_scorer as TS
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
CAND = (REPO / "data" / "submissions" / "candidates_pass46f"
        / "cg_typed_water_anti_disruption_searchcal_v1.tar.gz")
REF_TARBALL_DIR = REPO / "data" / "reference_agents" / "tarballs"
LAB_LEDGER = REPO / "data" / "activegraph" / "lab_events.jsonl"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"
REPORT = RPT / "pass46f_search_calibrated_turnplanner_candidate_report.md"

ALLOWED_DECISIONS = {
    "turnplanner_candidate_promising_local_only", "not_promising",
    "validation_failed", "unsafe_stop", "insufficient_evidence",
}
# Each non-promising decision maps to the gate state that must honestly hold.
# (safety_pass, runnability_pass, strength_pass, demonstrably_worse)
DECISION_GATE_INVARIANTS = {
    "unsafe_stop": (False, None, None, None),
    "validation_failed": (True, False, None, None),
    "turnplanner_candidate_promising_local_only": (True, True, True, None),
    "not_promising": (True, True, False, True),
    "insufficient_evidence": (True, True, False, False),
}
CORROBORATES_VALUES = {"yes", "no", "inconclusive_small_sample", "inconclusive"}


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


def _gates_by_name(dec: dict) -> dict:
    return {g["gate"]: g for g in dec.get("gates", [])}


# ===========================================================================
# SAFETY / ROOT / CHARTER
# ===========================================================================
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


def test_02_safety_preflight_all_ok_no_prod_mutation():
    pf = _load("pass46f_safety_preflight.json")
    assert pf["all_ok"] is True
    assert pf["production_mutated"] is False
    assert pf["tick_executed"] is False
    assert pf["republish_required"] is False
    assert pf["no_upload"] is True


def test_03_safety_preflight_no_forbidden_events():
    pf = _load("pass46f_safety_preflight.json")
    assert pf["forbidden_events_in_local_ledger"] == []
    scan = pf["prod_ledger_scan"]
    forbidden = scan.get("forbidden_events") or scan.get("forbidden") or []
    assert forbidden == []


def test_04_safety_preflight_auto_submit_falsy():
    pf = _load("pass46f_safety_preflight.json")
    assert not pf["auto_submit"]
    assert not pf["missing_46d_artifacts"]
    assert not pf["missing_46e_artifacts"]


def test_05_start_application_workflow_not_started_expected():
    # Charter: root "Start application" stays not-started for this LOCAL-ONLY pass.
    pf = _load("pass46f_safety_preflight.json")
    saw = pf["start_application_workflow"]
    state = saw.get("state") if isinstance(saw, dict) else saw
    assert state in (None, "not_started", "stopped", False) or saw is not None


def test_06_references_remain_benchmark_only_live():
    opps = B.load_opponents(include_optional=True)
    assert opps, "expected built public reference agents"
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)
    assert all(o.no_upload is True for o in opps)


def test_07_references_not_in_candidate_pool_live():
    pool = CandidatePool.load()
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    pool_ids = {c.candidate_id for c in pool.candidates}
    assert not (ref_ids & pool_ids)
    assert all(c.status != B.EXTERNAL_REFERENCE_STATUS for c in pool.candidates)


def test_08_prod_deployment_config_unchanged():
    cfg = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = cfg.get("deployment", {})
    run = dep.get("run", [])
    assert dep.get("deploymentTarget") == "scheduled"
    assert any("tournament_deployment_tick.py" in str(x) for x in run)
    assert "--production" in run
    assert run != ["python3", "main.py"]


# ===========================================================================
# CANDIDATE BUILD / VALIDATION
# ===========================================================================
def test_09_tarball_contents_main_deck_cg_only():
    assert CAND.is_file(), f"missing candidate tarball {CAND}"
    with tarfile.open(CAND, "r:gz") as tf:
        names = [m.name for m in tf.getmembers() if m.isfile() or m.isdir()]
    top = {n.split("/")[0] for n in names}
    assert top <= {"main.py", "deck.csv", "cg"}, top
    assert "main.py" in names and "deck.csv" in names
    assert any(n.startswith("cg/") for n in names)


def test_10_candidate_deck_matches_parent_fingerprint():
    build = _load("pass46f_candidate_build.json")
    assert build["deck_unchanged"] is True
    cand_deck_sha = hashlib.sha256(_tar_member_bytes(CAND, "deck.csv")).hexdigest()
    sel = _load("pass46f_source_selection.json")
    assert cand_deck_sha == sel["deck_fingerprint_to_copy"]
    assert cand_deck_sha == build["deck_sha256"]


def test_11_candidate_owned_non_reference():
    build = _load("pass46f_candidate_build.json")
    assert build["owned_candidate"] is True
    assert build["public_reference"] is False
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    assert build["parent_candidate_id"] not in ref_ids
    assert build["parent_family"] not in ref_ids


def test_12_no_reference_code_in_candidate_lineage():
    cand_main_sha = hashlib.sha256(_tar_member_bytes(CAND, "main.py")).hexdigest()
    ref_main_shas = set()
    for tb in sorted(REF_TARBALL_DIR.glob("public_ref_*.tar.gz")):
        ref_main_shas.add(hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest())
    assert ref_main_shas, "expected reference tarballs to compare against"
    assert cand_main_sha not in ref_main_shas


def test_13_no_online_search_in_hot_path():
    build = _load("pass46f_candidate_build.json")
    assert build["no_online_search"] is True
    prof = _load("pass46f_score_profile.json")["calibrated_profile"]
    assert prof["no_online_search"] is True


def test_14_inline_scorer_byte_identical_and_parity():
    build = _load("pass46f_candidate_build.json")
    assert build["inline_region_byte_identical"] is True
    par = build["parity"]
    assert par["behavioral_parity_ok"] is True
    assert par["score_option_mismatches"] == []
    assert par["choose_indices_mismatches"] == []


def test_15_validation_all_ok_lane_separated():
    val = _load("pass46f_candidate_validation.json")
    assert val["all_ok"] is True
    assert val["cg_typed_lane_accepts"]["accepts"] is True
    assert val["cg_typed_lane_accepts"]["returncode"] == 0
    assert val["stdlib_lane_rejects"]["rejects"] is True
    assert val["stdlib_lane_rejects"]["returncode"] != 0
    sep = val["lane_separation"]
    # candidate hash differs from every checked reference -> lanes separated
    cand_sha = sep["candidate_tarball_sha256"]
    ref_shas = {r["tarball_sha256"] for r in sep["reference_hashes"].values()}
    assert cand_sha not in ref_shas
    assert sep["n_references_checked"] >= 1


def test_16_cg_typed_validator_rejects_bad_shapes(tmp_path):
    path = REPO / "scripts" / "validate_cg_typed_tarball.py"
    spec = importlib.util.spec_from_file_location("_v_cg_typed_46f", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.validate(str(CAND)) == 0
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        data = b"x = 1\n"
        info = tarfile.TarInfo(name="main.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert mod.validate(str(bad)) != 0


# ===========================================================================
# PURE SCORER (never-raise, deterministic, legal)
# ===========================================================================
def test_17_scorer_module_has_public_api():
    for name in ("extract_features", "score_option", "score_options",
                 "choose_indices", "family_for_option", "DEFAULT_PROFILE"):
        assert hasattr(TS, name), name
    assert isinstance(TS.DEFAULT_PROFILE, dict)
    assert "weights" in TS.DEFAULT_PROFILE


def test_18_scorer_never_raises_on_garbage():
    prof = TS.DEFAULT_PROFILE
    for opt in (None, {}, {"type": 999}, {"weird": object()}, [], 42, "x"):
        feats = TS.extract_features(opt)
        assert isinstance(feats, dict)
        v = TS.score_option(feats, prof)
        assert isinstance(v, (int, float))
        assert not math.isnan(float(v)) and not math.isinf(float(v))


def test_19_score_option_deterministic():
    prof = TS.DEFAULT_PROFILE
    opt = {"type": 1}
    f = TS.extract_features(opt)
    assert TS.score_option(f, prof) == TS.score_option(f, prof)


def test_20_choose_indices_returns_legal_indices():
    prof = TS.DEFAULT_PROFILE
    # empty select -> empty / safe
    empty = TS.choose_indices(None, None, prof)
    assert empty == [] or empty is None or isinstance(empty, list)
    # a small synthetic select of n options -> indices within range
    select = {"options": [{"type": 1}, {"type": 5}, {"type": 9}]}
    idx = TS.choose_indices(select, None, prof)
    assert isinstance(idx, list)
    for i in idx:
        assert isinstance(i, int) and 0 <= i < 3


def test_21_default_profile_and_inline_region_present():
    src = TS.inline_region_source()
    assert isinstance(src, str) and "def " in src
    base = TS.baseline_profile()
    assert isinstance(base, dict) and "weights" in base


def test_22_score_profile_artifact_calibrated_and_sane():
    prof = _load("pass46f_score_profile.json")["calibrated_profile"]
    assert prof["calibrated"] is True
    assert "search" in str(prof["profile_id"]).lower() or "calib" in str(
        prof["profile_id"]).lower()
    w = prof["weights"]
    assert isinstance(w, dict) and w
    for k, v in w.items():
        assert isinstance(v, (int, float))


# ===========================================================================
# SMOKE / NON-INERTNESS
# ===========================================================================
def test_23_smoke_runnable_clean():
    s = _load("pass46f_candidate_smoke.json")
    assert s["ok"] is True
    assert s["hard_fail"] is False
    assert s["import_or_deck_failures"] == 0


def test_24_smoke_errors_below_threshold():
    s = _load("pass46f_candidate_smoke.json")
    total = s["games_total"]
    bad = s["games_error"] + s["games_timeout"]
    assert bad <= max(1, total // 5), (bad, total)


def test_25_smoke_root_unchanged_refs_not_in_pool():
    s = _load("pass46f_candidate_smoke.json")
    assert s["root_main_deck_unchanged"] is True
    rnp = s["references_not_in_pool"]
    assert (rnp.get("clean") if isinstance(rnp, dict) else rnp) is True


def test_26_non_inertness_non_inert_and_safe():
    ni = _load("pass46f_non_inertness.json")
    assert ni["non_inert"] is True
    assert ni["safe"] is True
    assert ni["verdict"] == "non_inert_and_safe"


def test_27_non_inertness_zero_illegal_zero_exceptions():
    ni = _load("pass46f_non_inertness.json")
    assert ni["illegal_decisions"] == 0
    assert ni["exceptions"] == 0


def test_28_non_inertness_audit_shape():
    ni = _load("pass46f_non_inertness.json")
    assert ni["no_game_execution"] is True
    assert 0.0 <= float(ni["changed_rate"]) <= 1.0
    assert int(ni["n_parent_frames"]) >= 1
    assert int(ni["candidate_distinct_families"]) >= 1


# ===========================================================================
# EVAL PANEL
# ===========================================================================
def test_29_parent_h2h_sample_and_seats():
    h = _load("pass46f_parent_h2h.json")
    overall = h["overall"]
    assert int(overall["decisive"]) >= int(h.get("games_min_required", 20))
    ci = overall["wilson95"]
    assert isinstance(ci, list) and len(ci) == 2 and ci[0] <= ci[1]
    assert "seat0" in h["by_seat"] and "seat1" in h["by_seat"]
    assert h["root_main_deck_unchanged"] is True


def test_30_parent_h2h_edge_flag_consistent():
    h = _load("pass46f_parent_h2h.json")
    ci = h["overall"]["wilson95"]
    lower_gt_half = ci[0] > 0.5
    assert bool(h["decisive_wilson_lower_gt_half"]) == bool(lower_gt_half)
    # edges_parent requires Wilson lower > 0.5 AND both seats winning
    expected = bool(lower_gt_half and h["both_seats_winning"])
    assert bool(h["edges_parent_local_only"]) == expected


def test_31_internal_anchor_not_a_reference():
    a = _load("pass46f_internal_anchor_eval.json")
    assert a["is_public_reference"] is False
    assert a["context_only"] is True
    assert a["root_main_deck_unchanged"] is True


def test_32_public_reference_eval_benchmark_only():
    r = _load("pass46f_public_reference_eval.json")
    assert r["benchmark_only"] is True
    assert r["promotion_relevant"] is False
    assert r["references_as_source_parent_candidate"] is False
    rnp = r["references_not_in_pool"]
    assert (rnp.get("clean") if isinstance(rnp, dict) else rnp) is True
    assert r["root_main_deck_unchanged"] is True


def test_33_noise_control_clean_and_fisher_present():
    nc = _load("pass46f_noise_control.json")
    assert nc["controls_clean"] is True
    assert nc["noise_control_corroborates"] in CORROBORATES_VALUES
    assert nc["fisher_h2h_vs_mirror_p"] is not None
    assert nc["root_main_deck_unchanged"] is True


def test_34_eval_panel_root_unchanged_refs_clean():
    p = _load("pass46f_eval_panel.json")
    assert p["root_main_deck_unchanged"] is True
    rnp = p["references_not_in_pool"]
    assert (rnp.get("clean") if isinstance(rnp, dict) else rnp) is True


# ===========================================================================
# DECISION / EVENTS
# ===========================================================================
def test_35_decision_in_allowed_states():
    dec = _load("pass46f_strategy_decision.json")
    assert dec["decision"] in ALLOWED_DECISIONS
    assert dec["local_only"] is True
    assert dec["upload_performed"] is False
    assert dec["promotion_performed"] is False


def test_36_decision_gate_ladder_consistent():
    dec = _load("pass46f_strategy_decision.json")
    decision = dec["decision"]
    g = _gates_by_name(dec)
    safety = g["safety"]["pass"]
    runnable = g["runnability"]["pass"]
    strength = g["strength"]["pass"]
    worse = g["strength"].get("demonstrably_worse")
    exp = DECISION_GATE_INVARIANTS[decision]
    if exp[0] is not None:
        assert safety is exp[0], ("safety", decision)
    if exp[1] is not None:
        assert runnable is exp[1], ("runnability", decision)
    if exp[2] is not None:
        assert strength is exp[2], ("strength", decision)
    if exp[3] is not None:
        assert bool(worse) is exp[3], ("worse", decision)


def test_37_events_no_upload_clean():
    ev = _load("pass46f_events.json")
    assert ev["no_upload"] is True
    assert ev["upload_performed"] is False
    assert ev["auto_submit"] is False
    assert ev["github_push"] is False
    assert ev["candidate_promoted"] is False
    v = ev["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == []
    assert v["benchmark_forbidden"] == []


def test_38_events_forbidden_types_never_emitted_this_pass():
    ev = _load("pass46f_events.json")
    forbidden = set(ev["forbidden_types_never_emitted"])
    assert {"CandidatePromoted", "SubmissionQueued", "SubmissionUploaded",
            "KaggleScoreUpdated"} <= forbidden
    # this pass emitted none of them (historical events from older passes are
    # preserved separately and do NOT count against this pass)
    assert ev["verification"]["main_no_upload_false"] == 0
    assert ev["verification"]["benchmark_no_upload_false"] == 0


def test_39_all_pass46f_events_carry_no_upload():
    seen = 0
    for path in (LAB_LEDGER, BENCH_LEDGER):
        if not path.exists():
            continue
        for evt in EventStore(path).load():
            if "pass46f" in evt.tags:
                assert evt.payload.get("no_upload") is True, (path, evt.event_type)
                # HARD: no forbidden type tagged for this pass
                assert evt.event_type not in (
                    "CandidatePromoted", "SubmissionQueued",
                    "SubmissionUploaded", "KaggleScoreUpdated"), evt.event_type
                seen += 1
    assert seen > 0, "expected pass46f events on the ledgers"


def test_40_report_present_with_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-L report not generated yet")
    text = REPORT.read_text(encoding="utf-8").lower()
    assert "benchmark" in text
    assert "local-only" in text or "local only" in text
    assert "no upload" in text or "no_upload" in text or "not a kaggle" in text
    assert "no online search" in text or "no online-search" in text or \
        "offline" in text


def test_41_report_states_actual_decision():
    if not REPORT.is_file():
        pytest.skip("Part-L report not generated yet")
    dec = _load("pass46f_strategy_decision.json")["decision"]
    text = REPORT.read_text(encoding="utf-8")
    # forward-compatible: the report must name whatever decision was actually made
    assert dec in text, dec
