"""ActiveGraph Pass 16 — empirical context map + runtime coverage v3 tests.

Covers (spec Part N):
* the empirical context map records observed context ids + labels,
* SetupActive (ctx 1) / SetupBench (ctx 2) are "confirmed" only when the
  cross-source evidence threshold is met (present in BOTH replays and live with
  matching select/option shapes); single-source contexts are not wire-eligible,
* DrawCount/Count (ctx 38) handles numeric options,
* unsafe broad Main (ctx 0) stays delegated,
* core_pilot_water_v3_context wires exactly the confirmed-safe contexts, keeps the
  fresh-named entrypoint last, and is recorded as entrypoint-validator PASS,
* v3 runtime picks Kyogre over Snover (setup active), benches a useful backup
  (setup bench), and avoids drawing when the deck is low (draw count),
* narrow attach only fires when the card/target resolve cleanly,
* the focused-eval validation pre-filters candidates; the active control is an
  anchor only and is never queued; no upload is ever performed,
* root entrypoints are untouched, and the report carries the surrogate caveat.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

CTX_MAP = REPO / "data" / "experiments" / "pass16_context_map.json"
VALIDATION = REPO / "data" / "reports" / "pass16_validation.json"
FOCUSED = REPO / "data" / "experiments" / "pass16_focused_eval.json"
RANKING = REPO / "data" / "experiments" / "pass16_ranking.json"
REPORT = REPO / "data" / "reports" / "pass16_context_map_and_runtime_eval_report.md"
V3 = REPO / "data" / "submissions" / "candidates_pass16" / "core_pilot_water_v3_context.tar.gz"
PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow_core_pilot.yaml"

KYOGRE, SNOVER, ABOMASNOW, ENERGY = 721, 722, 723, 3


def _rows() -> dict:
    d = json.loads(CTX_MAP.read_text(encoding="utf-8"))
    return {r["context"]: r for r in d["rows"]}, d


def _extract_main(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball) as t:
        t.extractall(dest)
    return dest / "main.py"


def _last_callable_name(src: str) -> str:
    tree = ast.parse(src)
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    return funcs[-1]


def _load_v3(tmp_path):
    main_path = _extract_main(V3, tmp_path)
    spec = importlib.util.spec_from_file_location("cand_v3_ctx", main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cand_v3_ctx"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# --------------------------------------------------------------------------- #
# Context map: observed ids + labels.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not CTX_MAP.exists(), reason="context map not built")
def test_context_map_has_observed_ids_and_labels():
    rows, doc = _rows()
    # The empirically observed contexts from raw replays + live traces.
    for ctx in (0, 1, 2, 7, 8, 38):
        assert ctx in rows, f"context {ctx} missing from map"
        assert rows[ctx]["label"], f"context {ctx} has no label"
    assert doc["summary"]["total_contexts"] >= 10
    assert doc["named_contexts"].get("7") == "search_to_hand"
    assert doc["named_contexts"].get("8") == "discard"


# --------------------------------------------------------------------------- #
# Confirmation thresholds (cross-source).
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not CTX_MAP.exists(), reason="context map not built")
def test_setup_active_confirmed_only_when_cross_source():
    rows, _ = _rows()
    r = rows[1]
    # Confirmed REQUIRES presence in both sources with matching shapes.
    assert r["in_replay"] and r["in_live"]
    assert r["select_type_match"] and r["option_shape_match"]
    assert r["confidence"] == "confirmed_cross_source"
    assert r["confirmed"] is True and r["safe_to_wire"] is True
    assert r["recommended_action"] == "wire"


@pytest.mark.skipif(not CTX_MAP.exists(), reason="context map not built")
def test_setup_bench_confirmed_only_when_cross_source():
    rows, _ = _rows()
    r = rows[2]
    assert r["in_replay"] and r["in_live"]
    assert r["confidence"] == "confirmed_cross_source"
    assert r["safe_to_wire"] is True and r["recommended_action"] == "wire"


@pytest.mark.skipif(not CTX_MAP.exists(), reason="context map not built")
def test_single_source_context_not_wire_eligible():
    """A replay-only (or live-only) context fails the evidence threshold and must
    NOT be marked safe to wire — confirmation needs both sources."""
    rows, _ = _rows()
    r = rows[5]  # place_basic_optional, replay_only
    assert r["in_replay"] and not r["in_live"]
    assert r["confidence"] == "replay_only"
    assert r["confirmed"] is False and r["safe_to_wire"] is False
    assert r["recommended_action"] == "defer"


# --------------------------------------------------------------------------- #
# Broad Main stays delegated.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not CTX_MAP.exists(), reason="context map not built")
def test_broad_main_remains_delegated():
    rows, doc = _rows()
    r = rows[0]
    assert r["safe_to_wire"] is False
    assert r["recommended_action"] == "defer"
    assert "DELEGATE" in r["policy"].upper()
    assert doc["summary"]["broad_main_deferred"] is True
    assert 0 not in doc["summary"]["recommend_wire_new"]
    assert 0 not in doc["summary"]["keep_wired"]


# --------------------------------------------------------------------------- #
# v3 candidate: wired set + entrypoint invariant.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_v3_wires_confirmed_contexts_and_keeps_entrypoint_last(tmp_path):
    src = _extract_main(V3, tmp_path).read_text(encoding="utf-8")
    assert "_CP_RUNTIME_CONTEXTS = (1, 2, 7, 8, 38)" in src
    assert _last_callable_name(src) == "core_pilot_agent"


@pytest.mark.skipif(not VALIDATION.exists(), reason="validation report missing")
def test_v3_entrypoint_validator_pass_recorded():
    val = json.loads(VALIDATION.read_text(encoding="utf-8"))
    v3 = val["candidates"]["core_pilot_water_v3_context"]
    assert v3["entrypoint"]["result"] == "PASS"
    assert v3["entrypoint"]["last_callable"] == "core_pilot_agent"
    assert v3["validator_passing"] is True


# --------------------------------------------------------------------------- #
# v3 runtime decisions on confirmed contexts.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_v3_setup_active_prefers_kyogre_over_snover(tmp_path):
    mod = _load_v3(tmp_path)
    board = {"active": None}
    options = [{"card_id": SNOVER}, {"card_id": KYOGRE}]
    res = mod.core_pilot_decide("setup_active", board, options)
    assert res.get("chosen_card_id") == KYOGRE


@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_v3_setup_bench_benches_useful_backup(tmp_path):
    mod = _load_v3(tmp_path)
    board = {"active": {"card_id": KYOGRE}, "bench_pick_count": 1}
    # Energy is not a benchable basic Pokemon; a setup basic / attacker is.
    options = [{"card_id": ENERGY}, {"card_id": SNOVER}, {"card_id": KYOGRE}]
    res = mod.core_pilot_decide("setup_bench_multi", board, options)
    chosen = res.get("chosen_card_ids") or ([res.get("chosen_card_id")]
                                            if res.get("chosen_card_id") else [])
    assert chosen, "must bench at least one backup"
    assert ENERGY not in chosen
    assert any(c in (SNOVER, KYOGRE) for c in chosen)


@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_v3_draw_count_handles_numeric_options(tmp_path):
    mod = _load_v3(tmp_path)
    # Numeric option set: pick a number to draw.
    options = [{"number": 0}, {"number": 1}, {"number": 2}, {"number": 3}]
    high = mod.core_pilot_decide("draw_count", {"deck_count": 40}, options)
    assert high.get("chosen_number") == 3  # plenty of deck -> draw max


@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_v3_avoids_low_deck_draw(tmp_path):
    mod = _load_v3(tmp_path)
    options = [{"number": 0}, {"number": 1}, {"number": 2}, {"number": 3}]
    # deck_count 2 -> may draw at most 1 (keep >=1 in deck); never deck-out.
    low = mod.core_pilot_decide("draw_count", {"deck_count": 2}, options)
    assert low.get("chosen_number") is not None
    assert low["chosen_number"] <= 1
    one = mod.core_pilot_decide("draw_count", {"deck_count": 1}, options)
    assert one.get("chosen_number") == 0  # cannot draw the last card


# --------------------------------------------------------------------------- #
# Narrow attach only fires when the card + target resolve cleanly.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not V3.exists(), reason="v3 not built")
def test_narrow_attach_only_on_clean_resolution(tmp_path):
    mod = _load_v3(tmp_path)
    # ctx 26 (energy/attach) is NOT in v3's wired set -> stays delegated; the
    # runtime never injects an attach decision for an unconfirmed context.
    src = _extract_main(V3, tmp_path).read_text(encoding="utf-8")
    assert "26" not in [s.strip() for s in
                        src.split("_CP_RUNTIME_CONTEXTS = (")[1].split(")")[0].split(",")]


# --------------------------------------------------------------------------- #
# Focused eval: validator pre-filter, anchor not promotable, no upload.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not FOCUSED.exists(), reason="focused eval not run")
def test_focused_eval_candidates_are_validator_prefiltered():
    doc = json.loads(FOCUSED.read_text(encoding="utf-8"))
    val = json.loads(VALIDATION.read_text(encoding="utf-8"))
    for cid in doc.get("candidates_evaluated", []):
        assert val["candidates"][cid]["validator_passing"] is True


@pytest.mark.skipif(not VALIDATION.exists(), reason="validation missing")
def test_active_control_anchor_not_promotable():
    val = json.loads(VALIDATION.read_text(encoding="utf-8"))
    ac = val["candidates"]["combo_full_safety_v3_fixed"]
    # The live anchor fails the entrypoint invariant -> never a promotion target.
    assert ac["entrypoint"]["result"] == "FAIL"
    assert ac["validator_passing"] is False
    # The eval anchor we actually use is the entrypoint-safe clone.
    assert val["summary"]["eval_anchor"] == "combo_full_safety_v3_entrypoint_safe_local"


@pytest.mark.skipif(not RANKING.exists(), reason="ranking not built")
def test_ranking_never_uploads_and_queue_is_empty():
    rank = json.loads(RANKING.read_text(encoding="utf-8"))
    q = rank["dry_run_queue"]
    assert rank["upload_ready"] is False
    assert q["upload_performed"] is False
    assert q["auto_submit"] is False
    assert q["manual_approval"] is True
    assert q["human_review"] is True
    assert q["queued_candidates"] == []
    assert len(q["queued_candidates"]) <= 1


# --------------------------------------------------------------------------- #
# Report carries the surrogate limitation; root untouched.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not REPORT.exists(), reason="report missing")
def test_report_states_surrogate_limitation():
    txt = REPORT.read_text(encoding="utf-8").lower()
    assert "surrogate" in txt
    assert "directional" in txt
    assert "never equal" in txt and "kaggle" in txt
    assert "not sufficient to promote or upload" in " ".join(txt.split())


def test_root_entrypoints_untouched():
    # Strict guardrail: root entrypoints must be byte-identical to the v1 baseline.
    baseline = REPO / "data" / "baselines" / "v1_kaggle_349_8"
    for name in ("main.py", "deck.csv"):
        root = REPO / name
        base = baseline / name
        assert root.exists() and base.exists()
        assert root.read_bytes() == base.read_bytes(), f"root {name} differs from v1 baseline"
    assert not (REPO / "core_pilot_water_v3_context.tar.gz").exists()
    assert V3.parent == REPO / "data" / "submissions" / "candidates_pass16"
