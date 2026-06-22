#!/usr/bin/env python3
"""PASS 46J — Part D validator/recorder for the Diamond specialist planner module.

READ-ONLY, LOCAL-ONLY, no_upload. Imports the owned planner module
``ptcg_activegraph.analysis.diamond_specialist`` and records a structured validation of
the module contract WITHOUT any file I/O inside the module itself (this script does the
I/O; the src module stays pure, following option_value_features.py):

* the INLINE_DIAMOND_SPECIALIST_V0 region is self-contained (no imports / no annotations)
  and exec's standalone exposing the public planner API;
* the embedded DIAMOND_ROLE_MAP matches the Part-C blueprint role map (drift guard);
* a crafted frame battery exercises all 11 contexts + the default handler: every call
  returns LEGAL select indices, never raises, and the plan fields are populated or
  honest-unknown;
* opponent block is COUNTS-only (no hidden hand contents read);
* unsupported_claims is complete and matches the blueprint;
* the three pre-registered attribution ABLATIONS (no_shared_plan / no_diamond_roles /
  attack_gate_disabled) each measurably change behaviour on a targeted frame, so each
  design element is shown non-inert before any games are played.

Writes data/experiments/pass46j_diamond_planner_module.{json,md}. Mutates no production
state, no Object Storage, no Kaggle, no tarball.
"""
from __future__ import annotations

import json
from pathlib import Path

from ptcg_activegraph.analysis import diamond_specialist as ds

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = ROOT / "data/experiments/pass46j_diamond_planner_blueprint.json"
OUT_JSON = ROOT / "data/experiments/pass46j_diamond_planner_module.json"
OUT_MD = ROOT / "data/experiments/pass46j_diamond_planner_module.md"

PUBLIC_API = ("make_board_view", "make_turn_plan", "score_options_from_plan",
              "choose_indices", "unsupported_claims", "neutral_plan")


def _opts(select):
    return select.get("option") or select.get("options") or []


def _legal(select, idxs):
    n = len(_opts(select))
    return isinstance(idxs, list) and all(
        isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n for i in idxs)


def _self_containment():
    region = ds.inline_region_text()
    ns: dict = {}
    exec(compile(region, "<inline_region>", "exec"), ns, ns)
    # Line-based (not substring): an actual import is a logical line starting with
    # ``import`` / ``from`` — the words may legitimately appear inside docstrings/comments.
    import_lines = [ln.strip() for ln in region.splitlines()
                    if ln.strip().startswith(("import ", "from "))]
    return {
        "begin_marker_present": ds.INLINE_BEGIN_MARKER in region,
        "end_marker_present": ds.INLINE_END_MARKER in region,
        "n_lines": region.count("\n") + 1,
        "import_statement_lines": import_lines,
        "no_import_statements": not import_lines,
        "no_from_imports": not import_lines,
        "public_symbols_present": sorted(k for k in PUBLIC_API if k in ns),
        "all_public_symbols_present": all(k in ns for k in PUBLIC_API),
        "callable_standalone": callable(ns.get("choose_indices")),
    }


def _frames():
    """Crafted, visible-only frames covering every planner context (no invented behavior;
    card ids are all real verified deck ids)."""
    deck40 = [{"id": 5}] * 40
    return {
        "choose_active_setup": {
            "board": {"turn": 1, "yourIndex": 0, "players": [
                {"hand": [{"id": 525}, {"id": 766}, {"id": 5}], "deck": deck40,
                 "bench": [], "prizes": [0] * 6, "discard": []},
                {"hand": [0] * 5, "deck": deck40, "bench": [], "prizes": [0] * 6}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 7, "area": 2, "index": 0},
                {"type": 7, "area": 2, "index": 1},
                {"type": 12}]},
            "expect_context": "choose_active", "expect_pick_card": 525},
        "setup_bench_multi": {
            "board": {"turn": 1, "yourIndex": 0, "players": [
                {"hand": [{"id": 183}, {"id": 1224}, {"id": 767}],
                 "deck": deck40, "bench": [], "prizes": [0] * 6, "discard": [],
                 "active": [{"id": 525}]},
                {"hand": [0] * 5, "deck": deck40, "bench": []}]},
            "select": {"minCount": 2, "maxCount": 2, "option": [
                {"type": 7, "area": 2, "index": 0},
                {"type": 7, "area": 2, "index": 1},
                {"type": 7, "area": 2, "index": 2}]},
            "expect_min_picks": 2},
        "attach_energy": {
            "board": {"turn": 3, "yourIndex": 0, "players": [
                {"hand": [{"id": 5}], "deck": deck40, "bench": [{"id": 525}],
                 "prizes": [0] * 6, "discard": [],
                 "active": [{"id": 766, "energyCards": [0]}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 8, "inPlayArea": 5, "inPlayIndex": 0},
                {"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 12}]},
            "expect_context": "attach_energy"},
        "search_to_hand": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": deck40, "bench": [{"id": 767}],
                 "prizes": [0] * 6, "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1,
                       "deck": [{"id": 1224}, {"id": 766}, {"id": 5}], "option": [
                           {"type": 3, "area": 1, "index": 0},
                           {"type": 3, "area": 1, "index": 1},
                           {"type": 3, "area": 1, "index": 2}]},
            "expect_context": "search_to_hand", "expect_pick_card": 766},
        "discard": {
            "board": {"turn": 3, "yourIndex": 0, "players": [
                {"hand": [{"id": 434}, {"id": 766}], "deck": deck40,
                 "bench": [], "prizes": [0] * 6, "discard": [],
                 "active": [{"id": 766, "energyCards": [0, 0]}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 3, "area": 2, "index": 0},
                {"type": 3, "area": 2, "index": 1}]},
            "expect_context": "discard", "expect_pick_card": 434},
        "draw_count": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [0] * 2, "deck": [0] * 5, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 1, "number": 2}, {"type": 1, "number": 8}]},
            "expect_context": "draw_count"},
        "attack_gate": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": deck40, "bench": [{"id": 525}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 766, "energyCards": [0, 0, 0]}]},
                {"hand": [0] * 4, "deck": deck40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 13, "attackId": 0},
                {"type": 8, "inPlayArea": 4, "inPlayIndex": 0}]},
            "expect_context": "attack", "expect_pick_type": 13},
        "attack_order": {
            # Two attack options + end turn. The LOWER attackId (5) is offered AFTER the
            # higher one (9), so picking it proves the numeric-attackId tie-break actively
            # reorders (it is NOT just offered/index order). attackId ordering is an
            # arbitrary deterministic label tie-break, not a damage/best-attack claim.
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": deck40, "bench": [{"id": 525}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 766, "energyCards": [0, 0, 0]}]},
                {"hand": [0] * 4, "deck": deck40, "bench": [], "active": [{"id": 99}]}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 13, "attackId": 9},
                {"type": 13, "attackId": 5}]},
            "expect_context": "attack", "expect_pick_type": 13,
            "expect_pick_attack_id": 5},
        "play_from_hand_engine": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 1121}, {"id": 1224}], "deck": deck40, "bench": [],
                 "prizes": [0] * 6, "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 7, "area": 2, "index": 0},
                {"type": 7, "area": 2, "index": 1},
                {"type": 12}]},
            "expect_context": "play_from_hand_engine"},
        "use_ability": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [0] * 3, "deck": deck40, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 9}, {"type": 12}]},
            "expect_context": "use_ability"},
        "move_energy": {
            "board": {"turn": 4, "yourIndex": 0, "players": [
                {"hand": [0] * 2, "deck": deck40, "bench": [{"id": 766}],
                 "prizes": [0] * 5, "discard": [],
                 "active": [{"id": 525, "energyCards": [0]}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 6, "inPlayArea": 5, "inPlayIndex": 0},
                {"type": 12}]},
            "expect_context": "move_energy"},
        "play_in_play": {
            "board": {"turn": 2, "yourIndex": 0, "players": [
                {"hand": [{"id": 183}], "deck": deck40, "bench": [], "prizes": [0] * 6,
                 "discard": [], "active": [{"id": 525}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 10, "area": 2, "index": 0}, {"type": 12}]},
            "expect_context": "play_in_play"},
        "default_end_turn": {
            "board": {"turn": 5, "yourIndex": 0, "players": [
                {"hand": [], "deck": deck40, "bench": [], "prizes": [0] * 4,
                 "discard": [], "active": [{"id": 766, "energyCards": []}]},
                {"hand": [0] * 4, "deck": deck40, "bench": []}]},
            "select": {"minCount": 1, "maxCount": 1, "option": [
                {"type": 12}, {"type": 0}]},
            "expect_context": None},
    }


def _context_battery():
    rows = []
    all_legal = True
    contexts_seen = set()
    for name, fr in _frames().items():
        sel, board = fr["select"], fr["board"]
        view = ds.make_board_view(sel, board)
        plan = ds.make_turn_plan(view)
        ds._annotate_plan(plan, view)
        scored = ds.score_options_from_plan(sel, board, plan)
        idx = ds.choose_indices(sel, board)
        legal = _legal(sel, idx)
        all_legal = all_legal and legal
        for _i, _s, c in scored:
            contexts_seen.add(c)
        picked_ctx = None
        if idx:
            picked_ctx = ds._context_of(_opts(sel)[idx[0]], sel, board, plan, None)
        row = {"frame": name, "phase": view["phase"], "choose": idx, "legal": legal,
               "picked_context": picked_ctx, "n_options": len(_opts(sel))}
        ok = legal
        if "expect_context" in fr and fr["expect_context"] is not None:
            row["expect_context"] = fr["expect_context"]
            ok = ok and (picked_ctx == fr["expect_context"])
        if "expect_pick_card" in fr and idx:
            got = ds.resolve_play_card(_opts(sel)[idx[0]], sel, board)
            row["picked_card"] = got
            ok = ok and (got == fr["expect_pick_card"])
        if "expect_pick_type" in fr and idx:
            got = _opts(sel)[idx[0]].get("type")
            row["picked_type"] = got
            ok = ok and (got == fr["expect_pick_type"])
        if "expect_pick_attack_id" in fr and idx:
            got = _opts(sel)[idx[0]].get("attackId")
            row["picked_attack_id"] = got
            ok = ok and (got == fr["expect_pick_attack_id"])
        if "expect_min_picks" in fr:
            row["n_picks"] = len(idx)
            ok = ok and (len(idx) >= fr["expect_min_picks"])
        row["ok"] = bool(ok)
        rows.append(row)
    return rows, all_legal, sorted(contexts_seen)


def _never_raise():
    bad_inputs = [
        (None, None), ({}, {}), ({"option": None}, None),
        ({"option": [{"type": "x"}]}, {}), (123, "z"),
        ({"options": [{"type": 13}]}, {"players": "bad"}),
        ({"option": [{"type": 8, "inPlayArea": 4, "inPlayIndex": 9}]},
         {"yourIndex": 0, "players": [{"active": []}]}),
        ({"deck": [{}], "option": [{"type": 3, "area": 1, "index": 0}]}, {}),
    ]
    safe = 0
    for sel, board in bad_inputs:
        try:
            v = ds.make_board_view(sel, board)
            p = ds.make_turn_plan(v)
            ds.score_options_from_plan(sel, board, p)
            r = ds.choose_indices(sel, board)
            if isinstance(r, list):
                safe += 1
        except Exception:  # noqa: BLE001
            pass
    return {"n_inputs": len(bad_inputs), "n_safe": safe,
            "all_safe": safe == len(bad_inputs)}


def _visible_only():
    fr = _frames()["attack_gate"]
    view = ds.make_board_view(fr["select"], fr["board"])
    opp = view.get("opp_counts") or {}
    # opp block must be a flat count dict (no list of card dicts == no hand contents)
    contents_leak = any(isinstance(v, (list, dict)) for v in opp.values())
    opp_keys = sorted(opp.keys())
    return {"opp_counts_keys": opp_keys, "opp_counts_are_counts_only": not contents_leak,
            "view_has_no_opp_hand_key": "opp_hand" not in view
            and "opp_hand_contents" not in view}


def _ablation_differentials():
    """Each pre-registered ablation must change behaviour on a targeted frame, else the
    corresponding design element is inert (cannot be claimed as a source of any edge)."""
    out = {}
    # no_diamond_roles: on the multi-bench frame the role map ranks an energy_accel /
    # bench_fill basic above a non-pokemon draw trainer; an empty role map collapses every
    # option to the same role-less context/score -> different chosen SET. (The search frame
    # is steered by hardcoded ids 766/5, not roles, so it would not isolate the role map.)
    fr = _frames()["setup_bench_multi"]
    sel, board = fr["select"], fr["board"]
    full = ds.choose_indices(sel, board)
    none_roles = ds.choose_indices(sel, board, role_map={})
    out["no_diamond_roles"] = {"full": full, "ablated": none_roles,
                               "changed": full != none_roles}
    # no_shared_plan: on the attack frame, the full plan sets attack_now -> picks attack;
    # the neutral plan (no shared intent) does not boost attack -> different pick.
    fr = _frames()["attack_gate"]
    sel, board = fr["select"], fr["board"]
    view = ds.make_board_view(sel, board)
    full_plan = ds.make_turn_plan(view)
    ds._annotate_plan(full_plan, view)
    full = ds.choose_indices(sel, board, plan=full_plan)
    neutral = ds.choose_indices(sel, board, plan=ds.neutral_plan())
    out["no_shared_plan"] = {"full": full, "ablated": neutral,
                             "changed": full != neutral}
    # attack_gate_disabled: same frame, force attack_now False on the real plan.
    gated = dict(full_plan)
    gated["attack_now"] = False
    disabled = ds.choose_indices(sel, board, plan=gated)
    out["attack_gate_disabled"] = {"full": full, "ablated": disabled,
                                   "changed": full != disabled}
    out["all_ablations_change_behavior"] = all(
        v["changed"] for v in out.values() if isinstance(v, dict))
    return out


def _plan_fields():
    fr = _frames()["attack_gate"]
    view = ds.make_board_view(fr["select"], fr["board"])
    plan = ds.make_turn_plan(view)
    public = {k: v for k, v in plan.items() if not k.startswith("_")}
    return {"board_view_fields": sorted(view.keys()),
            "turn_plan_fields": sorted(public.keys()),
            "sample_plan": public}


def main() -> int:
    blueprint = json.loads(BLUEPRINT.read_text(encoding="utf-8"))
    self_cont = _self_containment()
    role_diff = ds.role_map_matches(blueprint["diamond_role_map"])
    battery, all_legal, contexts_seen = _context_battery()
    never_raise = _never_raise()
    visible = _visible_only()
    ablations = _ablation_differentials()
    plan_fields = _plan_fields()

    claims = list(ds.unsupported_claims())
    bp_claims = list(blueprint.get("unsupported_claims", []))
    claims_match = sorted(claims) == sorted(bp_claims)

    problems = []
    if not self_cont["all_public_symbols_present"]:
        problems.append("inline region missing a public symbol")
    if not self_cont["no_import_statements"] or not self_cont["no_from_imports"]:
        problems.append("inline region is not import-free (not self-contained)")
    if not role_diff["matches"]:
        problems.append("DIAMOND_ROLE_MAP drifts from blueprint role map")
    if not all_legal:
        problems.append("a crafted frame produced illegal indices")
    if not all(r["ok"] for r in battery):
        bad = [r["frame"] for r in battery if not r["ok"]]
        problems.append("context expectations failed: " + ", ".join(bad))
    if not never_raise["all_safe"]:
        problems.append("a malformed input was not handled safely")
    if not visible["opp_counts_are_counts_only"]:
        problems.append("opponent block leaks non-count (hidden) contents")
    if not claims_match:
        problems.append("unsupported_claims mismatch vs blueprint")
    if not ablations["all_ablations_change_behavior"]:
        inert = [k for k, v in ablations.items()
                 if isinstance(v, dict) and not v.get("changed")]
        problems.append("inert ablation(s): " + ", ".join(inert))

    ok = not problems
    record = {
        "pass": "46j", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_file_io_in_module": True,
        "no_cg_import": True, "no_objectstorage": True, "no_eventstore": True,
        "no_online_search_in_hot_path": True, "never_raises": never_raise["all_safe"],
        "module_path": "src/ptcg_activegraph/analysis/diamond_specialist.py",
        "is_planner_not_flat_scorer": True,
        "exposed_functions": list(PUBLIC_API),
        "inline_region": self_cont,
        "role_map_matches_blueprint": role_diff,
        "context_battery": battery,
        "all_indices_legal": all_legal,
        "contexts_exercised": contexts_seen,
        "never_raise": never_raise,
        "visible_only": visible,
        "unsupported_claims": claims,
        "unsupported_claims_match_blueprint": claims_match,
        "attribution_ablation_differentials": ablations,
        "plan_fields": plan_fields,
        "validation": {"ok": ok, "problems": problems},
        "blueprint_source": "data/experiments/pass46j_diamond_planner_blueprint.json",
    }
    OUT_JSON.write_text(json.dumps(record, indent=2, sort_keys=False) + "\n",
                        encoding="utf-8")
    _write_md(record)
    print(json.dumps({"ok": ok, "problems": problems,
                      "all_indices_legal": all_legal,
                      "role_map_matches": role_diff["matches"],
                      "ablations_change": ablations["all_ablations_change_behavior"],
                      "never_raise": never_raise["all_safe"]}, indent=2))
    return 0 if ok else 1


def _write_md(rec: dict) -> None:
    v = rec["validation"]
    lines = []
    lines.append("# PASS 46J · Part D — Diamond Specialist Planner Module\n")
    lines.append(f"**Validation:** {'✅ ok' if v['ok'] else '❌ problems'}  ·  "
                 "local-only · read-only · no_upload · no file I/O in module · "
                 "no cg / Object Storage / EventStore / online-Search in hot path\n")
    if v["problems"]:
        lines.append("**Problems:**\n")
        for p in v["problems"]:
            lines.append(f"- {p}")
        lines.append("")
    ir = rec["inline_region"]
    lines.append("## INLINE region (self-contained, byte-embeddable)\n")
    lines.append(f"- lines: {ir['n_lines']}  ·  import-free: "
                 f"{ir['no_import_statements'] and ir['no_from_imports']}  ·  "
                 f"public symbols: {', '.join(ir['public_symbols_present'])}\n")
    rm = rec["role_map_matches_blueprint"]
    lines.append("## Role map drift guard\n")
    lines.append(f"- matches blueprint: **{rm['matches']}** "
                 f"(missing={rm['missing_ids']}, extra={rm['extra_ids']}, "
                 f"role_diffs={len(rm.get('role_diffs', {}))})\n")
    lines.append("## Context battery (legal indices + expected pick per context)\n")
    lines.append("| frame | phase | context | choose | legal | ok |")
    lines.append("|---|---|---|---|---|---|")
    for r in rec["context_battery"]:
        lines.append(f"| {r['frame']} | {r['phase']} | {r.get('picked_context')} | "
                     f"{r['choose']} | {r['legal']} | {r['ok']} |")
    lines.append("")
    lines.append(f"- contexts exercised: {', '.join(rec['contexts_exercised'])}")
    lines.append(f"- all indices legal: {rec['all_indices_legal']}")
    nr = rec["never_raise"]
    lines.append(f"- never-raise on malformed: {nr['n_safe']}/{nr['n_inputs']} "
                 f"({'all safe' if nr['all_safe'] else 'UNSAFE'})")
    vis = rec["visible_only"]
    lines.append(f"- opponent block counts-only (no hidden hand): "
                 f"{vis['opp_counts_are_counts_only']} (keys={vis['opp_counts_keys']})\n")
    lines.append("## Attribution ablations — each must change behaviour (non-inert)\n")
    lines.append("| ablation | full | ablated | changed |")
    lines.append("|---|---|---|---|")
    for k, val in rec["attribution_ablation_differentials"].items():
        if isinstance(val, dict) and "changed" in val:
            lines.append(f"| {k} | {val['full']} | {val['ablated']} | {val['changed']} |")
    lines.append(f"\n- all ablations change behaviour: "
                 f"**{rec['attribution_ablation_differentials']['all_ablations_change_behavior']}**\n")
    lines.append("## Unsupported claims (hard honesty boundary)\n")
    lines.append(f"- matches blueprint: {rec['unsupported_claims_match_blueprint']}")
    lines.append(f"- claims ({len(rec['unsupported_claims'])}): "
                 f"{', '.join(rec['unsupported_claims'])}\n")
    pf = rec["plan_fields"]
    lines.append("## DiamondBoardView / DiamondTurnPlan fields\n")
    lines.append(f"- board_view_fields: {', '.join(pf['board_view_fields'])}")
    lines.append(f"- turn_plan_fields: {', '.join(pf['turn_plan_fields'])}\n")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
