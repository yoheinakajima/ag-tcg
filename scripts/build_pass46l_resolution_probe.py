#!/usr/bin/env python3
"""PASS 46L (Part B supplement) — option-resolution probe.

The Part-B trace found v0's chosen search / bench / discard cards mostly resolve to UNKNOWN
roles in live reference play, so the plan's role-keyed refinements rarely fire. Before designing
v1 we must know WHY: is it that ``resolve_play_card`` FAILS to map the offered option to a card
id (a real, fixable, visible-only resolution gap v1 could honestly close), or that the cards are
genuinely OFF the owned diamond role map (e.g. an option shape we cannot honestly attribute)?

This replays a couple of real games vs references (subprocess-isolated, hard-killable) and, for
every ACTIVE multi-option frame, dumps for each CHOSEN non-attack action option: the raw option
``type``/keys, area/index/inPlayArea/inPlayIndex, the ``resolve_play_card`` result, whether that
id is in the owned role map, the resolved roles, and the offered select.deck / your-hand lengths.
Aggregates: of chosen action options, how many resolve to an id, how many are in the role map,
how many carry non-empty roles. LOCAL / READ-ONLY; benchmark-only refs; no claims.
Writes data/experiments/pass46l_resolution_probe.{json,md}.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_ref_work"
TRACE_WORKER = ROOT / "scripts" / "_pass46c_trace_worker.py"
RAW_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_probe_raw"
SUBJECT = "cg_typed_diamond_specialist_planner_v0"
GAME_TIMEOUT = 30
ACTION_CTXS = {"search_to_hand", "discard", "setup_bench", "play_in_play",
               "choose_active", "attach_energy", "play_from_hand_engine"}

# A loss ref and a win ref from the Part-B panel, both seats.
PROBE_GAMES = [
    ("public_ref_kiyotah_iono", 0),
    ("public_ref_kiyotah_iono", 1),
    ("public_ref_kiyotah_mega_lucario", 0),
]


def _planner():
    subj_dir = REF_WORK / SUBJECT
    if str(subj_dir) not in sys.path:
        sys.path.insert(0, str(subj_dir))
    spec = importlib.util.spec_from_file_location("subj_main_probe", subj_dir / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _play(a_main: str, b_main: str, out_json: Path) -> dict:
    try:
        subprocess.run([sys.executable, str(TRACE_WORKER), a_main, b_main,
                        str(out_json), str(GAME_TIMEOUT)],
                       capture_output=True, text=True, timeout=GAME_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return {"ok": False}
    if not out_json.exists():
        return {"ok": False}
    try:
        return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"ok": False}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    mod = _planner()
    subj_main = str(REF_WORK / SUBJECT / "main.py")

    role_map = getattr(mod, "DIAMOND_ROLE_MAP", {})
    samples = []
    agg = Counter()
    by_ctx = {}
    games_done = 0
    for rid, seat in PROBE_GAMES:
        ref_main = str(REF_WORK / rid / "main.py")
        a = subj_main if seat == 0 else ref_main
        b = ref_main if seat == 0 else subj_main
        out_json = RAW_DIR / f"{rid}#s{seat}.json"
        rec = _play(a, b, out_json)
        if not rec.get("ok"):
            continue
        games_done += 1
        steps = rec.get("steps") or []
        for fr in steps:
            if seat >= len(fr):
                continue
            cell = fr[seat]
            if cell.get("status") != "ACTIVE":
                continue
            obs = cell.get("observation") or {}
            select = obs.get("select")
            board = obs.get("current")
            if not isinstance(select, dict):
                continue
            opts = select.get("option")
            if not isinstance(opts, list) or len(opts) < 2:
                continue
            try:
                view = mod.make_board_view(select, board)
                plan = mod.make_turn_plan(view)
                ann = getattr(mod, "_annotate_plan", None)
                if callable(ann):
                    ann(plan, view)
                chosen = mod.choose_indices(select, board)
            except Exception:  # noqa: BLE001
                continue
            deck = select.get("deck") if isinstance(select.get("deck"), list) else []
            hand = mod._your_hand(board)
            for i in chosen:
                if not (isinstance(i, int) and 0 <= i < len(opts)):
                    continue
                o = opts[i]
                ctx = mod._context_of(o, select, board, plan, None)
                if ctx not in ACTION_CTXS:
                    continue
                cid = mod.resolve_play_card(o, select, board)
                roles = sorted(mod._roles(cid, None))
                in_map = (cid in role_map) or (str(cid) in role_map) if cid is not None else False
                agg["chosen_action_options"] += 1
                if cid is not None:
                    agg["resolved_to_id"] += 1
                if in_map:
                    agg["id_in_role_map"] += 1
                if roles:
                    agg["nonempty_roles"] += 1
                d = by_ctx.setdefault(ctx, Counter())
                d["n"] += 1
                d["resolved"] += int(cid is not None)
                d["in_map"] += int(in_map)
                d["roles"] += int(bool(roles))
                if len(samples) < 60:
                    samples.append({
                        "ref": rid, "seat": seat, "ctx": ctx,
                        "opt_type": o.get("type") if isinstance(o, dict) else None,
                        "opt_keys": sorted(o.keys()) if isinstance(o, dict) else None,
                        "area": o.get("area") if isinstance(o, dict) else None,
                        "index": o.get("index") if isinstance(o, dict) else None,
                        "inPlayArea": o.get("inPlayArea") if isinstance(o, dict) else None,
                        "inPlayIndex": o.get("inPlayIndex") if isinstance(o, dict) else None,
                        "resolved_cid": cid, "in_role_map": in_map, "roles": roles,
                        "select_deck_len": len(deck), "your_hand_len": len(hand)})
        try:
            out_json.unlink()
        except Exception:  # noqa: BLE001
            pass

    n = agg["chosen_action_options"]
    data = {
        "pass": "46L", "part": "B-supplement", "read_only": True, "local_only": True,
        "no_upload": True, "benchmark_only": True, "subject": SUBJECT,
        "games_probed": games_done, "chosen_action_options": n,
        "resolved_to_id": agg["resolved_to_id"],
        "id_in_role_map": agg["id_in_role_map"],
        "nonempty_roles": agg["nonempty_roles"],
        "resolve_rate": round(agg["resolved_to_id"] / n, 4) if n else None,
        "in_map_rate": round(agg["id_in_role_map"] / n, 4) if n else None,
        "nonempty_role_rate": round(agg["nonempty_roles"] / n, 4) if n else None,
        "by_context": {k: dict(v) for k, v in by_ctx.items()},
        "samples": samples,
        "caveats": [
            "Benchmark-only references (cross-deck); no parity/strength/Kaggle claim.",
            "Diagnoses WHY role-keyed refinements are inert: a low resolve_rate means the "
            "option->card mapping itself fails (a fixable visible-only resolution gap); a high "
            "resolve_rate with low in_map_rate means the offered cards are genuinely off the "
            "owned diamond role map (not honestly attributable).",
        ],
    }
    (EXP / "pass46l_resolution_probe.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = ["# Pass 46L (Part B supplement) — option-resolution probe", "",
          "_Why are v0's chosen search/bench/discard roles mostly UNKNOWN in live reference "
          "play? Low resolve_rate => the option->card mapping fails (fixable visible-only gap). "
          "High resolve_rate + low in_map_rate => offered cards are genuinely off the owned "
          "role map (not honestly attributable). Benchmark-only; no claims._", "",
          f"- games probed: {games_done} | chosen action options examined: {n}",
          f"- resolve_rate (option->card id): **{data['resolve_rate']}** "
          f"({agg['resolved_to_id']}/{n})",
          f"- in_map_rate (id in owned role map): **{data['in_map_rate']}** "
          f"({agg['id_in_role_map']}/{n})",
          f"- nonempty_role_rate: **{data['nonempty_role_rate']}** "
          f"({agg['nonempty_roles']}/{n})", "",
          "## By context", "| context | n | resolved | in_map | roles |",
          "|---|:---:|:---:|:---:|:---:|"]
    for k, v in sorted(by_ctx.items()):
        md.append(f"| {k} | {v['n']} | {v['resolved']} | {v['in_map']} | {v['roles']} |")
    md += ["", "## Sample chosen action options (first few)",
           "| ref | ctx | type | keys | cid | in_map | roles | deck_len | hand_len |",
           "|---|---|:---:|---|:---:|:---:|---|:---:|:---:|"]
    for s in samples[:24]:
        md.append(f"| {s['ref'].replace('public_ref_','')} | {s['ctx']} | {s['opt_type']} | "
                  f"{','.join(s['opt_keys'] or [])} | {s['resolved_cid']} | {s['in_role_map']} | "
                  f"{'+'.join(s['roles']) or '-'} | {s['select_deck_len']} | {s['your_hand_len']} |")
    md += ["", "## Caveats"] + [f"- {c}" for c in data["caveats"]]
    (EXP / "pass46l_resolution_probe.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"games_probed": games_done, "chosen_action_options": n,
                      "resolve_rate": data["resolve_rate"], "in_map_rate": data["in_map_rate"],
                      "nonempty_role_rate": data["nonempty_role_rate"],
                      "by_context": data["by_context"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
