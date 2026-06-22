"""Pass 46J — Diamond cg_typed SPECIALIST TURN PLANNER v0 (LOCAL-ONLY).

Unit + cross-artifact tests for the ONE owned deck-specific turn planner for the
internal parent ``diamond_toolbox_diancie`` (a real DiamondBoardView / DiamondTurnPlan /
per-context-policy PLANNER, not a flat option scorer), its lane-separated ``cg_typed``
candidate, and the pre-registered strategy decision.

No network, no Kaggle, no native ``libcg.so`` execution, no real game runs here.

Honesty + safety invariants asserted: the planner is pure / never-raises / returns LEGAL
indices; it reads only your own visible board + the offered menu (never opponent hidden
hand contents); it declares — and refuses — every exact-damage / lethal / KO / missed-KO /
Boss-gust / spread / best-action strength claim; the candidate deck is byte-identical to the
parent while the owned ``main.py`` differs and matches NO public reference; nothing was
uploaded / promoted / mutated in production.

Forward-compatible: the pass DECISION is RE-DERIVED from the frozen pre-registered rule via
``build_pass46j_strategy_decision.derive_decision`` over the current evidence, and panel
assertions check invariants / ranges / cross-artifact consistency and the decision->gate-state
map rather than pinning shared numbers that legitimately move between re-runs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

from ptcg_activegraph.analysis import diamond_specialist as DS
from ptcg_activegraph.analysis import action_resolver as AR

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
SCRIPTS = REPO / "scripts"
CAND = REPO / "data" / "submissions" / "candidates_pass46j" / \
    "cg_typed_diamond_specialist_planner_v0.tar.gz"
PARENT = REPO / "data" / "submissions" / "candidates_pass34" / \
    "diamond_toolbox_diancie.tar.gz"
REF_DIR = REPO / "data" / "reference_agents" / "tarballs"

MAIN_ATTACKER = 766
ENERGY = 5


# --------------------------- helpers ---------------------------------------
def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _sha_member(tar: Path, name: str) -> str | None:
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name == name or m.name.endswith("/" + name):
                f = tf.extractfile(m)
                if f is not None:
                    return hashlib.sha256(f.read()).hexdigest()
    return None


def _member_text(tar: Path, name: str) -> str:
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf.getmembers():
            if m.name == name or m.name.endswith("/" + name):
                f = tf.extractfile(m)
                assert f is not None
                return f.read().decode("utf-8")
    raise AssertionError(f"{name} not found in {tar}")


def _tarball_region(tar: Path) -> str:
    text = _member_text(tar, "main.py")
    b = text.index(DS.INLINE_BEGIN_MARKER)
    e = text.index(DS.INLINE_END_MARKER) + len(DS.INLINE_END_MARKER)
    return text[b:e]


def _poke(cid, energy=0):
    return {"card_id": cid, "energyCards": [{"card_id": ENERGY} for _ in range(energy)]}


def _frame(active_id=MAIN_ATTACKER, active_energy=0, bench_ids=(), opp_active_id=None,
           turn=3, hand_ids=(), opp_hand_ids=(), your_index=0):
    you = {"active": [_poke(active_id, active_energy)] if active_id is not None else [],
           "bench": [_poke(c) for c in bench_ids],
           "hand": [{"card_id": c} for c in hand_ids],
           "deckCount": 40, "prizeCount": 6, "discardCount": 0}
    opp = {"active": [_poke(opp_active_id)] if opp_active_id is not None else [],
           "bench": [], "hand": [{"card_id": c} for c in opp_hand_ids],
           "deckCount": 40, "prizeCount": 6}
    players = [you, opp] if your_index == 0 else [opp, you]
    return {"turn": turn, "yourIndex": your_index, "players": players}


def _select(options, deck=None, min_count=1, max_count=None):
    s = {"option": options, "minCount": min_count,
         "maxCount": max_count if max_count is not None else min_count}
    if deck is not None:
        s["deck"] = deck
    return s


# the canonical discriminating menu (real plan != neutral plan top-1) reused across tests:
# active=525 (0 energy => energy short), 766 on bench (=> attacker in play), deck offers a
# 766 and an energy. Real plan wants the ENERGY (idx1); neutral plan wants the 766 (idx0).
DISCRIM_BOARD = _frame(active_id=525, active_energy=0, bench_ids=(MAIN_ATTACKER,), turn=3)
DISCRIM_SELECT = _select([{"type": 3, "area": 1, "index": 0},
                          {"type": 3, "area": 1, "index": 1}],
                         deck=[{"card_id": MAIN_ATTACKER}, {"card_id": ENERGY}])

GARBAGE = [None, 0, 5, -1, 1.5, True, False, "x", b"x", [], {}, (), {"option": "no"},
           {"option": [None, 5, "x"]}, {"players": "bad"}, {"players": [1, 2]},
           [1, 2, 3], {"option": [{"type": 999}]}]


@pytest.fixture(scope="module")
def strat_mod():
    path = SCRIPTS / "build_pass46j_strategy_decision.py"
    spec = importlib.util.spec_from_file_location("p46j_strat_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46j_strat_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


def _promising_ctx() -> dict:
    """A context with every gate green + a clean confirmed practical edge."""
    return {
        "safety_all_ok": True, "safety_stop_required": False,
        "validation_all_ok": True, "smoke_all_ok": True, "root_unchanged": True,
        "non_inert_ok": True, "non_inert_illegal": 0, "plan_field_driven_ok": True,
        "gating_unsafe_invalid": False, "references_excluded": True,
        "practical_label": "confirmed_edge", "practical_seat_confounded": False,
        "attributable_to_planner": True, "noise_clean": True,
    }


# ===================== A. pure planner: honesty + never-raise ==============
def test_unsupported_claims_declares_all_strength_claims():
    claims = set(DS.unsupported_claims())
    for forbidden in ("exact_damage", "lethal", "ko", "missed_ko", "boss_gust_target",
                      "spread", "best_action", "best_attack", "opponent_hand_contents",
                      "kaggle_score_or_strength"):
        assert forbidden in claims


@pytest.mark.parametrize("g", GARBAGE)
def test_make_board_view_never_raises(g):
    v = DS.make_board_view(g, g)
    assert isinstance(v, dict) and "fallback_reason" in v and "phase" in v


@pytest.mark.parametrize("g", GARBAGE)
def test_make_turn_plan_never_raises(g):
    p = DS.make_turn_plan(g)
    assert isinstance(p, dict) and "phase" in p and "attack_now" in p


@pytest.mark.parametrize("g", GARBAGE)
def test_score_options_never_raises(g):
    out = DS.score_options_from_plan(g, g, DS.neutral_plan())
    assert isinstance(out, list)
    for t in out:
        assert len(t) == 3


@pytest.mark.parametrize("g", GARBAGE)
def test_choose_indices_never_raises_and_legal(g):
    idx = DS.choose_indices(g, g)
    assert isinstance(idx, list)
    assert all(isinstance(i, int) and i >= 0 for i in idx)


def test_choose_indices_only_returns_offered_indices():
    sel = _select([{"type": 7, "area": 2, "index": 0},
                   {"type": 12}, {"type": 8, "inPlayArea": 4, "inPlayIndex": 0}])
    idx = DS.choose_indices(sel, _frame(hand_ids=(1121,)))
    assert all(0 <= i < 3 for i in idx)


def test_option_type_class_parity_with_action_resolver():
    assert DS.OPTION_TYPE_CLASS == AR.OPTION_TYPE_CLASS


def test_family_for_option_maps_codes_and_unknown():
    assert DS.family_for_option({"type": 8}) == "attach_energy"
    assert DS.family_for_option({"type": 13}) == "attack"
    assert DS.family_for_option({"type": 3}) == "select_card"
    assert DS.family_for_option({"type": 999}) == "unknown"
    assert DS.family_for_option("nope") == "unknown"


def test_role_map_main_attacker_and_energy():
    assert "main_attacker" in DS.DIAMOND_ROLE_MAP[MAIN_ATTACKER]
    assert "ex" in DS.DIAMOND_ROLE_MAP[MAIN_ATTACKER]
    assert "scaling_discard" in DS.DIAMOND_ROLE_MAP[MAIN_ATTACKER]
    assert DS.DIAMOND_ROLE_MAP[ENERGY] == ("energy",)


def test_roles_override_empty_map_is_no_roles_ablation():
    assert DS._roles(MAIN_ATTACKER, None) == DS.DIAMOND_ROLE_MAP[MAIN_ATTACKER]
    assert DS._roles(MAIN_ATTACKER, {}) == ()  # ablation: explicit empty override


def test_resolve_play_card_deck_hand_and_out_of_range():
    sel = _select([{"type": 3, "area": 1, "index": 1}], deck=[{"card_id": 1}, {"card_id": 2}])
    board = _frame(hand_ids=(7, 8))
    assert DS.resolve_play_card({"area": 1, "index": 1}, sel, board) == 2  # deck zone
    assert DS.resolve_play_card({"area": 2, "index": 0}, sel, board) == 7  # hand zone
    assert DS.resolve_play_card({"index": 1}, sel, board) == 8             # bare idx=hand
    assert DS.resolve_play_card({"area": 1, "index": 9}, sel, board) is None
    assert DS.resolve_play_card({"card_id": 766}, sel, board) == 766       # direct id


def test_make_board_view_reads_only_visible_self_and_opp_active():
    v = DS.make_board_view(DISCRIM_SELECT,
                           _frame(active_id=766, active_energy=2, bench_ids=(525, 751),
                                  opp_active_id=331, opp_hand_ids=(999, 998)))
    assert v["checkable"] is True
    assert v["my_active_id"] == 766
    assert v["my_active_energy_count"] == 2
    assert set(v["my_bench_ids"]) == {525, 751}
    assert v["opp_active_id"] == 331
    assert v["opp_active_is_ex"] is True  # 331 is an ex


def test_board_view_never_leaks_opponent_hidden_hand_contents():
    v = DS.make_board_view(DISCRIM_SELECT, _frame(opp_active_id=331, opp_hand_ids=(999, 998)))
    blob = json.dumps(v)
    assert "999" not in blob and "998" not in blob          # opp hand ids never surface
    assert "opp_hand" not in v and "opponent_hand" not in v
    # only COUNTS are exposed for the opponent
    assert set(v["opp_counts"]) == {"hand_count", "deck_count", "prize_remaining",
                                    "discard_count", "bench_count", "active_present"}


def test_infer_phase_setup_attack_develop():
    assert DS._infer_phase(0, {"active_present": False}, None, 0) == "setup"
    assert DS._infer_phase(1, {"active_present": True}, _poke(766), 0) == "setup"
    assert DS._infer_phase(4, {"active_present": True}, _poke(766, 2), 2) == "attack"
    assert DS._infer_phase(4, {"active_present": True}, _poke(766, 0), 0) == "develop"


def test_turn_plan_targets_main_attacker_and_energy():
    v = DS.make_board_view(_select([]), _frame(active_id=766, active_energy=0))
    p = DS.make_turn_plan(v)
    assert p["attacker_target"] == MAIN_ATTACKER
    assert p["energy_target"] == MAIN_ATTACKER
    assert ENERGY in p["search_targets"]            # energy short => search energy
    assert p["neutral"] is False


def test_turn_plan_searches_main_attacker_when_absent():
    v = DS.make_board_view(_select([]), _frame(active_id=525, active_energy=2))
    p = DS.make_turn_plan(v)
    assert MAIN_ATTACKER in p["search_targets"]      # attacker not in play => search it
    assert p["attacker_target"] is None


def test_attack_now_gate_requires_phase_energy_and_attacker():
    v_ok = DS.make_board_view(_select([]), _frame(active_id=766, active_energy=2, turn=4))
    assert DS.make_turn_plan(v_ok)["attack_now"] is True
    v_no = DS.make_board_view(_select([]), _frame(active_id=766, active_energy=0, turn=4))
    assert DS.make_turn_plan(v_no)["attack_now"] is False


def test_choose_search_picks_planned_energy_target():
    # real plan (energy short, attacker already in play) wants the ENERGY card (idx1)
    assert DS.choose_indices(DISCRIM_SELECT, DISCRIM_BOARD) == [1]


def test_choose_attach_prefers_energy_target_active():
    board = _frame(active_id=766, active_energy=0, bench_ids=(525,))
    sel = _select([{"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                   {"type": 8, "inPlayArea": 5, "inPlayIndex": 0}])
    assert DS.choose_indices(sel, board) == [0]      # attach to active main attacker


def test_discard_protects_main_attacker_but_picks_safe():
    board = _frame(active_id=766, active_energy=2, hand_ids=(ENERGY, 766))
    sel = _select([{"type": 3, "area": 2, "index": 0},
                   {"type": 3, "area": 2, "index": 1}])  # no deck => discard context
    assert DS.choose_indices(sel, board) == [0]      # discard surplus energy, not the 766


def test_protected_discard_still_returned_when_forced():
    board = _frame(active_id=525, active_energy=0, hand_ids=(766,))
    sel = _select([{"type": 3, "area": 2, "index": 0}])  # only the protected card offered
    assert DS.choose_indices(sel, board) == [0]      # protection never makes it illegal


def test_attack_options_ordered_by_attackid_only_no_damage_claim():
    sel = _select([{"type": 13, "attackId": 2}, {"type": 13, "attackId": 0},
                   {"type": 13, "attackId": 5}])
    plan = {"phase": "attack", "attack_now": True}
    scored = DS.score_options_from_plan(sel, {}, plan)
    order = [i for i, _s, _c in sorted(scored, key=lambda t: -t[1])]
    assert order == [1, 0, 2]                        # ascending attackId, arbitrary tiebreak
    assert all(c == "attack" for _i, _s, c in scored)


def test_attack_missing_id_is_neutral():
    assert DS._within("attack", {"type": 13}, {}, {}, {}, None) == 0.0


def test_planner_is_non_inert_vs_neutral_plan_ablation():
    real = DS.choose_indices(DISCRIM_SELECT, DISCRIM_BOARD)             # plan built internally
    neutral = DS.choose_indices(DISCRIM_SELECT, DISCRIM_BOARD, plan=DS.neutral_plan())
    assert real == [1] and neutral == [0] and real != neutral


def test_choose_indices_respects_min_count():
    sel = _select([{"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
                   {"type": 12}], min_count=2, max_count=2)
    idx = DS.choose_indices(sel, _frame(hand_ids=(1121, 1224)))
    assert len(idx) == 2 and len(set(idx)) == 2 and idx == sorted(idx)


def test_choose_indices_forced_single():
    assert DS.choose_indices(_select([{"type": 9}]), _frame()) == [0]


def test_end_turn_deprioritized_when_play_available():
    sel = _select([{"type": 7, "area": 2, "index": 0}, {"type": 12}])
    assert DS.choose_indices(sel, _frame(hand_ids=(1121,))) == [0]


# ===================== B. candidate artifact / lane separation ============
def test_candidate_tarball_present_and_top_level_members():
    assert CAND.is_file()
    with tarfile.open(CAND, "r:gz") as tf:
        names = {m.name for m in tf.getmembers()}
    assert "main.py" in names and "deck.csv" in names
    assert any(n.startswith("cg/") for n in names)


def test_candidate_deck_byte_identical_to_parent():
    assert _sha_member(CAND, "deck.csv") == _sha_member(PARENT, "deck.csv")


def test_candidate_main_differs_from_parent_main():
    assert _sha_member(CAND, "main.py") != _sha_member(PARENT, "main.py")


def test_inline_region_byte_identical_module_vs_tarball():
    assert _tarball_region(CAND) == DS.inline_region_text()


def test_inline_region_behavioral_parity_module_vs_tarball():
    ns: dict = {}
    exec(compile(_tarball_region(CAND), "<cand_region>", "exec"), ns)  # noqa: S102
    assert ns["choose_indices"](DISCRIM_SELECT, DISCRIM_BOARD) == \
        DS.choose_indices(DISCRIM_SELECT, DISCRIM_BOARD) == [1]


def test_candidate_main_no_src_import_no_network_uses_cg():
    text = _member_text(CAND, "main.py")
    # a provenance COMMENT may name the source module, but there must be no live src import
    assert "import ptcg_activegraph" not in text and "from ptcg_activegraph" not in text
    for net in ("requests", "urllib", "http.client", "socket", "aiohttp"):
        assert net not in text                            # no online Search in hot path
    assert ("import cg" in text or "from cg" in text)     # typed cg lane


def test_candidate_main_matches_no_public_reference():
    cand = _sha_member(CAND, "main.py")
    for ref in sorted(REF_DIR.glob("*.tar.gz")):
        assert cand != _sha_member(ref, "main.py")        # owned, not ref code


def test_candidate_main_declares_unsupported_claims_mirrored():
    region = _tarball_region(CAND)
    for forbidden in ("exact_damage", "lethal", "missed_ko", "boss_gust_target",
                      "spread", "best_action"):
        assert forbidden in region


def test_build_json_invariants():
    b = _load("pass46j_candidate_build.json")
    assert b["owned_candidate"] is True and b["public_reference"] is False
    assert b["is_planner_not_flat_scorer"] is True
    assert b["deck_unchanged"] is True
    assert b["inline_region_byte_identical"] is True
    assert b["no_src_import"] is True and b["no_online_search"] is True
    assert b["cg_imported"] is True
    assert b["candidate_ok"] is True
    assert b["production_mutated"] is False and b["no_upload"] is True


def test_validation_json_lane_separation_and_root_unchanged():
    v = _load("pass46j_candidate_validation.json")
    assert v["all_ok"] is True
    assert v["cg_typed_lane_accepts"]["accepts"] is True
    assert v["stdlib_lane_rejects"]["rejects"] is True
    assert v["deck_vs_parent"]["deck_byte_identical_to_parent"] is True
    assert v["is_planner_not_flat_scorer"] is True
    assert v["root_unchanged"]["root_main_unchanged"] is True
    assert v["root_unchanged"]["root_deck_unchanged"] is True
    assert v["production_mutated"] is False and v["no_upload"] is True


# ===================== C. strategy decision re-derivation =================
def test_derive_promising(strat_mod):
    assert strat_mod.derive_decision(_promising_ctx())["decision"] == \
        "diamond_specialist_promising_local_only"


def test_derive_directional_edge(strat_mod):
    ctx = _promising_ctx()
    ctx["practical_label"] = "directional_edge"
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_directional_needs_more_n"


def test_derive_confirmed_but_noise_dirty_is_directional(strat_mod):
    ctx = _promising_ctx()
    ctx["noise_clean"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_directional_needs_more_n"


def test_derive_no_edge_is_not_promising(strat_mod):
    ctx = _promising_ctx()
    ctx["practical_label"] = "no_edge"
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_not_promising"


def test_derive_confirmed_but_not_attributable_is_not_promising(strat_mod):
    ctx = _promising_ctx()
    ctx["attributable_to_planner"] = False
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_not_promising"


def test_derive_seat_confounded_is_not_promising(strat_mod):
    ctx = _promising_ctx()
    ctx["practical_seat_confounded"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == \
        "diamond_specialist_not_promising"


def test_derive_safety_stop_takes_precedence(strat_mod):
    ctx = _promising_ctx()
    ctx["safety_stop_required"] = True
    assert strat_mod.derive_decision(ctx)["decision"] == "safety_stop_required"


@pytest.mark.parametrize("mutate", [
    {"safety_all_ok": False}, {"validation_all_ok": False}, {"smoke_all_ok": False},
    {"root_unchanged": False}, {"non_inert_ok": False}, {"non_inert_illegal": 1},
    {"plan_field_driven_ok": False}, {"gating_unsafe_invalid": True},
    {"references_excluded": False},
])
def test_derive_validation_failed_on_any_broken_gate(strat_mod, mutate):
    ctx = _promising_ctx()
    ctx.update(mutate)
    assert strat_mod.derive_decision(ctx)["decision"] == "validation_failed"


@pytest.mark.parametrize("gate", [
    "attributable_to_planner", "noise_clean",
])
def test_promising_requires_all_positive_gates(strat_mod, gate):
    ctx = _promising_ctx()
    ctx[gate] = False
    assert strat_mod.derive_decision(ctx)["decision"] != \
        "diamond_specialist_promising_local_only"


def test_persisted_decision_matches_rederivation(strat_mod):
    persisted = _load("pass46j_strategy_decision.json")["decision"]
    rederived = strat_mod.derive_decision(strat_mod.build_context())["decision"]
    assert persisted == rederived


# ===================== D. eval panel + upstream invariants ================
def test_eval_panel_complete_and_ci_well_formed():
    d = _load("pass46j_diamond_eval_panel.json")
    assert d["complete"] is True
    for p in d["panels"]:
        assert 0.0 <= p["subject_win_rate"] <= 1.0
        assert p["wilson_low"] <= p["subject_win_rate"] <= p["wilson_high"]
        assert p["n_decisive"] >= 0
    assert d["n_invalid_total"] <= 0.05 * d["n_games_total"]   # invalid rate not unsafe


def test_eval_decision_gate_invariants_hold():
    """For whatever decision is persisted, its required gate-state must honestly hold."""
    panel = _load("pass46j_diamond_eval_panel.json")
    decision = _load("pass46j_strategy_decision.json")["decision"]
    by_id = {p["panel_id"]: p for p in panel["panels"]}
    practical = by_id["spec_vs_parent"]
    attributable = panel["attribution"]["attributable_to_planner"]
    if decision == "diamond_specialist_promising_local_only":
        assert practical["edge_label"] == "confirmed_edge"
        assert practical["wilson_low"] > 0.5 and practical["seat_confounded"] is False
        assert attributable is True
        for p in panel["panels"]:
            if p["arm"] == "noise_control":
                assert p["noise_ci_contains_half"] is True
    elif decision == "diamond_specialist_directional_needs_more_n":
        assert practical["edge_label"] in ("confirmed_edge", "directional_edge")
        assert attributable is True
    elif decision == "diamond_specialist_not_promising":
        assert (practical["edge_label"] in ("no_edge", "seat_confounded")
                or practical["seat_confounded"] or attributable is False)


def test_attribution_fisher_increments_internally_consistent():
    a = _load("pass46j_diamond_eval_panel.json")["attribution"]
    for _gen, inc in a["fisher_increments_vs_parent"].items():
        assert inc["significant"] == (inc["fisher_right_p"] < 0.05)


def test_safety_preflight_all_ok_and_no_prod_mutation():
    s = _load("pass46j_safety_preflight.json")
    assert s["all_ok"] is True and s["stop_required"] is False
    assert s["production_mutated"] is False and s["no_upload"] is True
    assert s["promotion_performed"] is False and s["registration_performed"] is False
    assert s["tick_executed"] is False


def test_smoke_and_non_inertness_gates():
    sm = _load("pass46j_diamond_smoke.json")
    ni = _load("pass46j_diamond_non_inertness.json")
    assert sm["all_ok"] is True and sm["root_main_deck_unchanged"] is True
    assert ni["non_inert_ok"] is True
    assert ni["non_inertness_vs_parent"]["illegal_decisions"] == 0
    assert ni["plan_field_driven_ok"] is True


def test_fixture_validation_all_ok_and_legal():
    f = _load("pass46j_planner_fixture_validation.json")
    assert f["all_ok"] is True
    assert f["all_indices_legal"] is True
    assert f["never_raise"]["all_safe"] is True


def test_references_are_benchmark_only_and_excluded():
    plan = _load("pass46j_diamond_eval_plan.json")
    assert not any("public_ref" in cid for cid in plan["participants"])
    assert plan["optional_reference_context"]["scheduled"] is False
    panel = _load("pass46j_diamond_eval_panel.json")
    ids = {p["subject_id"] for p in panel["panels"]} | \
        {p["opponent_id"] for p in panel["panels"]}
    assert not any("public_ref" in cid for cid in ids)


def test_blueprint_role_map_matches_embedded():
    bp = _load("pass46j_diamond_planner_blueprint.json")
    diff = DS.role_map_matches(bp["diamond_role_map"])
    assert diff["matches"] is True, diff


# ===================== E. events safety (Part K) ==========================
@pytest.fixture(scope="module")
def emit_mod():
    """Load the LOCAL events emitter as a module WITHOUT running main() (import-only)."""
    path = SCRIPTS / "emit_pass46j_events.py"
    spec = importlib.util.spec_from_file_location("p46j_emit_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p46j_emit_under_test"] = mod  # set before exec (script-as-module gotcha)
    spec.loader.exec_module(mod)
    return mod


# every dangerous event type the LOCAL-ONLY contract forbids this pass from emitting.
_MUST_FORBID = {
    "SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
    "CandidatePromoted", "DeckPromoted", "PolicyPromoted", "StrategyPromotionDecision",
    "OwnedCgCandidateRegistered", "PublicReferenceAgentRegistered",
    "TournamentParticipantRegistered", "BaselineRegistered", "HypothesisRegistered",
    "StrategyFamilyRegistered",
    "TournamentTickStarted", "TournamentTickFinished",
    "PublicBenchmarkTickStarted", "PublicBenchmarkTickFinished",
}
# the only types the emitter is allowed to write — must NOT be in the forbidden guard.
_ALLOWED_EMIT = {"LocalEvaluationFinished", "StrategyDecisionRecorded", "ReportSiteGenerated"}


def test_emit_guard_set_covers_all_forbidden_types(emit_mod):
    missing = _MUST_FORBID - set(emit_mod.FORBIDDEN_TYPES)
    assert not missing, f"guard set omits forbidden types: {sorted(missing)}"
    # the emitter must still be able to write its safe local-evaluation/decision/report types
    assert not (_ALLOWED_EMIT & set(emit_mod.FORBIDDEN_TYPES))


def test_events_json_local_only_and_clean():
    e = _load("pass46j_events.json")
    v = e["verification"]
    assert v["clean"] is True
    assert v["main_forbidden"] == [] and v["benchmark_forbidden"] == []
    assert v["main_no_upload_false"] == 0 and v["benchmark_no_upload_false"] == 0
    # negative invariants — this LOCAL pass changes NOTHING in production
    assert e["no_upload"] is True and e["upload_performed"] is False
    assert e["auto_submit"] is False and e["github_push"] is False
    assert e["candidate_promoted"] is False and e["candidate_registered"] is False
    assert e["redeploy"] is False and e["prod_mutated"] is False
    assert e["shared_report_site_regenerated"] is False
    assert e["references_emitted_to_benchmark_ledger"] is False
    assert e["references_excluded_from_eval"] is True
    assert e["emitted_main"] >= 9            # the >=9 core logical events
    assert _MUST_FORBID <= set(e["forbidden_types_never_emitted"])


def test_lab_ledger_pass46j_events_never_forbidden_and_no_upload(emit_mod):
    """Every pass46j-tagged event physically on the ledger is safe (defense in depth)."""
    path = emit_mod.LAB_EVENTS_PATH
    assert path.exists(), path
    seen = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if emit_mod.TAG not in (ev.get("tags") or []):
            continue
        seen += 1
        assert ev.get("event_type") not in emit_mod.FORBIDDEN_TYPES, ev.get("event_type")
        assert (ev.get("payload") or {}).get("no_upload") is True
    assert seen >= 9                         # our events are present and all clean
