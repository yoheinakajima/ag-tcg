"""Pass 46H — within-family per-option value sprint v0 (LOCAL-ONLY).

Committed-artifact integrity + live-repo guardrail + pure-scorer behavior checks
for a SMALL BATCH of owned local-only ``cg_typed`` candidates, each driven by an
interpretable WITHIN-FAMILY per-option VALUE profile (card/role/target-area/energy/
search-discard/end-with-alternatives) and MEASURED offline against the Pass-46E
Search oracle labels. There is NO online Search in the live hot path.

No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

These tests assert that nothing was uploaded/submitted/promoted, that the public
references stayed benchmark-only (never source/parent/candidate, never in the pool),
that root/prod config is untouched, that every candidate is lane-separated and the
pure scorer never raises, and that the honest finding — whether per-option VISIBLE
features escape 46G's documented coarse phase/role TOP-1-INERTNESS, measured as a
within-family option-value treatment that is distinguishable from the family-only
floor in BOTH live menus AND gameplay — is faithfully recorded.

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

from ptcg_activegraph.analysis import option_value_features as OV
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass46h"
REF_TARBALL_DIR = REPO / "data" / "reference_agents" / "tarballs"
LAB_LEDGER = REPO / "data" / "activegraph" / "lab_events.jsonl"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"
REPORT = RPT / "pass46h_within_family_option_value_report.md"

ALLOWED_DECISIONS = {
    "option_value_profile_promising_local_only",
    "option_value_profile_inconclusive_continue_iteration",
    "no_option_value_profile_promising",
    "validation_failed", "safety_stop_required",
}
# Each decision maps to the gate state that must honestly hold.
# (safety_ok, validation_ok, smoke_ok, eval_integrity_ok,
#  option_value_layer_non_inert_live, coherent_escape_present)
DECISION_GATE_INVARIANTS = {
    "safety_stop_required": (False, None, None, None, None, None),
    "validation_failed": (True, None, None, None, None, None),
    "option_value_profile_promising_local_only":
        (True, True, True, True, None, True),
    "option_value_profile_inconclusive_continue_iteration":
        (True, True, True, True, True, False),
    "no_option_value_profile_promising":
        (True, True, True, True, False, False),
}
GATE_KEYS = ("safety_ok", "validation_ok", "smoke_ok", "eval_integrity_ok",
             "option_value_layer_non_inert_live", "coherent_escape_present")
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
    build = _load("pass46h_candidate_build.json")
    return [REPO / c["tarball"] for c in build["candidates"]]


def _ref_ids() -> set[str]:
    return {o.agent_id for o in B.load_opponents(include_optional=True)}


# ===========================================================================
# SAFETY / ROOT / CHARTER
# ===========================================================================
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


def test_02_safety_preflight_all_ok_no_prod_mutation():
    pf = _load("pass46h_safety_preflight.json")
    assert pf["all_ok"] is True
    assert pf["stop_required"] is False
    assert pf["production_mutated"] is False
    assert pf["tick_executed"] is False
    assert pf["republish_required"] is False
    assert pf["no_upload"] is True


def test_03_safety_preflight_no_forbidden_events():
    pf = _load("pass46h_safety_preflight.json")
    assert pf["forbidden_events_in_local_ledger"] == []
    scan = pf["prod_ledger_scan"]
    forbidden = scan.get("forbidden_events") or scan.get("forbidden") or []
    assert forbidden == []


def test_04_safety_preflight_auto_submit_falsy():
    pf = _load("pass46h_safety_preflight.json")
    assert not pf["auto_submit"]
    assert not pf["registration_performed"]
    assert not pf["promotion_performed"]
    assert not pf["candidate_generated"]


def test_05_references_remain_benchmark_only_live():
    opps = B.load_opponents(include_optional=True)
    assert opps, "expected built public reference agents"
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)
    assert all(o.no_upload is True for o in opps)


def test_06_references_not_in_candidate_pool_live():
    pool = CandidatePool.load()
    ref_ids = _ref_ids()
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
    sel = _load("pass46h_source_selection.json")
    # 46H source records the references' role rather than an excluded-id list.
    assert sel["public_reference_role"] == "benchmark_opponent_only"
    ref_ids = _ref_ids()
    build = _load("pass46h_candidate_build.json")
    for c in build["candidates"]:
        assert c["parent_candidate_id"] not in ref_ids
        assert c["parent_family"] not in ref_ids
        assert c["candidate_id"] not in ref_ids
        assert c["public_reference"] is False
    # no selected source family is a reference
    for s in sel.get("sources", []):
        assert s.get("parent_candidate_id") not in ref_ids


# ===========================================================================
# PURE SCORER MODULE (option_value_features — never-raise, observable-only)
# ===========================================================================
def test_09_scorer_module_has_public_api():
    for name in ("extract_features", "option_value", "score_option",
                 "score_options", "choose_indices", "family_for_option",
                 "resolve_play_card", "inline_region_source",
                 "unsupported_scorer_claims", "default_profiles",
                 "FEATURE_KEYS", "ROLE_TOKENS", "OPTION_TYPE_CLASS",
                 "FAMILY_FEATURE", "FLOOR_FAMILY_WEIGHTS", "OPTION_VALUE_PRIORS",
                 "LEX_SCALE", "PROFILE_SCHEMA_VERSION"):
        assert hasattr(OV, name), name
    assert OV.PROFILE_SCHEMA_VERSION == "pass46h_option_value_v1"
    profs = OV.default_profiles()
    assert isinstance(profs, dict)
    assert {"family_only_floor_v1", "option_value_v1",
            "conservative_option_value_v1"} <= set(profs)


def test_10_scorer_never_raises_on_garbage():
    prof = OV.default_profiles()["option_value_v1"]
    for opt in (None, {}, {"type": 999}, {"weird": object()}, [], 42, "x"):
        feats = OV.extract_features(opt)
        assert isinstance(feats, dict)
        for v in (OV.score_option(feats, prof), OV.option_value(feats, prof)):
            assert isinstance(v, (int, float))
            assert not math.isnan(float(v)) and not math.isinf(float(v))


def test_11_score_option_deterministic():
    prof = OV.default_profiles()["option_value_v1"]
    f = OV.extract_features({"type": 7})
    assert OV.score_option(f, prof) == OV.score_option(f, prof)
    assert OV.option_value(f, prof) == OV.option_value(f, prof)


def test_12_choose_indices_returns_legal_indices():
    prof = OV.default_profiles()["option_value_v1"]
    empty = OV.choose_indices(None, None, prof)
    assert empty == [] or empty is None or isinstance(empty, list)
    select = {"options": [{"type": 1}, {"type": 7}, {"type": 9}]}
    idx = OV.choose_indices(select, None, prof)
    assert isinstance(idx, list)
    for i in idx:
        assert isinstance(i, int) and 0 <= i < 3


def test_13_score_options_returns_ranked_indexed_values():
    prof = OV.default_profiles()["option_value_v1"]
    select = {"options": [{"type": 1}, {"type": 7}, {"type": 9}]}
    so = OV.score_options(select, None, prof)
    assert isinstance(so, list) and len(so) == 3
    seen_idx = set()
    for row in so:
        idx = row[0]
        val = row[1]
        assert isinstance(idx, int) and 0 <= idx < 3
        seen_idx.add(idx)
        assert isinstance(val, (int, float))
        assert not math.isnan(float(val)) and not math.isinf(float(val))
    assert seen_idx == {0, 1, 2}


def test_14_feature_and_role_vocabularies():
    # neutral action-family feature names, never damage/KO/win language
    for k in OV.FEATURE_KEYS:
        assert isinstance(k, str)
        assert not any(w in k.lower() for w in ("damage", "lethal", "ko", "win"))
    # role tokens are coarse visible-card priors (area/type), not optimality claims
    assert set(OV.ROLE_TOKENS) >= {"energy", "basic", "search", "draw", "attacker"}
    # option-type -> action-family map present and string-valued
    assert isinstance(OV.OPTION_TYPE_CLASS, dict) and OV.OPTION_TYPE_CLASS
    assert isinstance(OV.FAMILY_FEATURE, dict) and OV.FAMILY_FEATURE
    for fam, feat in OV.FAMILY_FEATURE.items():
        assert feat in OV.FEATURE_KEYS, (fam, feat)


def test_15_scorer_source_makes_no_strength_claims():
    src = OV.inline_region_source().lower()
    assert "def " in src
    for w in FORBIDDEN_CLAIM_WORDS:
        assert w not in src, w
    claims = OV.unsupported_scorer_claims()
    assert isinstance(claims, dict)
    for key in ("exact_damage", "lethal", "missed_ko", "boss_gust", "spread",
                "best_action"):
        assert key in claims


# ===========================================================================
# FEATURE CATALOG / OPTION-VALUE DATASET / VALUE PROFILES (fit metrics only)
# ===========================================================================
def test_16_feature_catalog_valid_and_schema_matches():
    cat = _load("pass46h_option_feature_catalog.json")
    assert cat["schema_version"] == OV.PROFILE_SCHEMA_VERSION
    assert "option_value_features" in cat["module"]
    assert cat["family_feature_keys"]
    assert cat["role_tokens"]
    profs = cat["profiles"]
    profs = profs if isinstance(profs, list) else list(profs.values())
    assert profs, "expected catalog profiles"
    for p in profs:
        assert "weights" in p and isinstance(p["weights"], dict)
        assert p["schema_version"] == OV.PROFILE_SCHEMA_VERSION
        for v in p["weights"].values():
            assert isinstance(v, (int, float))


def test_17_option_value_dataset_supported_only_and_oracle_reused():
    ds = _load("pass46h_option_value_dataset.json")
    assert ds["oracle_reused_not_rerun"] is True
    assert ds["no_upload"] is True
    assert 0 <= ds["n_supported"] <= ds["n_rows"]
    fk = ds["feature_keys"]
    assert isinstance(fk, list) and fk
    # per-option visible features only — card identity / area / energy / roles
    assert "family" in fk
    assert any("card" in k for k in fk)


def test_18_value_profiles_fit_metrics_only():
    vp = _load("pass46h_value_profiles.json")
    assert vp["schema_version"] == OV.PROFILE_SCHEMA_VERSION
    assert 0.0 <= float(vp["floor_oracle_top1_agreement"]) <= 1.0
    res = vp["results"]
    res = res if isinstance(res, dict) else {r["profile_id"]: r for r in res}
    assert res, "expected measured value profiles"
    for m in res.values():
        assert 0.0 <= float(m["oracle_top1_agreement"]) <= 1.0
        # fit/lift vs the floor, NOT a win rate or Kaggle score
        assert "median_oracle_lift_vs_floor" in m
        assert "divergence_vs_floor" in m
    assert "unsupported_claims" in vp


def test_19_value_profiles_top1_change_gate_consistent():
    vp = _load("pass46h_value_profiles.json")
    gate = float(vp["top1_change_gate"])
    assert 0.0 <= gate <= 1.0
    res = vp["results"]
    res = res if isinstance(res, dict) else {r["profile_id"]: r for r in res}
    ov = res.get("option_value_v1")
    if ov is not None:
        # "option_value_changes_picks" must agree with floor divergence vs the gate
        changes = bool(vp.get("option_value_changes_picks"))
        assert changes == bool(float(ov["divergence_vs_floor"]) >= gate)


# ===========================================================================
# CANDIDATE BUILD / VALIDATION (small batch, lane-separated)
# ===========================================================================
def test_20_build_small_batch_cg_typed():
    build = _load("pass46h_candidate_build.json")
    assert build["lane"] == "cg_typed"
    n = build["n_candidates"]
    assert 1 <= n <= 6
    assert n == len(build["candidates"])
    assert build["scorer_schema_version"] == OV.PROFILE_SCHEMA_VERSION
    assert build["all_candidates_ok"] is True
    assert build["no_upload"] is True


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
    build = _load("pass46h_candidate_build.json")
    for c in build["candidates"]:
        assert c["deck_unchanged"] is True
        cand = REPO / c["tarball"]
        cand_deck_sha = hashlib.sha256(_tar_member_bytes(cand, "deck.csv")).hexdigest()
        assert cand_deck_sha == c["deck_sha256"]


def test_23_candidates_owned_non_reference():
    build = _load("pass46h_candidate_build.json")
    for c in build["candidates"]:
        assert c["owned_candidate"] is True
        assert c["public_reference"] is False
        assert c["mutation_parent"] == "internal"


def test_24_no_reference_code_in_candidate_lineage():
    ref_main_shas = set()
    for tb in sorted(REF_TARBALL_DIR.glob("public_ref_*.tar.gz")):
        ref_main_shas.add(hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest())
    assert ref_main_shas, "expected reference tarballs to compare against"
    for cand in _candidate_tarballs():
        cand_main_sha = hashlib.sha256(_tar_member_bytes(cand, "main.py")).hexdigest()
        assert cand_main_sha not in ref_main_shas


def test_25_no_online_search_in_hot_path():
    build = _load("pass46h_candidate_build.json")
    for c in build["candidates"]:
        assert c["no_online_search"] is True
        assert "option_value_features" in c["scorer_source_module"]
        assert c["inline_region_byte_identical"] is True


def test_26_validation_all_ok_distinct_candidates():
    val = _load("pass46h_candidate_validation.json")
    assert val["all_ok"] is True
    cc = val["cross_candidate"]
    assert cc["distinct_tarballs"] is True
    assert cc["distinct_main_py"] is True
    assert cc["n_distinct_tarballs"] == val["n_candidates"]
    assert cc["n_distinct_main_py"] == val["n_candidates"]


def test_27_per_candidate_lane_separation():
    val = _load("pass46h_candidate_validation.json")
    for pc in val["per_candidate"]:
        assert pc["public_reference"] is False
        assert pc["cg_typed_lane_accepts"]["accepts"] is True
        assert pc["cg_typed_lane_accepts"]["returncode"] == 0
        assert pc["stdlib_lane_rejects"]["rejects"] is True
        assert pc["stdlib_lane_rejects"]["returncode"] != 0
        assert pc["candidate_ok"] is True


def test_28_cg_typed_validator_rejects_bad_shapes(tmp_path):
    path = REPO / "scripts" / "validate_cg_typed_tarball.py"
    spec = importlib.util.spec_from_file_location("_v_cg_typed_46h", path)
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
# SMOKE / NON-INERTNESS / WITHIN-FAMILY DISTINGUISHABILITY
# ===========================================================================
def test_29_smoke_runnable_clean():
    s = _load("pass46h_smoke_non_inertness.json")
    sm = s["smoke"]
    assert sm["smoke_ok"] is True
    assert sm["import_or_deck_failures"] == 0
    assert sm["root_main_deck_unchanged"] is True


def test_30_smoke_errors_below_threshold():
    sm = _load("pass46h_smoke_non_inertness.json")["smoke"]
    total = sm["games_total"]
    bad = sm["games_error"] + sm["games_timeout"]
    assert bad <= max(1, total // 5), (bad, total)


def test_31_all_candidates_non_inert_and_safe():
    s = _load("pass46h_smoke_non_inertness.json")
    assert s["all_non_inert_vs_parent"] is True
    assert s["all_safe"] is True
    for ni in s["non_inertness_vs_parent"].values():
        assert ni["non_inert"] is True
        assert ni["safe"] is True
        assert 0.0 <= float(ni["changed_rate"]) <= 1.0
        assert int(ni["n_parent_frames"]) >= 1
        assert int(ni["candidate_distinct_families"]) >= 1


def test_32_non_inertness_zero_illegal_zero_exceptions():
    s = _load("pass46h_smoke_non_inertness.json")
    for ni in s["non_inertness_vs_parent"].values():
        assert ni["illegal_decisions"] == 0
        assert ni["exceptions"] == 0


def test_33_admit_subset_of_candidates():
    s = _load("pass46h_smoke_non_inertness.json")
    build = _load("pass46h_candidate_build.json")
    cand_ids = {c["candidate_id"] for c in build["candidates"]}
    assert set(s["admit_to_part_i"]) <= cand_ids
    assert s["admit_to_part_i"], "expected at least one admitted candidate"


def test_34_within_family_distinguishability_recorded():
    # The central finding: do per-option VISIBLE features move the top-1 pick off the
    # family-only floor on real menus (escaping 46G's coarse phase/role top-1-inertness)?
    s = _load("pass46h_smoke_non_inertness.json")
    wfd = s["within_family_distinguishability"]
    assert wfd, "expected within-family distinguishability per family"
    assert isinstance(s["option_value_active_on_live_frames_any_family"], bool)
    for fam in wfd.values():
        assert "option_value_distinguishable_from_floor" in fam
        assert "conservative_distinguishable_from_floor" in fam
        for pair in fam["pairs"].values():
            assert 0.0 <= float(pair["top1_diff_rate"]) <= 1.0


# ===========================================================================
# EVAL PANEL
# ===========================================================================
def test_35_eval_panel_integrity():
    p = _load("pass46h_eval_panel.json")
    assert p["games_error"] == 0
    assert p["games_timeout"] == 0
    assert p["root_main_deck_unchanged"] is True
    rnp = p["references_not_in_pool"]
    assert (rnp.get("clean") if isinstance(rnp, dict) else rnp) is True
    assert p["n_games"] >= 1


def test_36_parent_h2h_pairings_have_wilson_bounds():
    p = _load("pass46h_eval_panel.json")
    parent_rows = [r for r in p["pairings"] if r["kind"] == "parent_h2h"]
    assert parent_rows, "expected parent-H2H pairings"
    for r in parent_rows:
        lo, hi = r["wilson_low"], r["wilson_high"]
        assert 0.0 <= lo <= hi <= 1.0
        assert r["wins"] + r["losses"] + r["draws"] >= 1


def test_37_parent_edge_flag_consistent_with_wilson():
    p = _load("pass46h_eval_panel.json")
    edge = set(p["parent_h2h_edge_candidates_95"])
    for r in p["pairings"]:
        if r["kind"] != "parent_h2h":
            continue
        if r["subject"] in edge:
            assert r["wilson_low"] > 0.5, (r["subject"], r["wilson_low"])
        assert bool(r.get("beats_opp_95")) == bool(r["wilson_low"] > 0.5)


def test_38_treatment_vs_floor_distinct_flag_consistent():
    p = _load("pass46h_eval_panel.json")
    distinct = p["treatment_vs_floor_distinct_in_gameplay"]
    intra = {r["subject"]: r for r in p["pairings"]
             if r["kind"] == "intra_family_vs_floor"}
    for subj, is_distinct in distinct.items():
        r = intra.get(subj)
        if r is None:
            continue
        # "distinct" == the CI does NOT span 0.5 (beats OR loses at 95%)
        decisive = bool(r.get("beats_opp_95")) or bool(r.get("loses_to_opp_95"))
        assert bool(is_distinct) == decisive, subj


def test_39_reference_context_benchmark_only():
    p = _load("pass46h_eval_panel.json")
    ref_rows = [r for r in p["pairings"] if r["kind"] == "reference_context"]
    assert ref_rows, "expected reference-context pairings"
    ref_ids = _ref_ids()
    for r in ref_rows:
        assert r["opp_id"] in ref_ids  # opponent is a public reference
        assert r["subject"] not in ref_ids  # subject is an owned candidate


# ===========================================================================
# DECISION / EVENTS
# ===========================================================================
def test_40_decision_in_allowed_states():
    dec = _load("pass46h_strategy_decision.json")
    assert dec["decision"] in ALLOWED_DECISIONS
    assert dec["local_only"] is True
    assert dec["no_upload"] is True
    assert dec["production_mutated"] is False
    assert dec["no_promotion"] is True


def test_41_decision_gate_ladder_consistent():
    dec = _load("pass46h_strategy_decision.json")
    g = dec["gates"]
    exp = DECISION_GATE_INVARIANTS[dec["decision"]]
    for want, key in zip(exp, GATE_KEYS):
        if want is not None:
            assert bool(g[key]) is want, (key, dec["decision"])


def test_42_decision_safety_invariants_ok():
    dec = _load("pass46h_strategy_decision.json")
    assert dec["safety_invariants_ok"] is True
    inv = dec["safety_invariants"]
    assert inv["production_mutated"] is False
    assert inv["tick_executed"] is False
    assert inv["promotion_performed"] is False
    assert inv["root_main_deck_unchanged"] is True
    assert inv["references_benchmark_only_not_pooled"] is True
    assert inv["no_public_ref_as_source_parent_candidate"] is True


def test_43_promising_decision_requires_coherent_escape():
    # An honest "promising" decision must be backed by a within-family option-value
    # treatment that is COHERENT — distinguishable from the family-only floor in BOTH
    # live menus AND gameplay (escaping 46G's coarse phase/role top-1-inertness).
    dec = _load("pass46h_strategy_decision.json")
    if dec["decision"] == "option_value_profile_promising_local_only":
        assert dec["coherent_escape_candidates"], "promising needs a coherent escape"
        assert dec["option_value_escapes_46g_top1_inertness"] is True
    # parent edge claim must be consistent with the recorded edge list
    if dec.get("parent_edge_established"):
        assert dec["parent_h2h_edge_candidates_95"]


def test_44_events_no_upload_clean():
    ev = _load("pass46h_events.json")
    assert ev["no_upload"] is True
    assert ev["upload_performed"] is False
    assert ev["auto_submit"] is False
    assert ev["github_push"] is False
    assert ev["candidate_promoted"] is False
    assert ev["shared_report_site_regenerated"] is False
    v = ev["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == []
    assert v["benchmark_forbidden"] == []
    assert v["main_no_upload_false"] == 0
    assert v["benchmark_no_upload_false"] == 0


def test_45_events_forbidden_types_never_emitted_this_pass():
    ev = _load("pass46h_events.json")
    forbidden = set(ev["forbidden_types_never_emitted"])
    assert {"CandidatePromoted", "SubmissionQueued", "SubmissionUploaded",
            "KaggleScoreUpdated"} <= forbidden


def test_46_all_pass46h_events_carry_no_upload_live():
    seen = 0
    for path in (LAB_LEDGER, BENCH_LEDGER):
        if not path.exists():
            continue
        for evt in EventStore(path).load():
            if "pass46h" in evt.tags:
                assert evt.payload.get("no_upload") is True, (path, evt.event_type)
                assert evt.event_type not in (
                    "CandidatePromoted", "SubmissionQueued",
                    "SubmissionUploaded", "KaggleScoreUpdated"), evt.event_type
                seen += 1
    assert seen > 0, "expected pass46h events on the ledgers"


# ===========================================================================
# REPORT (Part M — present only after the report is generated)
# ===========================================================================
def test_47_report_present_with_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-M report not generated yet")
    text = REPORT.read_text(encoding="utf-8").lower()
    assert "benchmark" in text
    assert "local-only" in text or "local only" in text
    assert "no upload" in text or "no_upload" in text or "not a kaggle" in text
    assert "no online search" in text or "offline" in text
    assert "floor" in text  # the family-only floor framing


def test_48_report_states_actual_decision():
    if not REPORT.is_file():
        pytest.skip("Part-M report not generated yet")
    dec = _load("pass46h_strategy_decision.json")["decision"]
    assert dec in REPORT.read_text(encoding="utf-8"), dec


# ===========================================================================
# HONESTY LOCKS — parent-edge / escape-partition / caveats cannot drift unstated
# ===========================================================================
def test_49_parent_edge_flag_matches_eval_edge_list():
    dec = _load("pass46h_strategy_decision.json")
    e = _load("pass46h_eval_panel.json")
    # the decision's edge list must equal the eval panel's, and the boolean flag
    # must be a faithful biconditional of that list (no edge claim without an edge)
    assert dec["parent_h2h_edge_candidates_95"] == e["parent_h2h_edge_candidates_95"]
    assert bool(dec["parent_edge_established"]) == bool(
        dec["parent_h2h_edge_candidates_95"])


def test_50_escape_partition_disjoint_and_gameplay_consistent():
    dec = _load("pass46h_strategy_decision.json")
    e = _load("pass46h_eval_panel.json")
    coherent = set(dec["coherent_escape_candidates"])
    live_only = set(dec["live_distinct_only_candidates"])
    gameplay_var = set(dec["gameplay_only_variance_candidates"])
    # the three buckets are a disjoint partition
    assert coherent.isdisjoint(live_only)
    assert coherent.isdisjoint(gameplay_var)
    assert live_only.isdisjoint(gameplay_var)
    # gameplay-distinct set == coherent (live AND gameplay) ∪ gameplay_var (gameplay
    # AND NOT live); live_only candidates are NOT gameplay-distinct from the floor
    distinct_gp = {k for k, v in e["treatment_vs_floor_distinct_in_gameplay"].items()
                   if v}
    assert (coherent | gameplay_var) == distinct_gp
    assert live_only.isdisjoint(distinct_gp)


def test_51_coherent_escape_is_live_distinct():
    # Every coherent escape must ALSO be distinguishable from its family-only floor in
    # the LIVE menu (the live leg of the live∩gameplay intersection) — not gameplay only.
    dec = _load("pass46h_strategy_decision.json")
    smoke = _load("pass46h_smoke_non_inertness.json")
    build = {c["candidate_id"]: c
             for c in _load("pass46h_candidate_build.json")["candidates"]}
    wfd = smoke["within_family_distinguishability"]
    for cid in dec["coherent_escape_candidates"]:
        c = build[cid]
        fam = c["parent_family"]
        key = ("conservative_distinguishable_from_floor"
               if c["scoring_mode"] == "lexicographic"
               else "option_value_distinguishable_from_floor")
        assert wfd[fam][key] is True, (cid, fam, key)


def test_52_report_states_honesty_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-M report not generated yet")
    t = REPORT.read_text(encoding="utf-8").lower()
    dec = _load("pass46h_strategy_decision.json")
    # if no parent edge was established, the report must SAY there is no parent edge
    if not dec["parent_edge_established"]:
        assert "parent edge" in t
        assert ("no 95%-confident parent edge" in t or "no parent edge" in t
                or "not a parent edge" in t)
    # tiny offline oracle coverage must be disclosed (hand-set priors, not fit)
    assert "hand-set prior" in t or "2 decisive" in t
    # at least one gameplay-vs-floor split must be flagged as likely variance
    assert "variance" in t
