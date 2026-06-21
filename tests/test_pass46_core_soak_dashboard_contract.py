"""PASS 46 — core tournament soak monitor + dashboard data contract (READ-ONLY).

Validates the honest artifacts produced by the Pass-46 read-only soak monitor and the
dashboard-contract support: the core soak snapshot (root/deploy safety + daemon soak),
the probation promotion-readiness refresh, the promotion-gate production DRY-RUN, the
scheduler/lifecycle audit, and the dashboard data contract + its secret-safe check.

HARD invariants asserted: root main.py/deck.csv byte-identical to baseline; no forbidden
events (CandidatePromoted / SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated)
anywhere in scope; no Pass-46 script emits a forbidden/status-change event, deletes or
overwrites a tarball, or starts the root workflow; no public-reference leakage into the
worklist; no production mutation and no upload; the gate dry-run never enters its apply
path; quarantine requires COMPLETE hard-failure evidence (decisive==0 alone never
quarantines); the soak honestly yields probation-soak-continue; and the dashboard data
contract leaks NO secret/bucket/credential value.
"""
from __future__ import annotations

import filecmp
import json
import re
from pathlib import Path

import pytest

from ptcg_activegraph.tournament.ledger import TournamentLedger

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
SCRIPTS = REPO / "scripts"
DOC = REPO / "docs" / "DASHBOARD_DATA_CONTRACT.md"

TARGETS = {
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
}
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
STATUS_CHANGE = "CandidateStatusChanged"

PASS46_SCRIPTS = [
    "build_pass46_core_soak_snapshot.py",
    "build_pass46_probation_readiness_refresh.py",
    "build_pass46_promotion_gate_dry_run.py",
    "build_pass46_scheduler_lifecycle_audit.py",
    "build_pass46_dashboard_data_contract_check.py",
]


def _j(name: str) -> dict:
    return json.loads((EXP / f"pass46_{name}.json").read_text(encoding="utf-8"))


# -- 1-2. root immutability (fresh filecmp) --------------------------------
def test_root_main_py_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_csv_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# -- 3-6. core soak snapshot -----------------------------------------------
def test_core_soak_healthy_and_read_only():
    d = _j("core_soak_snapshot")
    assert d["soak_healthy"] is True
    assert d["daemon_attention_required"] is False
    assert d["read_only"] is True
    assert d["production_mutated"] is False
    assert d["tick_executed"] is False
    assert d["start_application_started"] is False


def test_core_soak_root_and_deploy_safety():
    d = _j("core_soak_snapshot")
    assert d["root_safety"]["root_unchanged"] is True
    assert d["root_safety"]["filecmp_derived"] is True
    assert d["deployment_safety"]["all_ok"] is True
    assert d["deployment_safety"]["deployment_not_root_main"] is True


def test_core_soak_integrity_checks_pass():
    d = _j("core_soak_snapshot")
    c = d["checks"]
    assert c["ticks_started_equal_finished"] is True
    assert c["hardfail_rate_within_budget"] is True
    assert c["all_events_no_upload"] is True
    assert c["no_forbidden_events_in_scope"] is True
    assert c["manifest_event_count_matches_ledger"] is True
    assert d["no_upload_violations"] == 0
    assert d["forbidden_events_present"] == []


def test_core_soak_targets_accruing():
    d = _j("core_soak_snapshot")
    assert d["targets_any_accruing"] is True
    assert TARGETS <= set(d["probation_targets"])
    assert d["game_count"]["finished"] > 0


# -- 7-9. probation readiness refresh --------------------------------------
def test_readiness_all_targets_in_pool_none_ready():
    d = _j("probation_readiness_refresh")
    assert d["targets_all_in_prod_pool"] is True
    assert d["any_target_promotion_ready"] is False
    assert d["all_targets_insufficient_or_stay"] is True
    assert d["production_mutated"] is False


def test_readiness_no_quarantine_and_decisive_zero_safe():
    d = _j("probation_readiness_refresh")
    assert d["any_quarantine_warranted"] is False
    assert d["no_false_quarantine_from_small_sample"] is True
    for cid, t in d["per_target"].items():
        if t.get("decisive_zero") and not (t.get("complete_hardfail_evidence")
                                           or t.get("high_rate_hardfail_evidence")):
            assert t["quarantine_warranted"] is False, cid


def test_readiness_each_target_has_distance_to_thresholds():
    d = _j("probation_readiness_refresh")
    for cid in TARGETS:
        t = d["per_target"][cid]
        assert t["in_prod_pool"] is True
        assert t["status"] == "probation"
        assert t["promotion_ready"] is False
        dist = t["distance_to_thresholds"]
        # honest distance: still something to accrue on the big sample-size gates
        assert dist["total_games"] > 0
        assert dist["decisive_games"] > 0


# -- 10-11. promotion gate DRY-RUN only ------------------------------------
def test_gate_is_dry_run_only_no_apply():
    d = _j("promotion_gate_dry_run")
    assert d["mode"] == "dry_run_only"
    assert d["apply_invoked"] is False
    assert d["emitted_events"] == 0
    assert d["mutated"] is False
    assert d["production_mutated"] is False
    assert d["no_forbidden_events_in_local_ledger"] is True


def test_gate_no_target_actionable():
    d = _j("promotion_gate_dry_run")
    assert d["any_target_actionable"] is False
    assert d["local"]["n_actionable"] == 0
    if d["production_state_available"]:
        assert d["production"]["n_actionable"] == 0
        for rec in d["production"]["target_recommendations"]:
            assert rec["action"] in {"insufficient_evidence", "stay_probation"}
    for rec in d["local"]["target_recommendations"]:
        assert rec["action"] in {"insufficient_evidence", "stay_probation"}


# -- 12-14. scheduler / lifecycle audit ------------------------------------
def test_scheduler_all_ok():
    d = _j("scheduler_lifecycle_audit")
    assert d["all_ok"] is True
    for name, ok in d["checks"].items():
        assert ok is True, f"scheduler check failed: {name}"
    assert d["production_mutated"] is False


def test_scheduler_targets_placed_and_deterministic():
    d = _j("scheduler_lifecycle_audit")
    assert d["checks"]["deterministic_worklist"] is True
    assert set(d["targets"]["placed_in_worklist"]) == TARGETS
    assert set(d["targets"]["probation_status"]) == TARGETS


def test_scheduler_no_ref_never_schedule_or_demotion():
    d = _j("scheduler_lifecycle_audit")
    assert d["public_refs_in_worklist"] == []
    assert d["never_schedule_in_worklist"] == []
    assert d["protected_demotions_detected"] == []
    assert d["active_cap_replacements_detected"] == []
    assert d["forbidden_events_present"] == []
    assert d["retirement_or_promotion_events_present"] == []


# -- 15-17. dashboard data contract + check --------------------------------
def test_contract_doc_exists_and_check_all_ok():
    d = _j("dashboard_data_contract_check")
    assert d["contract_doc_exists"] is True
    assert d["all_ok"] is True
    assert d["dashboard_ready"] is True
    assert d["production_mutated"] is False
    assert d["object_bodies_downloaded"] is False


def test_contract_contains_no_secrets():
    d = _j("dashboard_data_contract_check")
    assert d["contains_no_secrets"] is True
    scan = d["secret_scan"]
    assert scan["clean"] is True
    assert scan["env_value_leaks_by_name"] == []
    assert scan["pattern_hits"] == []


def test_contract_keys_match_prod_where_verifiable():
    d = _j("dashboard_data_contract_check")
    assert d["documented_missing_in_prod"] == []
    assert d["keys_match_status"] in {"matched", "unverified"}
    assert d["checks"]["documented_keys_match_prod_where_verifiable"] is True


def test_contract_doc_has_no_bucket_or_token_strings():
    # an independent (non-script) scan of the committed doc text
    text = DOC.read_text(encoding="utf-8")
    assert not re.search(r"replit-objstore-[0-9a-fA-F-]{8,}", text)
    assert not re.search(r"\b[0-9a-f]{32,}\b", text)
    assert not re.search(r"\bAKIA[0-9A-Z]{12,}\b", text)


def test_contract_doc_surfaces_required_caveats():
    text = DOC.read_text(encoding="utf-8")
    assert "read-only" in text.lower()
    assert "NOT a Kaggle leaderboard" in text
    assert "bulk-read" in text.lower()
    assert "TOURNAMENT_STORAGE_PREFIX" in text


# -- 18. no Pass-46 script deletes/overwrites a tarball --------------------
def test_pass46_scripts_never_delete_or_overwrite_tarballs():
    for name in PASS46_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "unlink" not in blob, name
        assert "rmtree" not in blob, name
        assert "os.remove" not in blob, name
        assert "shutil.move" not in blob, name


# -- 19. no Pass-46 script emits a forbidden / status-change event ---------
def test_pass46_scripts_emit_no_forbidden_or_status_events():
    for name in PASS46_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        for et in FORBIDDEN | {STATUS_CHANGE}:
            assert f"emit(EventType.{et}" not in blob, (name, et)
            assert f'emit("{et}"' not in blob, (name, et)
            assert f".emit('{et}'" not in blob, (name, et)


# -- 20. no Pass-46 script starts the root Start application workflow -------
def test_pass46_scripts_never_start_root_workflow():
    for name in PASS46_SCRIPTS:
        blob = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "restart_workflow" not in blob, name
        assert "python3 main.py" not in blob, name


# -- 21. tournament ledger still refuses forbidden upload events -----------
def test_ledger_refuses_forbidden_upload_events(tmp_path):
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    for et in FORBIDDEN:
        with pytest.raises(PermissionError):
            ledger.emit(et, {"x": 1})
    assert len(ledger.load()) == 0


# -- 22. consistency: every part agrees production was never mutated -------
def test_all_parts_agree_no_production_mutation():
    for name in ("core_soak_snapshot", "probation_readiness_refresh",
                 "promotion_gate_dry_run", "scheduler_lifecycle_audit",
                 "dashboard_data_contract_check"):
        d = _j(name)
        assert d.get("production_mutated") is False, name
