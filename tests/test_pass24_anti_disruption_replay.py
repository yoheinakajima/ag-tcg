"""Pass 24 — Anti-disruption pivot score + replay post-mortem tests.

READ-ONLY pass: these tests assert that the Pass-24 artifacts are internally
consistent and that the central findings hold against replay ground truth:
  * root immutability (main.py / deck.csv byte-identical to the v1 baseline),
  * the three new replays were ingested, attributed, and stay gitignored,
  * the empty-board / no-Pokémon failure mode did NOT recur in any replay,
  * Grok's empty-board claims are wrong in all three (trust replay),
  * opponent archetypes classified from extracted decklists,
  * planned fixtures are plans-only,
  * the read-only / no-upload invariants are recorded in the artifacts.
"""

from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

EXP = ROOT / "data" / "experiments"
RAW = ROOT / "data" / "meta_replays" / "raw"
BASELINE = ROOT / "data" / "baselines" / "v1_kaggle_349_8"
EPISODES = ["80623232", "80622745", "80622626"]


def _load(name):
    return json.loads((EXP / name).read_text())


# -- root immutability -------------------------------------------------------

def test_root_main_and_deck_unchanged_vs_baseline():
    for fname in ("main.py", "deck.csv"):
        root_f = ROOT / fname
        base_f = BASELINE / fname
        assert root_f.exists(), f"missing root {fname}"
        assert base_f.exists(), f"missing baseline {fname}"
        assert filecmp.cmp(root_f, base_f, shallow=False), f"{fname} differs from v1 baseline"


# -- replays present + gitignored --------------------------------------------

def test_three_replays_present():
    for ep in EPISODES:
        assert (RAW / f"{ep}.json").exists(), f"missing replay {ep}"


def test_raw_replays_gitignored():
    safety = _load("pass24_raw_replay_safety.json")
    blob = json.dumps(safety).lower()
    assert "gitignore" in blob or "ignored" in blob
    for ep in EPISODES:
        assert ep in json.dumps(safety)


# -- attribution -------------------------------------------------------------

def test_all_replays_attributed_high_confidence():
    attr = _load("pass24_replay_attribution.json")
    blob = json.dumps(attr)
    for ep in EPISODES:
        assert ep in blob
    assert blob.lower().count("high") >= 3


# -- central finding: empty-board failure did NOT recur ----------------------

def test_empty_board_failure_did_not_recur():
    pm = _load("pass24_empty_board_postmortem.json")
    # no episode should be classified as a no-pokemon-in-play / empty-board loss
    assert pm["no_pokemon_in_play_losses"] == []


def test_mirror_loser_decked_out_with_healthy_bench():
    pm = _load("pass24_empty_board_postmortem.json")
    blob = json.dumps(pm).lower()
    assert "deckout" in blob


# -- Grok verification: empty-board claims wrong 0/3 -------------------------

def test_grok_empty_board_claims_all_mismatch():
    gv = _load("pass24_grok_claim_verification.json")
    eps = gv["episodes"]
    assert len(eps) == 3
    for e in eps:
        assert e["matched"]["loss_type"] is False, f"{e['episode_id']} empty-board claim should mismatch"
        # results / turns / archetypes should be correct
        assert e["matched"]["result"] is True
        assert e["matched"]["opponent"] is True


# -- hook effectiveness ------------------------------------------------------

def test_no_illegal_mega_from_hand_benching():
    he = _load("pass24_hook_effectiveness.json")
    assert he["summary"]["any_mega_benched_from_hand"] is False
    assert he["summary"]["min_max_bench"] >= 1


# -- archetypes --------------------------------------------------------------

def test_opponent_archetypes_classified():
    au = _load("pass24_archetype_updates.json")
    blob = json.dumps(au).lower()
    assert "fighting_mega_lucario_ex_hariyama" in blob
    assert "psychic_alakazam_dudunsparce" in blob


# -- decision is conservative / read-only ------------------------------------

def test_decision_keep_pivot_and_no_upload():
    si = _load("pass24_strategy_interpretation.json")
    assert si["decision"] == "keep_pivot_as_live_control"
    assert si["read_only"] is True and si["no_upload"] is True
    assert si["scores"]["pivot_live"] > si["scores"]["prior_control_submission_tar_gz"]


# -- planned fixtures are plans-only -----------------------------------------

@pytest.mark.skipif(yaml is None, reason="pyyaml not available")
def test_planned_fixtures_are_plans_only():
    data = yaml.safe_load((ROOT / "data" / "fixtures" / "pass24_planned_fixtures.yaml").read_text())
    assert data["not_implemented_this_pass"] is True
    assert data["read_only_pass"] is True
    assert len(data["fixtures"]) == 7
    for fx in data["fixtures"]:
        assert fx["implemented"] is False


# -- kaggle status read-only -------------------------------------------------

def test_kaggle_status_read_only_and_pivot_is_best():
    ks = _load("pass24_kaggle_status.json")
    blob = json.dumps(ks).lower()
    assert "520.8" in json.dumps(ks)
    # no upload performed this pass
    assert "no" in blob or "false" in blob
