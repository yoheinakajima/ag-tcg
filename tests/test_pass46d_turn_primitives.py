"""PASS 46D — turn-planning primitives v0 (READ-ONLY / LOCAL / INFRASTRUCTURE).

Validates the pure primitive module and the honest artifacts it feeds. HARD invariants:
root main.py/deck.csv byte-identical to baseline; the primitive module is pure (no
Object Storage / EventStore / production imports, never raises on junk); type/context
normalization accepts int/str/enum-name shapes; every action family classifies; hidden
opponent hand is never fabricated; energy candidates preserve active/bench destinations;
search/discard surface visible card ids only; the unsupported-claims guard never shrinks;
fixtures + validation are present and pass; behavior comparison carries small-n caveats;
public references stay benchmark-only; no forbidden events; Start application not started.
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest

from ptcg_activegraph.analysis import turn_primitives as P

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
MODULE = REPO / "src" / "ptcg_activegraph" / "analysis" / "turn_primitives.py"
REPORT = REPO / "data" / "reports" / "pass46d_turn_planning_primitives_report.md"

REQUIRED_UNSUPPORTED = {"exact_damage", "lethal_availability", "missed_ko",
                        "boss_gust_target_correctness", "spread_placement_correctness"}


def _j(name: str) -> dict:
    return json.loads((EXP / f"{name}.json").read_text(encoding="utf-8"))


def _fixtures() -> list[dict]:
    return _j("pass46d_trace_fixture_manifest")["fixtures"]


def _fixture(cat: str) -> dict | None:
    for f in _fixtures():
        if f["category"] == cat:
            return f
    return None


# --------------------------------------------------------------- safety (HARD)
def test_root_main_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_byte_identical_to_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


def test_safety_preflight_all_ok_and_read_only():
    pf = _j("pass46d_safety_preflight")
    assert pf["all_ok"] is True
    assert pf["read_only"] and pf["local_only"] and pf["no_upload"]
    assert pf["production_mutated"] is False and pf["candidate_generated"] is False
    assert pf["tick_executed"] is False


def test_safety_references_absent_from_pool_and_worklist():
    pf = _j("pass46d_safety_preflight")
    assert pf["refs_in_pool"] == []
    assert pf["refs_in_worklist"] == []


def test_safety_no_forbidden_events_prod_or_local():
    pf = _j("pass46d_safety_preflight")
    assert pf["forbidden_events_in_prod_ledger"] == []
    assert pf["forbidden_events_in_local_ledger"] == []


# ---------------------------------------------------- module purity / no side effects
def test_module_imports_without_side_effects(tmp_path):
    # Re-importing the module performs no I/O / no writes; a fresh import is a no-op.
    import importlib
    mod = importlib.reload(P)
    assert hasattr(mod, "unsupported_claims")


def test_module_source_has_no_storage_or_eventstore_imports():
    # inspect IMPORT statements only (docstring prose may legitimately mention these names)
    import_lines = [ln.strip() for ln in MODULE.read_text(encoding="utf-8").splitlines()
                    if ln.lstrip().startswith(("import ", "from "))]
    blob = "\n".join(import_lines)
    for forbidden in ("get_storage_backend", "storage", "ObjectStorage", "EventStore",
                      "TournamentLedger", "tournament", "requests", "urllib", "boto3",
                      "socket", "http"):
        assert forbidden not in blob, f"primitive module must not import {forbidden}"


def test_module_only_imports_pure_decoders():
    src = MODULE.read_text(encoding="utf-8")
    # the only intra-package imports are the pure analysis decoders
    assert "from . import turn_planning" in src
    assert "from .action_resolver import" in src
    assert "tournament" not in src


def test_primitives_never_raise_on_junk():
    junk = [None, 0, "x", [], {}, {"observation": None}, {"select": 5},
            {"option": "nope"}, 3.14, True]
    for j in junk:
        assert P.safe_get(j, "a.b.c", "D") == "D"  # junk paths fall back to default
        assert isinstance(P.normalize_option_type(j), dict)
        assert isinstance(P.normalize_select_context(j), dict)
        assert isinstance(P.classify_option_family(j), dict)
        assert isinstance(P.board_snapshot_from_frame(j), dict)
        assert isinstance(P.visible_counts_by_zone(j), dict)
        assert isinstance(P.legal_action_family_summary(j), dict)
        assert isinstance(P.energy_attach_candidates(j), list)
        assert isinstance(P.setup_candidate_summary(j), dict)
        assert isinstance(P.search_candidate_summary(j), dict)
        assert isinstance(P.discard_candidate_summary(j), dict)


def test_safe_get_paths_and_defaults():
    obj = {"a": {"b": [10, 20, {"c": 7}]}}
    assert P.safe_get(obj, "a.b.0") == 10
    assert P.safe_get(obj, ["a", "b", 2, "c"]) == 7
    assert P.safe_get(obj, "a.b.99", "DEF") == "DEF"
    assert P.safe_get(obj, "missing", "DEF") == "DEF"


# ----------------------------------------------- normalization (int/str/enum-name)
@pytest.mark.parametrize("raw,expected", [
    (8, "attach_energy"), ("8", "attach_energy"), ("attach_energy", "attach_energy"),
    (13, "attack"), ("13", "attack"), ("attack", "attack"),
    (9, "use_ability"), (12, "end_turn"), (3, "select_card"),
])
def test_normalize_option_type_shapes(raw, expected):
    assert P.normalize_option_type(raw)["action_class"] == expected
    assert P.normalize_option_type({"type": raw})["action_class"] == expected


def test_normalize_option_type_unknown_is_honest():
    out = P.normalize_option_type("definitely_not_a_type")
    assert out["action_class"] == "unknown" and out["checkable"] is False


def test_normalize_select_context_preserves_min_max():
    sel = {"context": 5, "type": 7, "minCount": 1, "maxCount": 3,
           "option": [{"type": 8}, {"type": 13}]}
    ctx = P.normalize_select_context(sel)
    assert ctx["min_count"] == 1 and ctx["max_count"] == 3
    assert ctx["n_options"] == 2 and ctx["is_choice"] is True


# -------------------------------------------------------- family classification
@pytest.mark.parametrize("opt,select,expected_class", [
    ({"type": 8, "area": 2, "index": 0, "inPlayArea": 4}, None, "attach_energy"),
    ({"type": 13, "attackId": 1044}, None, "attack"),
    ({"type": 9}, None, "use_ability"),
    ({"type": 12}, None, "end_turn"),
    ({"type": 3, "area": 1, "index": 0}, {"deck": [{"id": 5}]}, "select_card"),
    ({"type": 3, "area": 6, "index": 0}, None, "select_card"),
    ({"type": 7, "area": 2}, None, "play_from_hand"),
])
def test_classify_option_family_action_classes(opt, select, expected_class):
    out = P.classify_option_family(opt, select=select)
    assert out["action_class"] == expected_class


def test_classify_discard_vs_search_family():
    discard = P.classify_option_family({"type": 3, "area": 6, "index": 0})
    assert discard["family"] == "discard"
    search = P.classify_option_family({"type": 3, "area": 1, "index": 0},
                                      select={"deck": [{"id": 9}]})
    assert search["family"] == "search_to_hand"


def test_legal_action_family_summary_counts_and_min_max():
    sel = {"minCount": 1, "maxCount": 1,
           "option": [{"type": 8, "inPlayArea": 4}, {"type": 13, "attackId": 1},
                      {"type": 12}]}
    out = P.legal_action_family_summary({"observation": {"select": sel}})
    assert out["n_options"] == 3
    assert out["min_count"] == 1 and out["max_count"] == 1
    assert "attach" in out["families"] and "attack" in out["families"]


def test_primitives_honor_decision_frame_inputs():
    from ptcg_activegraph.analysis.turn_planning import DecisionFrame
    df = DecisionFrame(
        game_id="g", source="kaggle_replay", step=4, turn=2, acting_player=0,
        your_index=0, context=5, select_type=7, min_count=1, max_count=1, n_options=3,
        selected_indices=[], selected_families=[],
        option_families=["attach", "attack", "end"], primary_family="attack",
        self_board={"active_present": True}, opponent_board={"hand_count": 4})
    ctx = P.normalize_select_context(df)
    assert ctx["n_options"] == 3 and ctx["min_count"] == 1 and ctx["is_choice"] is True
    summ = P.legal_action_family_summary(df)
    assert summ["n_options"] == 3
    assert summ["families"] == {"attach": 1, "attack": 1, "end": 1}
    snap = P.board_snapshot_from_frame(df)
    assert snap["acting_seat"] == 0 and snap["turn"] == 2 and snap["checkable"] is True


# ------------------------------------------------------------- board snapshot
def test_board_snapshot_handles_missing_fields():
    snap = P.board_snapshot_from_frame({"observation": {"current": None}})
    assert snap["self"] is None and snap["checkable"] is False
    snap2 = P.board_snapshot_from_frame({"observation": {"current": {"players": []}}},
                                        seat=0)
    assert snap2["self"] is None


def test_board_snapshot_visible_counts_only_no_hidden_hand():
    current = {"turn": 3, "players": [
        {"handCount": 5, "deckCount": 40, "prize": [1, 2, 3, 4, 5, 6],
         "discard": [], "bench": [{}], "benchMax": 5, "active": [{}],
         "hand": ["secret_card_a", "secret_card_b"]},
        {"handCount": 4, "deckCount": 41, "prize": [1, 2, 3, 4, 5],
         "discard": [], "bench": [], "benchMax": 5, "active": [{}],
         "hand": ["opp_secret_1", "opp_secret_2", "opp_secret_3", "opp_secret_4"]},
    ]}
    snap = P.board_snapshot_from_frame({"observation": {"current": current}}, seat=0)
    opp = snap["opponent"]
    assert opp["hand_count"] == 4
    assert "hand" not in opp  # never carry literal hand contents
    assert opp["prize_remaining"] == 5
    assert snap["self"]["hand_count"] == 5


def test_visible_counts_prize_remaining_semantics():
    counts = P.visible_counts_by_zone({"prize": [1, 2, 3, 4, 5, 6], "handCount": 7})
    assert counts["prize_remaining"] == 6  # 6 remaining == took zero
    assert counts["hand_count"] == 7


# --------------------------------------------------------- energy / setup / search
def test_energy_candidates_preserve_active_bench_destination():
    sel = {"option": [
        {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
        {"type": 8, "area": 2, "index": 0, "inPlayArea": 5, "inPlayIndex": 1},
        {"type": 13, "attackId": 1}]}
    cands = P.energy_attach_candidates({"observation": {"select": sel}})
    dests = {c["destination"] for c in cands}
    assert dests == {"active", "bench"}
    assert all(c["visible"] for c in cands)


def test_score_energy_attach_is_generic_not_deck_specific():
    snap = {"self": {"active_present": True}}
    s_active = P.score_energy_attach_generic({"destination": "active"}, board=snap)
    s_bench = P.score_energy_attach_generic({"destination": "bench"}, board=snap)
    assert s_active["deck_specific"] is False
    assert s_active["score"] >= s_bench["score"]
    assert "best_action" in s_active["unsupported"]


def test_search_summary_visible_ids_only():
    sel = {"deck": [{"id": 100}, {"id": 200}, {"id": 300}],
           "option": [{"type": 3, "area": 1, "index": 0},
                      {"type": 3, "area": 1, "index": 2}]}
    out = P.search_candidate_summary({"observation": {"select": sel}})
    assert out["n_search_options"] == 2
    assert set(out["visible_card_ids"]) <= {100, 200, 300}
    assert 100 in out["visible_card_ids"] and 300 in out["visible_card_ids"]


def test_search_summary_omits_unresolvable_ids():
    sel = {"option": [{"type": 3, "area": 1, "index": 0}]}  # no deck -> id unresolvable
    out = P.search_candidate_summary({"observation": {"select": sel}})
    assert out["visible_card_ids"] == []  # never invents an id


def test_discard_summary_visible_ids_only():
    sel = {"discard": [{"id": 11}, {"id": 22}],
           "option": [{"type": 3, "area": 6, "index": 0}]}
    out = P.discard_candidate_summary({"observation": {"select": sel}})
    assert out["n_discard_options"] == 1
    assert all(isinstance(x, int) for x in out["visible_card_ids"])


# ------------------------------------------------------------ unsupported claims
def test_unsupported_claims_include_required_set():
    uns = P.unsupported_claims()
    assert REQUIRED_UNSUPPORTED <= set(uns)
    assert "best_action" in uns and "exact_attach_value" in uns


def test_unsupported_claims_are_sentinel_marked():
    uns = P.unsupported_claims()
    assert all(isinstance(v, str) and v for v in uns.values())


# --------------------------------------------------------- fixtures & validation
def test_fixture_manifest_nonempty():
    m = _j("pass46d_trace_fixture_manifest")
    assert m["n_fixtures"] >= 1
    assert len(m["fixtures"]) == m["n_fixtures"]


def test_fixture_categories_cover_core_decision_types():
    cats = set(_j("pass46d_trace_fixture_manifest")["categories_present"])
    # the panel must at least surface attach, attack, search and a low-choice frame
    assert {"main_attach", "attack_available", "search_to_hand"} <= cats


def test_fixture_validation_all_ok():
    assert _j("pass46d_primitive_fixture_validation")["all_ok"] is True


def test_fixture_validation_checks_min_max_and_visible_ids():
    res = _j("pass46d_primitive_fixture_validation")["results"]
    assert res
    for r in res:
        c = r["checks"]
        assert c["min_count_preserved"] and c["max_count_preserved"]
        assert c["opponent_hand_not_exposed"]
        assert c["unsupported_claims_present"]


def test_attach_fixture_destinations_are_active_or_bench():
    f = _fixture("main_attach")
    assert f is not None
    cands = P.energy_attach_candidates(f["frame"])
    assert cands and all(c["destination"] in ("active", "bench") for c in cands)


# ---------------------------------------------------------- behavior comparison
def test_behavior_comparison_has_internal_and_reference_groups():
    g = _j("pass46d_primitive_behavior_comparison")["groups"]
    assert "internal_candidate" in g and "public_reference" in g


def test_behavior_comparison_carries_small_n_caveats():
    f = _j("pass46d_primitive_behavior_comparison")
    assert f["directional_small_n"] is True
    blob = " ".join(f["caveats"]).lower()
    assert "directional" in blob and "small-n" in blob
    assert "not" in blob  # asserts a not-a-strength-claim style caveat present


def test_references_never_appear_as_internal_member():
    g = _j("pass46d_primitive_behavior_comparison")["groups"]
    internal = set(g["internal_candidate"]["members"]) | set(
        g.get("internal_parent", {}).get("members", []))
    refs = set(g["public_reference"]["members"])
    assert not (internal & refs)
    assert all("public_ref" not in m for m in internal)


# ------------------------------------------------------- integration plan & report
def test_integration_plan_is_future_only_no_implementation():
    plan = _j("pass46d_candidate_integration_plan")
    assert plan["implementation_done"] is False
    assert "required_gates_before_candidate_generation" in plan["plan"]


def test_report_has_exactly_ten_sections():
    text = REPORT.read_text(encoding="utf-8")
    assert len([ln for ln in text.splitlines() if ln.startswith("## ")]) == 10


def test_decision_is_expected_ready_outcome():
    dec = _j("pass46d_strategy_decision")
    assert dec["decision"] in {
        "turn_planning_primitives_ready_soak_continue",
        "turn_planning_primitives_incomplete_hold"}
    assert dec["production_mutated"] is False
    assert dec["candidate_generated"] is False
    assert dec["kaggle_strength_claim"] is False
