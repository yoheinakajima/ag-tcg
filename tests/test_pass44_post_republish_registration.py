"""PASS 44 — Post-republish production probation registration + verification bridge.

Validates the honest artifacts produced by Parts A–G: the post-republish safety
preflight, the republish attestation + deploy-image candidate availability (case_1),
the KEY-SCOPED production registration apply (only the 3 missing probation events,
never the ~950 sidecars), the post-registration prod state audit, the controlled
production tick runtime proof (the live deploy path resolves the newly baked
tarballs), the promotion-gate rerun (insufficient_evidence => apply_skipped), and
the scheduler/lifecycle follow-up audit.

HARD invariants asserted: root main.py/deck.csv byte-identical to baseline; no
forbidden events (CandidatePromoted / SubmissionQueued / SubmissionUploaded /
KaggleScoreUpdated) anywhere in scope; no tarball deletion/overwrite by any Pass-44
script; no public-reference leakage into pool/queue/worklist; production registration
only after the safety gate is green; manifest/ledger lockstep. Pure artifact reads +
ledger guard checks — no production mutation, no upload.
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest

from ptcg_activegraph.tournament.ledger import TournamentLedger

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
SCRIPTS = REPO / "scripts"

TARGETS = {
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
}
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}

PASS44_SCRIPTS = [
    "build_pass44_production_probation_registration.py",
    "build_pass44_post_registration_prod_state_audit.py",
    "build_pass44_controlled_prod_tick.py",
    "build_pass44_promotion_gate_post_registration.py",
    "build_pass44_scheduler_lifecycle_after_prod_registration.py",
]


def _j(name: str) -> dict:
    return json.loads((EXP / f"pass44_{name}.json").read_text(encoding="utf-8"))


# -- 1-2. root immutability --------------------------------------------------
def test_root_main_py_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_csv_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# -- 3. post-republish safety preflight --------------------------------------
def test_post_republish_preflight_safe_and_not_stopped():
    d = _j("post_republish_safety_preflight")
    assert d["preflight_safe"] is True
    assert d["stop_required"] is False
    assert d["upload_performed"] is False
    assert d["production_mutation_performed_here"] is False
    assert d["promotion_performed"] is False
    assert d["generation_performed"] is False


def test_preflight_root_safe_via_shared_pass43():
    d = _j("post_republish_safety_preflight")
    shared = d["shared_pass43_preflight"]
    # root safety must be a real derived signal, never hardcoded yes
    assert shared.get("preflight_safe") is True
    assert shared.get("prod_health_healthy") is True
    assert shared.get("prod_health_hard_failures") == []


# -- 4. republish attestation ------------------------------------------------
def test_republish_attestation_head_is_published_and_clean_tarballs():
    d = _j("republish_attestation")
    assert d["head_is_published_commit"] is True
    assert d["all_candidates_deploy_baked_inferred"] is True
    wt = d["working_tree"]
    # tarballs + root entrypoint must be clean even if session files are untracked
    assert wt["tarball_paths_dirty"] == []
    assert wt["root_entrypoint_dirty"] == []


def test_attestation_every_candidate_git_tracked_and_sha_match():
    d = _j("republish_attestation")
    cands = d["candidates"]
    seen = {c["candidate_id"] for c in cands}
    assert TARGETS <= seen
    for c in cands:
        if c["candidate_id"] in TARGETS:
            assert c["git_tracked_at_published_commit"] is True
            assert c["sha_match"] is True


# -- 5. deploy-image candidate availability => case_1 ------------------------
def test_deploy_image_case_1_ready_to_register():
    d = _j("deploy_image_candidate_availability")
    assert d["pass43_decision_case"].startswith("case_1")
    assert d["mutate_prod_os"] is True
    assert d["proceed_to_part_d"] is True
    assert d["ready_to_register"] is True
    assert d["all_safe_to_register_after_republish"] is True


def test_deploy_image_every_target_has_tarball_and_safe():
    d = _j("deploy_image_candidate_availability")
    for c in d["candidates"]:
        if c["candidate_id"] in TARGETS:
            assert c["deploy_image_has_tarball"] is True
            assert c["sha_match"] is True
            assert c["availability"] == "safe_to_register_after_republish"


# -- 6-7. production registration apply (key-scoped) -------------------------
def test_registration_apply_succeeded_and_mutated_prod():
    d = _j("production_probation_registration_apply")
    assert d["apply_skipped"] is False
    assert d["safe_to_apply"] is True
    assert d["root_safe"] is True
    res = d["apply_result"]
    assert res["applied"] is True
    assert res["status"] == "clean"
    assert res["verify_ok"] is True
    assert len(res["newly_registered"]) == 3
    assert set(res["newly_registered"]) == TARGETS
    assert d["guardrails"]["production_mutated"] is True
    assert d["guardrails"]["no_upload_only"] is True
    assert d["guardrails"]["sidecars_untouched"] is True


def test_registration_uploaded_only_changed_keys_not_sidecars():
    # KEY-SCOPED: only events.jsonl + pool + config + manifest get re-uploaded, NOT
    # the ~950 game sidecars. Guard against an accidental full re-push.
    d = _j("production_probation_registration_apply")
    res = d["apply_result"]
    assert res["uploaded_count"] <= 25, res["uploaded_count"]
    keys = res.get("uploaded_keys", [])
    assert not any(k.startswith("games/") for k in keys), keys


def test_registration_pool_grew_by_three():
    d = _j("production_probation_registration_apply")
    res = d["apply_result"]
    assert res["pool_count_after"] - res["pool_count_before"] == 3


# -- 8-12. post-registration prod state audit --------------------------------
def test_prod_audit_all_ok():
    d = _j("post_registration_prod_state_audit")
    assert d["all_ok"] is True
    for name, ok in d["checks"].items():
        assert ok is True, f"audit check failed: {name}"


def test_prod_audit_each_target_probation_registered_sha_ok():
    d = _j("post_registration_prod_state_audit")
    pt = d["per_target"]
    assert TARGETS <= set(pt)
    for cid in TARGETS:
        e = pt[cid]
        assert e["in_prod_pool"] is True
        assert e["status_probation"] is True
        assert e["registration_event_present"] is True
        assert e["tarball_sha_matches_manifest"] is True


def test_prod_audit_manifest_event_count_matches_ledger():
    d = _j("post_registration_prod_state_audit")
    assert d["manifest_event_count"] == d["ledger_event_count"]
    assert d["checks"]["manifest_event_count_matches_ledger"] is True


def test_prod_audit_no_reference_leak_and_no_never_schedule():
    d = _j("post_registration_prod_state_audit")
    assert d["public_reference_in_queue"] == []
    assert d["public_reference_in_pool"] == []
    assert d["public_reference_as_parent"] == []
    assert d["never_schedule_in_queue"] == []


def test_prod_audit_no_forbidden_events():
    d = _j("post_registration_prod_state_audit")
    assert d["forbidden_event_hits"] in ([], {})
    assert d["checks"]["no_forbidden_events"] is True


# -- 13-14. controlled production tick runtime proof -------------------------
def test_controlled_prod_tick_runtime_proof_ok():
    d = _j("post_registration_controlled_prod_tick")
    assert d["runtime_proof_ok"] is True
    assert d["extraction_ok"] is True
    assert d["game_ran_without_resolution_failure"] is True
    # every target tarball must have been resolvable by the engine
    assert TARGETS <= set(d["extraction"])


def test_controlled_prod_tick_no_forbidden_and_tarballs_clean():
    d = _j("post_registration_controlled_prod_tick")
    s = d["safety"]
    assert s["no_forbidden_events_emitted"] is True
    assert s["forbidden_in_temp_ledger"] in ([], {})
    assert s["pass42_tarballs_unchanged_sha_match"] is True


# -- 15-16. promotion gate rerun (insufficient_evidence) ---------------------
def test_gate_dry_run_targets_insufficient_evidence():
    d = _j("promotion_gate_post_registration_dry_run")
    assert d["local"]["n_actionable"] == 0
    if d["production_state_available"]:
        assert d["production"]["n_actionable"] == 0
    # no target should carry an actionable recommendation
    for rec in d["local"]["target_recommendations"]:
        assert rec["action"] in {"insufficient_evidence", "stay_probation"}


def test_gate_apply_skipped_no_promotion():
    d = _j("promotion_gate_post_registration_apply")
    assert d["apply_skipped"] is True
    assert d["applied_changes"] == []
    g = d["guardrails"]
    assert g["no_candidate_promoted_event"] is True
    assert g["no_forbidden_events_in_ledger"] is True
    assert g["production_mutated"] is False
    assert g["local_ledger_mutated"] is False


# -- 17-19. scheduler / lifecycle follow-up audit ----------------------------
def test_scheduler_lifecycle_all_ok():
    d = _j("scheduler_lifecycle_after_prod_registration")
    assert d["all_ok"] is True
    for name, ok in d["checks"].items():
        assert ok is True, f"scheduler check failed: {name}"


def test_scheduler_targets_placed_and_deterministic():
    d = _j("scheduler_lifecycle_after_prod_registration")
    assert d["checks"]["deterministic_worklist"] is True
    assert set(d["targets"]["placed_in_worklist"]) == TARGETS


def test_scheduler_no_ref_or_never_schedule_or_demotion():
    d = _j("scheduler_lifecycle_after_prod_registration")
    assert d["public_refs_in_worklist"] == []
    assert d["never_schedule_in_worklist"] == []
    assert d["protected_demotions_detected"] == []
    assert d["active_cap_replacements_detected"] == []
    assert d["forbidden_events_present"] == []
    assert d["retirement_or_promotion_events_present"] == []


# -- 20. no Pass-44 script deletes or overwrites a tarball -------------------
def test_pass44_scripts_never_delete_or_overwrite_tarballs():
    for name in PASS44_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "unlink" not in blob, name
        assert "rmtree" not in blob, name
        assert "os.remove" not in blob, name
        assert "shutil.move" not in blob, name


# -- 21. no Pass-44 script emits a forbidden event --------------------------
def test_pass44_scripts_emit_no_forbidden_events():
    for name in PASS44_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        for et in FORBIDDEN:
            # the only allowed mention is inside a FORBIDDEN guard set, never an emit
            assert f"emit(EventType.{et}" not in blob, (name, et)
            assert f'emit("{et}"' not in blob, (name, et)


# -- 22. tournament ledger still refuses forbidden upload events -------------
def test_ledger_refuses_forbidden_upload_events(tmp_path):
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    for et in FORBIDDEN:
        with pytest.raises(PermissionError):
            ledger.emit(et, {"x": 1})
    assert len(ledger.load()) == 0


# -- 23. all 3 frozen workflows expected not-started ------------------------
def test_artifacts_record_start_application_not_started_expected():
    for name in ("post_republish_safety_preflight",
                 "deploy_image_candidate_availability",
                 "production_probation_registration_apply",
                 "post_registration_prod_state_audit"):
        d = _j(name)
        assert d.get("start_application_not_started_expected") is True


# -- 24. binding runtime proof linkage --------------------------------------
def test_attestation_defers_to_runtime_proof():
    # the attestation must NOT claim deploy-bakedness as proven by itself; the
    # binding proof is the controlled production tick (Part E).
    d = _j("republish_attestation")
    assert "binding_runtime_proof" in d
    tick = _j("post_registration_controlled_prod_tick")
    assert tick["runtime_proof_ok"] is True
