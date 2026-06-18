"""ActiveGraph Pass 10 — meta-calibrated evaluation + tempo playbook tests.

Covers (Part K):
* Part A score ingestion classifies ``combo_full_safety_v3_fixed`` as
  live-rejected and keeps v2 as the active control.
* replay deck extraction produces per-seat decks of confirmed ids only;
* the archetypes yaml never invents ids (blocked rows carry no card ids);
* meta-pool weighting + ``weighted_meta_score`` math;
* a candidate is NOT promotable while external archetypes are missing
  (coverage < 1.0 / incomplete eval);
* the dry-run queue excludes the live-rejected line and stays empty;
* the candidate tarball validator is mandatory (rejects junk);
* root ``main.py`` / ``deck.csv`` are unchanged vs the v1 baseline.

All tests read the lab's own artifacts; none run Kaggle or mutate root files.
"""

from __future__ import annotations

import importlib.util
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from ptcg_activegraph.meta.archetypes import (
    ArchetypeStatus,
    build_archetypes_yaml_obj,
)
from ptcg_activegraph.meta.scoring import (
    load_meta_pool,
    meta_pool_weights,
    weighted_meta_score,
)
from ptcg_activegraph.playbooks.schema import CONFIRMED_CARDS
from ptcg_activegraph.replays.kaggle_replay import load_replay

REPO = Path(__file__).resolve().parent.parent
META_POOL = REPO / "experiments" / "meta_pool.yaml"
EVAL_STATUS = REPO / "data" / "meta_replays" / "pass10_eval_status.json"
MANIFEST = REPO / "data" / "submissions" / "pass10_candidates_manifest.json"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"
RAW_REPLAY = REPO / "data" / "meta_replays" / "raw" / "80374966_self_mirror.json"
CANDIDATE_TARBALLS = REPO / "data" / "submissions" / "candidates_pass10"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
V1_BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
V2_CONTROL = REPO / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"
CONFIRMED_IDS = set(CONFIRMED_CARDS.values())


def _load_validator():
    """Import the stdlib-only candidate tarball validator script as a module."""
    path = REPO / "scripts" / "validate_candidate_tarball.py"
    spec = importlib.util.spec_from_file_location("_vct_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_pool() -> dict:
    return yaml.safe_load(META_POOL.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Part A — score ingestion / control selection
# --------------------------------------------------------------------------- #
def test_combo_fixed_classified_live_rejected():
    pool = _load_pool()
    rej = pool["controls"]["rejected"]
    assert rej["candidate_id"] == "combo_full_safety_v3_fixed"
    assert rej["decision"] == "live_rejected"
    assert rej["reason"] == "passed_validation_but_underperformed_live_control"
    assert rej["status"] == "complete"


def test_v2_remains_active_control_with_v1_discrepancy_noted():
    pool = _load_pool()
    ctrl = pool["controls"]
    assert ctrl["active_control"]["candidate_id"] == "deck_energy_trim_light"
    # The v1/v2 live discrepancy (v1 > v2) must be visible, not hidden.
    assert ctrl["reference_v1"]["live_public_score"] > \
        ctrl["active_control"]["live_public_score"]


# --------------------------------------------------------------------------- #
# Replay deck extraction
# --------------------------------------------------------------------------- #
def test_extracted_replay_decks_use_confirmed_ids_only():
    decks = sorted(DECKS_DIR.glob("*_deck.csv"))
    assert decks, "expected at least one extracted replay deck"
    for deck in decks:
        ids = [int(x) for x in deck.read_text().split() if x.strip()]
        assert ids, f"{deck.name} should not be empty"
        unknown = sorted(set(ids) - CONFIRMED_IDS)
        assert not unknown, f"{deck.name} contains unconfirmed ids {unknown}"


# --------------------------------------------------------------------------- #
# Archetype yaml — never invent ids
# --------------------------------------------------------------------------- #
def test_archetype_yaml_blocked_rows_carry_no_ids():
    obj = build_archetypes_yaml_obj()
    arch = {a["key"]: a for a in obj["archetypes"]}
    for key in ("metal_ex_zacian_ramp", "water_kyogre_abomasnow_maxbelt"):
        a = arch[key]
        assert a["status"] == ArchetypeStatus.BLOCKED.value
        assert a["card_ids"] == []
        assert a["card_ids_status"] == "unknown"


def test_archetype_yaml_no_invented_ids_anywhere():
    obj = build_archetypes_yaml_obj()
    for a in obj["archetypes"]:
        unknown = sorted(set(a["card_ids"]) - CONFIRMED_IDS)
        assert not unknown, f"{a['key']} lists unconfirmed ids {unknown}"


# --------------------------------------------------------------------------- #
# Meta-pool weighting + weighted_meta_score
# --------------------------------------------------------------------------- #
def test_meta_pool_weights_loaded():
    pool = load_meta_pool(META_POOL)
    weights = meta_pool_weights(pool)
    assert set(weights) == {
        "water_kyogre_abomasnow_mirror_passive",
        "metal_ex_zacian_ramp",
        "water_kyogre_abomasnow_maxbelt",
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_weighted_meta_score_full_coverage():
    weights = {"a": 0.5, "b": 0.5}
    winrates = {"a": 0.6, "b": 0.4}
    res = weighted_meta_score(winrates, weights, available={"a", "b"})
    assert res["complete"] is True
    assert abs(res["coverage"] - 1.0) < 1e-9
    assert abs(res["weighted_meta_score"] - 0.5) < 1e-9


def test_weighted_meta_score_partial_coverage_is_incomplete():
    weights = {"a": 0.34, "b": 0.33, "c": 0.33}
    winrates = {"a": 0.7}  # only the mirror has data
    res = weighted_meta_score(winrates, weights, available={"a"})
    assert res["complete"] is False
    assert res["coverage"] < 1.0
    assert set(res["missing_archetypes"]) == {"b", "c"}
    # score over the single available archetype equals its own win rate.
    assert abs(res["weighted_meta_score"] - 0.7) < 1e-9


def test_weighted_meta_score_none_when_no_data():
    res = weighted_meta_score({}, {"a": 1.0}, available=set())
    assert res["weighted_meta_score"] is None
    assert res["coverage"] == 0.0
    assert res["complete"] is False


# --------------------------------------------------------------------------- #
# Not promotable while external archetypes are missing
# --------------------------------------------------------------------------- #
def test_eval_incomplete_and_nothing_promotable():
    status = json.loads(EVAL_STATUS.read_text(encoding="utf-8"))
    assert status["mode"] == "scout_only"
    assert status["eval_complete"] is False
    assert status["games_runnable_locally"] is False
    assert status["weighted_meta_score"] is None
    assert status["promotable"] == []
    # Every candidate is explicitly not promotable.
    assert status["candidates"], "expected candidate rows in eval status"
    assert all(c["promotable"] is False for c in status["candidates"])


def test_blocked_externals_recorded_in_pool_coverage():
    pool = _load_pool()
    cov = pool["coverage"]
    assert set(cov["blocked_archetypes"]) == {
        "metal_ex_zacian_ramp",
        "water_kyogre_abomasnow_maxbelt",
    }
    assert cov["eval_complete"] is False
    assert cov["weight_missing"] > 0


# --------------------------------------------------------------------------- #
# Queue excludes the live-rejected line and stays empty
# --------------------------------------------------------------------------- #
def test_queue_action_is_none_and_excludes_live_rejected():
    status = json.loads(EVAL_STATUS.read_text(encoding="utf-8"))
    assert status["queue_action"].startswith("none")
    ids = {c["id"] for c in status["candidates"]}
    assert "combo_full_safety_v3_fixed" not in ids


# --------------------------------------------------------------------------- #
# Candidate manifest — validator mandatory, unconfirmed ids blocked
# --------------------------------------------------------------------------- #
def test_manifest_built_candidates_are_validated():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    built = manifest["built"]
    assert built, "expected built candidates"
    assert all(c["validated"] is True for c in built)
    assert manifest["all_built_validated"] is True


def test_manifest_blocks_unconfirmed_id_decks():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    blocked_ids = {c["id"] for c in manifest["blocked"]}
    assert {"deck_maximum_belt", "deck_cyrano_waitress", "deck_metal_zacian"} \
        <= blocked_ids
    for c in manifest["blocked"]:
        assert c["validated"] is False
        assert c["reason"]


# --------------------------------------------------------------------------- #
# Root immutability
# --------------------------------------------------------------------------- #
def test_root_main_and_deck_unchanged_vs_v1_baseline():
    import filecmp
    assert (REPO / "main.py").exists() and (V1_BASELINE / "main.py").exists()
    assert filecmp.cmp(REPO / "main.py", V1_BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(REPO / "deck.csv", V1_BASELINE / "deck.csv", shallow=False)


# --------------------------------------------------------------------------- #
# Behavioral: replay extraction from the step-0 submitted-deck action
# --------------------------------------------------------------------------- #
def test_replay_submitted_decks_extracted_from_step0_confirmed_only():
    if not RAW_REPLAY.exists():
        pytest.skip("raw self-mirror replay not present")
    replay = load_replay(RAW_REPLAY)
    decks = replay.submitted_decks()
    assert decks, "replay should yield at least one seat's submitted deck"
    for seat, ids in decks.items():
        assert len(ids) == 60, f"seat {seat} deck should be 60 cards, got {len(ids)}"
        unknown = sorted(set(ids) - CONFIRMED_IDS)
        assert not unknown, f"seat {seat} extracted unconfirmed ids {unknown}"


# --------------------------------------------------------------------------- #
# Behavioral: tarball validator is mandatory (negative + positive control)
# --------------------------------------------------------------------------- #
def test_validator_rejects_junk_tarball(tmp_path):
    vct = _load_validator()
    junk = tmp_path / "junk.tar.gz"
    bad = tmp_path / "main.py"
    bad.write_text("print('not an agent')\n", encoding="utf-8")
    with tarfile.open(junk, "w:gz") as tf:
        tf.add(bad, arcname="main.py")  # missing deck.csv + no valid agent
    assert vct.validate(str(junk)) == 1


def test_validator_accepts_a_real_built_candidate():
    vct = _load_validator()
    tarballs = sorted(CANDIDATE_TARBALLS.glob("*.tar.gz"))
    if not tarballs:
        pytest.skip("no built candidate tarballs present")
    assert vct.validate(str(tarballs[0])) == 0


# --------------------------------------------------------------------------- #
# Behavioral: Part A event ingestion classifies the live-rejected line
# --------------------------------------------------------------------------- #
def test_lab_events_record_combo_fixed_as_live_rejected():
    if not LAB_EVENTS.exists():
        pytest.skip("lab events log not present")
    rejected = []
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event_type") != "CandidateRejected":
            continue
        if (ev.get("payload") or {}).get("candidate_id") == \
                "combo_full_safety_v3_fixed":
            rejected.append(ev["payload"])
    assert rejected, "expected a CandidateRejected event for combo_full_safety_v3_fixed"
    p = rejected[-1]
    assert p["reason"] == "passed_validation_but_underperformed_live_control"
    assert float(p["live_score"]) < float(p["control_score"])
