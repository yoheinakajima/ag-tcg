"""Pass 46K — Diamond specialist larger-N confirmation + reference-gap audit (LOCAL-ONLY).

Cross-artifact + forward-compatible tests for the LOCAL-ONLY re-evaluation of the EXISTING
Pass-46J candidate ``cg_typed_diamond_specialist_planner_v0`` at larger N. This pass builds
nothing, promotes nothing, uploads nothing and re-uses the 46J / 46H tarballs byte-for-byte.

No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

The pass DECISION is RE-DERIVED from the frozen pre-registered ladder via
``build_pass46k_strategy_decision.derive_decision`` over a synthetic evidence context, so the
suite stays green when the underlying numbers legitimately move between re-runs: it asserts the
ladder's branch logic and the decision -> required-gate-state map, not pinned shared numbers.

Invariants asserted: root immutable + production untouched; the candidate tarballs were REUSED
(``tarballs_regenerated`` false, ``no_overwrite`` true, sha matches recorded) not rebuilt; the
specialist deck is byte-identical to the parent; the cg_typed lane accepts while stdlib rejects;
no public-reference code leaked into any candidate; the eval plan was pre-registered; the games
checkpoint exists; the edge panels carry well-formed Wilson + seat splits with carried/new split;
public references are BENCHMARK-ONLY and EXCLUDED from the decision; the trace declares every
forbidden strength claim; the LOCAL events emitter forbids every dangerous type and is clean; the
report carries its honesty caveats; the persisted decision is in the allowed list.
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

CAND = REPO / "data" / "submissions" / "candidates_pass46j" / \
    "cg_typed_diamond_specialist_planner_v0.tar.gz"
PARENT = REPO / "data" / "submissions" / "candidates_pass34" / \
    "diamond_toolbox_diancie.tar.gz"
GEN_OV = REPO / "data" / "submissions" / "candidates_pass46h" / \
    "cg_typed_diamond_option_value_v1.tar.gz"
GEN_FLOOR = REPO / "data" / "submissions" / "candidates_pass46h" / \
    "cg_typed_diamond_family_only_floor_v1.tar.gz"
REF_DIR = REPO / "data" / "reference_agents" / "tarballs"

REPORT = REPORTS / "pass46k_diamond_specialist_confirmation_report.md"

ALLOWED = {
    "diamond_specialist_confirmed_local_candidate",
    "diamond_specialist_promising_needs_reference_work",
    "diamond_specialist_inconclusive_needs_more_n",
    "diamond_specialist_not_promising",
    "validation_failed",
    "safety_stop_required",
}


# --------------------------- helpers ---------------------------------------
def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _sha_member(tar: Path, name: str) -> str | None:
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name == name or m.name.endswith("/" + name):
                f = tf.extractfile(m)
                if f is not None:
                    return hashlib.sha256(f.read()).hexdigest()
    return None


@pytest.fixture(scope="module")
def strat_mod():
    path = SCRIPTS / "build_pass46k_strategy_decision.py"
    spec = importlib.util.spec_from_file_location("p46k_strat_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46k_strat_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def emit_mod():
    """Load the LOCAL events emitter as a module WITHOUT running main() (import-only)."""
    path = SCRIPTS / "emit_pass46k_events.py"
    spec = importlib.util.spec_from_file_location("p46k_emit_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46k_emit_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


def _confirmable_ctx() -> dict:
    """A synthetic evidence context where every gate is green: practical confirmed,
    attribution confirmed, all triggered noise controls clean -> the ONLY context that
    yields ``confirmed_local_candidate``. Each branch test mutates exactly one field."""
    return {
        # upstream gates
        "safety_stop_required": False, "safety_all_ok": True, "artifact_all_ok": True,
        "references_excluded": True, "no_upload_ok": True, "root_unchanged": True,
        "any_gating_unsafe_invalid": False,
        # practical arm
        "practical_label": "confirmed_edge", "practical_seat_confounded": False,
        "practical_confirmed": True, "practical_directional": False,
        # attribution arm
        "attribution_label": "confirmed_edge", "attribution_negative": False,
        "attribution_confirmed": True, "attribution_directional": False,
        "fisher_ov_increment_significant": True,
        # gating + noise
        "gating_reached_min_acceptable": True,
        "noise_required": True, "noise_clean": True,
        "noise_results": {"parent_vs_parent": True, "spec_vs_spec": True},
    }


# ===================== A. forward-compatible decision re-derivation ========
def test_confirmable_ctx_yields_confirmed_local_candidate(strat_mod):
    assert strat_mod.derive_decision(_confirmable_ctx())["decision"] == \
        "diamond_specialist_confirmed_local_candidate"


def test_safety_stop_takes_precedence(strat_mod):
    ctx = _confirmable_ctx()
    ctx["safety_stop_required"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == "safety_stop_required"


@pytest.mark.parametrize("mutate", [
    {"safety_all_ok": False}, {"artifact_all_ok": False}, {"references_excluded": False},
    {"no_upload_ok": False}, {"root_unchanged": False}, {"any_gating_unsafe_invalid": True},
])
def test_validation_failed_on_any_broken_upstream_gate(strat_mod, mutate):
    ctx = _confirmable_ctx()
    ctx.update(mutate)
    assert strat_mod.derive_decision(ctx)["decision"] == "validation_failed"


@pytest.mark.parametrize("mutate", [
    {"practical_label": "no_edge"},
    {"practical_label": "seat_confounded"},
    {"practical_seat_confounded": True},
    {"attribution_negative": True},
])
def test_not_promising_on_no_edge_or_negative_attribution(strat_mod, mutate):
    ctx = _confirmable_ctx()
    ctx.update(mutate)
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_not_promising"


def test_inconclusive_when_gating_below_min(strat_mod):
    ctx = _confirmable_ctx()
    ctx["gating_reached_min_acceptable"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_inconclusive_needs_more_n"


def test_inconclusive_when_practical_only_directional(strat_mod):
    ctx = _confirmable_ctx()
    ctx["practical_directional"] = True
    ctx["practical_confirmed"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_inconclusive_needs_more_n"


def test_inconclusive_when_triggered_noise_not_clean(strat_mod):
    """The ACTUAL 46K case: clean+attributable edge, but a triggered self-mirror is dirty."""
    ctx = _confirmable_ctx()
    ctx["noise_clean"] = False
    ctx["noise_results"] = {"parent_vs_parent": True, "spec_vs_spec": False}
    res = strat_mod.derive_decision(ctx)
    assert res["decision"] == "diamond_specialist_inconclusive_needs_more_n"
    assert any("noise" in r.lower() and "spec_vs_spec" in r for r in res["reasons"])


def test_untriggered_stale_noise_results_ignored_when_aggregate_clean(strat_mod):
    """When noise is NOT required, the per-control noise_results map is not consulted by the
    inconclusive trigger; only the aggregate noise_clean gates. A stale False entry with
    aggregate noise_clean=True therefore does NOT block confirmation."""
    ctx = _confirmable_ctx()
    ctx["noise_required"] = False
    ctx["noise_results"] = {"spec_vs_spec": False}  # stale; not consulted (aggregate clean)
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_confirmed_local_candidate"


def test_aggregate_dirty_noise_blocks_confirmation_even_when_not_required(strat_mod):
    """Aggregate noise_clean=False blocks confirmation/promising regardless of noise_required —
    BOTH the confirmation and the promising branches require ctx['noise_clean'] — so the ladder
    falls through to inconclusive even when no control was 'required'."""
    ctx = _confirmable_ctx()
    ctx["noise_required"] = False
    ctx["noise_clean"] = False
    ctx["noise_results"] = {"spec_vs_spec": False}
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_inconclusive_needs_more_n"


def test_confirmed_via_directional_attribution_with_fisher_increment(strat_mod):
    ctx = _confirmable_ctx()
    ctx["attribution_confirmed"] = False
    ctx["attribution_directional"] = True
    ctx["fisher_ov_increment_significant"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_confirmed_local_candidate"


def test_promising_needs_reference_work_when_attribution_not_confirmed(strat_mod):
    ctx = _confirmable_ctx()
    ctx["attribution_label"] = "no_edge"
    ctx["attribution_confirmed"] = False
    ctx["attribution_directional"] = False
    ctx["fisher_ov_increment_significant"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_promising_needs_reference_work"


def test_every_derived_decision_is_in_allowed_list(strat_mod):
    for mutate in ({}, {"safety_stop_required": True}, {"safety_all_ok": False},
                   {"practical_label": "no_edge"}, {"attribution_negative": True},
                   {"noise_clean": False, "noise_results": {"spec_vs_spec": False}},
                   {"gating_reached_min_acceptable": False}):
        ctx = _confirmable_ctx()
        ctx.update(mutate)
        assert strat_mod.derive_decision(ctx)["decision"] in ALLOWED


def test_persisted_decision_matches_rederivation(strat_mod):
    persisted = _load("pass46k_strategy_decision.json")["decision"]
    rederived = strat_mod.derive_decision(strat_mod.build_context())["decision"]
    assert persisted == rederived
    assert persisted in ALLOWED


def test_persisted_decision_independent_of_references():
    d = _load("pass46k_strategy_decision.json")
    assert d["decision_independent_of_references"] is True
    assert d["references_benchmark_only"] is True
    assert d["references_are_decision_gate"] is False


def test_actual_46k_inconclusive_is_specifically_noise_blocked():
    """SNAPSHOT of THIS pass's own (pass46k_*) evidence — pass-specific artifacts, never
    overwritten by a future pass. The persisted inconclusive is SPECIFICALLY caused by a
    TRIGGERED self-mirror noise control being dirty, NOT by gating falling short or practical
    being only directional: every other confirmation precondition is met."""
    di = _load("pass46k_edge_analysis.json")["decision_inputs"]
    assert _load("pass46k_strategy_decision.json")["decision"] == \
        "diamond_specialist_inconclusive_needs_more_n"
    # otherwise-confirmable preconditions all hold:
    assert di["practical_confirmed"] is True
    assert di["attribution_confirmed"] is True
    assert di["fisher_ov_increment_significant"] is True
    assert di["gating_reached_min_acceptable"] is True
    assert di["practical_directional"] is False
    assert di["attribution_negative"] is False
    # ...blocked SOLELY by a triggered dirty noise control:
    assert di["noise_required"] is True
    assert di["noise_clean"] is False
    assert di["noise_results"]["spec_vs_spec"] is False
    assert di["noise_results"]["parent_vs_parent"] is True


def test_strategy_allowed_list_matches_plan(strat_mod):
    assert set(strat_mod.ALLOWED) == ALLOWED


# ===================== B. safety + artifact reuse (NOT rebuilt) ============
def test_safety_preflight_all_ok_and_no_prod_mutation():
    s = _load("pass46k_safety_preflight.json")
    assert s["all_ok"] is True and s["stop_required"] is False
    assert s["production_mutated"] is False and s["no_upload"] is True
    assert s["promotion_performed"] is False and s["registration_performed"] is False
    assert s["candidate_rebuilt"] is False and s["candidate_generated"] is False
    assert s["tick_executed"] is False and s["lifecycle_applied"] is False
    assert s["forbidden_events_in_local_ledger"] in (0, [], None) or \
        not s["forbidden_events_in_local_ledger"]


def test_artifact_check_all_ok_and_no_rebuild():
    a = _load("pass46k_artifact_check.json")
    assert a["all_ok"] is True
    assert a["tarballs_regenerated"] is False
    assert a["production_mutated"] is False and a["no_upload"] is True


def test_artifact_check_every_target_reused_sha_matches_recorded():
    a = _load("pass46k_artifact_check.json")
    for t in a["per_target"]:
        assert t["tarball_present"] is True, t["candidate_id"]
        assert t["no_overwrite"] is True, t["candidate_id"]
        assert t["members_ok"] is True, t["candidate_id"]
        assert t["tarball_sha256"] == t["recorded_sha256"], t["candidate_id"]
        assert t["ok"] is True, t["candidate_id"]


def test_artifact_check_specialist_deck_equals_parent_and_lane_separation():
    a = _load("pass46k_artifact_check.json")
    spec = next(t for t in a["per_target"]
                if t["candidate_id"] == "cg_typed_diamond_specialist_planner_v0")
    assert spec["deck_equals_parent"] is True
    assert spec["cg_typed_lane_accepts"]["accepts"] is True
    assert spec["stdlib_lane_rejects"]["rejects"] is True
    assert a["cross_target"]["specialist_deck_equals_parent"] is True


def test_specialist_deck_byte_identical_to_parent_on_disk():
    assert CAND.is_file() and PARENT.is_file()
    assert _sha_member(CAND, "deck.csv") == _sha_member(PARENT, "deck.csv")


def test_specialist_main_differs_from_parent_main_on_disk():
    assert _sha_member(CAND, "main.py") != _sha_member(PARENT, "main.py")


def test_comparison_tarballs_present_and_distinct():
    a = _load("pass46k_artifact_check.json")
    assert GEN_OV.is_file() and GEN_FLOOR.is_file()
    assert a["cross_target"]["n_distinct_tarballs"] == len(a["per_target"])


def test_root_main_and_deck_unchanged_vs_recorded_baseline():
    """Direct filesystem check (not artifact self-report): root main.py / deck.csv on disk
    still hash to the SHAs Part-A recorded — this LOCAL pass mutated neither."""
    s = _load("pass46k_safety_preflight.json")
    root_main, root_deck = REPO / "main.py", REPO / "deck.csv"
    assert root_main.is_file() and root_deck.is_file()
    assert hashlib.sha256(root_main.read_bytes()).hexdigest() == s["root_main_sha256"]
    assert hashlib.sha256(root_deck.read_bytes()).hexdigest() == s["root_deck_sha256"]


# ===================== C. no public-reference leakage =====================
def test_no_candidate_owned_member_matches_any_public_reference():
    """No OWNED member (main.py / deck.csv — cg/ is shared typed-lane infra, not policy) of any
    candidate matches the same-named member of any public reference: zero ref code copied."""
    refs = sorted(REF_DIR.glob("*.tar.gz"))
    assert refs, "expected public reference tarballs present"
    for cand in (CAND, GEN_OV, GEN_FLOOR):
        for member in ("main.py", "deck.csv"):
            csha = _sha_member(cand, member)
            assert csha is not None, f"{cand.name} missing {member}"
            for r in refs:
                assert csha != _sha_member(r, member), f"{cand.name}:{member} == {r.name}"


def test_artifact_check_counted_all_references():
    a = _load("pass46k_artifact_check.json")
    assert a["n_references_checked"] == len(list(REF_DIR.glob("*.tar.gz")))


# ===================== D. eval plan pre-registered + refs excluded =========
def test_eval_plan_pre_registered_and_reuses_existing_candidate():
    p = _load("pass46k_eval_plan.json")
    assert p["pre_registered"] is True
    assert p["evaluates_existing_candidate"] is True
    assert p["rebuilds_candidate"] is False
    assert p["all_ok"] is True
    assert p["all_participants_present"] is True


def test_eval_plan_allowed_decisions_frozen():
    p = _load("pass46k_eval_plan.json")
    assert set(p["decision_rules"]["allowed_decisions"]) == ALLOWED


def test_eval_plan_gating_participants_exclude_public_refs():
    p = _load("pass46k_eval_plan.json")
    assert not any("public_ref" in str(cid) for cid in p["participants"])
    for pan in p["panels"]:
        assert not any("public_ref" in str(v) for v in (pan.get("subject"),
                                                         pan.get("opponent")))


def test_eval_plan_reference_context_is_benchmark_only_non_gating():
    p = _load("pass46k_eval_plan.json")
    rc = p["optional_reference_context"]
    rc0 = rc[0] if isinstance(rc, list) else rc
    assert rc0["benchmark_only"] is True
    assert rc0["gating"] is False
    assert rc0["decision_excluded"] is True


# ===================== E. confirmation games + edge analysis ===============
def test_confirmation_games_checkpoint_exists_nonempty():
    games = EXP / "pass46k_diamond_confirmation_games.jsonl"
    assert games.is_file()
    n = sum(1 for ln in games.read_text(encoding="utf-8").splitlines() if ln.strip())
    assert n > 0


def test_confirmation_summary_complete_and_split_recorded():
    c = _load("pass46k_diamond_confirmation.json")
    assert c["complete"] is True
    assert c["rebuilds_candidate"] is False and c["evaluates_existing_candidate"] is True
    assert c["n_games_total"] == c["n_carried_total"] + c["n_new_total"]
    assert c["n_invalid_total"] <= 0.05 * c["n_games_total"]    # invalid rate not unsafe
    assert c["production_mutated"] is False and c["no_upload"] is True


def test_edge_analysis_references_excluded_and_clean():
    e = _load("pass46k_edge_analysis.json")
    assert e["all_ok"] is True
    assert e["references_in_analysis"] is False
    assert e["no_upload"] is True and e["production_mutated"] is False


def test_required_gating_panels_present_and_meet_min_decisive():
    """Every PRE-REGISTERED gating panel exists in the edge analysis and cleared its
    min_acceptable_decisive (guards against a truncated/empty gating run sneaking through)."""
    plan = _load("pass46k_eval_plan.json")
    edge = _load("pass46k_edge_analysis.json")["panels"]
    gating = [p for p in plan["panels"] if p.get("gating")]
    assert len(gating) >= 2  # at least the practical + the attribution arm
    for p in gating:
        pid = p["panel_id"]
        assert pid in edge, f"gating panel {pid} missing from edge analysis"
        assert edge[pid]["n_decisive"] >= p["min_acceptable_decisive"], pid


def test_edge_panels_wilson_and_seat_well_formed():
    e = _load("pass46k_edge_analysis.json")
    assert e["panels"], "edge analysis has no panels"
    for pid, p in e["panels"].items():
        assert 0.0 <= p["point"] <= 1.0, pid
        assert p["wilson_low"] <= p["point"] <= p["wilson_high"], pid
        assert p["n_decisive"] >= 0 and p["subject_wins"] >= 0, pid
        assert p["subject_wins"] <= p["n_decisive"], pid
        for seat in ("seat0", "seat1"):
            s = p.get(seat) or {}
            if s.get("win_rate") is not None:
                assert 0.0 <= s["win_rate"] <= 1.0, (pid, seat)


def test_edge_panels_carried_plus_new_equals_total_decisive():
    e = _load("pass46k_edge_analysis.json")
    assert e["panels"], "edge analysis has no panels"
    for pid, p in e["panels"].items():
        if p.get("carried_decisive") is not None and p.get("new_decisive") is not None:
            assert p["carried_decisive"] + p["new_decisive"] == p["n_decisive"], pid
            assert p["carried_wins"] + p["new_wins"] == p["subject_wins"], pid


def test_attribution_fisher_increment_internally_consistent():
    e = _load("pass46k_edge_analysis.json")
    assert e["attribution_increments_fisher"], "no attribution Fisher increments recorded"
    for _gen, inc in e["attribution_increments_fisher"].items():
        assert inc["significant_at_0_05"] == (inc["fisher_right_p"] < 0.05)


def test_edge_decision_inputs_gate_state_matches_decision(strat_mod):
    """Whatever decision is persisted, its required gate-state must honestly hold in the
    edge-analysis decision_inputs (defense in depth vs the pure re-derivation)."""
    di = _load("pass46k_edge_analysis.json")["decision_inputs"]
    decision = _load("pass46k_strategy_decision.json")["decision"]
    if decision == "diamond_specialist_confirmed_local_candidate":
        assert di["practical_confirmed"] is True and di["noise_clean"] is True
        assert (di["attribution_confirmed"]
                or (di["attribution_directional"] and di["fisher_ov_increment_significant"]))
    elif decision == "diamond_specialist_inconclusive_needs_more_n":
        assert ((not di["gating_reached_min_acceptable"]) or di["practical_directional"]
                or (di["noise_required"] and not di["noise_clean"]))
    elif decision == "diamond_specialist_not_promising":
        assert (di["practical_label"] in ("no_edge", "seat_confounded")
                or di["attribution_negative"])
    elif decision == "diamond_specialist_promising_needs_reference_work":
        assert di["practical_confirmed"] and di["noise_clean"] \
            and not di["attribution_negative"]


# ===================== F. reference gap (benchmark-only) ===================
def test_reference_gap_benchmark_only_and_excluded():
    g = _load("pass46k_public_reference_gap.json")
    assert g["benchmark_only"] is True
    assert g["is_decision_gate"] is False
    assert g["excluded_from_decisions"] is True
    assert g["parity_claim"] is False
    assert g["no_upload"] is True and g["production_mutated"] is False
    assert g["all_ok"] is True


def test_reference_gap_pooled_wilson_well_formed_and_no_parity():
    g = _load("pass46k_public_reference_gap.json")
    po = g["pooled"]
    assert po["wins"] + po["losses"] == po["decisive"]
    assert po["decisive"] + po["draws"] + po["invalid"] == po["total"]
    assert 0.0 <= po["win_rate"] <= 1.0
    assert po["wilson_low"] <= po["win_rate"] <= po["wilson_high"]
    assert g["pooled_parity_supported"] is False
    assert g["parity_supported_any_ref"] is False


def test_reference_gap_all_five_references_present_and_counts_sane():
    g = _load("pass46k_public_reference_gap.json")
    pr = g["per_reference"]
    items = list(pr.values()) if isinstance(pr, dict) else list(pr)
    assert len(items) == 5                                   # all five refs evaluated
    assert set(g["safe_opponents"]) == set(g["opponents_requested"])
    total = 0
    for r in items:
        assert r["wins"] + r["losses"] == r["decisive"]
        assert 0 <= r["wins"] <= r["decisive"]
        assert 0.0 <= r["win_rate"] <= 1.0
        total += r["decisive"]
    assert total == g["pooled"]["decisive"]


# ===================== G. planner trace caveats ===========================
def test_trace_declares_every_forbidden_strength_claim():
    t = _load("pass46k_planner_trace_diagnostic.json")
    claims = set(t["planner_unsupported_claims"])
    for forbidden in ("exact_damage", "lethal", "ko", "missed_ko", "boss_gust_target",
                      "spread", "best_action", "opponent_hand_contents",
                      "kaggle_score_or_strength"):
        assert forbidden in claims


def test_trace_faithful_and_reference_frames_benchmark_only():
    t = _load("pass46k_planner_trace_diagnostic.json")
    assert t["all_ok"] is True and t["complete"] is True
    assert t["reference_benchmark_only"] is True
    assert 0.0 <= t["replay_faithful_rate"] <= 1.0
    assert t["n_decision_frames"] >= 0
    assert t["no_upload"] is True and t["production_mutated"] is False


def test_trace_cooccurrence_keeps_internal_and_benchmark_cohorts_separate():
    t = _load("pass46k_planner_trace_diagnostic.json")
    co = t["cooccurrence_descriptive"]
    assert "win_frames_internal" in co and "loss_frames_internal" in co
    assert "benchmark_ref_frames" in co  # refs never pooled into win/loss attribution


# ===================== H. events safety (Part I) ==========================
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
    e = _load("pass46k_events.json")
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
    assert e["emitted_main"] >= 5
    assert _MUST_FORBID <= set(e["forbidden_types_never_emitted"])


def test_lab_ledger_pass46k_events_never_forbidden_and_no_upload(emit_mod):
    """Every pass46k-tagged event physically on the ledger is safe (defense in depth)."""
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
    assert seen >= 5


def test_benchmark_ledger_physically_untouched_by_pass46k(emit_mod):
    """Defense in depth vs the events.json self-report: NOT ONE pass46k-tagged event was
    physically appended to the ActiveGraph benchmark ledger — public-reference games live in
    their own experiment ledger; the benchmark ledger is only scanned, never written."""
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
    assert "diamond_specialist_inconclusive_needs_more_n" in text
    assert "benchmark-only" in text.lower()
    assert "never" in text.lower() and "kaggle" in text.lower()
    assert "LOCAL-ONLY" in text or "local-only" in text.lower()
    # explicitly disclaims the forbidden strength-claim vocabulary
    for forbidden in ("lethal", "KO", "Boss-gust", "spread", "best-action"):
        assert forbidden in text
