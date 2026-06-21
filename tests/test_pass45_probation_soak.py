"""PASS 45 — Production probation soak + promotion-readiness audit (READ-ONLY).

Validates the honest artifacts produced by Parts A–H: the soak safety preflight, the
scheduled-daemon soak / tick-cadence audit, the per-target probation evidence audit,
the runtime failure / quarantine screen, the promotion-gate production DRY-RUN, the
scheduler / lifecycle soak audit, the controlled-tick DECISION (default skip), and the
consolidated readiness table.

HARD invariants asserted: root main.py/deck.csv byte-identical to baseline; no
forbidden events (CandidatePromoted / SubmissionQueued / SubmissionUploaded /
KaggleScoreUpdated) anywhere in scope; no Pass-45 script emits a forbidden /
status-change event, deletes/overwrites a tarball, or starts the root workflow; no
public-reference leakage into pool/queue/worklist; no production mutation and no
upload; the gate dry-run never enters its apply path; quarantine requires COMPLETE
hard-failure evidence (decisive==0 alone never quarantines); and the soak honestly
yields probation_soak_continue. Pure artifact reads + ledger guard checks.
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
STATUS_CHANGE = "CandidateStatusChanged"

PASS45_SCRIPTS = [
    "build_pass45_soak_safety_preflight.py",
    "build_pass45_scheduled_daemon_soak_audit.py",
    "build_pass45_probation_evidence_audit.py",
    "build_pass45_probation_failure_screen.py",
    "build_pass45_promotion_gate_prod_dry_run.py",
    "build_pass45_scheduler_lifecycle_soak_audit.py",
    "build_pass45_optional_controlled_tick_decision.py",
    "build_pass45_probation_readiness_table.py",
]


def _j(name: str) -> dict:
    return json.loads((EXP / f"pass45_{name}.json").read_text(encoding="utf-8"))


# -- 1-2. root immutability (fresh filecmp) ---------------------------------
def test_root_main_py_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_csv_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# -- 3-4. Part A soak safety preflight --------------------------------------
def test_part_a_preflight_safe_and_not_stopped():
    d = _j("soak_safety_preflight")
    assert d["preflight_safe"] is True
    assert d["stop_required"] is False
    assert d["upload_performed"] is False
    assert d["production_mutation_performed_here"] is False
    assert d["promotion_performed"] is False
    assert d["generation_performed"] is False
    assert d["deck_mutation_performed"] is False
    assert d["tarball_mutation"] is False


def test_part_a_root_immutability_is_freshly_filecmp_derived():
    d = _j("soak_safety_preflight")
    fresh = d["root_immutability_fresh"]
    # the critical root check must be derived live (filecmp), never inherited/hardcoded
    assert fresh["filecmp_derived"] is True
    assert fresh["main_py_byte_identical"] is True
    assert fresh["deck_csv_byte_identical"] is True
    assert fresh["cross_check_pass43"] is True


def test_part_a_shared_health_green():
    d = _j("soak_safety_preflight")
    shared = d["shared_pass43_preflight"]
    assert shared.get("prod_health_healthy") is True
    assert shared.get("prod_health_hard_failures") == []


# -- 5-7. Part B scheduled-daemon soak audit --------------------------------
def test_part_b_soak_healthy_and_cadence_regular():
    d = _j("scheduled_daemon_soak_audit")
    assert d["soak_healthy"] is True
    assert d["cadence_regular"] is True
    assert d["read_only"] is True
    assert d["production_mutated"] is False
    assert d["tick_executed"] is False


def test_part_b_no_forbidden_and_manifest_lockstep():
    d = _j("scheduled_daemon_soak_audit")
    assert d["forbidden_events_present"] == []
    assert d["checks"]["no_forbidden_events"] is True
    assert d["checks"]["manifest_event_count_matches_ledger"] is True


def test_part_b_targets_accruing_placement_evidence():
    d = _j("scheduled_daemon_soak_audit")
    assert d["targets_any_accruing"] is True
    pt = d["probation_targets"]
    assert TARGETS <= set(pt)
    for cid in TARGETS:
        assert pt[cid]["total_games"] >= 0


# -- 8-10. Part C probation evidence audit ----------------------------------
def test_part_c_all_targets_in_prod_pool():
    d = _j("probation_evidence_audit")
    assert d["targets_all_in_prod_pool"] is True
    assert d["read_only"] is True
    assert d["production_mutated"] is False


def test_part_c_no_target_promotion_ready():
    d = _j("probation_evidence_audit")
    assert d["any_target_promotion_ready"] is False
    assert d["all_targets_insufficient_or_stay"] is True


def test_part_c_each_target_has_sample_gaps_and_status():
    d = _j("probation_evidence_audit")
    for cid in TARGETS:
        t = d["per_target"][cid]
        assert t["in_prod_pool"] is True
        assert t["status"] == "probation"
        assert t["promotion_ready"] is False
        gaps = t["sample_size_gaps"]
        # honest "distance to threshold": something still needed on the big gates
        assert gaps["total_games"]["still_needed"] > 0
        assert gaps["decisive_games"]["still_needed"] > 0


# -- 11-12. Part D runtime failure / quarantine screen ----------------------
def test_part_d_no_quarantine_warranted():
    d = _j("probation_failure_screen")
    assert d["any_quarantine_warranted"] is False
    assert d["quarantine_emitted"] is False
    assert d["production_mutated"] is False


def test_part_d_decisive_zero_never_auto_quarantines():
    d = _j("probation_failure_screen")
    assert d["no_false_quarantine_from_small_sample"] is True
    for cid, t in d["per_target"].items():
        # a target may have decisive==0, but that alone must never warrant quarantine
        if t["decisive_zero"] and not (t["complete_hardfail_evidence"]
                                       or t["high_rate_hardfail_evidence"]):
            assert t["quarantine_warranted"] is False, cid


# -- 13-14. Part E promotion gate DRY-RUN only ------------------------------
def test_part_e_gate_is_dry_run_only_no_apply():
    d = _j("promotion_gate_prod_dry_run")
    assert d["mode"] == "dry_run_only"
    assert d["apply_invoked"] is False
    assert d["emitted_events"] == 0
    assert d["mutated"] is False
    assert d["production_mutated"] is False
    assert d["no_forbidden_events_in_local_ledger"] is True


def test_part_e_no_target_actionable():
    d = _j("promotion_gate_prod_dry_run")
    assert d["any_target_actionable"] is False
    assert d["local"]["n_actionable"] == 0
    if d["production_state_available"]:
        assert d["production"]["n_actionable"] == 0
        for rec in d["production"]["target_recommendations"]:
            assert rec["action"] in {"insufficient_evidence", "stay_probation"}
    for rec in d["local"]["target_recommendations"]:
        assert rec["action"] in {"insufficient_evidence", "stay_probation"}


# -- 15-17. Part F scheduler / lifecycle soak audit -------------------------
def test_part_f_scheduler_all_ok():
    d = _j("scheduler_lifecycle_soak_audit")
    assert d["all_ok"] is True
    for name, ok in d["checks"].items():
        assert ok is True, f"scheduler check failed: {name}"
    assert d["production_mutated"] is False


def test_part_f_targets_placed_and_deterministic():
    d = _j("scheduler_lifecycle_soak_audit")
    assert d["checks"]["deterministic_worklist"] is True
    assert set(d["targets"]["placed_in_worklist"]) == TARGETS
    assert set(d["targets"]["probation_status"]) == TARGETS


def test_part_f_no_ref_or_never_schedule_or_demotion():
    d = _j("scheduler_lifecycle_soak_audit")
    assert d["public_refs_in_worklist"] == []
    assert d["never_schedule_in_worklist"] == []
    assert d["protected_demotions_detected"] == []
    assert d["active_cap_replacements_detected"] == []
    assert d["forbidden_events_present"] == []
    assert d["retirement_or_promotion_events_present"] == []


# -- 18. Part G controlled-tick decision (skip, daemon live) ----------------
def test_part_g_skips_tick_because_daemon_live():
    d = _j("optional_controlled_tick_decision")
    assert d["controlled_tick_performed"] is False
    assert d["production_mutated"] is False
    assert d["decision"] == "skip_daemon_live"
    assert d["cron_live"] is True


# -- 19-20. Part H readiness table ------------------------------------------
def test_part_h_implied_decision_is_soak_continue():
    d = _j("probation_readiness_table")
    assert d["implied_decision"] == "probation_soak_continue"
    assert d["any_promotion_ready"] is False
    assert d["any_quarantine_warranted"] is False
    assert d["all_targets_probation"] is True


def test_part_h_rows_cover_all_targets():
    d = _j("probation_readiness_table")
    seen = {r["candidate_id"] for r in d["rows"]}
    assert TARGETS == seen
    for r in d["rows"]:
        assert r["status"] == "probation"
        assert r["promotion_ready"] is False


# -- 21. no Pass-45 script deletes/overwrites a tarball ---------------------
def test_pass45_scripts_never_delete_or_overwrite_tarballs():
    for name in PASS45_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "unlink" not in blob, name
        assert "rmtree" not in blob, name
        assert "os.remove" not in blob, name
        assert "shutil.move" not in blob, name


# -- 22. no Pass-45 script emits a forbidden / status-change event ----------
def test_pass45_scripts_emit_no_forbidden_or_status_events():
    for name in PASS45_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        for et in FORBIDDEN | {STATUS_CHANGE}:
            assert f"emit(EventType.{et}" not in blob, (name, et)
            assert f'emit("{et}"' not in blob, (name, et)
            assert f".emit('{et}'" not in blob, (name, et)


# -- 23. no Pass-45 script starts the root Start application workflow --------
def test_pass45_scripts_never_start_root_workflow():
    # the charter forbids starting the root entrypoint. The only programmatic way
    # to start a workflow here is restart_workflow; a docstring mention of the
    # workflow name, or a string literal inspecting the deploy config (Part B's
    # "must NOT be root main.py" check), is allowed.
    for name in PASS45_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "restart_workflow" not in blob, name
        assert "python3 main.py" not in blob, name
        assert "subprocess.run([\"python3\", \"main.py\"" not in blob, name


# -- 24. tournament ledger still refuses forbidden upload events ------------
def test_ledger_refuses_forbidden_upload_events(tmp_path):
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    for et in FORBIDDEN:
        with pytest.raises(PermissionError):
            ledger.emit(et, {"x": 1})
    assert len(ledger.load()) == 0


# -- 25. consistency: every part agrees production was never mutated ---------
def test_all_parts_agree_no_production_mutation():
    for name in ("soak_safety_preflight", "scheduled_daemon_soak_audit",
                 "probation_evidence_audit", "probation_failure_screen",
                 "promotion_gate_prod_dry_run", "scheduler_lifecycle_soak_audit",
                 "optional_controlled_tick_decision"):
        d = _j(name)
        mutated = d.get("production_mutated",
                        d.get("production_mutation_performed_here"))
        assert mutated is False, name
