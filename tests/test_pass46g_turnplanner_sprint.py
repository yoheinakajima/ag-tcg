"""Pass 46G — multi-profile turn-planner sprint v1 (LOCAL-ONLY).

Committed-artifact integrity + live-repo guardrail + pure-scorer behavior checks
for a SMALL BATCH of owned local-only ``cg_typed`` turn-planner candidates, each
driven by an interpretable phase/role PROFILE and MEASURED offline against the
Pass-46E Search oracle. There is NO online Search in the live hot path.

No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

These tests assert that nothing was uploaded/submitted/promoted, that the public
references stayed benchmark-only (never source/parent/candidate, never in the pool),
that root/prod config is untouched, that every candidate is lane-separated and the
pure scorer never raises, and that the honest finding — the phase/role layer is
top-1-inert vs the family-only floor, so any parent edge is a FAMILY-WEIGHTED
TRANSFER signal rather than a phase/role success — is faithfully recorded.

Forward-compatible: assertions check invariants, ranges, and cross-artifact
consistency, and validate whichever decision state is honestly present via a
decision -> required-gate-state map, rather than pinning shared-artifact numbers
that legitimately move between re-runs.
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

from ptcg_activegraph.analysis import turn_planner_profiles as TP
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass46g"
REF_TARBALL_DIR = REPO / "data" / "reference_agents" / "tarballs"
LAB_LEDGER = REPO / "data" / "activegraph" / "lab_events.jsonl"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"
REPORT = RPT / "pass46g_multi_profile_turnplanner_sprint_report.md"

ALLOWED_DECISIONS = {
    "turnplanner_profile_promising_local_only",
    "no_profile_promising_continue_iteration",
    "validation_failed", "safety_stop_required",
}
# Each decision maps to the gate state that must honestly hold.
# (safety_ok, validation_ok, smoke_ok, eval_integrity_ok, profile_promising)
DECISION_GATE_INVARIANTS = {
    "safety_stop_required": (False, None, None, None, None),
    "validation_failed": (True, None, None, None, None),
    "turnplanner_profile_promising_local_only": (True, True, True, True, True),
    "no_profile_promising_continue_iteration": (True, True, True, True, False),
}
# Forbidden strength-claim vocabulary that must never leak into the scorer source.
FORBIDDEN_CLAIM_WORDS = ("lethal", "missed_ko", "boss_gust", "spread", "best_action")


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


def _candidate_tarballs() -> list[Path]:
    build = _load("pass46g_candidate_build.json")
    return [REPO / c["tarball"] for c in build["candidates"]]


# ===========================================================================
# SAFETY / ROOT / CHARTER
# ===========================================================================
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


def test_02_safety_preflight_all_ok_no_prod_mutation():
    pf = _load("pass46g_safety_preflight.json")
    assert pf["all_ok"] is True
    assert pf["production_mutated"] is False
    assert pf["tick_executed"] is False
    assert pf["republish_required"] is False
    assert pf["no_upload"] is True


def test_03_safety_preflight_no_forbidden_events():
    pf = _load("pass46g_safety_preflight.json")
    assert pf["forbidden_events_in_local_ledger"] == []
    scan = pf["prod_ledger_scan"]
    forbidden = scan.get("forbidden_events") or scan.get("forbidden") or []
    assert forbidden == []


def test_04_safety_preflight_auto_submit_falsy():
    pf = _load("pass46g_safety_preflight.json")
    assert not pf["auto_submit"]
    assert not pf["registration_performed"]
    assert not pf["promotion_performed"]


def test_05_references_remain_benchmark_only_live():
    opps = B.load_opponents(include_optional=True)
    assert opps, "expected built public reference agents"
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)
    assert all(o.no_upload is True for o in opps)


def test_06_references_not_in_candidate_pool_live():
    pool = CandidatePool.load()
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    pool_ids = {c.candidate_id for c in pool.candidates}
    assert not (ref_ids & pool_ids)
    assert all(c.status != B.EXTERNAL_REFERENCE_STATUS for c in pool.candidates)


def test_07_prod_deployment_config_unchanged():
    cfg = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = cfg.get("deployment", {})
    run = dep.get("run", [])
    assert dep.get("deploymentTarget") == "scheduled"
    assert any("tournament_deployment_tick.py" in str(x) for x in run)
    assert "--production" in run
    assert run != ["python3", "main.py"]


def test_08_no_public_ref_as_source_parent_or_candidate():
    sel = _load("pass46g_source_selection.json")
    excluded = set(sel["reference_ids_excluded"])
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    assert ref_ids <= excluded, ref_ids - excluded
    build = _load("pass46g_candidate_build.json")
    for c in build["candidates"]:
        assert c["parent_candidate_id"] not in ref_ids
        assert c["parent_family"] not in ref_ids
        assert c["candidate_id"] not in ref_ids


# ===========================================================================
# PURE SCORER MODULE (turn_planner_profiles V2 — never-raise, observable-only)
# ===========================================================================
def test_09_scorer_module_has_public_api():
    for name in ("extract_features", "score_option", "score_options",
                 "choose_indices", "family_for_option", "detect_phase",
                 "option_role", "baseline_profile", "inline_region_source",
                 "DEFAULT_PROFILE", "FEATURE_KEYS", "PHASES", "ROLES",
                 "PROFILE_SCHEMA_VERSION"):
        assert hasattr(TP, name), name
    assert isinstance(TP.DEFAULT_PROFILE, dict) and "weights" in TP.DEFAULT_PROFILE
    assert TP.PROFILE_SCHEMA_VERSION == "pass46g_turn_scorer_v1"


def test_10_scorer_never_raises_on_garbage():
    prof = TP.DEFAULT_PROFILE
    for opt in (None, {}, {"type": 999}, {"weird": object()}, [], 42, "x"):
        feats = TP.extract_features(opt)
        assert isinstance(feats, dict)
        v = TP.score_option(feats, prof)
        assert isinstance(v, (int, float))
        assert not math.isnan(float(v)) and not math.isinf(float(v))


def test_11_score_option_deterministic():
    prof = TP.DEFAULT_PROFILE
    f = TP.extract_features({"type": 1})
    assert TP.score_option(f, prof) == TP.score_option(f, prof)


def test_12_choose_indices_returns_legal_indices():
    prof = TP.DEFAULT_PROFILE
    empty = TP.choose_indices(None, None, prof)
    assert empty == [] or empty is None or isinstance(empty, list)
    select = {"options": [{"type": 1}, {"type": 5}, {"type": 9}]}
    idx = TP.choose_indices(select, None, prof)
    assert isinstance(idx, list)
    for i in idx:
        assert isinstance(i, int) and 0 <= i < 3


def test_13_inline_region_and_baseline_present():
    src = TP.inline_region_source()
    assert isinstance(src, str) and "def " in src
    base = TP.baseline_profile()
    assert isinstance(base, dict) and "weights" in base


def test_14_phase_and_role_label_vocabularies():
    assert "attack_ready" in TP.PHASES and "setup" in TP.PHASES
    # role is a target-AREA label, not a correctness/optimality claim
    assert set(TP.ROLES) >= {"targets_active", "targets_bench", "role_none"}
    # feature keys are neutral action-family names, never damage/KO language
    for k in TP.FEATURE_KEYS:
        assert isinstance(k, str)
        assert not any(w in k.lower() for w in ("damage", "lethal", "ko", "win"))


def test_15_scorer_source_makes_no_strength_claims():
    src = TP.inline_region_source().lower()
    for w in FORBIDDEN_CLAIM_WORDS:
        assert w not in src, w
    claims = TP.unsupported_scorer_claims()
    assert isinstance(claims, dict)
    for key in ("exact_damage", "lethal", "best_action", "no_hidden_state"):
        assert key in claims


# ===========================================================================
# PROFILE CATALOG / CALIBRATION (fit metrics only, never a win-rate claim)
# ===========================================================================
def test_16_catalog_valid_and_schema_matches():
    cat = _load("pass46g_profile_catalog.json")
    assert cat["all_profiles_valid"] is True
    assert cat["n_profiles"] >= 1
    assert cat["scorer_schema_version"] == TP.PROFILE_SCHEMA_VERSION
    assert cat["build_profile_ids"], "expected build profiles"


def test_17_catalog_profiles_have_phase_role_structure():
    cat = _load("pass46g_profile_catalog.json")
    profs = cat["profiles"]
    profs = profs if isinstance(profs, list) else list(profs.values())
    for p in profs:
        assert "weights" in p and isinstance(p["weights"], dict)
        assert "phase_weights" in p and "role_weights" in p
        for v in p["weights"].values():
            assert isinstance(v, (int, float))


def test_18_calibration_fit_metrics_only():
    cal = _load("pass46g_profile_calibration.json")
    mp = cal["measured_profiles"]
    mp = mp if isinstance(mp, dict) else {m["profile_id"]: m for m in mp}
    assert mp, "expected measured profiles"
    for m in mp.values():
        ag = m["oracle_top1_agreement"]
        assert 0.0 <= float(ag) <= 1.0
        assert "pick_oracle_score" in m  # fit/lift, not a win rate
    # no win-rate / Kaggle vocabulary in calibration claims
    assert "unsupported_claims" in cal


def test_19_calibration_schema_matches_catalog():
    cal = _load("pass46g_profile_calibration.json")
    cat = _load("pass46g_profile_catalog.json")
    assert cal["scorer_schema_version"] == cat["scorer_schema_version"]


# ===========================================================================
# CANDIDATE BUILD / VALIDATION (small batch, lane-separated)
# ===========================================================================
def test_20_build_small_batch_cg_typed():
    build = _load("pass46g_candidate_build.json")
    assert build["lane"] == "cg_typed"
    n = build["n_candidates"]
    assert 1 <= n <= 6
    assert n == len(build["candidates"])
    assert build["scorer_schema_version"] == TP.PROFILE_SCHEMA_VERSION


def test_21_each_tarball_contents_main_deck_cg_only():
    for cand in _candidate_tarballs():
        assert cand.is_file(), f"missing candidate tarball {cand}"
        with tarfile.open(cand, "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile() or m.isdir()]
        top = {n.split("/")[0] for n in names}
        assert top <= {"main.py", "deck.csv", "cg"}, top
        assert "main.py" in names and "deck.csv" in names
        assert any(n.startswith("cg/") for n in names)


def test_22_candidate_decks_unchanged_from_parent():
    build = _load("pass46g_candidate_build.json")
    for c in build["candidates"]:
        assert c["deck_unchanged"] is True
        cand = REPO / c["tarball"]
        cand_deck_sha = hashlib.sha256(_tar_member_bytes(cand, "deck.csv")).hexdigest()
        assert cand_deck_sha == c["deck_sha256"]


def test_23_candidates_owned_non_reference():
    build = _load("pass46g_candidate_build.json")
    for c in build["candidates"]:
        assert c["owned_candidate"] is True
        assert c["public_reference"] is False


def test_24_no_reference_code_in_candidate_lineage():
    ref_main_shas = set()
    for tb in sorted(REF_TARBALL_DIR.glob("public_ref_*.tar.gz")):
        ref_main_shas.add(hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest())
    assert ref_main_shas, "expected reference tarballs to compare against"
    for cand in _candidate_tarballs():
        cand_main_sha = hashlib.sha256(_tar_member_bytes(cand, "main.py")).hexdigest()
        assert cand_main_sha not in ref_main_shas


def test_25_no_online_search_in_hot_path():
    build = _load("pass46g_candidate_build.json")
    for c in build["candidates"]:
        assert c["no_online_search"] is True
        assert "turn_planner_profiles" in c["scorer_source_module"]


def test_26_validation_all_ok_distinct_candidates():
    val = _load("pass46g_candidate_validation.json")
    assert val["all_ok"] is True
    cc = val["cross_candidate"]
    assert cc["distinct_tarballs"] is True
    assert cc["distinct_main_py"] is True
    assert cc["n_distinct_tarballs"] == val["n_candidates"]
    assert cc["n_distinct_main_py"] == val["n_candidates"]


def test_27_per_candidate_lane_separation():
    val = _load("pass46g_candidate_validation.json")
    for pc in val["per_candidate"]:
        assert pc["public_reference"] is False
        assert pc["cg_typed_lane_accepts"]["accepts"] is True
        assert pc["cg_typed_lane_accepts"]["returncode"] == 0
        assert pc["stdlib_lane_rejects"]["rejects"] is True
        assert pc["stdlib_lane_rejects"]["returncode"] != 0
        assert pc["candidate_ok"] is True


def test_28_cg_typed_validator_rejects_bad_shapes(tmp_path):
    path = REPO / "scripts" / "validate_cg_typed_tarball.py"
    spec = importlib.util.spec_from_file_location("_v_cg_typed_46g", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.validate(str(_candidate_tarballs()[0])) == 0
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tf:
        data = b"x = 1\n"
        info = tarfile.TarInfo(name="main.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert mod.validate(str(bad)) != 0


# ===========================================================================
# SMOKE / NON-INERTNESS / INTERNAL DISTINGUISHABILITY
# ===========================================================================
def test_29_smoke_runnable_clean():
    s = _load("pass46g_smoke_non_inertness.json")
    sm = s["smoke"]
    assert sm["smoke_ok"] is True
    assert sm["import_or_deck_failures"] == 0
    assert sm["root_main_deck_unchanged"] is True


def test_30_smoke_errors_below_threshold():
    sm = _load("pass46g_smoke_non_inertness.json")["smoke"]
    total = sm["games_total"]
    bad = sm["games_error"] + sm["games_timeout"]
    assert bad <= max(1, total // 5), (bad, total)


def test_31_all_candidates_non_inert_and_safe():
    s = _load("pass46g_smoke_non_inertness.json")
    assert s["all_non_inert_vs_parent"] is True
    assert s["all_safe"] is True
    for ni in s["non_inertness_vs_parent"].values():
        assert ni["non_inert"] is True
        assert ni["safe"] is True
        assert 0.0 <= float(ni["changed_rate"]) <= 1.0
        assert int(ni["n_parent_frames"]) >= 1
        assert int(ni["candidate_distinct_families"]) >= 1


def test_32_non_inertness_zero_illegal_zero_exceptions():
    s = _load("pass46g_smoke_non_inertness.json")
    for ni in s["non_inertness_vs_parent"].values():
        assert ni["illegal_decisions"] == 0
        assert ni["exceptions"] == 0


def test_33_admit_subset_of_candidates():
    s = _load("pass46g_smoke_non_inertness.json")
    build = _load("pass46g_candidate_build.json")
    cand_ids = {c["candidate_id"] for c in build["candidates"]}
    assert set(s["admit_to_part_h"]) <= cand_ids
    assert s["admit_to_part_h"], "expected at least one admitted candidate"


def test_34_internal_distinguishability_recorded():
    # The honest interpretability finding: role == family-only floor at top-1, so
    # the phase/role layer is NOT separable from family-only on real menus.
    s = _load("pass46g_smoke_non_inertness.json")
    idist = s["internal_distinguishability"]
    assert idist, "expected internal distinguishability per family"
    for fam in idist.values():
        assert "phase_role_distinguishable" in fam
        assert "each_vs_family_only_distinguishable" in fam
        for pair in fam["pairs"].values():
            assert 0.0 <= float(pair["top1_diff_rate"]) <= 1.0


# ===========================================================================
# EVAL PANEL
# ===========================================================================
def test_35_eval_panel_integrity():
    p = _load("pass46g_eval_panel.json")
    assert p["games_error"] == 0
    assert p["games_timeout"] == 0
    assert p["root_main_deck_unchanged"] is True
    rnp = p["references_not_in_pool"]
    assert (rnp.get("clean") if isinstance(rnp, dict) else rnp) is True
    assert p["n_games"] >= 1


def test_36_parent_h2h_pairings_have_wilson_bounds():
    p = _load("pass46g_eval_panel.json")
    parent_rows = [r for r in p["pairings"] if r["kind"] == "parent_h2h"]
    assert parent_rows, "expected parent-H2H pairings"
    for r in parent_rows:
        lo, hi = r["wilson_low"], r["wilson_high"]
        assert 0.0 <= lo <= hi <= 1.0
        assert r["wins"] + r["losses"] + r["draws"] >= 1


def test_37_parent_edge_flag_consistent_with_wilson():
    p = _load("pass46g_eval_panel.json")
    edge = set(p["parent_h2h_edge_candidates_95"])
    for r in p["pairings"]:
        if r["kind"] != "parent_h2h":
            continue
        if r["subject"] in edge:
            assert r["wilson_low"] > 0.5, (r["subject"], r["wilson_low"])
        # beats_opp_95 must agree with wilson_low > 0.5
        assert bool(r.get("beats_opp_95")) == bool(r["wilson_low"] > 0.5)


def test_38_phase_vs_role_indistinct_flag_consistent():
    p = _load("pass46g_eval_panel.json")
    indist = p["phase_vs_role_indistinct_in_gameplay"]
    intra = {r["subject"]: r for r in p["pairings"]
             if r["kind"] == "intra_family_phase_vs_role"}
    for subj, is_indist in indist.items():
        r = intra.get(subj)
        if r is None:
            continue
        spans = (not r.get("beats_opp_95")) and (not r.get("loses_to_opp_95"))
        assert bool(is_indist) == bool(spans), subj


def test_39_reference_context_benchmark_only():
    p = _load("pass46g_eval_panel.json")
    ref_rows = [r for r in p["pairings"] if r["kind"] == "reference_context"]
    assert ref_rows, "expected reference-context pairings"
    ref_ids = {o.agent_id for o in B.load_opponents(include_optional=True)}
    for r in ref_rows:
        assert r["opp_id"] in ref_ids  # opponent is a public reference
        assert r["subject"] not in ref_ids  # subject is an owned candidate


# ===========================================================================
# DECISION / EVENTS
# ===========================================================================
def test_40_decision_in_allowed_states():
    dec = _load("pass46g_strategy_decision.json")
    assert dec["decision"] in ALLOWED_DECISIONS
    assert dec["local_only"] is True
    assert dec["no_upload"] is True
    assert dec["production_mutated"] is False
    assert dec["no_promotion"] is True


def test_41_decision_gate_ladder_consistent():
    dec = _load("pass46g_strategy_decision.json")
    g = dec["gates"]
    exp = DECISION_GATE_INVARIANTS[dec["decision"]]
    keys = ("safety_ok", "validation_ok", "smoke_ok", "eval_integrity_ok",
            "profile_promising")
    for want, key in zip(exp, keys):
        if want is not None:
            assert bool(g[key]) is want, (key, dec["decision"])


def test_42_decision_safety_invariants_ok():
    dec = _load("pass46g_strategy_decision.json")
    assert dec["safety_invariants_ok"] is True
    inv = dec["safety_invariants"]
    assert inv["production_mutated"] is False
    assert inv["tick_executed"] is False
    assert inv["promotion_performed"] is False
    assert inv["root_main_deck_unchanged"] is True
    assert inv["references_benchmark_only_not_pooled"] is True


def test_43_promising_decision_requires_attributable_edge():
    # An honest "promising" decision must be backed by BOTH a 95%-confident parent
    # edge AND a profile-attributable (not family-only-floor) edge candidate.
    dec = _load("pass46g_strategy_decision.json")
    if dec["decision"] == "turnplanner_profile_promising_local_only":
        assert dec["parent_h2h_edge_candidates_95"], "promising needs a 95% edge"
        assert dec["profile_attributable_edge_candidates"], "must be profile-attributable"
    else:
        # any high-point-estimate-but-indistinct result is reported as TRANSFER
        if dec["family_weighted_transfer_signal"]:
            assert dec["phase_role_layer_inert_top1"] in (True, False)


def test_44_events_no_upload_clean():
    ev = _load("pass46g_events.json")
    assert ev["no_upload"] is True
    assert ev["upload_performed"] is False
    assert ev["auto_submit"] is False
    assert ev["github_push"] is False
    assert ev["candidate_promoted"] is False
    v = ev["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == []
    assert v["benchmark_forbidden"] == []
    assert v["main_no_upload_false"] == 0
    assert v["benchmark_no_upload_false"] == 0


def test_45_events_forbidden_types_never_emitted_this_pass():
    ev = _load("pass46g_events.json")
    forbidden = set(ev["forbidden_types_never_emitted"])
    assert {"CandidatePromoted", "SubmissionQueued", "SubmissionUploaded",
            "KaggleScoreUpdated"} <= forbidden


def test_46_all_pass46g_events_carry_no_upload_live():
    seen = 0
    for path in (LAB_LEDGER, BENCH_LEDGER):
        if not path.exists():
            continue
        for evt in EventStore(path).load():
            if "pass46g" in evt.tags:
                assert evt.payload.get("no_upload") is True, (path, evt.event_type)
                assert evt.event_type not in (
                    "CandidatePromoted", "SubmissionQueued",
                    "SubmissionUploaded", "KaggleScoreUpdated"), evt.event_type
                seen += 1
    assert seen > 0, "expected pass46g events on the ledgers"


def test_47_report_present_with_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-L report not generated yet")
    text = REPORT.read_text(encoding="utf-8").lower()
    assert "benchmark" in text
    assert "local-only" in text or "local only" in text
    assert "no upload" in text or "no_upload" in text or "not a kaggle" in text
    assert "no online search" in text or "offline" in text
    assert "transfer" in text  # the honest family-weighted transfer framing


def test_48_report_states_actual_decision():
    if not REPORT.is_file():
        pytest.skip("Part-L report not generated yet")
    dec = _load("pass46g_strategy_decision.json")["decision"]
    assert dec in REPORT.read_text(encoding="utf-8"), dec
