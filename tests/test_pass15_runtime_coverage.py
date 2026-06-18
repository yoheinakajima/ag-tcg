"""ActiveGraph Pass 15 — runtime coverage + entrypoint-invariant tests.

Covers:
* the compiler's per-candidate ``_CP_RUNTIME_CONTEXTS`` literal (v1 = (7,),
  v2_runtime = (7, 8)) and that the discard handler is only emitted/active when
  context 8 is enabled,
* the cabt entrypoint invariant ratcheted into
  ``scripts/validate_candidate_entrypoint.py``: the last top-level callable must
  be the fresh-named deck-safe entrypoint and the bad-helper-last fixture must be
  REJECTED,
* that compiling never changes the deck-selection / entrypoint ordering, and
* root immutability (Pass 15 never touches root main.py / deck.csv).
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.pilot import compiler

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "data" / "submissions" / "candidates" / "combo_full_safety_v3_fixed.tar.gz"
PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow_core_pilot.yaml"
CAND14 = REPO / "data" / "submissions" / "candidates_pass14"
V1 = CAND14 / "core_pilot_water_v1.tar.gz"
V2 = CAND14 / "core_pilot_water_v2_runtime.tar.gz"
BAD_FIXTURE = REPO / "tests" / "fixtures" / "entrypoint" / "bad_helper_last.tar.gz"
VALIDATOR = REPO / "scripts" / "validate_candidate_entrypoint.py"


def _extract_main(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball) as t:
        t.extractall(dest)
    return dest / "main.py"


def _last_callable_name(src: str) -> str:
    tree = ast.parse(src)
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    return funcs[-1]


# --------------------------------------------------------------------------- #
# Compiler: per-candidate runtime context set.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not BASE.exists() or not PLAYBOOK.exists(),
                    reason="base tarball / playbook missing")
def test_compiler_emits_runtime_contexts_literal(tmp_path):
    import yaml
    base_main = _extract_main(BASE, tmp_path).read_text(encoding="utf-8")
    pb = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))

    v1_src = compiler.compile_candidate_source(base_main, pb, "v1",
                                               runtime_contexts=(7,))
    v2_src = compiler.compile_candidate_source(base_main, pb, "v2",
                                               runtime_contexts=(7, 8))
    assert "_CP_RUNTIME_CONTEXTS = (7,)" in v1_src
    assert "_CP_RUNTIME_CONTEXTS = (7, 8)" in v2_src
    # Both keep the fresh-named entrypoint LAST (the hard cabt invariant).
    assert _last_callable_name(v1_src) == "core_pilot_agent"
    assert _last_callable_name(v2_src) == "core_pilot_agent"
    # The discard refinement is gated on context 8 being enabled.
    assert "ctx == 8 and 8 in _CP_RUNTIME_CONTEXTS" in v2_src
    assert "ctx == 7 and 7 in _CP_RUNTIME_CONTEXTS" in v2_src


def test_compiler_default_runtime_contexts_is_search_only(tmp_path):
    """Default (no override) must match v1 behaviour: search context only."""
    import yaml
    if not (BASE.exists() and PLAYBOOK.exists()):
        pytest.skip("base/playbook missing")
    base_main = _extract_main(BASE, tmp_path).read_text(encoding="utf-8")
    pb = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    src = compiler.compile_candidate_source(base_main, pb, "default")
    assert "_CP_RUNTIME_CONTEXTS = (7,)" in src


# --------------------------------------------------------------------------- #
# Shipped candidates carry the expected runtime-context set.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not V2.exists(), reason="v2_runtime not built")
def test_v2_runtime_wires_discard_context(tmp_path):
    src = _extract_main(V2, tmp_path).read_text(encoding="utf-8")
    assert "_CP_RUNTIME_CONTEXTS = (7, 8)" in src
    assert _last_callable_name(src) == "core_pilot_agent"


@pytest.mark.skipif(not V1.exists(), reason="v1 not built")
def test_v1_search_context_only(tmp_path):
    src = _extract_main(V1, tmp_path).read_text(encoding="utf-8")
    # v1 predates the literal; either it has (7,) or no literal (defaults to {7}).
    assert "_CP_RUNTIME_CONTEXTS = (7, 8)" not in src
    assert _last_callable_name(src) == "core_pilot_agent"


@pytest.mark.skipif(not V2.exists(), reason="v2_runtime not built")
def test_v2_discard_refinement_keeps_base_count(tmp_path):
    """The discard handler must keep the base policy's committed count: it only
    refines WHICH cards, returning the base result on any count mismatch."""
    main_path = _extract_main(V2, tmp_path)
    spec = importlib.util.spec_from_file_location("cand_v2_discard", main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cand_v2_discard"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # The reduced-model discard layer prefers basic energy (id 3) over payoff
    # cards (matches fixture 07). This proves the layer the runtime delegates to.
    board = {"active": {"card_id": 721}, "discard_count": 1}
    options = [{"card_id": 722}, {"card_id": 3}, {"card_id": 723}]
    res = mod.core_pilot_decide("discard", board, options)
    assert 3 in (res.get("chosen_card_ids") or [])
    assert 722 not in (res.get("chosen_card_ids") or [])
    assert 723 not in (res.get("chosen_card_ids") or [])
    assert len(res["chosen_card_ids"]) == 1  # respects the requested count


# --------------------------------------------------------------------------- #
# Entrypoint-invariant validator: the ratchet.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not BAD_FIXTURE.exists() or not VALIDATOR.exists(),
                    reason="bad-helper fixture or validator missing")
def test_validator_rejects_bad_helper_last():
    """A candidate whose LAST callable is a helper returning [] must FAIL."""
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(BAD_FIXTURE)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, "validator must reject the bad-helper-last fixture"
    assert "FAIL" in (proc.stdout + proc.stderr)


@pytest.mark.skipif(not BAD_FIXTURE.exists(), reason="bad fixture missing")
def test_bad_fixture_last_callable_is_the_bad_helper(tmp_path):
    """Guard the fixture itself: its last callable really is the broken helper."""
    src = _extract_main(BAD_FIXTURE, tmp_path).read_text(encoding="utf-8")
    assert _last_callable_name(src) == "_bad_last_helper"


# --------------------------------------------------------------------------- #
# Recommendation / dry-run queue (T-K / T-L): never uploads, gate is honest.
# --------------------------------------------------------------------------- #
def _load_reco():
    spec = importlib.util.spec_from_file_location(
        "p15_reco", REPO / "scripts" / "run_pass15_recommendation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_recommendation_never_uploads_and_gate_is_honest():
    reco = _load_reco()
    focused = {
        "active_control": "ac",
        "matchups": [
            {"role": "core_pilot_water_v2_runtime", "wins": 4, "losses": 2,
             "draws": 0, "crashes": 0, "timeouts": 0, "skipped": 0},
            {"role": "core_pilot_water_v2_runtime", "wins": 3, "losses": 3,
             "draws": 0, "crashes": 0, "timeouts": 0, "skipped": 0},
            {"role": "active_control", "wins": 3, "losses": 3, "draws": 0,
             "crashes": 0, "timeouts": 0, "skipped": 0},
        ],
        "ranking": [
            {"role": "core_pilot_water_v2_runtime", "subfamilies": 2,
             "weighted_directional_win_rate": 0.5833},
            {"role": "active_control", "subfamilies": 2,
             "weighted_directional_win_rate": 0.5833},
        ],
    }
    smoke = {"smoke": [{"crashes": 0, "timeouts": 0, "skipped": 0}]}
    metrics = reco.build_metrics(focused, smoke)
    queue = reco.build_queue(metrics)
    # Hard invariant: the queue NEVER performs an upload.
    assert queue["upload_performed"] is False
    # 12 games (< 20) → no candidate clears the gate; queue is empty by design.
    assert queue["queued_count"] == 0
    cp = next(r for r in metrics["rows"]
              if r["candidate"] == "core_pilot_water_v2_runtime")
    assert cp["valid_live"] is True
    assert cp["promotion_gate"] == "insufficient_games"


def test_recommendation_flags_invalid_on_crash():
    reco = _load_reco()
    focused = {
        "active_control": "ac",
        "matchups": [
            {"role": "core_pilot_water_v2_runtime", "wins": 1, "losses": 0,
             "draws": 0, "crashes": 1, "timeouts": 0, "skipped": 0},
            {"role": "active_control", "wins": 1, "losses": 0, "draws": 0,
             "crashes": 0, "timeouts": 0, "skipped": 0},
        ],
        "ranking": [
            {"role": "core_pilot_water_v2_runtime",
             "weighted_directional_win_rate": 1.0},
            {"role": "active_control", "weighted_directional_win_rate": 1.0},
        ],
    }
    metrics = reco.build_metrics(focused, {"smoke": []})
    cp = next(r for r in metrics["rows"]
              if r["candidate"] == "core_pilot_water_v2_runtime")
    assert cp["valid_live"] is False
    assert cp["promotion_gate"] == "fail_validity"
    assert reco.build_queue(metrics)["queued_count"] == 0


def test_recommendation_fail_smoke_validity():
    """A candidate that crashes in LIVE SMOKE cannot promote, even with a clean
    focused eval."""
    reco = _load_reco()
    focused = {
        "active_control": "ac",
        "matchups": [
            {"role": "core_pilot_water_v2_runtime", "wins": 5, "losses": 1,
             "draws": 0, "crashes": 0, "timeouts": 0, "skipped": 0},
            {"role": "active_control", "wins": 1, "losses": 5, "draws": 0,
             "crashes": 0, "timeouts": 0, "skipped": 0},
        ],
        "ranking": [
            {"role": "core_pilot_water_v2_runtime",
             "weighted_directional_win_rate": 0.83},
            {"role": "active_control", "weighted_directional_win_rate": 0.17},
        ],
    }
    smoke = {"smoke": [
        {"matchup": "v2_runtime_vs_active_control", "crashes": 1,
         "timeouts": 0, "skipped": 0},
    ]}
    metrics = reco.build_metrics(focused, smoke)
    cp = next(r for r in metrics["rows"]
              if r["candidate"] == "core_pilot_water_v2_runtime")
    assert cp["smoke_valid"] is False
    assert cp["valid_live"] is False
    assert cp["promotion_gate"] == "fail_smoke_validity"
    assert reco.build_queue(metrics)["queued_count"] == 0


def test_recommendation_fail_validator(monkeypatch):
    """A candidate that fails the entrypoint-invariant validator cannot promote,
    regardless of win rate or sample size."""
    reco = _load_reco()
    monkeypatch.setattr(reco, "_entrypoint_ok",
                        lambda *_a, **_k: False)
    focused = {
        "active_control": "ac",
        "matchups": [
            {"role": "core_pilot_water_v2_runtime", "wins": 20, "losses": 0,
             "draws": 0, "crashes": 0, "timeouts": 0, "skipped": 0},
            {"role": "active_control", "wins": 0, "losses": 20, "draws": 0,
             "crashes": 0, "timeouts": 0, "skipped": 0},
        ],
        "ranking": [
            {"role": "core_pilot_water_v2_runtime",
             "weighted_directional_win_rate": 1.0},
            {"role": "active_control", "weighted_directional_win_rate": 0.0},
        ],
    }
    metrics = reco.build_metrics(focused, {"smoke": []})
    cp = next(r for r in metrics["rows"]
              if r["candidate"] == "core_pilot_water_v2_runtime")
    assert cp["entrypoint_validator_pass"] is False
    assert cp["promotion_gate"] == "fail_validator"
    assert reco.build_queue(metrics)["queued_count"] == 0


def test_eval_validation_block_flags_active_control_anchor():
    """The focused-eval artifact records the entrypoint-validator pre-filter; the
    active control is kept as an anchor with entrypoint_pass False."""
    import json
    doc = json.loads(
        (REPO / "data" / "reports" / "pass15_core_focused_eval.json")
        .read_text(encoding="utf-8"))
    val = doc.get("validation") or {}
    assert val, "focused eval must persist a validation block"
    anchors = [v for v in val.values()
               if "anchor" in str(v.get("role", ""))]
    assert anchors, "an active-control anchor must be recorded"
    assert all(a.get("entrypoint_pass") is False for a in anchors)
    candidates = [v for v in val.values() if v.get("role") == "candidate"]
    assert candidates and all(c.get("entrypoint_pass") is True
                              for c in candidates)


# --------------------------------------------------------------------------- #
# Report-site wiring: the two Pass 15 reports + index section render.
# --------------------------------------------------------------------------- #
def test_report_site_emits_pass15_sections(tmp_path):
    from ptcg_activegraph.experiments import report as rep
    data = rep.gather()
    html = rep._overview_html(data)
    md = rep.write_pass15_eval_report(data, tmp_path / "eval.md")
    runtime = rep.write_pass15_runtime_report(data, tmp_path / "runtime.md")
    assert "Pass 15" in html
    assert "upload_performed" in html.lower() or "Upload performed" in html
    assert "Pass 15" in md.read_text(encoding="utf-8")
    assert "Runtime coverage" in runtime.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Root immutability.
# --------------------------------------------------------------------------- #
def test_root_entrypoints_untouched():
    assert (REPO / "main.py").exists()
    assert (REPO / "deck.csv").exists()
    assert not (REPO / "core_pilot_water_v2_runtime.tar.gz").exists()
    assert V2.parent == REPO / "data" / "submissions" / "candidates_pass14"
