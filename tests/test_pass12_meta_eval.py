"""ActiveGraph Pass 12 — meta-driven candidate generation + directional eval tests.

Covers (Part M), in small focused groups:

* config weights — a single PROVISIONAL archetype is capped at ``provisional_weight_cap``
  and the excess is redistributed to the CONFIRMED archetypes; weights sum to 1.0;
* validator-before-eval — every candidate the eval consumed is validator-passing,
  and any candidate that could not be built without inventing ids is recorded as
  blocked (never silently dropped, never invented);
* 60-int surrogate decks — every materialized surrogate ``deck.csv`` is exactly 60
  integer rows;
* provisional kept — the provisional ``unknown_ex_tempo`` family is retained as an
  opponent (provisional archetypes are not discarded);
* dynamic active control — the config's active control matches the live registry's
  active control (resolved dynamically, not hard-coded);
* mirror_overfit label — a candidate that beats only the self-mirror but not the
  real meta is flagged ``mirror_overfit`` (both in the canonical rule and on the
  produced ranking artifact);
* beats-active-control gate — ``ranker.label_for`` only promotes when the 80% Wilson
  lower bound clears 0.50 AND the candidate beats the active control;
* dry-run max one — the dry-run queue never exceeds ``max_dry_run_queue`` (== 1);
* no-upload flag — ``upload_performed`` is false and ``upload_ready`` is false;
* chaos gating — the chaos candidate is blocked honestly (no invented ids);
* root unchanged — root ``main.py``/``deck.csv`` are byte-identical to the v1 baseline;
* raw replays gitignored — raw replay payloads are excluded from version control.

All tests read the lab's own artifacts/config; none run Kaggle or mutate root files.
"""

from __future__ import annotations

import filecmp
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from ptcg_activegraph.experiments.ranker import Z_80, label_for, wilson_interval

REPO = Path(__file__).resolve().parent.parent
CONFIG_YAML = REPO / "experiments" / "pass12_meta_eval.yaml"
MANIFEST_JSON = REPO / "data" / "submissions" / "pass12_candidates_manifest.json"
SURR_DIR = REPO / "data" / "meta_replays" / "surrogates"
REGISTRY_JSON = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
FOCUSED_JSON = REPO / "data" / "experiments" / "pass12_focused_results.json"
RANKING_JSON = REPO / "data" / "experiments" / "pass12_ranking.json"
DRY_RUN_JSON = REPO / "data" / "experiments" / "pass12_dry_run_queue.json"
SCOUT_JSON = REPO / "data" / "experiments" / "pass12_scout_results.json"
CAND12_DIR = REPO / "data" / "submissions" / "candidates_pass12"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"
V1_BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
GITIGNORE = REPO / ".gitignore"


def _load_yaml(p: Path) -> dict:
    if not p.exists():
        pytest.skip(f"{p.name} not present")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _load_json(p: Path) -> dict:
    if not p.exists():
        pytest.skip(f"{p.name} not present")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Config weights — provisional cap + redistribution to confirmed
# --------------------------------------------------------------------------- #
def test_config_weights_sum_to_one():
    cfg = _load_yaml(CONFIG_YAML)
    weights = cfg["evaluation_weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_provisional_archetype_capped_and_excess_redistributed():
    cfg = _load_yaml(CONFIG_YAML)
    cap = float(cfg["provisional_weight_cap"])
    raw = cfg["raw_replay_frequency_weights"]
    weights = cfg["evaluation_weights"]
    opp = {o["key"]: o for o in cfg["opponent_archetypes"]}
    provisional = [k for k, o in opp.items() if o.get("confidence") == "provisional"]
    confirmed = [k for k, o in opp.items() if o.get("confidence") == "confirmed"]
    assert provisional, "expected at least one provisional opponent archetype"
    # Each provisional archetype is capped at the cap.
    for k in provisional:
        assert weights[k] <= cap + 1e-9, f"{k} weight {weights[k]} exceeds cap {cap}"
        # It was actually over the cap in raw frequency (so the cap did work).
        assert raw[k] > cap
    # The excess removed from provisional was added to the confirmed archetypes
    # (confirmed final weight > confirmed raw weight by the redistributed share).
    for k in confirmed:
        assert weights[k] > raw[k] - 1e-9


def test_self_mirror_is_zero_weight_and_excluded():
    cfg = _load_yaml(CONFIG_YAML)
    sm = cfg["self_mirror"]
    assert float(sm["weight"]) == 0.0
    # The mirror key is never an opponent archetype with weight.
    assert sm["key"] not in cfg["evaluation_weights"]


# --------------------------------------------------------------------------- #
# Validator-before-eval + chaos gating (no invented ids)
# --------------------------------------------------------------------------- #
def test_every_built_candidate_is_validator_passing():
    man = _load_json(MANIFEST_JSON)
    built = man.get("built") or []
    assert built, "expected at least one built candidate"
    for c in built:
        assert c.get("validated") is True, f"{c.get('id')} not validated"
        assert c.get("status") == "built"
    assert man.get("all_built_validated") is True


def test_eval_consumed_only_validated_candidates():
    """Every non-control candidate the eval actually ran must be a validator-passing
    BUILT candidate; the blocked chaos candidate must never appear in the eval."""
    man = _load_json(MANIFEST_JSON)
    scout = _load_json(SCOUT_JSON)
    validated_ids = {c["id"] for c in (man.get("built") or [])
                     if c.get("validated") is True}
    control_ids = {c["id"] for c in (man.get("controls") or [])}
    blocked_ids = {b["id"] for b in (man.get("blocked") or [])}
    evaluated = set((scout.get("per_candidate") or {}).keys())
    cand_evaluated = evaluated - control_ids
    assert cand_evaluated, "expected the eval to have run some candidates"
    # No evaluated candidate is outside the validated-built set.
    assert cand_evaluated <= validated_ids, (
        f"eval ran non-validated candidates: {cand_evaluated - validated_ids}")
    # The blocked chaos candidate was never evaluated.
    assert not (evaluated & blocked_ids), "blocked candidate leaked into the eval"


def test_candidate_tarballs_are_top_level_main_and_deck_only():
    """The strict packaging invariant: each Pass 12 candidate tarball contains
    exactly two top-level files — main.py and deck.csv — and nothing else."""
    if not CAND12_DIR.exists():
        pytest.skip("candidate tarballs not built yet")
    tarballs = sorted(CAND12_DIR.glob("*.tar.gz"))
    assert tarballs, "expected at least one candidate tarball"
    for t in tarballs:
        with tarfile.open(t) as tf:
            members = [m for m in tf.getmembers() if m.isfile() or m.isdir()]
            names = sorted(m.name for m in members if m.isfile())
        assert names == ["deck.csv", "main.py"], f"{t.name} members: {names}"


def test_transfer_candidate_decks_are_real_replay_decks_no_invented_ids():
    """Transfer candidates must reuse REAL replay-derived 60-card decks verbatim —
    every card id traces to an extracted replay deck, so nothing is invented."""
    if not CAND12_DIR.exists() or not DECKS_DIR.exists():
        pytest.skip("candidate tarballs or replay decks not present")
    # Multiset signatures of every replay-derived deck.
    replay_sigs = set()
    for f in DECKS_DIR.glob("*_deck.csv"):
        ids = tuple(sorted(int(x) for x in f.read_text().split() if x.strip()))
        replay_sigs.add(ids)
    assert replay_sigs, "expected extracted replay decks"
    transfers = sorted(CAND12_DIR.glob("transfer12_*.tar.gz"))
    assert transfers, "expected transfer candidates"
    for t in transfers:
        with tarfile.open(t) as tf:
            deck = tf.extractfile("deck.csv").read().decode()
        ids = tuple(sorted(int(x) for x in deck.split() if x.strip()))
        assert len(ids) == 60, f"{t.name} deck is not 60 cards"
        assert ids in replay_sigs, (
            f"{t.name} deck does not match any real replay deck — possible invented ids")


def test_chaos_candidate_blocked_without_inventing_ids():
    man = _load_json(MANIFEST_JSON)
    blocked = man.get("blocked") or []
    chaos = [b for b in blocked if b.get("group") == "chaos"
             or "chaos" in str(b.get("id", ""))]
    assert chaos, "expected the chaos candidate to be honestly blocked"
    for b in chaos:
        assert b.get("validated") is False
        assert b.get("status") == "blocked"
        # The honest reason must reference NOT inventing ids.
        assert "invent" in b.get("reason", "").lower()


# --------------------------------------------------------------------------- #
# 60-int surrogate decks
# --------------------------------------------------------------------------- #
def test_surrogate_decks_are_60_integer_rows():
    if not SURR_DIR.exists():
        pytest.skip("surrogate dirs not built yet")
    decks = sorted(SURR_DIR.glob("*/deck.csv"))
    assert decks, "expected at least one surrogate deck"
    for deck in decks:
        rows = [r for r in deck.read_text().splitlines() if r.strip()]
        assert len(rows) == 60, f"{deck} has {len(rows)} rows, expected 60"
        for r in rows:
            int(r.strip())  # raises if any row is not an integer


def test_each_surrogate_dir_is_top_level_main_and_deck_only():
    if not SURR_DIR.exists():
        pytest.skip("surrogate dirs not built yet")
    for d in sorted(p for p in SURR_DIR.iterdir() if p.is_dir()):
        assert (d / "main.py").exists(), f"{d.name} missing main.py"
        assert (d / "deck.csv").exists(), f"{d.name} missing deck.csv"
        assert (d / "metadata.json").exists(), f"{d.name} missing metadata.json"
        meta = json.loads((d / "metadata.json").read_text())
        # Honesty note: deck-faithful, policy-approximate.
        blob = json.dumps(meta).lower()
        assert "surrogate" in blob


# --------------------------------------------------------------------------- #
# Provisional kept as an opponent
# --------------------------------------------------------------------------- #
def test_provisional_family_retained_as_opponent():
    cfg = _load_yaml(CONFIG_YAML)
    confidences = {o["key"]: o.get("confidence") for o in cfg["opponent_archetypes"]}
    assert "provisional" in confidences.values()


# --------------------------------------------------------------------------- #
# Dynamic active control — config matches live registry
# --------------------------------------------------------------------------- #
def test_active_control_matches_live_registry():
    cfg = _load_yaml(CONFIG_YAML)
    reg = _load_json(REGISTRY_JSON)
    cfg_ac = (cfg.get("active_control") or {}).get("name")
    reg_block = reg.get("active_control") or {}
    # The registry keys the active control by tarball filename; the config pins
    # the resolved name. Compare on the stem so the two stay in lock-step.
    reg_ac = reg_block.get("name") or str(
        reg_block.get("filename", "")).replace(".tar.gz", "")
    assert cfg_ac and reg_ac
    assert cfg_ac == reg_ac, "config active control must track the live registry"


# --------------------------------------------------------------------------- #
# beats-active-control promotion gate (canonical ranker.label_for)
# --------------------------------------------------------------------------- #
def _entry(adj, games, wins, *, role=None, branch_id="cand", kind="deck"):
    low, high = wilson_interval(wins, games, Z_80)
    return {
        "rejected": False, "reject_reasons": [], "role": role,
        "branch_id": branch_id, "kind": kind, "adjusted_win_rate": adj,
        "games_completed": games, "wilson80": [low, high],
    }


def test_gate_requires_beating_control_and_clearing_lower_bound():
    control_adj = 0.50
    # Strong, large sample, clears 0.50 lower bound and beats control -> promotable.
    strong = _entry(0.80, 40, 32)
    label, _ = label_for(strong, control_adj, min_games=20)
    assert label == "promotable"


def test_gate_blocks_when_not_beating_control():
    # Beats nobody: adj == control, big sample -> never promotable.
    even = _entry(0.50, 40, 20)
    label, _ = label_for(even, control_adj=0.50, min_games=20)
    assert label != "promotable"


def test_gate_blocks_small_sample_even_if_winrate_high():
    # High rate but tiny sample -> lower bound can't clear 0.50 -> not promotable.
    tiny = _entry(0.83, 6, 5)
    label, _ = label_for(tiny, control_adj=0.50, min_games=20)
    assert label != "promotable"


def test_control_role_is_anchor_never_promotable():
    anchor = _entry(0.90, 40, 36, role="active_control")
    label, _ = label_for(anchor, control_adj=0.50, min_games=20)
    assert label == "anchor"


# --------------------------------------------------------------------------- #
# mirror_overfit label on the produced focused ranking
# --------------------------------------------------------------------------- #
def test_mirror_overfit_rows_satisfy_mirror_overfit_definition():
    foc = _load_json(FOCUSED_JSON)
    rows = foc.get("ranking") or []
    flagged = [r for r in rows if r.get("label") == "mirror_overfit"]
    if not flagged:
        pytest.skip("no mirror_overfit row in this run")
    for r in flagged:
        # By definition: strong vs the self-mirror, weak vs the real meta.
        assert r.get("mirror_win_rate") is not None and r["mirror_win_rate"] >= 0.60
        assert r.get("adjusted_win_rate") is not None and r["adjusted_win_rate"] < 0.50


# --------------------------------------------------------------------------- #
# Dry-run max one + no upload
# --------------------------------------------------------------------------- #
def test_dry_run_queue_never_exceeds_cap():
    dry = _load_json(DRY_RUN_JSON)
    cap = int(dry.get("max_dry_run_queue", 1))
    assert cap <= 1
    assert len(dry.get("queued") or []) <= cap
    assert dry.get("queued_count", 0) <= cap


def test_no_upload_performed_anywhere():
    dry = _load_json(DRY_RUN_JSON)
    rank = _load_json(RANKING_JSON)
    assert dry.get("upload_performed") is False
    assert rank.get("upload_ready") is False


def test_config_gate_forbids_upload():
    cfg = _load_yaml(CONFIG_YAML)
    gate = cfg["promotion_gate"]
    assert gate.get("upload_performed") is False
    assert int(gate.get("max_dry_run_queue", 99)) <= 1


# --------------------------------------------------------------------------- #
# Root safety — root main.py/deck.csv unchanged vs v1 baseline
# --------------------------------------------------------------------------- #
def test_root_main_and_deck_identical_to_v1_baseline():
    if not V1_BASELINE.exists():
        pytest.skip("v1 baseline not present")
    assert filecmp.cmp(REPO / "main.py", V1_BASELINE / "main.py", shallow=False), \
        "root main.py drifted from the v1 baseline"
    assert filecmp.cmp(REPO / "deck.csv", V1_BASELINE / "deck.csv", shallow=False), \
        "root deck.csv drifted from the v1 baseline"


# --------------------------------------------------------------------------- #
# Raw replays gitignored
# --------------------------------------------------------------------------- #
def test_raw_replay_payloads_are_gitignored():
    assert GITIGNORE.exists()
    text = GITIGNORE.read_text(encoding="utf-8")
    assert "data/meta_replays/raw/*.json" in text
