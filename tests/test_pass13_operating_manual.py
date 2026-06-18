"""ActiveGraph Pass 13 — operating manual + unknown_ex_tempo decomposition tests.

Covers (Part J), in small focused groups:

* operating manual exists and contains the required golden invariants;
* NEXT_AGENT_README exists and says no upload by default;
* the unknown_ex_tempo decomposition preserves ALL source episode IDs;
* the decomposition never invents card IDs (every signature id comes from the
  source archetype's evidence ids and actually appears in the opponent deck);
* refined meta-pool weights sum to 1.0 when the refined pool exists;
* the generic_unknown_ex_tempo fallback category is retained;
* raw replays remain gitignored;
* root main.py / deck.csv are byte-identical to the v1 baseline;
* no upload was performed / flagged this pass;
* the tarball validator is still referenced in the operating manual.

All tests read the lab's own artifacts/config; none run Kaggle or mutate root files.
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MANUAL = REPO_ROOT / "docs" / "ACTIVEGRAPH_LAB_OPERATING_MANUAL.md"
NEXT_AGENT = REPO_ROOT / "docs" / "NEXT_AGENT_README.md"
DECOMP_JSON = REPO_ROOT / "data" / "meta_replays" / "unknown_ex_tempo_decomposition.json"
REFINED_POOL = REPO_ROOT / "experiments" / "pass13_refined_meta_pool.yaml"
ARCHETYPES = REPO_ROOT / "data" / "meta_replays" / "archetypes.yaml"
DECKS_DIR = REPO_ROOT / "data" / "meta_replays" / "decks"
GITIGNORE = REPO_ROOT / ".gitignore"
BASELINE = REPO_ROOT / "data" / "baselines" / "v1_kaggle_349_8"

GENERIC_LABEL = "generic_unknown_ex_tempo"


def _load_decomp() -> dict:
    assert DECOMP_JSON.exists(), f"missing {DECOMP_JSON}"
    return json.loads(DECOMP_JSON.read_text())


def _unknown_evidence_ids() -> set[int]:
    doc = yaml.safe_load(ARCHETYPES.read_text())
    for a in doc.get("archetypes", []):
        if a.get("archetype_id") == "unknown_ex_tempo":
            return set(int(x) for x in a.get("evidence_card_ids", []))
    raise AssertionError("unknown_ex_tempo not found in archetypes.yaml")


# --- operating manual -------------------------------------------------------
def test_operating_manual_exists_with_invariants():
    assert MANUAL.exists(), "operating manual must exist"
    text = MANUAL.read_text()
    required = [
        "submitted tarball is the unit of truth",
        "main.py",
        "deck.csv",
        "60 card",
        "Live Kaggle scores drift",
        "No upload unless explicitly human-approved",
        "Upload checklist",
        "Lessons learned",
    ]
    for needle in required:
        assert needle.lower() in text.lower(), f"manual missing invariant: {needle!r}"


def test_manual_references_tarball_validator():
    text = MANUAL.read_text()
    assert "validate_candidate_tarball.py" in text, \
        "manual must reference scripts/validate_candidate_tarball.py"


def test_next_agent_readme_says_no_upload_by_default():
    assert NEXT_AGENT.exists(), "NEXT_AGENT_README must exist"
    text = NEXT_AGENT.read_text().lower()
    assert "operating_manual" in text or "operating manual" in text, \
        "next-agent readme must point to the operating manual"
    assert "upload" in text and "default" in text, \
        "next-agent readme must state no upload by default"


# --- decomposition integrity ------------------------------------------------
def test_decomposition_preserves_all_source_episode_ids():
    d = _load_decomp()
    source = set(d["source_episode_ids"])
    # Every source episode must be accounted for across the subfamilies.
    placed: set[int] = set()
    for sf in d["subfamilies"]:
        placed.update(sf.get("episode_ids", []))
    assert placed == source, (
        f"episodes lost/added in decomposition: source={source} placed={placed}"
    )
    # And every source episode must appear in the per-episode breakdown.
    per_ep = {e["episode_id"] for e in d["episodes"]}
    assert source <= per_ep, f"episodes missing from per-episode list: {source - per_ep}"


def test_decomposition_never_invents_card_ids():
    d = _load_decomp()
    evidence = _unknown_evidence_ids()
    assert d.get("no_invented_card_ids") is True
    # Every signature id used to label a subfamily must come from the source
    # archetype's evidence ids (no invented signature).
    for sf in d["subfamilies"]:
        for cid in sf.get("signature_card_ids", []):
            assert cid in evidence, f"signature id {cid} not in source evidence ids"
    # Every per-episode signature / top card id must actually exist in the real
    # opponent deck file (no fabricated cards in the fingerprint).
    for ep in d["episodes"]:
        if ep.get("error"):
            continue
        deck_path = REPO_ROOT / ep["deck_source"]
        deck_ids = {int(t) for t in deck_path.read_text().split() if t.strip().isdigit()}
        for c in ep.get("top_distinctive_cards", []):
            assert c["card_id"] in deck_ids, (
                f"episode {ep['episode_id']} top card {c['card_id']} not in its deck"
            )


def test_generic_fallback_category_retained():
    d = _load_decomp()
    labels = {sf["subfamily_id"] for sf in d["subfamilies"]}
    assert GENERIC_LABEL in labels, "generic_unknown_ex_tempo fallback must be retained"


def test_unresolved_episodes_land_in_generic():
    d = _load_decomp()
    generic = next(sf for sf in d["subfamilies"] if sf["subfamily_id"] == GENERIC_LABEL)
    assert sorted(d["unresolved_generic_episodes"]) == sorted(generic["episode_ids"]), \
        "unresolved episodes must equal the generic subfamily members"


# --- refined meta pool ------------------------------------------------------
def test_refined_weights_sum_to_one():
    if not REFINED_POOL.exists():
        pytest.skip("no refined pool created this pass")
    pool = yaml.safe_load(REFINED_POOL.read_text())
    weights = pool.get("evaluation_weights") or {}
    assert weights, "refined pool must define evaluation_weights"
    assert abs(sum(float(v) for v in weights.values()) - 1.0) < 1e-6, \
        f"refined weights must sum to 1.0, got {weights}"


def test_refined_pool_marks_confirmed_vs_provisional():
    if not REFINED_POOL.exists():
        pytest.skip("no refined pool created this pass")
    pool = yaml.safe_load(REFINED_POOL.read_text())
    split = pool.get("confirmed_vs_provisional") or {}
    assert "metal_ex_zacian_ramp" in (split.get("confirmed") or [])
    assert "water_kyogre_abomasnow_maxbelt" in (split.get("confirmed") or [])
    # The new subfamilies are provisional, not confirmed.
    prov = split.get("provisional") or []
    assert "mega_lucario_ex_tempo" in prov


# --- safety invariants ------------------------------------------------------
def test_raw_replays_remain_gitignored():
    text = GITIGNORE.read_text()
    assert "data/meta_replays/raw/*.json" in text, \
        "raw replay payloads must remain gitignored"
    assert "data/cards/*.csv" in text, "official card data must remain gitignored"


def test_root_files_unchanged_vs_v1_baseline():
    assert filecmp.cmp(REPO_ROOT / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to v1 baseline"
    assert filecmp.cmp(REPO_ROOT / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to v1 baseline"


def test_no_upload_performed_or_flagged_this_pass():
    pool = yaml.safe_load(REFINED_POOL.read_text())
    ac = (pool.get("controls") or {}).get("active_control") or {}
    assert ac.get("scores_refreshed_this_pass") is False, \
        "scores were not refreshed; flag must be explicitly false (honest)"
    # No 'upload' truthy flag anywhere in the decomposition artifact.
    raw = DECOMP_JSON.read_text().lower()
    assert "\"upload\": true" not in raw and "upload_performed: true" not in raw


def test_dry_run_queue_artifact_reports_no_upload():
    """Directly assert the canonical dry-run queue never claims an upload."""
    q = REPO_ROOT / "data" / "submission_queue.json"
    if not q.exists():
        pytest.skip("no dry-run queue artifact present")
    doc = json.loads(q.read_text())
    assert doc.get("upload_performed") is False, \
        "dry-run queue must report upload_performed=false"
    assert doc.get("auto_submit_enabled") is False, \
        "auto-submit must remain disabled"
    for entry in doc.get("queue") or []:
        assert entry.get("upload_performed") is False, \
            f"queued candidate {entry.get('candidate_id')} must not be uploaded"
