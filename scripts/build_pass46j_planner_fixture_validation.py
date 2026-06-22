#!/usr/bin/env python3
"""PASS 46J (Part G) — planner fixture tests (per-context policies + honesty).

Exercises the owned Diamond specialist planner module directly (read-only, pure) on a
battery of crafted diamond frames covering EVERY per-context policy, and asserts:

  * legal indices everywhere (in-range, distinct, honour min/max — incl. multi-pick);
  * each fixture dispatches to the intended context (every context policy is hit);
  * a coherent shared turn plan is built (public plan fields populated or honest-unknown);
  * the numeric-attackId tie-break actively reorders attacks (lower id offered LAST);
  * UNSUPPORTED claims stay unsupported — unsupported_claims() enumerates the prohibited
    categories (exact damage / lethal / missed-KO / KO / Boss-gust / spread / best-action /
    card value / hidden zones) and NO board-view or plan field name encodes such a claim;
  * HIDDEN-ZONE NON-USE is behavioural, not just structural: mutating the opponent's hidden
    hand / deck / prize CONTENTS leaves every decision byte-identical (the planner cannot be
    reading hidden information), and the board view exposes opponent COUNTS only;
  * never-raises on malformed / adversarial observations and always returns a list.

LOCAL / READ-ONLY. No ObjectStorage, EventStore, cg, Search, Kaggle, or file mutation beyond
the two report files. Writes data/experiments/pass46j_planner_fixture_validation.{json,md}.
Exit 0 iff all_ok.
"""
from __future__ import annotations

import json
from pathlib import Path

from ptcg_activegraph.analysis import diamond_specialist as ds

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
DECK40 = [0] * 40

# Exact underscore-token matches only (so legitimate fields like ``draw_deckout_safety``
# — which merely contains the substring "ko" inside "deckout" — and the public ``prize``
# COUNT are NOT false-flagged). A field NAME must not advertise a prohibited capability.
PROHIBITED_FIELD_TOKENS = {"damage", "lethal", "ko", "knock", "knockout",
                           "missed", "boss", "gust", "spread", "best"}


def _opts(select):
    if isinstance(select, dict) and isinstance(select.get("option"), list):
        return select["option"]
    return []


def _legal(select, idxs):
    """In-range, distinct, and honouring min/max (with the standard min<=n clamp)."""
    if not isinstance(idxs, list):
        return False
    n = len(_opts(select))
    if any((not isinstance(i, int)) or i < 0 or i >= n for i in idxs):
        return False
    if len(set(idxs)) != len(idxs):
        return False
    mn = select.get("minCount", 1) if isinstance(select, dict) else 1
    mx = select.get("maxCount", 1) if isinstance(select, dict) else 1
    mn = mn if isinstance(mn, int) else 1
    mx = mx if isinstance(mx, int) else 1
    if mx >= 0 and len(idxs) > mx:
        return False
    eff_min = min(mn, n) if mn > 0 else 0
    if len(idxs) < eff_min:
        return False
    return True


def _fixtures():
    """name -> {select, board, expect_context?, expect_pick_card?, expect_pick_type?,
    expect_pick_attack_id?, expect_n_picks?}."""
    return {
        "setup_choose_active": {
            "board": {"turn": 1, "yourIndex": 0, "players": [
                {"hand": [{"id": 525}, {"id": 766}], "deck": DECK40, "bench": [],
                 "prizes": [0] * 6, "discard": [], "active": []},
                {"hand": [0] * 7, "deck": DECK40, "bench": [], "active": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1}]},
            "expect_context": "choose_active", "expect_pick_card": 525},
        "setup_bench_fill": {
            "board": {"turn": 1, "yourIndex": 0, "players": [
                {"hand": [{"id": 751}, {"id": 1224}], "deck": DECK40, "bench": [],
                 "prizes": [0] * 6, "discard": [], "active": [{"id": 766}]},
                {"hand": [0] * 7, "deck": DECK40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
                {"type": 12}]},
            "expect_context": "setup_bench"},
        "attach_energy_to_attacker": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [{"id": 5}], "deck": DECK40, "bench": [{"id": 525,
                 "energyCards": [0]}], "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 766, "energyCards": [0]}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "inPlayArea": 5, "inPlayIndex": 0}, {"type": 12}]},
            "expect_context": "attach_energy"},
        "search_to_hand_attacker": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 1121}], "deck": DECK40, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "deck": [
                {"id": 766}, {"id": 1224}, {"id": 5}], "option": [
                {"type": 3, "area": 1, "index": 0}, {"type": 3, "area": 1, "index": 1},
                {"type": 3, "area": 1, "index": 2}]},
            "expect_context": "search_to_hand", "expect_pick_card": 766},
        "discard_protect_attacker": {
            "board": {"turn": 3, "yourIndex": 0, "players": [
                {"hand": [{"id": 766}, {"id": 434}], "deck": DECK40, "bench": [],
                 "prizes": [0] * 6, "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 3, "area": 2, "index": 0}, {"type": 3, "area": 2, "index": 1}]},
            "expect_context": "discard", "expect_pick_card": 434},
        "multi_play_main": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 767}, {"id": 751}, {"id": 186}], "deck": DECK40,
                 "bench": [], "prizes": [0] * 6, "discard": [], "active": [{"id": 766}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 2, "maxCount": 2, "option": [
                {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
                {"type": 7, "area": 2, "index": 2}]},
            "expect_context": "setup_bench", "expect_n_picks": 2},
        "draw_count_deckout_safe": {
            "board": {"turn": 6, "yourIndex": 0, "players": [
                {"hand": [0] * 2, "deck": [0] * 3, "bench": [], "prizes": [0] * 3,
                 "discard": [], "active": [{"id": 766, "energyCards": [0, 0]}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 0, "number": 1}, {"type": 0, "number": 3}]},
            "expect_context": "draw_count"},
        "use_ability": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": DECK40, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 9}, {"type": 12}]},
            "expect_context": "use_ability"},
        "move_energy_to_attacker": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 2, "deck": DECK40, "bench": [{"id": 766}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 525, "energyCards": [0]}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 6, "inPlayArea": 5, "inPlayIndex": 0}, {"type": 12}]},
            "expect_context": "move_energy"},
        "play_in_play_accel": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 183}], "deck": DECK40, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 10, "area": 2, "index": 0}, {"type": 12}]},
            "expect_context": "play_in_play"},
        "engine_search_trainer": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 1121}, {"id": 1224}], "deck": DECK40, "bench": [],
                 "prizes": [0] * 6, "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
                {"type": 12}]},
            "expect_context": "play_from_hand_engine"},
        "attack_gate_on": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": DECK40, "bench": [{"id": 525}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 766, "energyCards": [0, 0, 0]}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 13, "attackId": 0},
                {"type": 8, "inPlayArea": 4, "inPlayIndex": 0}]},
            "expect_context": "attack", "expect_pick_type": 13},
        "attack_id_tiebreak": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": DECK40, "bench": [{"id": 525}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 766, "energyCards": [0, 0, 0]}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 13, "attackId": 9},
                {"type": 13, "attackId": 5}]},
            "expect_context": "attack", "expect_pick_type": 13,
            "expect_pick_attack_id": 5},
        "end_turn_default": {
            "board": {"turn": 7, "yourIndex": 0, "players": [
                {"hand": [], "deck": DECK40, "bench": [], "prizes": [0] * 4,
                 "discard": [], "active": [{"id": 766, "energyCards": []}]},
                {"hand": [0] * 4, "deck": DECK40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 0}]}},
    }


def _public_plan(plan):
    return {k: v for k, v in plan.items() if not k.startswith("_")} if isinstance(
        plan, dict) else {}


def _run_fixtures():
    rows = []
    all_legal = True
    contexts_seen = set()
    for name, fr in _fixtures().items():
        sel, board = fr["select"], fr["board"]
        view = ds.make_board_view(sel, board)
        plan = ds.make_turn_plan(view)
        ds._annotate_plan(plan, view)
        scored = ds.score_options_from_plan(sel, board, plan)
        idx = ds.choose_indices(sel, board)
        legal = _legal(sel, idx)
        all_legal = all_legal and legal
        picked_ctx = (ds._context_of(_opts(sel)[idx[0]], sel, board, plan, None)
                      if idx else None)
        for _i, _s, c in scored:
            contexts_seen.add(c)
        public = _public_plan(plan)
        row = {"fixture": name, "phase": view.get("phase"), "choose": idx,
               "legal": legal, "picked_context": picked_ctx,
               "n_options": len(_opts(sel)), "n_plan_fields": len(public)}
        ok = legal and len(public) > 0
        if fr.get("expect_context") is not None:
            row["expect_context"] = fr["expect_context"]
            ok = ok and picked_ctx == fr["expect_context"]
        if "expect_pick_card" in fr and idx:
            got = ds.resolve_play_card(_opts(sel)[idx[0]], sel, board)
            row["picked_card"] = got
            ok = ok and got == fr["expect_pick_card"]
        if "expect_pick_type" in fr and idx:
            got = _opts(sel)[idx[0]].get("type")
            row["picked_type"] = got
            ok = ok and got == fr["expect_pick_type"]
        if "expect_pick_attack_id" in fr and idx:
            got = _opts(sel)[idx[0]].get("attackId")
            row["picked_attack_id"] = got
            ok = ok and got == fr["expect_pick_attack_id"]
        if "expect_n_picks" in fr:
            row["n_picks"] = len(idx)
            ok = ok and len(idx) == fr["expect_n_picks"]
        row["ok"] = bool(ok)
        rows.append(row)
    return rows, all_legal, sorted(contexts_seen)


def _claims_honest():
    claims = ds.unsupported_claims()
    is_seq = isinstance(claims, (list, tuple)) and len(claims) >= 10
    blob = " ".join(str(c).lower() for c in claims) if is_seq else ""
    need = {"damage": "damage" in blob, "lethal": "lethal" in blob,
            "ko": ("ko" in blob or "knock" in blob),
            "boss_gust": ("boss" in blob or "gust" in blob),
            "spread": "spread" in blob, "best_action": "best" in blob}
    # No board-view / plan field NAME may encode a prohibited claim (exact underscore-token
    # match, so "deckout"/"prize-count" public fields are not false-flagged).
    fr = _fixtures()["attack_gate_on"]
    view = ds.make_board_view(fr["select"], fr["board"])
    plan = ds.make_turn_plan(view)
    field_tokens = set()
    for k in list(view.keys()) + list(_public_plan(plan).keys()):
        field_tokens.update(str(k).lower().split("_"))
    leaky = sorted(field_tokens & PROHIBITED_FIELD_TOKENS)
    return {"n_claims": len(claims) if is_seq else 0, "claims_is_list": is_seq,
            "covers_categories": need, "all_categories_covered": all(need.values()),
            "field_names_with_prohibited_token": leaky,
            "no_claimy_field_names": not leaky}


def _hidden_zone_invariance():
    """Decisions must be byte-identical when only HIDDEN opponent zones change content."""
    cases = []
    ok_all = True
    for name, fr in _fixtures().items():
        sel = json.loads(json.dumps(fr["select"]))
        base = json.loads(json.dumps(fr["board"]))
        mut = json.loads(json.dumps(fr["board"]))
        # Mutate ONLY the opponent's hidden zones (hand / deck / prizes) CONTENTS.
        try:
            opp = mut["players"][1]
            opp["hand"] = [{"id": 766}, {"id": 1182}, {"id": 1121}, {"id": 5}]
            opp["deck"] = [{"id": 766}] * 30
            opp["prizes"] = [{"id": 766}] * 6
        except Exception:  # noqa: BLE001
            pass
        a = ds.choose_indices(sel, base)
        b = ds.choose_indices(sel, mut)
        same = a == b
        ok_all = ok_all and same
        cases.append({"fixture": name, "base": a, "opp_hidden_mutated": b,
                      "decision_invariant": same})
    # Structural: opponent block in the view is counts-only (no card-content containers).
    view = ds.make_board_view(_fixtures()["attack_gate_on"]["select"],
                              _fixtures()["attack_gate_on"]["board"])
    opp = view.get("opp_counts") or {}
    counts_only = isinstance(opp, dict) and not any(
        isinstance(v, (list, dict)) for v in opp.values())
    return {"all_decisions_invariant_to_hidden_zones": ok_all,
            "opp_block_counts_only": counts_only,
            "view_has_no_opp_hand_key": "opp_hand" not in view
            and "opp_hand_contents" not in view, "cases": cases}


def _never_raise():
    bad = [None, {}, {"option": None}, {"option": [{"type": "x"}]}, 123, "z",
           {"options": [{"type": 13}]},
           {"option": [{"type": 8, "inPlayArea": 4, "inPlayIndex": 9}]},
           {"deck": [{}], "option": [{"type": 3, "area": 1, "index": 0}]},
           {"select": {"option": [{"type": 13}], "minCount": -1, "maxCount": 99}}]
    boards = [None, {}, {"players": "bad"}, {"yourIndex": 0, "players": [{"active": []}]}]
    safe = 0
    total = 0
    for sel in bad:
        for board in boards:
            total += 1
            try:
                v = ds.make_board_view(sel, board)
                p = ds.make_turn_plan(v)
                ds.score_options_from_plan(sel, board, p)
                r = ds.choose_indices(sel, board)
                if isinstance(r, list):
                    safe += 1
            except Exception:  # noqa: BLE001
                pass
    return {"n_inputs": total, "n_safe": safe, "all_safe": safe == total}


def main() -> int:
    rows, all_legal, contexts_seen = _run_fixtures()
    fixtures_ok = all(r["ok"] for r in rows)
    claims = _claims_honest()
    hidden = _hidden_zone_invariance()
    never = _never_raise()

    expected_contexts = {"choose_active", "setup_bench", "attach_energy",
                         "search_to_hand", "discard", "draw_count", "use_ability",
                         "move_energy", "play_in_play", "play_from_hand_engine", "attack"}
    contexts_covered = expected_contexts.issubset(set(contexts_seen))

    all_ok = bool(
        fixtures_ok and all_legal and contexts_covered
        and claims["claims_is_list"] and claims["all_categories_covered"]
        and claims["no_claimy_field_names"]
        and hidden["all_decisions_invariant_to_hidden_zones"]
        and hidden["opp_block_counts_only"] and hidden["view_has_no_opp_hand_key"]
        and never["all_safe"])

    data = {"pass": "46j", "part": "G", "read_only": True, "local_only": True,
            "no_upload": True, "production_mutated": False,
            "n_fixtures": len(rows), "fixtures_ok": fixtures_ok,
            "all_indices_legal": all_legal, "contexts_seen": contexts_seen,
            "contexts_covered": contexts_covered,
            "claims_honesty": claims, "hidden_zone": {k: v for k, v in hidden.items()
                                                      if k != "cases"},
            "never_raise": never, "fixtures": rows,
            "hidden_zone_cases": hidden["cases"], "all_ok": all_ok}
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46j_planner_fixture_validation.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# PASS 46J · Part G — planner fixture tests", "",
        "_LOCAL / READ-ONLY. Exercises every per-context policy of the owned Diamond "
        "specialist planner, proves legality + context dispatch, that unsupported claims "
        "stay unsupported, and that decisions are INVARIANT to hidden-opponent-zone "
        "contents (the planner cannot be reading hidden information)._", "",
        f"**ALL OK:** **{all_ok}**", "",
        f"- fixtures pass: **{fixtures_ok}** ({len(rows)})",
        f"- all indices legal: **{all_legal}**",
        f"- every context covered: **{contexts_covered}** ({len(contexts_seen)} seen)",
        f"- unsupported-claims enumerated + all categories: "
        f"**{claims['all_categories_covered']}** ({claims['n_claims']} claims)",
        f"- no claim-encoding field names: **{claims['no_claimy_field_names']}**",
        f"- decisions invariant to hidden opp zones: "
        f"**{hidden['all_decisions_invariant_to_hidden_zones']}**",
        f"- opponent view is counts-only: **{hidden['opp_block_counts_only']}**",
        f"- never-raises on malformed input: **{never['all_safe']}** "
        f"({never['n_safe']}/{never['n_inputs']})", "",
        "## Per-fixture",
        "| fixture | phase | context | choose | legal | ok |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(f"| {r['fixture']} | {r.get('phase')} | {r.get('picked_context')} | "
                  f"{r['choose']} | {r['legal']} | {r['ok']} |")
    md += ["", f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**", ""]
    (EXP / "pass46j_planner_fixture_validation.md").write_text("\n".join(md) + "\n",
                                                               encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "fixtures_ok": fixtures_ok,
                      "all_legal": all_legal, "contexts_covered": contexts_covered,
                      "claims_ok": claims["all_categories_covered"]
                      and claims["no_claimy_field_names"],
                      "hidden_zone_invariant":
                      hidden["all_decisions_invariant_to_hidden_zones"],
                      "never_raise": never["all_safe"]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
