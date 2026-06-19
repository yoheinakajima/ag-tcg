#!/usr/bin/env python3
"""Pass 25 (Part H) — decision replay on the real loss/positive-control windows.

LOCAL ONLY. Replays the REAL observations our analyzed seat actually faced in the
three Part-C episodes through the CONTROL (Pass-22 pivot) and each Pass-25
candidate, at every Main/search/discard/draw-count decision (ctx 0/7/8/38). For
each decision it records what the control chose vs what the candidate chose, and
classifies whether the candidate made a LEGAL, NARROW change confined to the
seam-context its hook targets:

  * deckout_guard_v1          targets ctx38 (low-deck draw-count clamp)
  * prize_liability_guard_v1  targets ctx7  (prize-liability search pivot)
  * hybrid_guard_v1           targets ctx7 + ctx38

A change OUTSIDE a candidate's target context is a MISFIRE (must be 0, since all
other flags/contexts are identical to the control). On the positive-control
episode (80622745, a healthy-deck win) no candidate may diverge from the control.

This proves narrowness/safety of the deltas; it is NOT a strength signal. No
upload, no submission, no root edits. Writes
data/reports/pass25_decision_replay.{json,md}.
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
WINDOWS = REPO / "data" / "experiments" / "pass25_loss_windows.jsonl"
OUT_JSON = REPO / "data" / "experiments" / "pass25_decision_replay.json"
OUT_MD = REPO / "data" / "experiments" / "pass25_decision_replay.md"

CONTROL_TAR = (REPO / "data" / "submissions" / "candidates_pass22"
               / "league_water_anti_disruption_pivot_v1.tar.gz")
CANDIDATES = [
    ("deckout_guard_v1", {38},
     REPO / "data" / "submissions" / "candidates_pass25" / "deckout_guard_v1.tar.gz"),
    ("prize_liability_guard_v1", {7},
     REPO / "data" / "submissions" / "candidates_pass25"
     / "prize_liability_guard_v1.tar.gz"),
    ("hybrid_guard_v1", {7, 38},
     REPO / "data" / "submissions" / "candidates_pass25" / "hybrid_guard_v1.tar.gz"),
]
POSITIVE_CONTROL_EP = "80622745"
CTX = {0: "main", 7: "search_to_hand", 8: "discard", 38: "draw_count"}


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
        return {}, None
    players = cur.get("players") or []
    yi = cur.get("yourIndex")
    if isinstance(yi, int) and 0 <= yi < len(players):
        return players[yi] or {}, yi
    return {}, yi


def _pick_action(agent, obs, sel):
    """Run the agent; return {indices, legal, raw}. ``legal`` means a non-empty
    list of in-range option indices -- discard (ctx8) legitimately returns more
    than one index, so we do NOT require a single index here."""
    n = len(sel.get("option") or [])
    try:
        pick = agent(obs)
    except Exception as exc:  # noqa: BLE001
        return {"indices": None, "legal": False, "raw": {"error": repr(exc)}}
    if isinstance(pick, list) and pick and all(
            isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n
            for i in pick):
        return {"indices": list(pick), "legal": True, "raw": pick}
    return {"indices": None, "legal": False, "raw": pick}


def _decode(sel, idx):
    opts = sel.get("option") or []
    if not (isinstance(idx, int) and 0 <= idx < len(opts)):
        return {"index": idx, "in_range": False}
    o = opts[idx]
    d = {"index": idx, "in_range": True}
    if isinstance(o, dict):
        d["type"] = o.get("type")
        for k in ("number", "id", "area", "cardId"):
            if o.get(k) is not None:
                d[k] = o.get(k)
    return d


def _iter_decisions(raw, seat):
    """Yield (obs, sel, ctx) for OUR-seat decisions at ctx 0/7/8/38."""
    for step in raw.get("steps", []):
        if not isinstance(step, list):
            continue
        for rec in step:
            if not isinstance(rec, dict):
                continue
            obs = rec.get("observation")
            if not isinstance(obs, dict):
                continue
            me, yi = _own(obs)
            if yi != seat:
                continue
            sel = obs.get("select")
            if not isinstance(sel, dict):
                continue
            ctx = sel.get("context")
            if ctx in CTX and (sel.get("option") or []):
                yield obs, sel, ctx, me


def main() -> int:
    episodes = []
    if WINDOWS.exists():
        for line in WINDOWS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                episodes.append(json.loads(line))

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        control = _import_agent(CONTROL_TAR, tmp / "control")
        cand_agents = {cid: _import_agent(tar, tmp / cid)
                       for cid, _t, tar in CANDIDATES}

        per_candidate = {cid: {
            "target_contexts": sorted(targets),
            "decisions_examined": 0,
            "by_context": {},
            "changes": [],
            "changed_total": 0,
            "on_seam": 0,
            "misfires": 0,
            "illegal": 0,
            "ctx38_decisions_our_seat": 0,
            "ctx7_decisions_our_seat": 0,
            "positive_control_changes": 0,
        } for cid, targets, _t in CANDIDATES}
        targets_by_cid = {cid: targets for cid, targets, _t in CANDIDATES}

        per_episode = []
        for ep in episodes:
            eid = str(ep.get("episode_id"))
            seat = ep.get("analyzed_seat")
            raw_path = RAW / f"{eid}.json"
            if not raw_path.exists():
                per_episode.append({"episode_id": eid, "raw_present": False})
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            ep_ctx_counts = {}
            ep_changes = {cid: 0 for cid, _t, _ in CANDIDATES}
            for obs, sel, ctx, me in _iter_decisions(raw, seat):
                ep_ctx_counts[ctx] = ep_ctx_counts.get(ctx, 0) + 1
                c_act = _pick_action(control, obs, sel)
                deck_count = me.get("deckCount")
                for cid, agent in cand_agents.items():
                    rec = per_candidate[cid]
                    rec["decisions_examined"] += 1
                    rec["by_context"][CTX[ctx]] = rec["by_context"].get(CTX[ctx], 0) + 1
                    if ctx == 38:
                        rec["ctx38_decisions_our_seat"] += 1
                    if ctx == 7:
                        rec["ctx7_decisions_our_seat"] += 1
                    k_act = _pick_action(agent, obs, sel)
                    if not k_act["legal"]:
                        rec["illegal"] += 1
                    changed = (k_act["indices"] is not None
                               and c_act["indices"] is not None
                               and k_act["indices"] != c_act["indices"])
                    if not changed:
                        continue
                    rec["changed_total"] += 1
                    ep_changes[cid] += 1
                    on_seam = ctx in targets_by_cid[cid]
                    if on_seam:
                        rec["on_seam"] += 1
                    else:
                        rec["misfires"] += 1
                    if eid == POSITIVE_CONTROL_EP:
                        rec["positive_control_changes"] += 1
                    rec["changes"].append({
                        "episode_id": eid, "seam": ep.get("seam"),
                        "context": ctx, "context_name": CTX[ctx],
                        "deck_count": deck_count,
                        "control_indices": c_act["indices"],
                        "candidate_indices": k_act["indices"],
                        "control_choice": (_decode(sel, c_act["indices"][0])
                                           if c_act["indices"] else {"index": None}),
                        "candidate_choice": (_decode(sel, k_act["indices"][0])
                                             if k_act["indices"] else {"index": None}),
                        "candidate_legal": k_act["legal"],
                        "on_seam": on_seam,
                        "is_positive_control": eid == POSITIVE_CONTROL_EP,
                    })
            per_episode.append({
                "episode_id": eid, "seam": ep.get("seam"),
                "analyzed_seat": seat, "raw_present": True,
                "our_seat_decisions_by_context": {CTX[k]: v for k, v
                                                  in sorted(ep_ctx_counts.items())},
                "candidate_changes": ep_changes,
            })

    # Verdict per candidate.
    for cid, rec in per_candidate.items():
        rec["all_legal"] = rec["illegal"] == 0
        rec["narrow_no_misfire"] = rec["misfires"] == 0
        rec["positive_control_preserved"] = rec["positive_control_changes"] == 0
        rec["hook_had_applicable_decisions"] = (
            (38 in targets_by_cid[cid] and rec["ctx38_decisions_our_seat"] > 0)
            or (7 in targets_by_cid[cid] and rec["ctx7_decisions_our_seat"] > 0))

    summary = {
        "pass": "25", "part": "H", "local_only": True, "no_upload": True,
        "upload_performed": False,
        "control": "league_water_anti_disruption_pivot_v1 (Pass-22 pivot)",
        "note": ("Decision replay proves the candidate deltas are LEGAL, NARROW "
                 "(confined to the hook's target context) and do not perturb the "
                 "positive-control episode. It is a SAFETY proof, not a strength "
                 "signal; outcomes are not measured here."),
        "positive_control_episode": POSITIVE_CONTROL_EP,
        "per_episode": per_episode,
        "per_candidate": per_candidate,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    L = ["# Pass 25 — Decision Replay (Part H)", "",
         "> LOCAL ONLY. Control = `league_water_anti_disruption_pivot_v1` "
         "(Pass-22 pivot). Replays our analyzed seat's real decisions through "
         "control vs each candidate. Proves the deltas are legal/narrow; this is "
         "**not** a strength signal.", "",
         "## Our-seat decisions available per episode", "",
         "| episode | seam | ctx0 | ctx7 | ctx8 | ctx38 |", "|---|---|---|---|---|---|"]
    for e in per_episode:
        if not e.get("raw_present"):
            L.append(f"| {e['episode_id']} | (raw absent) | — | — | — | — |")
            continue
        c = e["our_seat_decisions_by_context"]
        L.append(f"| {e['episode_id']} | {e.get('seam')} | {c.get('main',0)} | "
                 f"{c.get('search_to_hand',0)} | {c.get('discard',0)} | "
                 f"{c.get('draw_count',0)} |")
    L += ["", "## Per-candidate verdict", "",
          "| candidate | target ctx | examined | changed | on-seam | misfires | "
          "illegal | pos-ctrl preserved | applicable decisions |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cid, r in per_candidate.items():
        L.append(f"| {cid} | {r['target_contexts']} | {r['decisions_examined']} | "
                 f"{r['changed_total']} | {r['on_seam']} | {r['misfires']} | "
                 f"{r['illegal']} | {r['positive_control_preserved']} | "
                 f"{r['hook_had_applicable_decisions']} |")
    L += ["", "## Changes (first 12)", "",
          "| candidate | episode | ctx | deck | control idx | candidate idx | legal | on-seam |",
          "|---|---|---|---|---|---|---|---|"]
    shown = 0
    for cid, r in per_candidate.items():
        for ch in r["changes"]:
            if shown >= 12:
                break
            L.append(f"| {cid} | {ch['episode_id']} | {ch['context_name']} | "
                     f"{ch['deck_count']} | {ch['control_choice'].get('index')} | "
                     f"{ch['candidate_choice'].get('index')} | "
                     f"{ch['candidate_legal']} | {ch['on_seam']} |")
            shown += 1
    if shown == 0:
        L.append("| _(none — no candidate diverged from control on our-seat windows)_ "
                 "| | | | | | | |")
    L += ["", "### Honest applicability note", "",
          "- The deckout hook targets **ctx38** (numeric draw-count). The observed "
          "deckout seam (80622626) ran through repeated **ctx7 searches / ctx0 "
          "optional-trainer plays** at low deck, and our analyzed seat faced "
          "**zero ctx38 decisions** in these episodes — so the ctx38 clamp is a "
          "generic self-deckout safety with **no applicable decision point on the "
          "real seam**.", "",
          summary["note"], ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    for cid, r in per_candidate.items():
        print(f"{cid:28} examined={r['decisions_examined']} changed={r['changed_total']} "
              f"on_seam={r['on_seam']} misfires={r['misfires']} illegal={r['illegal']} "
              f"pos_ctrl_preserved={r['positive_control_preserved']} "
              f"applicable={r['hook_had_applicable_decisions']}")
    print(f"-> {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
