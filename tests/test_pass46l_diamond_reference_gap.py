"""Pass 46L — Diamond reference-gap planner upgrade v1 (LOCAL-ONLY, NO redeploy).

Cross-artifact + forward-compatible tests for the LOCAL-ONLY construction of ONE owned upgrade
``cg_typed_diamond_specialist_planner_v1`` from the existing 46J v0 via a narrow visible-only
structural diff, judged by a PRE-REGISTERED pooled reference-improvement test against the frozen
46K baseline (v0 = W1/L59). The pass promotes nothing, uploads nothing, registers nothing, and
does not touch production.

No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

The pass DECISION and the frozen reference-improvement test are RE-DERIVED from the pure
``build_pass46l_strategy_decision.derive_decision`` / ``reference_improvement_test`` over
synthetic evidence, so the suite stays green when the underlying numbers legitimately move
between re-runs: it asserts the ladder's branch logic and the frozen test arithmetic, not pinned
shared numbers.

Invariants asserted: root immutable + production untouched; the owned v1 candidate is built
locally (deck byte-identical to the diamond parent, owned original main.py, no public-reference
code copied); the cg_typed lane accepts while the stdlib lane rejects unchanged; the stage-2
non-inertness gate is the BLOCKING GATE (v1 inert here -> clean ``diamond_v1_not_promising``);
public references are BENCHMARK-ONLY and never gate any other outcome; the LOCAL events emitter
forbids every dangerous type and is clean; the report carries its honesty caveats; the persisted
decision is in the allowed list and is independent of references.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
SCRIPTS = REPO / "scripts"
REPORTS = REPO / "data" / "reports"

CAND = REPO / "data" / "submissions" / "candidates_pass46l" / \
    "cg_typed_diamond_specialist_planner_v1.tar.gz"
PARENT = REPO / "data" / "submissions" / "candidates_pass34" / \
    "diamond_toolbox_diancie.tar.gz"
V0 = REPO / "data" / "submissions" / "candidates_pass46j" / \
    "cg_typed_diamond_specialist_planner_v0.tar.gz"

REPORT = REPORTS / "pass46l_diamond_reference_gap_planner_report.md"

ALLOWED = {
    "safety_stop_required",
    "validation_failed",
    "diamond_v1_not_promising",
    "diamond_v1_internal_only_no_reference_gain",
    "diamond_v1_reference_gap_improved_local_only",
}


# --------------------------- helpers ---------------------------------------
def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _sha_member(tar: Path, name: str) -> "str | None":
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name == name or m.name.endswith("/" + name):
                f = tf.extractfile(m)
                if f is not None:
                    return hashlib.sha256(f.read()).hexdigest()
    return None


@pytest.fixture(scope="module")
def strat_mod():
    path = SCRIPTS / "build_pass46l_strategy_decision.py"
    spec = importlib.util.spec_from_file_location("p46l_strat_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46l_strat_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def emit_mod():
    """Load the LOCAL events emitter as a module WITHOUT running main() (import-only)."""
    path = SCRIPTS / "emit_pass46l_events.py"
    spec = importlib.util.spec_from_file_location("p46l_emit_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46l_emit_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


def _inert_ctx() -> dict:
    """The ACTUAL-run context: every upstream gate green, but the stage-2 non-inertness gate
    fails (v1 inert) -> diamond_v1_not_promising. Each branch test mutates exactly one field."""
    return {
        # upstream gates (all green)
        "safety_all_ok": True, "safety_stop_required": False,
        "candidate_build_ok": True, "candidate_public_reference": False,
        "validation_all_ok": True, "fixtures_all_ok": True,
        "no_upload_ok": True, "references_excluded": True,
        "root_unchanged": True, "deck_eq_parent": True,
        "non_inertness_complete": True,
        # stage-2 blocking gate: INERT
        "changed_decision_rate": 0.0, "non_inert_min_rate": 0.05,
        "changes_in_relevant_context": False, "v1_illegal_decisions": 0,
        "non_inertness_frames": 312, "changed_decisions": 0,
        "non_inert_gate_pass_upstream": False,
        # stage-3/4 absent on the inert path
        "v1_internally_worse": None, "reference_improvement_test": None,
    }


def _non_inert_ctx() -> dict:
    """Hypothetical non-inert context (panels would run). Used to exercise stage 3/4."""
    ctx = _inert_ctx()
    ctx.update({
        "changed_decision_rate": 0.20, "changes_in_relevant_context": True,
        "v1_illegal_decisions": 0, "changed_decisions": 62,
        "v1_internally_worse": False,
        "reference_improvement_test": {"passed": False, "conditions": {}},
    })
    return ctx


def _passing_metrics() -> dict:
    return {"safety_artifact_all_ok": True, "pooled_decisive": 60, "invalid_rate": 0.0,
            "both_seats_represented": True, "mirror_ci_straddles_half": True,
            "fisher_p": 0.001, "win_rate": 0.15}


# ===================== A. forward-compatible decision re-derivation ========
def test_inert_ctx_yields_not_promising(strat_mod):
    assert strat_mod.derive_decision(_inert_ctx())["decision"] == "diamond_v1_not_promising"


def test_safety_stop_takes_precedence(strat_mod):
    ctx = _inert_ctx()
    ctx["safety_stop_required"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == "safety_stop_required"


@pytest.mark.parametrize("field,value", [
    ("safety_all_ok", False), ("candidate_build_ok", False),
    ("candidate_public_reference", True), ("validation_all_ok", False),
    ("fixtures_all_ok", False),
    ("no_upload_ok", False), ("references_excluded", False),
    ("root_unchanged", False), ("deck_eq_parent", False),
    ("non_inertness_complete", False),
])
def test_validation_failed_on_any_broken_upstream_gate(strat_mod, field, value):
    ctx = _inert_ctx()
    ctx[field] = value
    assert strat_mod.derive_decision(ctx)["decision"] == "validation_failed"


def test_not_promising_when_rate_below_min(strat_mod):
    ctx = _inert_ctx()
    ctx["changed_decision_rate"] = 0.04   # < 0.05, even if it were relevant
    ctx["changes_in_relevant_context"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == "diamond_v1_not_promising"


def test_not_promising_when_changes_not_in_relevant_context(strat_mod):
    ctx = _inert_ctx()
    ctx["changed_decision_rate"] = 0.30
    ctx["changes_in_relevant_context"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == "diamond_v1_not_promising"


def test_not_promising_when_any_illegal_decision(strat_mod):
    ctx = _inert_ctx()
    ctx["changed_decision_rate"] = 0.30
    ctx["changes_in_relevant_context"] = True
    ctx["v1_illegal_decisions"] = 1
    assert strat_mod.derive_decision(ctx)["decision"] == "diamond_v1_not_promising"


def test_non_inert_but_internally_worse_is_not_promising(strat_mod):
    ctx = _non_inert_ctx()
    ctx["v1_internally_worse"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == "diamond_v1_not_promising"


def test_non_inert_not_worse_reference_test_pass_is_reference_improved(strat_mod):
    ctx = _non_inert_ctx()
    ctx["reference_improvement_test"] = {"passed": True, "conditions": {}}
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_v1_reference_gap_improved_local_only"


def test_non_inert_not_worse_reference_test_fail_is_internal_only(strat_mod):
    ctx = _non_inert_ctx()
    ctx["reference_improvement_test"] = {"passed": False, "conditions": {}}
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_v1_internal_only_no_reference_gain"


def test_every_derived_decision_is_in_allowed_list(strat_mod):
    ctxs = [_inert_ctx(), _non_inert_ctx()]
    extra = _non_inert_ctx(); extra["reference_improvement_test"] = {"passed": True}
    worse = _non_inert_ctx(); worse["v1_internally_worse"] = True
    stop = _inert_ctx(); stop["safety_stop_required"] = True
    bad = _inert_ctx(); bad["validation_all_ok"] = False
    for ctx in ctxs + [extra, worse, stop, bad]:
        assert strat_mod.derive_decision(ctx)["decision"] in ALLOWED


def test_strategy_allowed_list_matches_module_and_plan(strat_mod):
    plan = _load("pass46l_eval_plan.json")
    assert set(strat_mod.ALLOWED) == ALLOWED
    assert strat_mod.ALLOWED == plan["decision_ladder_frozen"]


def test_persisted_decision_matches_rederivation(strat_mod):
    dec = _load("pass46l_strategy_decision.json")
    rederived = strat_mod.derive_decision(dec["evidence"])["decision"]
    assert rederived == dec["decision"]
    assert dec["decision"] in ALLOWED


def test_persisted_decision_is_the_inert_negative():
    dec = _load("pass46l_strategy_decision.json")
    ev = dec["evidence"]
    assert dec["decision"] == "diamond_v1_not_promising"
    assert ev["changed_decisions"] == 0
    assert ev["changed_decision_rate"] == 0.0
    assert ev["changes_in_relevant_context"] is False
    assert ev["v1_illegal_decisions"] == 0
    assert dec["reference_gap_improved"] is False


def test_persisted_decision_independent_of_references():
    dec = _load("pass46l_strategy_decision.json")
    assert dec["decision_independent_of_references"] is True
    assert dec["references_benchmark_only"] is True
    assert dec["references_are_decision_gate_for_other_outcomes"] is False
    assert dec["panels_run"] is False


def test_inert_decision_independent_of_reference_test(strat_mod):
    """On the inert path, forcing the reference test both ways must not move the decision."""
    base = strat_mod.derive_decision(_inert_ctx())["decision"]
    for forced in (True, False):
        ctx = _inert_ctx()
        ctx["reference_improvement_test"] = {"passed": forced, "conditions": {}}
        assert strat_mod.derive_decision(ctx)["decision"] == base


# ===================== B. frozen reference-improvement test ================
def test_reference_test_all_conditions_true_passes(strat_mod):
    assert strat_mod.reference_improvement_test(_passing_metrics())["passed"] is True


@pytest.mark.parametrize("field,value", [
    ("safety_artifact_all_ok", False), ("pooled_decisive", 49),
    ("invalid_rate", 0.06), ("both_seats_represented", False),
    ("mirror_ci_straddles_half", False), ("fisher_p", 0.06), ("win_rate", 0.09),
])
def test_reference_test_any_single_condition_false_fails(strat_mod, field, value):
    m = _passing_metrics()
    m[field] = value
    assert strat_mod.reference_improvement_test(m)["passed"] is False


def test_reference_test_conditions_are_the_seven_pre_registered(strat_mod):
    conds = strat_mod.reference_improvement_test(_passing_metrics())["conditions"]
    assert set(conds.keys()) == {
        "safety_artifact_all_ok", "pooled_v1_decisive_ge_50", "invalid_rate_le_5pct",
        "both_seats_represented", "mirror_ci_straddles_half",
        "fisher_one_sided_p_le_0_05", "v1_pooled_win_rate_ge_0_10"}


def test_reference_test_frozen_arithmetic_two_to_three_wins_is_no_gain(strat_mod):
    """Frozen note: at n=60, 2-3 wins is explicitly NO material gain (win-rate < 0.10)."""
    for wins in (2, 3):
        m = _passing_metrics(); m["win_rate"] = wins / 60.0; m["fisher_p"] = 0.001
        assert strat_mod.reference_improvement_test(m)["passed"] is False


def test_reference_test_frozen_arithmetic_seven_wins_can_pass(strat_mod):
    """Frozen note: ~>=7 wins clears the >=0.10 win-rate gate (with a significant Fisher p)."""
    m = _passing_metrics(); m["win_rate"] = 7 / 60.0; m["fisher_p"] = 0.03
    assert strat_mod.reference_improvement_test(m)["passed"] is True


# ===================== C. eval plan (pre-registered) ======================
def test_eval_plan_pre_registered_and_ladder_frozen():
    plan = _load("pass46l_eval_plan.json")
    assert plan["pre_registered_before_any_v1_game"] is True
    assert plan["decision_ladder_frozen"] == list(
        ["safety_stop_required", "validation_failed", "diamond_v1_not_promising",
         "diamond_v1_internal_only_no_reference_gain",
         "diamond_v1_reference_gap_improved_local_only"])


def test_eval_plan_baseline_frozen_w1_l59():
    plan = _load("pass46l_eval_plan.json")
    base = plan["baseline_frozen"]
    assert base["v0_decisive"] == "W1/L59"
    assert base["source"] == "pass46k"


def test_eval_plan_reference_test_pre_registered_with_all_conditions():
    plan = _load("pass46l_eval_plan.json")
    rit = plan["pre_registered_reference_improvement_test"]
    conds = rit["decision_TRUE_iff_ALL"]
    assert len(conds) == 7
    joined = " ".join(conds).lower()
    for needle in ("decisive", "invalid", "both seats", "mirror", "fisher", "win-rate"):
        assert needle in joined
    assert "explanatory only" in rit["per_reference_rows"].lower()


# ===================== D. safety preflight (STOP-GATE) ====================
def test_safety_preflight_all_ok_and_no_prod_mutation():
    s = _load("pass46l_safety_preflight.json")
    assert s["all_ok"] is True
    assert s.get("stop_required") is False
    assert s.get("no_upload") is True


# ===================== E. owned candidate build ===========================
def test_build_candidate_owned_local_and_not_a_reference():
    b = _load("pass46l_candidate_build.json")
    assert b["candidate_ok"] is True
    assert b["owned_candidate"] is True
    assert b["public_reference"] is False
    assert b["no_upload"] is True
    assert b["deck_unchanged"] is True
    assert b["deck_rows"] == 60
    assert b["inline_region_byte_identical"] is True
    assert b["parity"]["behavioral_parity_ok"] is True
    assert b["planner_parent_candidate_id"] == "cg_typed_diamond_specialist_planner_v0"


def test_candidate_tarball_present_and_sha_matches_recorded():
    b = _load("pass46l_candidate_build.json")
    assert CAND.is_file(), CAND
    on_disk = hashlib.sha256(CAND.read_bytes()).hexdigest()
    assert on_disk == b["tarball_sha256"]


def test_candidate_deck_byte_identical_to_parent_on_disk():
    assert CAND.is_file() and PARENT.is_file()
    cand_deck = _sha_member(CAND, "deck.csv")
    parent_deck = _sha_member(PARENT, "deck.csv")
    assert cand_deck is not None and parent_deck is not None
    assert cand_deck == parent_deck


def test_candidate_main_differs_from_parent_main_on_disk():
    assert CAND.is_file() and PARENT.is_file()
    assert _sha_member(CAND, "main.py") != _sha_member(PARENT, "main.py")


def test_candidate_present_and_distinct_from_v0_on_disk():
    """v1 is a real upgrade artifact, distinct from the v0 main.py (different bytes)."""
    assert CAND.is_file()
    if V0.is_file():
        assert _sha_member(CAND, "main.py") != _sha_member(V0, "main.py")


# ===================== F. validation + lane separation ====================
def test_validation_all_ok_and_lane_separation():
    v = _load("pass46l_candidate_validation.json")
    assert v["all_ok"] is True
    assert v["cg_typed_lane_accepts"]["accepts"] is True
    assert v["stdlib_lane_rejects"]["rejects"] is True
    assert v["lane_separation"]["no_ref_hash_match"] is True
    assert v["deck_vs_parent"]["deck_byte_identical_to_parent"] is True
    assert v["root_unchanged"]["root_main_unchanged"] is True
    assert v["root_unchanged"]["root_deck_unchanged"] is True
    assert v["production_mutated"] is False


# ===================== G. fixtures + non-inertness ========================
def test_fixtures_all_ok_legal_and_honest():
    f = _load("pass46l_planner_fixture_validation.json")
    assert f["all_ok"] is True
    assert f["all_indices_legal"] is True
    assert f["contexts_covered"] is True
    assert f["claims_honesty"]["all_categories_covered"] is True
    assert f["claims_honesty"]["no_claimy_field_names"] is True
    assert f["hidden_zone"]["all_decisions_invariant_to_hidden_zones"] is True
    assert f["never_raise"]["all_safe"] is True


def test_non_inertness_is_complete_and_inert():
    ni = _load("pass46l_non_inertness.json")
    assert ni["complete"] is True
    assert ni["changed_decisions"] == 0
    assert ni["changed_decision_rate"] == 0.0
    assert ni["changes_in_relevant_context"] is False
    assert ni["v1_illegal_decisions"] == 0
    assert ni["non_inert_gate_pass"] is False
    assert ni["reference_benchmark_only"] is True
    assert ni["no_upload"] is True


def test_non_inertness_counts_internally_consistent():
    ni = _load("pass46l_non_inertness.json")
    assert 0 <= ni["changed_decisions"] <= ni["frames"]
    assert 0 <= ni["attach_multi_changed"] <= ni["attach_multi_frames"]
    assert ni["frames"] >= 1
    # an inert run cannot have any changed decision land in a relevant context
    if ni["changed_decisions"] == 0:
        assert ni["changes_in_relevant_context"] is False


# ===================== H. events emitter (LOCAL, no_upload) ===============
_MUST_FORBID = {
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted", "StrategyPromotionDecision",
    "OwnedCgCandidateRegistered", "PublicReferenceAgentRegistered",
    "TournamentParticipantRegistered", "BaselineRegistered", "HypothesisRegistered",
    "StrategyFamilyRegistered",
    "TournamentTickStarted", "TournamentTickFinished",
    "PublicBenchmarkTickStarted", "PublicBenchmarkTickFinished",
}
_ALLOWED_EMIT = {"LocalEvaluationFinished", "StrategyDecisionRecorded", "ReportSiteGenerated"}


def test_emit_guard_set_covers_all_forbidden_types(emit_mod):
    missing = _MUST_FORBID - set(emit_mod.FORBIDDEN_TYPES)
    assert not missing, f"guard set omits forbidden types: {sorted(missing)}"
    assert not (_ALLOWED_EMIT & set(emit_mod.FORBIDDEN_TYPES))


def test_events_json_local_only_and_clean():
    e = _load("pass46l_events.json")
    v = e["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == [] and v["benchmark_forbidden"] == []
    assert v["main_no_upload_false"] == 0 and v["benchmark_no_upload_false"] == 0
    assert e["no_upload"] is True and e["upload_performed"] is False
    assert e["auto_submit"] is False and e["github_push"] is False
    assert e["candidate_promoted"] is False and e["candidate_registered"] is False
    assert e["redeploy"] is False and e["prod_mutated"] is False
    assert e["tick_executed"] is False
    assert e["shared_report_site_regenerated"] is False
    assert e["references_emitted_to_benchmark_ledger"] is False
    assert e["references_excluded_from_decision"] is True
    assert e["panels_run"] is False
    assert e["emitted_main"] >= 4
    assert _MUST_FORBID <= set(e["forbidden_types_never_emitted"])


def test_lab_ledger_pass46l_events_never_forbidden_and_no_upload(emit_mod):
    """Every pass46l-tagged event physically on the ledger is safe (defense in depth)."""
    path = emit_mod.LAB_EVENTS_PATH
    assert path.exists(), path
    seen = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if emit_mod.TAG not in (ev.get("tags") or []):
            continue
        seen += 1
        assert ev.get("event_type") not in emit_mod.FORBIDDEN_TYPES, ev.get("event_type")
        assert (ev.get("payload") or {}).get("no_upload") is True
    assert seen >= 4


def test_benchmark_ledger_physically_untouched_by_pass46l(emit_mod):
    """Defense in depth vs the events.json self-report: NOT ONE pass46l-tagged event was
    physically appended to the ActiveGraph benchmark ledger."""
    path = emit_mod.BENCHMARK_EVENTS_PATH
    if not path.exists():
        return                                   # absent => trivially untouched
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        assert emit_mod.TAG not in (ev.get("tags") or []), ev.get("event_type")


# ===================== I. report honesty caveats ==========================
def test_report_exists_and_has_exactly_ten_sections():
    assert REPORT.is_file()
    headers = [ln for ln in REPORT.read_text(encoding="utf-8").splitlines()
               if ln.startswith("## ")]
    assert len(headers) == 10, headers


def test_report_carries_honesty_caveats():
    text = REPORT.read_text(encoding="utf-8")
    assert "diamond_v1_not_promising" in text
    assert "benchmark-only" in text.lower()
    assert "never" in text.lower() and "kaggle" in text.lower()
    assert "LOCAL-ONLY" in text or "local-only" in text.lower()
    for forbidden in ("lethal", "KO", "Boss-gust", "spread", "best-action"):
        assert forbidden in text


# ===================== J. root immutability / prod untouched ==============
def test_artifacts_declare_production_untouched_and_local_only():
    for name in ("pass46l_candidate_build.json", "pass46l_candidate_validation.json",
                 "pass46l_non_inertness.json", "pass46l_strategy_decision.json"):
        d = _load(name)
        assert d.get("no_upload") is True, name
        if "production_mutated" in d:
            assert d["production_mutated"] is False, name


def test_root_main_and_deck_unchanged_vs_recorded_baseline():
    v = _load("pass46l_candidate_validation.json")
    assert v["root_unchanged"]["root_main_unchanged"] is True
    assert v["root_unchanged"]["root_deck_unchanged"] is True
    s = _load("pass46l_safety_preflight.json")
    assert s["all_ok"] is True
