#!/usr/bin/env python3
"""Pass 22 (Part J) — decision replay at the no-Pokemon-loss windows. LOCAL ONLY.

Replays the REAL observations from the lost episodes through BOTH the proven
reference agent (no Pass-22 hooks) and the Pass-22 candidate (with the three
flag-gated hooks). At every Main (ctx0) decision where OUR bench is empty and a
backup benchable Basic is playable from hand, it records what each agent chose,
proving the candidate makes a LEGAL, NARROW change (bench the backup basic)
exactly where the reference left the active orphaned.

No upload, no submission, no root edits. Raw replays are gitignored inputs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

RAW = REPO / "data" / "meta_replays" / "raw"
WINDOWS = REPO / "data" / "experiments" / "pass22_no_pokemon_loss_windows.jsonl"
OUT_JSON = REPO / "data" / "reports" / "pass22_decision_replay.json"
OUT_MD = REPO / "data" / "reports" / "pass22_decision_replay.md"

REFERENCE_TAR = (REPO / "data" / "submissions" / "candidates_pass17"
                 / "league_water_core_reference.tar.gz")
PIVOT_TAR = (REPO / "data" / "submissions" / "candidates_pass22"
             / "league_water_anti_disruption_pivot_v1.tar.gz")

# Benchable basics by role (NEVER by id guesswork): Kyogre 721, Snover 722.
PRIMARY_BASIC = {721}
SETUP_BASIC = {722}
BENCHABLE = PRIMARY_BASIC | SETUP_BASIC
MEGA = 723


def _import_agent(tar: Path, dest: Path):
    with tarfile.open(tar, "r:gz") as t:
        t.extractall(dest)  # noqa: S202 our own artifact
    main_path = dest / "main.py"
    old = os.getcwd()
    sys.path.insert(0, str(dest))
    os.chdir(dest)
    try:
        spec = importlib.util.spec_from_file_location(f"agent_{dest.name}", main_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)  # type: ignore
    finally:
        os.chdir(old)
        if str(dest) in sys.path:
            sys.path.remove(str(dest))
    fn = getattr(mod, "core_pilot_agent", None) or getattr(mod, "agent", None)
    if not callable(fn):
        raise RuntimeError(f"no agent entrypoint in {tar}")
    return fn


def _own(obs):
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return {}
    players = cur.get("players") or []
    yi = cur.get("yourIndex")
    if isinstance(yi, int) and 0 <= yi < len(players):
        return players[yi] or {}
    return {}


def _hand_ids(obs):
    return [c.get("id") for c in (_own(obs).get("hand") or []) if isinstance(c, dict)]


def _bench_ids(obs):
    return [c.get("id") for c in (_own(obs).get("bench") or []) if isinstance(c, dict)]


def _option_card(obs, opt, hand):
    """Resolve the card a Main option plays. type-7 = play hand[index]."""
    if not isinstance(opt, dict):
        return None
    if opt.get("type") == 7:
        ix = opt.get("index")
        if isinstance(ix, int) and not isinstance(ix, bool) and 0 <= ix < len(hand):
            return hand[ix]
    return None


def _action_summary(obs, idxs, options, hand):
    """Describe the chosen action: card benched, attack, or other type."""
    if not isinstance(idxs, list) or not idxs:
        return {"kind": "decline_or_empty", "card_id": None}
    i = idxs[0]
    if not (isinstance(i, int) and 0 <= i < len(options)):
        return {"kind": "out_of_range", "card_id": None}
    o = options[i]
    t = o.get("type") if isinstance(o, dict) else None
    cid = _option_card(obs, o, hand)
    if t == 13:
        return {"kind": "attack", "card_id": None}
    if t == 7 and cid in BENCHABLE:
        return {"kind": "bench_backup_basic", "card_id": cid}
    if t == 7:
        return {"kind": "play_from_hand", "card_id": cid}
    if t == 8:
        return {"kind": "attach", "card_id": None}
    if t in (12, 14):
        return {"kind": "end_turn", "card_id": None}
    return {"kind": "type_%s" % t, "card_id": cid}


def _iter_ctx0(raw):
    for step in raw.get("steps", []):
        if not isinstance(step, list):
            continue
        for rec in step:
            if not isinstance(rec, dict):
                continue
            obs = rec.get("observation")
            if not isinstance(obs, dict):
                continue
            sel = obs.get("select")
            if isinstance(sel, dict) and sel.get("context") == 0:
                yield obs, sel


def main() -> int:
    ref_results = {}
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        ref_agent = _import_agent(REFERENCE_TAR, tmp / "ref")
        pivot_agent = _import_agent(PIVOT_TAR, tmp / "pivot")

        episodes = []
        if WINDOWS.exists():
            for line in WINDOWS.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    episodes.append(json.loads(line))

        all_windows = []
        per_episode = []
        for ep in episodes:
            eid = ep.get("episode_id")
            raw_path = RAW / f"{eid}.json"
            if not raw_path.exists():
                per_episode.append({"episode_id": eid, "raw_present": False,
                                    "decision_windows": 0})
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            ep_windows = []
            for k, (obs, sel) in enumerate(_iter_ctx0(raw)):
                bench = _bench_ids(obs)
                if bench:
                    continue  # emergency hook only relevant on empty bench
                hand = _hand_ids(obs)
                options = sel.get("option") or []
                benchable_opt = any(
                    _option_card(obs, o, hand) in BENCHABLE for o in options)
                if not benchable_opt:
                    continue  # no legal backup-basic bench play here
                try:
                    ref_pick = ref_agent(obs)
                except Exception as exc:  # noqa: BLE001
                    ref_pick = {"error": repr(exc)}
                try:
                    pivot_pick = pivot_agent(obs)
                except Exception as exc:  # noqa: BLE001
                    pivot_pick = {"error": repr(exc)}
                ref_act = _action_summary(obs, ref_pick, options, hand)
                pivot_act = _action_summary(obs, pivot_pick, options, hand)
                legal = (isinstance(pivot_pick, list) and len(pivot_pick) == 1
                         and 0 <= pivot_pick[0] < len(options))
                w = {
                    "episode_id": eid, "ctx0_index": k,
                    "bench_empty": True,
                    "hand_ids": hand,
                    "n_options": len(options),
                    "reference_choice": ref_pick if isinstance(ref_pick, list) else ref_pick,
                    "reference_action": ref_act,
                    "pivot_choice": pivot_pick if isinstance(pivot_pick, list) else pivot_pick,
                    "pivot_action": pivot_act,
                    "pivot_legal_single": legal,
                    "changed": ref_pick != pivot_pick,
                    "pivot_benched_backup": pivot_act["kind"] == "bench_backup_basic",
                    "reference_left_active_orphaned": ref_act["kind"] != "bench_backup_basic",
                }
                ep_windows.append(w)
                all_windows.append(w)
            per_episode.append({
                "episode_id": eid, "raw_present": True,
                "root_cause": ep.get("no_pokemon_loss_root_cause"),
                "decision_windows": len(ep_windows),
                "pivot_fixes": sum(1 for w in ep_windows
                                   if w["pivot_benched_backup"]
                                   and w["reference_left_active_orphaned"]),
            })

    total = len(all_windows)
    fixes = sum(1 for w in all_windows
                if w["pivot_benched_backup"] and w["reference_left_active_orphaned"])
    all_legal = all(w["pivot_legal_single"] for w in all_windows) if all_windows else True
    summary = {
        "pass": "22", "part": "J", "local_only": True, "no_upload": True,
        "reference": "league_water_core_reference (no Pass-22 hooks)",
        "candidate": "league_water_anti_disruption_pivot_v1",
        "total_empty_bench_benchable_windows": total,
        "windows_pivot_benched_backup_where_reference_did_not": fixes,
        "all_pivot_choices_legal_single_option": all_legal,
        "per_episode": per_episode,
        "windows": all_windows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Pass 22 — Decision Replay (real loss windows)", "",
        "Reference = `league_water_core_reference` (no Pass-22 hooks). "
        "Candidate = `league_water_anti_disruption_pivot_v1`.", "",
        f"- empty-bench windows where a backup basic was playable: **{total}**",
        f"- windows the candidate benched a backup basic where the reference did "
        f"NOT: **{fixes}**",
        f"- every candidate choice was a single legal option index: **{all_legal}**",
        "",
        "| episode | root cause | windows | pivot fixes |",
        "|---|---|---|---|",
    ]
    for e in per_episode:
        if not e.get("raw_present"):
            lines.append(f"| {e['episode_id']} | (raw absent) | — | — |")
        else:
            lines.append(f"| {e['episode_id']} | {e.get('root_cause')} | "
                         f"{e['decision_windows']} | {e['pivot_fixes']} |")
    lines += ["", "## Sample windows (first 8)", "",
              "| episode | hand | reference action | candidate action | legal |",
              "|---|---|---|---|---|"]
    for w in all_windows[:8]:
        lines.append(
            f"| {w['episode_id']} | {w['hand_ids']} | "
            f"{w['reference_action']['kind']} | "
            f"{w['pivot_action']['kind']}"
            f"{(' ('+str(w['pivot_action']['card_id'])+')') if w['pivot_action']['card_id'] else ''} | "
            f"{w['pivot_legal_single']} |")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"decision replay: {total} windows, {fixes} pivot fixes, "
          f"all_legal={all_legal}")
    print(f"-> {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
