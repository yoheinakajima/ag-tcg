"""Pass 46I — water option-value CONFIRMATION v0 (LOCAL-ONLY, NO redeploy).

Confirmation-pass integrity + charter-guardrail checks for the 46H water winner
``cg_typed_water_option_value_v1``. This pass REUSES the existing 46H tarballs (it builds
NOTHING new) and replays them locally to decide whether the per-option value layer clears
BOTH (1) an ATTRIBUTION bar vs its own family-only floor control
(``cg_typed_water_family_only_floor_v1``) AND (2) a PRACTICAL bar vs the real internal parent
(``league_water_anti_disruption_pivot_v1``).

No network, no Kaggle, no promotion, no registration, no tarball regeneration, no real game
runs here — these tests read the committed artifacts only.

They assert: nothing uploaded/submitted/promoted/registered; the 46H tarballs were reused
byte-for-byte (sha matches the recorded 46H sha; no overwrite); public references stayed
benchmark-only and EXCLUDED from the decision; root/prod config untouched; the pre-registered
panels/thresholds are honoured; the edge labels are faithful to their Wilson intervals; the
parent-edge attribution decomposition (Fisher increment vs the floor) is honest; and the
final decision is exactly what the pre-registered rule yields from the observed labels.

Forward-compatible: assertions check invariants, ranges, and cross-artifact consistency, and
RE-DERIVE the decision from the pre-registered rule rather than pinning numbers that move
between honest re-runs.
"""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.tournament import benchmark as B
from ptcg_activegraph.tournament.pool import CandidatePool

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
RPT = REPO / "data" / "reports"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass46h"
PARENT_DIR = REPO / "data" / "submissions" / "candidates_pass33"
REF_TARBALL_DIR = REPO / "data" / "reference_agents" / "tarballs"
LAB_LEDGER = REPO / "data" / "activegraph" / "lab_events.jsonl"
BENCH_LEDGER = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"
REPORT = RPT / "pass46i_water_option_value_confirmation_report.md"

TREATMENT = "cg_typed_water_option_value_v1"
FLOOR = "cg_typed_water_family_only_floor_v1"
PARENT = "league_water_anti_disruption_pivot_v1"

ALLOWED_DECISIONS = {
    "water_option_value_confirmed_local_candidate",
    "water_option_value_floor_escape_only",
    "water_option_value_inconclusive_needs_more_n",
    "water_option_value_not_promising",
    "validation_failed", "safety_stop_required",
}
ALLOWED_LABELS = {"confirmed_edge", "directional_edge", "no_edge",
                  "seat_confounded", "unsafe_invalid"}
GATING_PANELS = ("ov_vs_floor", "ov_vs_parent")
NOISE_PANELS = ("parent_vs_parent", "ov_vs_ov")
FORBIDDEN_EVENT_TYPES = {"CandidatePromoted", "SubmissionQueued",
                         "SubmissionUploaded", "KaggleScoreUpdated"}


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


def _ref_ids() -> set[str]:
    return {o.agent_id for o in B.load_opponents(include_optional=True)}


def _candidate_tarball(cid: str) -> Path:
    return CAND_DIR / f"{cid}.tar.gz"


def _derive_decision(safety_ok: bool, validation_ok: bool, attribution: str,
                     practical: str, noise_required: bool, noise_clean) -> str:
    """Re-implementation of the pre-registered decision rule (Part C order)."""
    noise_blocks = noise_required and noise_clean is False
    if not safety_ok:
        return "safety_stop_required"
    if not validation_ok:
        return "validation_failed"
    if attribution == "confirmed_edge" and practical == "confirmed_edge" and not noise_blocks:
        return "water_option_value_confirmed_local_candidate"
    if attribution == "confirmed_edge" and practical == "no_edge":
        return "water_option_value_floor_escape_only"
    if attribution == "confirmed_edge" and practical in ("directional_edge", "seat_confounded"):
        return "water_option_value_inconclusive_needs_more_n"
    if attribution == "directional_edge":
        return "water_option_value_inconclusive_needs_more_n"
    if noise_blocks:
        return "water_option_value_inconclusive_needs_more_n"
    if attribution in ("no_edge", "seat_confounded"):
        return "water_option_value_not_promising"
    return "water_option_value_inconclusive_needs_more_n"


# ===========================================================================
# SAFETY / ROOT / CHARTER (Part A)
# ===========================================================================
def test_01_root_main_and_deck_unchanged():
    assert _sha(REPO / "main.py") == _sha(BASE / "main.py")
    assert _sha(REPO / "deck.csv") == _sha(BASE / "deck.csv")


def test_02_safety_preflight_all_ok_no_prod_mutation():
    pf = _load("pass46i_safety_preflight.json")
    assert pf["all_ok"] is True
    assert pf["stop_required"] is False
    assert pf["production_mutated"] is False
    assert pf["tick_executed"] is False
    assert pf["republish_required"] is False
    assert pf["no_upload"] is True


def test_03_safety_preflight_no_forbidden_events():
    pf = _load("pass46i_safety_preflight.json")
    assert pf["forbidden_events_in_local_ledger"] == []
    scan = pf["prod_ledger_scan"]
    assert scan["read_ok"] is True
    forbidden = scan.get("forbidden_events") or scan.get("forbidden") or []
    assert forbidden == []


def test_04_safety_preflight_no_write_actions():
    pf = _load("pass46i_safety_preflight.json")
    assert not pf["auto_submit"]
    assert not pf["registration_performed"]
    assert not pf["promotion_performed"]
    assert not pf["candidate_generated"]


def test_05_start_application_workflow_not_started_is_expected():
    pf = _load("pass46i_safety_preflight.json")
    saw = pf["start_application_workflow"]
    assert saw["is_frozen_kaggle_entrypoint"] is True
    assert saw["started_here"] is False
    assert saw["not_started_is_expected"] is True


def test_06_reuses_existing_46h_artifacts_nothing_missing():
    pf = _load("pass46i_safety_preflight.json")
    assert pf["missing_46h_eval_artifacts"] == []
    assert pf["missing_water_candidate_tarballs"] == []
    assert len(pf["water_candidate_tarballs"]) == 3
    assert pf["parent_tarball_present"] is True


def test_07_prod_deployment_config_unchanged():
    pf = _load("pass46i_safety_preflight.json")
    dc = pf["deployment_checks"]
    assert dc["deployment_target_scheduled"] is True
    assert dc["run_is_deployment_tick"] is True
    assert dc["run_not_root_main"] is True
    assert dc["run_has_production"] is True


def test_08_references_remain_benchmark_only_live():
    opps = B.load_opponents(include_optional=True)
    assert opps, "expected built public reference agents"
    assert all(o.status == B.EXTERNAL_REFERENCE_STATUS for o in opps)
    assert all(o.usage == "benchmark_opponent_only" for o in opps)
    assert all(o.no_upload is True for o in opps)


def test_09_references_not_in_candidate_pool_live():
    pool = CandidatePool.load()
    ref_ids = _ref_ids()
    pool_ids = {c.candidate_id for c in pool.candidates}
    assert not (ref_ids & pool_ids)
    assert all(c.status != B.EXTERNAL_REFERENCE_STATUS for c in pool.candidates)


# ===========================================================================
# CANDIDATE ARTIFACT REUSE (Part B) — 46H tarballs reused byte-for-byte
# ===========================================================================
def test_10_artifact_check_all_ok_water_family_no_regen():
    b = _load("pass46i_candidate_artifact_check.json")
    assert b["all_ok"] is True
    assert b["family"] == "water"
    assert b["parent_candidate_id"] == PARENT
    assert b["n_candidates"] == 3
    assert b["tarballs_regenerated"] is False
    assert b["production_mutated"] is False


def test_11_each_candidate_members_main_deck_cg_libcg():
    b = _load("pass46i_candidate_artifact_check.json")
    for pc in b["per_candidate"]:
        m = pc["members"]
        assert m["has_main_py"] and m["has_deck_csv"]
        assert m["has_cg_tree"] and m["has_libcg_so"]
        assert m["top_level_ok"] is True
        assert pc["members_ok"] is True
        top = {n.split("/")[0] for n in m["names"]}
        assert top <= {"main.py", "deck.csv", "cg"}, top


def test_12_tarballs_reused_byte_for_byte_no_overwrite():
    b = _load("pass46i_candidate_artifact_check.json")
    for pc in b["per_candidate"]:
        # recorded == 46H sha (true reuse, not a fresh build)
        assert pc["tarball_sha256"] == pc["recorded_46h_sha256"]
        assert pc["no_overwrite"] is True
        # and the on-disk file still hashes to that exact sha
        tb = _candidate_tarball(pc["candidate_id"])
        assert tb.is_file(), tb
        assert _sha(tb) == pc["tarball_sha256"], pc["candidate_id"]


def test_13_candidate_decks_equal_parent():
    b = _load("pass46i_candidate_artifact_check.json")
    parent_sha = b["parent_deck_sha256"]
    for pc in b["per_candidate"]:
        assert pc["deck_equals_parent"] is True
        assert pc["candidate_deck_sha256"] == parent_sha


def test_14_lane_separation_cg_typed_accepts_stdlib_rejects():
    b = _load("pass46i_candidate_artifact_check.json")
    for pc in b["per_candidate"]:
        assert pc["public_reference"] is False
        assert pc["cg_typed_lane_accepts"]["accepts"] is True
        assert pc["cg_typed_lane_accepts"]["returncode"] == 0
        assert pc["stdlib_lane_rejects"]["rejects"] is True
        assert pc["stdlib_lane_rejects"]["returncode"] != 0


def test_15_cross_candidate_distinct_treatment_and_floor_present():
    b = _load("pass46i_candidate_artifact_check.json")
    cc = b["cross_candidate"]
    assert cc["distinct_tarballs"] is True
    assert cc["n_distinct_tarballs"] == b["n_candidates"]
    assert cc["treatment_present_ok"] is True
    assert cc["floor_present_ok"] is True
    ids = {pc["candidate_id"] for pc in b["per_candidate"]}
    assert {TREATMENT, FLOOR} <= ids


def test_16_no_reference_code_in_candidate_lineage():
    ref_main_shas = set()
    for tb in sorted(REF_TARBALL_DIR.glob("public_ref_*.tar.gz")):
        ref_main_shas.add(hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest())
    assert ref_main_shas, "expected reference tarballs to compare against"
    b = _load("pass46i_candidate_artifact_check.json")
    for pc in b["per_candidate"]:
        tb = _candidate_tarball(pc["candidate_id"])
        cand_main_sha = hashlib.sha256(_tar_member_bytes(tb, "main.py")).hexdigest()
        assert cand_main_sha not in ref_main_shas, pc["candidate_id"]


# ===========================================================================
# EVAL PLAN (Part C) — pre-registered BEFORE games
# ===========================================================================
def test_17_plan_pre_registered_clean():
    p = _load("pass46i_eval_plan.json")
    assert p["pre_registered"] is True
    assert p["all_ok"] is True
    assert p["no_upload"] is True
    assert p["production_mutated"] is False


def test_18_plan_gating_arms_and_targets():
    p = _load("pass46i_eval_plan.json")
    by_id = {pl["panel_id"]: pl for pl in p["panels"]}
    for pid in GATING_PANELS:
        assert by_id[pid]["gating"] is True
        assert by_id[pid]["target_decisive"] >= 40
        assert by_id[pid]["seat_balanced"] is True
    assert by_id["ov_vs_floor"]["subject"] == TREATMENT
    assert by_id["ov_vs_floor"]["opponent"] == FLOOR
    assert by_id["ov_vs_parent"]["subject"] == TREATMENT
    assert by_id["ov_vs_parent"]["opponent"] == PARENT


def test_19_plan_thresholds_sane():
    t = _load("pass46i_eval_plan.json")["thresholds"]
    assert abs(t["wilson_z"] - 1.96) < 1e-9
    assert t["confirm_wilson_low"] == 0.5
    assert t["directional_point"] >= 0.5
    assert t["seat_confound_lo"] < 0.5 < t["seat_confound_hi"]
    assert t["noise_ci_must_contain"] == 0.5


def test_20_plan_decision_rules_arms_and_reference_policy():
    p = _load("pass46i_eval_plan.json")
    dr = p["decision_rules"]
    assert dr["arms"]["attribution"] == "ov_vs_floor"
    assert dr["arms"]["practical"] == "ov_vs_parent"
    listed = {o["decision"] for o in dr["order"]}
    assert ALLOWED_DECISIONS <= listed
    assert "benchmark" in dr["reference_policy"].lower()
    assert "never" in dr["reference_policy"].lower() or "excluded" in dr["reference_policy"].lower()


# ===========================================================================
# CONFIRMATION RUN (Part D)
# ===========================================================================
def test_21_confirmation_complete_clean():
    d = _load("pass46i_water_confirmation.json")
    assert d["complete"] is True
    assert d["production_mutated"] is False
    assert d["no_upload"] is True
    assert d["n_invalid_total"] == 0
    assert d["n_games_total"] >= 1


def test_22_confirmation_panels_invalid_within_tolerance():
    d = _load("pass46i_water_confirmation.json")
    for pl in d["panels"]:
        n = pl["n_results"]
        inv = pl["n_invalid"]
        assert inv <= 2, (pl["panel_id"], inv)
        if n:
            assert inv / n <= 0.05, (pl["panel_id"], inv, n)
        assert pl["n_decisive"] >= 1


def test_23_gating_panels_reached_target_and_seat_balanced():
    d = _load("pass46i_water_confirmation.json")
    by_id = {pl["panel_id"]: pl for pl in d["panels"]}
    for pid in GATING_PANELS:
        pl = by_id[pid]
        assert pl["n_decisive"] >= pl["target_decisive"], pid
        assert pl["seat0"]["decisive"] >= 1 and pl["seat1"]["decisive"] >= 1, pid


def test_24_noise_controls_added_iff_practical_clears_parent_trigger():
    d = _load("pass46i_water_confirmation.json")
    panel_ids = {pl["panel_id"] for pl in d["panels"]}
    has_noise = any(p in panel_ids for p in NOISE_PANELS)
    assert bool(d["noise_controls_added"]) == bool(d["practical_clears_parent_trigger"])
    assert has_noise == bool(d["noise_controls_added"])


# ===========================================================================
# EDGE ANALYSIS (Part E) — Wilson / seat / Fisher / labels
# ===========================================================================
def test_25_edge_all_ok_no_mutation_wilson_bounds_valid():
    e = _load("pass46i_edge_analysis.json")
    assert e["all_ok"] is True
    assert e["production_mutated"] is False
    assert e["no_upload"] is True
    for pid, a in e["panels"].items():
        lo, hi = a["wilson_low"], a["wilson_high"]
        assert 0.0 <= lo <= hi <= 1.0, pid
        assert 0.0 <= a["point"] <= 1.0, pid


def test_26_edge_labels_faithful_to_wilson():
    e = _load("pass46i_edge_analysis.json")
    t = e["thresholds"]
    for pid, a in e["panels"].items():
        lbl = a["edge_label"]
        assert lbl in ALLOWED_LABELS, (pid, lbl)
        if lbl == "confirmed_edge":
            assert a["wilson_low"] > t["confirm_wilson_low"], pid
        if lbl == "directional_edge":
            # leans in (point past the directional bar) but is NOT 95%-confident
            assert a["point"] >= t["directional_point"], pid
            assert a["wilson_low"] <= t["confirm_wilson_low"], pid
        if lbl == "no_edge":
            # not confirmed and not a strong directional point
            assert a["wilson_low"] <= t["confirm_wilson_low"], pid


def test_27_seat_confounded_flag_consistent_with_thresholds():
    e = _load("pass46i_edge_analysis.json")
    t = e["thresholds"]
    hi, lo = t["seat_confound_hi"], t["seat_confound_lo"]
    for pid, a in e["panels"].items():
        s0 = a["seat0"]["win_rate"]
        s1 = a["seat1"]["win_rate"]
        split = (s0 >= hi and s1 <= lo) or (s1 >= hi and s0 <= lo)
        assert bool(a["seat_confounded"]) == bool(split), (pid, s0, s1)


def test_28_attribution_increment_fisher_honest():
    e = _load("pass46i_edge_analysis.json")
    inc = e["attribution_increment_fisher"]
    assert "fisher" in inc["test"].lower()
    p = inc["p_value"]
    assert 0.0 <= p <= 1.0
    assert bool(inc["significant_at_0_05"]) == bool(p < 0.05)
    # if NOT significant the interpretation must say the edge is inherited from the floor
    if not inc["significant_at_0_05"]:
        assert "inherited" in inc["interpretation"].lower() or \
               "not added" in inc["interpretation"].lower()


def test_29_decision_inputs_labels_match_panels():
    e = _load("pass46i_edge_analysis.json")
    di = e["decision_inputs"]
    assert di["attribution_label"] == e["panels"][di["attribution_panel"]]["edge_label"]
    assert di["practical_label"] == e["panels"][di["practical_panel"]]["edge_label"]
    # noise required iff the practical arm is confirmed or directional
    expect_noise = di["practical_label"] in ("confirmed_edge", "directional_edge")
    assert bool(di["noise_required"]) == expect_noise


def test_30_noise_clean_consistent_with_noise_panels():
    e = _load("pass46i_edge_analysis.json")
    di = e["decision_inputs"]
    if not di["noise_required"]:
        return
    # a clean noise control is one whose Wilson interval contains 0.5
    for pid in NOISE_PANELS:
        a = e["panels"].get(pid)
        if a is None:
            continue
        contains_half = a["wilson_low"] <= 0.5 <= a["wilson_high"]
        assert bool(a.get("noise_clean")) == bool(contains_half), pid


# ===========================================================================
# REFERENCE CONTEXT (Part F) — benchmark-only, EXCLUDED
# ===========================================================================
def test_31_reference_context_benchmark_only_excluded():
    r = _load("pass46i_reference_context.json")
    assert r["benchmark_only"] is True
    assert r["parity_claim"] is False
    assert r["excluded_from_decisions"] is True
    assert r["no_upload"] is True
    assert r["production_mutated"] is False


def test_32_reference_opponents_are_public_refs_subject_owned():
    r = _load("pass46i_reference_context.json")
    ref_ids = _ref_ids()
    assert r["subject"] == TREATMENT
    assert r["subject"] not in ref_ids
    assert r["safe_opponents"], "expected at least one usable reference"
    for opp in r["safe_opponents"]:
        assert opp in ref_ids, opp


def test_33_reference_wilson_and_combined_consistent():
    r = _load("pass46i_reference_context.json")
    total_dec = 0
    total_wins = 0
    for opp, o in r["per_opponent"].items():
        assert 0.0 <= o["wilson_low"] <= o["wilson_high"] <= 1.0, opp
        total_dec += o["decisive"]
        total_wins += o["wins"]
    c = r["combined"]
    assert c["decisive"] == total_dec
    assert c["wins"] == total_wins
    assert 0.0 <= c["wilson_low"] <= c["wilson_high"] <= 1.0


# ===========================================================================
# STRATEGY DECISION (Part G)
# ===========================================================================
def test_34_decision_in_allowed_states_local_only():
    dec = _load("pass46i_strategy_decision.json")
    assert dec["decision"] in ALLOWED_DECISIONS
    assert dec["local_only"] is True
    assert dec["no_upload"] is True
    assert dec["production_mutated"] is False
    assert dec["no_promotion"] is True
    assert dec["no_registration"] is True
    assert dec["no_kaggle"] is True


def test_35_decision_re_derives_from_pre_registered_rule():
    dec = _load("pass46i_strategy_decision.json")
    g = dec["gates"]
    derived = _derive_decision(
        bool(g["safety_ok"]), bool(g["validation_ok"]),
        dec["attribution_label"], dec["practical_label"],
        bool(dec["noise_required"]), dec["noise_clean"])
    assert derived == dec["decision"], (derived, dec["decision"])


def test_36_decision_gate_booleans_match_labels():
    dec = _load("pass46i_strategy_decision.json")
    g = dec["gates"]
    assert bool(g["attribution_confirmed"]) == (dec["attribution_label"] == "confirmed_edge")
    assert bool(g["practical_confirmed"]) == (dec["practical_label"] == "confirmed_edge")
    assert bool(g["practical_directional"]) == (dec["practical_label"] == "directional_edge")
    if dec["decision"] not in ("safety_stop_required", "validation_failed"):
        assert g["safety_ok"] is True
        assert g["validation_ok"] is True


def test_37_decision_safety_invariants_ok():
    dec = _load("pass46i_strategy_decision.json")
    assert dec["safety_invariants_ok"] is True
    inv = dec["safety_invariants"]
    assert inv["production_mutated"] is False
    assert inv["tick_executed"] is False
    assert inv["registration_performed"] is False
    assert inv["promotion_performed"] is False
    assert inv["no_upload"] is True
    assert inv["no_tarball_regeneration"] is True
    assert inv["references_benchmark_only_excluded"] is True
    assert inv["forbidden_events_absent"] is True


def test_38_parent_edge_attribution_faithful_to_fisher():
    dec = _load("pass46i_strategy_decision.json")
    attributable = dec["parent_edge_attributable_to_option_value"]
    inc = dec.get("attribution_increment_fisher")
    if dec["practical_label"] in ("confirmed_edge", "directional_edge") and inc:
        # attributable iff the increment over the floor is significant
        assert bool(attributable) == bool(inc["significant_at_0_05"])
        if attributable is False:
            assert "inherited" in dec["parent_edge_attribution_note"].lower() \
                or "not added" in dec["parent_edge_attribution_note"].lower()


def test_39_decision_evidence_matches_edge_panels():
    dec = _load("pass46i_strategy_decision.json")
    e = _load("pass46i_edge_analysis.json")
    ev = dec["evidence"]["attribution_ov_vs_floor"]
    a = e["panels"]["ov_vs_floor"]
    assert ev["point"] == a["point"]
    assert ev["edge_label"] == a["edge_label"]
    assert ev["wilson95"] == [a["wilson_low"], a["wilson_high"]]


# ===========================================================================
# EVENTS (Part H) — local no_upload, idempotent, nothing forbidden
# ===========================================================================
def test_40_events_no_upload_verification_clean():
    ev = _load("pass46i_events.json")
    assert ev["no_upload"] is True
    assert ev["upload_performed"] is False
    assert ev["candidate_promoted"] is False
    assert ev["candidate_registered"] is False
    assert ev["shared_report_site_regenerated"] is False
    v = ev["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == []
    assert v["benchmark_forbidden"] == []
    assert v["main_no_upload_false"] == 0
    assert v["benchmark_no_upload_false"] == 0


def test_41_events_forbidden_types_never_emitted_this_pass():
    ev = _load("pass46i_events.json")
    forbidden = set(ev["forbidden_types_never_emitted"])
    assert FORBIDDEN_EVENT_TYPES <= forbidden


def test_42_all_pass46i_events_carry_no_upload_live():
    seen = 0
    for path in (LAB_LEDGER, BENCH_LEDGER):
        if not path.exists():
            continue
        for evt in EventStore(path).load():
            if "pass46i" in evt.tags:
                assert evt.payload.get("no_upload") is True, (path, evt.event_type)
                assert evt.event_type not in FORBIDDEN_EVENT_TYPES, evt.event_type
                seen += 1
    assert seen > 0, "expected pass46i events on the ledgers"


# ===========================================================================
# REPORT (Part J — present only after it is generated)
# ===========================================================================
def test_43_report_present_with_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-J report not generated yet")
    t = REPORT.read_text(encoding="utf-8").lower()
    assert "benchmark" in t
    assert "local-only" in t or "local only" in t
    assert "no upload" in t or "no_upload" in t or "not a kaggle" in t
    assert "floor" in t  # the family-only floor framing
    assert "parent" in t


def test_44_report_states_actual_decision():
    if not REPORT.is_file():
        pytest.skip("Part-J report not generated yet")
    dec = _load("pass46i_strategy_decision.json")["decision"]
    assert dec in REPORT.read_text(encoding="utf-8"), dec


def test_45_report_states_honesty_caveats():
    if not REPORT.is_file():
        pytest.skip("Part-J report not generated yet")
    t = REPORT.read_text(encoding="utf-8").lower()
    dec = _load("pass46i_strategy_decision.json")
    # references excluded from the decision must be disclosed
    assert "excluded" in t
    # if the parent edge is NOT attributable to option-value, the report must say so
    if dec["parent_edge_attributable_to_option_value"] is False:
        assert "inherited" in t or "not added" in t or "floor" in t
    # win/loss-is-not-a-kaggle-score honesty must be stated
    assert "not a kaggle" in t or "feasibility" in t
