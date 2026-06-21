"""PASS 46E — tests for the cg Search Outcome Oracle + one-step planner v0.

Covers (>=19 items): never-raise on garbage, module purity (no cg / no reference
policy import at top), unsupported-claim guards, signature compare semantics,
legality checks, hidden-hand-contents non-exposure, batch alignment, scoring
never-raise, worker structural invariants, and the read-only/honesty flags on
every produced artifact. One bounded live smoke test exercises the real cg
subprocess path.
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO / "src"), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"
ALLOWED_DECISIONS = {
    "search_oracle_ready_for_candidate_pilot",
    "search_oracle_partial_diagnostic_only",
    "search_oracle_blocked",
    "safety_stop_required",
}
REQUIRED_UNSUPPORTED = {"exact_damage", "lethal", "missed_ko", "boss_gust",
                        "spread", "best_action"}


def _load(stem: str) -> dict:
    p = EXP / f"{stem}.json"
    assert p.exists(), f"missing artifact {stem}.json (run the build scripts first)"
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- 1: module purity
def test_module_does_not_import_cg_at_top():
    src = (REPO / "src/ptcg_activegraph/analysis/search_oracle.py").read_text("utf-8")
    assert "import cg" not in src and "from cg" not in src
    # importing the oracle must not pull cg into the process
    assert "cg" not in sys.modules


# ----------------------------------------------------------- 2: no reference policy
def test_oracle_does_not_import_reference_or_promotion_policy():
    src = (REPO / "src/ptcg_activegraph/analysis/search_oracle.py").read_text("utf-8")
    assert "promotion" not in src
    assert "load_reference_ids" not in src
    assert "reference_ids" not in src


# --------------------------------------------------------- 3-5: never-raise on junk
@pytest.mark.parametrize("frame", [None, {}, 42, "x", {"observation": {}}, [1, 2]])
def test_evaluate_action_once_never_raises(frame):
    r = O.evaluate_action_once(frame, [0])
    assert isinstance(r, O.OracleResult)
    assert r.supported_level in {"assumption_based_hidden_state", "unsupported_or_failed"}


@pytest.mark.parametrize("frame", [None, {}, 42, "x", {"observation": 1}])
def test_rank_never_raises(frame):
    r = O.rank_legal_actions_one_step(frame)
    assert isinstance(r, dict) and r["ok"] is False
    assert "not_best_action" in r["label"]


def test_evaluate_actions_batch_never_raises_and_aligned():
    items = [(None, [0]), ({}, "bad"), (123, [1])]
    out = O.evaluate_actions_batch(items)
    assert isinstance(out, list) and len(out) == len(items)
    assert all(isinstance(x, O.OracleResult) for x in out)


# ----------------------------------------------------------- 6: build inputs purity
def test_build_inputs_never_raises_and_flags_reason():
    b = O.build_search_inputs_from_frame(None)
    assert b["ok"] is False and b["reason"] == "no_observation"


# ------------------------------------------------- 7: unsupported claims are guarded
def test_unsupported_claims_cover_required_keys():
    claims = O.unsupported_search_claims()
    assert REQUIRED_UNSUPPORTED <= set(claims)
    # returns a copy (mutation must not leak)
    claims["best_action"] = "now supported"
    assert "now supported" not in O.unsupported_search_claims()["best_action"]


# --------------------------------------------------- 8-11: signature compare/legality
def test_signature_from_current_none():
    assert O.signature_from_current(None) is None


def _sig(turn, result=None):
    return {"turn": turn, "result": result, "stadium_count": 0, "your_index": 0,
            "players": [{"deck_count": 10, "hand_count": 5, "active_hp": 100,
                         "active_ids": [1], "bench_count": 1, "discard_count": 0,
                         "prize_count": 6, "energy_total": 1},
                        {"deck_count": 10, "hand_count": 5, "active_hp": 100,
                         "active_ids": [2], "bench_count": 1, "discard_count": 0,
                         "prize_count": 6, "energy_total": 1}]}


def test_compare_exact_match():
    c = O.compare_signatures(_sig(3), _sig(3))
    assert c["classification"] == "exact_match"


def test_compare_core_mismatch_on_turn():
    c = O.compare_signatures(_sig(3), _sig(4))
    assert c["classification"] == "mismatch"
    assert "turn" in c["core_differed"]


def test_compare_partial_match_non_core():
    a = _sig(3)
    b = _sig(3)
    b["players"][1]["hand_count"] = 7  # non-core difference only
    c = O.compare_signatures(a, b)
    assert c["classification"] == "partial_match"


@pytest.mark.parametrize("action,n,mn,mx,ok", [
    ([0], 3, 1, 1, True),
    ([3], 3, 1, 1, False),          # index out of range
    ([0, 1], 3, 1, 1, False),       # too many for maxCount 1
    ("x", 3, 1, 1, False),
    ([], 3, 1, 1, False),
])
def test_is_index_action(action, n, mn, mx, ok):
    assert O._is_index_action(action, n, mn, mx) is ok


# --------------------------------------------- 12: scoring never-raise on bad outcome
def test_score_invalid_outcome_is_never_raise():
    sc = O.score_outcome_generic_progress_v0(None, 0)
    assert "invalid" in sc["breakdown"]
    assert sc["label"] == "one_step_score_rank_under_assumption"


# ------------------------------------- 13: hidden opponent hand contents not exposed
def test_build_inputs_exposes_opp_hand_count_only_not_contents():
    tp = sorted(glob.glob(str(TRACES / "*.json.gz")))[0]
    d = json.loads(gzip.open(tp).read())
    frame = None
    for st in d.get("steps", []):
        if not isinstance(st, list):
            continue
        for o in st:
            if isinstance(o, dict) and isinstance(o.get("observation"), dict) \
                    and o["observation"].get("search_begin_input"):
                frame = o
                break
        if frame:
            break
    assert frame is not None
    b = O.build_search_inputs_from_frame(frame)
    assert isinstance(b["opponent_hand_count"], int)
    # only a count is surfaced; no contents key for the opponent hand
    assert "opponent_hand" not in b and "opponent_hand_cards" not in b


# ------------------------------------------- 14: worker structural honesty invariants
def test_worker_imports_cg_and_cleans_up():
    src = (REPO / "src/ptcg_activegraph/analysis/_search_worker.py").read_text("utf-8")
    assert "from cg import api" in src
    assert "search_release" in src and "search_end" in src
    assert "finally:" in src
    assert '"kind": "start"' in src and '"kind": "result"' in src


# ------------------------------------------------------- 15-18: artifact honesty flags
def test_safety_artifact_all_ok_and_readonly():
    a = _load("pass46e_safety_preflight")
    assert a["all_ok"] is True
    assert a["production_mutated"] is False and a["read_only"] is True
    assert a["checks"]["references_absent_from_worklist"] is True


def test_surface_artifact_core_present():
    a = _load("pass46e_search_api_surface")
    assert a["ok"] is True and a["core_present"] is True
    for n in ("search_begin", "search_step", "search_end", "search_release"):
        assert a["callables"][n]["callable"] is True


def test_calibration_artifact_breakdown_and_flags():
    a = _load("pass46e_search_oracle_calibration")
    assert a["production_mutated"] is False and a["candidate_generated"] is False
    oc = a["overall_classification"]
    for k in ("exact_match", "partial_match", "mismatch", "unsupported",
              "timed_out", "error"):
        assert k in oc
    assert a["frames_attempted"] >= 1
    # md carries caveats
    md = (EXP / "pass46e_search_oracle_calibration.md").read_text("utf-8")
    assert "READ-ONLY" in md and "BENCHMARK-ONLY" in md


def test_runtime_artifact_has_stats():
    a = _load("pass46e_search_runtime_budget")
    assert "per_evaluate_native_step_s" in a
    assert "per_rank_call_wall_s_includes_subprocess_spawn" in a
    assert a["production_mutated"] is False


# ----------------------------------------------------- 19: planner label + buckets
def test_planner_artifact_label_and_buckets():
    a = _load("pass46e_one_step_planner_diagnostic")
    assert "not_best_action" in a["label"]
    assert a["candidate_generated"] is False
    assert set(a["by_role_bucket"]) >= {"public_reference", "internal_candidate",
                                        "internal_parent"}


# --------------------------------------------------------- 20: decision is in-charter
def test_decision_artifact_is_allowed_and_honest():
    a = _load("pass46e_strategy_decision")
    assert a["decision"] in ALLOWED_DECISIONS
    assert a["production_mutated"] is False
    assert REQUIRED_UNSUPPORTED <= set(a["unsupported_claims"])


# --------------------------------------------- 21: report exists with the 10 sections
def test_report_has_ten_sections():
    rp = REPO / "data/reports/pass46e_cg_search_oracle_report.md"
    assert rp.exists()
    txt = rp.read_text("utf-8")
    for i in range(1, 11):
        assert f"## {i}." in txt


# ------------------------------- 22: selectors admit ACTIVE-seat frames ONLY (causal)
def test_calibration_and_planner_select_active_frames_only():
    import build_pass46e_search_oracle_calibration as CAL
    import build_pass46e_one_step_planner_diagnostic as PLN
    tp = sorted(glob.glob(str(TRACES / "*.json.gz")))[0]
    d = json.loads(gzip.open(tp).read())
    steps = d.get("steps") or []
    a_seat = int(d.get("a_seat", 0))

    cal_frames = CAL._select_frames(steps, a_seat, d.get("role_a"), d.get("role_b"), 99)
    assert cal_frames, "calibration selector returned no frames"
    for f in cal_frames:
        status = steps[f["step"]][f["seat"]].get("status")
        assert str(status).upper() == "ACTIVE", f"INACTIVE frame admitted: {status}"

    pln_frames = PLN._rankable_frames(steps, a_seat, d.get("role_a"),
                                      d.get("role_b"), 99, {})
    for f in pln_frames:
        status = steps[f["step"]][f["seat"]].get("status")
        assert str(status).upper() == "ACTIVE", f"INACTIVE rankable admitted: {status}"


# --------------------------------------------------- 23: bounded live cg smoke path
def test_live_evaluate_one_real_frame_supported():
    tp = sorted(glob.glob(str(TRACES / "*.json.gz")))[0]
    d = json.loads(gzip.open(tp).read())
    target = None
    for st in d.get("steps", []):
        if not isinstance(st, list):
            continue
        for o in st:
            if not (isinstance(o, dict) and isinstance(o.get("observation"), dict)):
                continue
            obs = o["observation"]
            sel = obs.get("select")
            if not (obs.get("search_begin_input") and isinstance(sel, dict)):
                continue
            n_opt = len(sel.get("option") or [])
            if O._is_index_action(o.get("action"), n_opt, sel.get("minCount"),
                                  sel.get("maxCount")):
                target = o
                break
        if target:
            break
    assert target is not None, "no usable real frame found"
    r = O.evaluate_action_once(target, target["action"], timeout_s=8.0)
    assert r.ok is True
    assert r.supported_level == "assumption_based_hidden_state"
    assert r.outcome is not None and r.outcome.post_signature is not None
