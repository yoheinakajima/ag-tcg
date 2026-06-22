#!/usr/bin/env python3
"""PASS 46L (Part G, blocking gate) — v1-vs-v0 non-inertness on REAL frames.

The architect's staged plan makes non-inertness a BLOCKING gate: before building any eval
panel we must show that v1 actually changes live decisions on real frames, and WHERE. If the
changed-decision rate is < 5% or the changes land only in forced/irrelevant contexts, the pass
stops with a clean-negative (diamond_v1_not_promising) and NO panel is run.

METHOD (same proven trace mechanism as Part B): play the v0 subject vs each ready reference and
vs the diamond parent, both seats, subprocess-isolated + hard-killable + resumable. For every
frame where the subject seat is ACTIVE with a real multi-option select, RE-RUN BOTH the v0 and
the v1 planner (choose_indices) on the recorded select+board and compare the chosen index sets.
Both planners are loaded from their src module files; the v0 candidate's INLINE region is
byte-identical to the v0 src module (parity guarantee), so re-scoring frames with the src v0 is
faithful to the candidate. Aggregate: changed-decision rate (overall + per context), the
attach_energy-specific change rate (the primary live lever), illegal-v1 and fallback-v1 counts.

HONESTY (hard): references are BENCHMARK-ONLY (never a gate); nothing here is a parity / Kaggle
/ strength / lethal / KO / best-action claim. A "changed decision" is only: the two
deterministic visible-only planners selected different legal option indices on the same frame.
LOCAL / READ-ONLY: no Object Storage, no Kaggle, no events, no tarball writes, no promotion.
Writes data/experiments/pass46l_non_inertness.{json,md} + a per-game ledger.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tarfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
READINESS = EXP / "pass46l_reference_readiness.json"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_ref_work"
TRACE_WORKER = ROOT / "scripts" / "_pass46c_trace_worker.py"
LEDGER = EXP / "pass46l_non_inertness_games.jsonl"
RAW_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_inert_raw"

V0_SRC = ROOT / "src" / "ptcg_activegraph" / "analysis" / "diamond_specialist.py"
V1_SRC = ROOT / "src" / "ptcg_activegraph" / "analysis" / "diamond_specialist_v1.py"
SUBJECT = "cg_typed_diamond_specialist_planner_v0"
SUBJECT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass46j"
                   / f"{SUBJECT}.tar.gz")
PARENT_ID = "diamond_parent"
PARENT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass34"
                  / "diamond_toolbox_diancie.tar.gz")
ALL_REFS = [
    "public_ref_kiyotah_dragapult", "public_ref_kiyotah_iono",
    "public_ref_kiyotah_mega_abomasnow", "public_ref_kiyotah_mega_lucario",
    "public_ref_ryotasueyoshi_alakazam",
]
GAME_TIMEOUT = 30
GAMES_PER_OPP = 2
MAX_FRAMES_PER_GAME = 40
NON_INERT_MIN_RATE = 0.05  # blocking-gate threshold (architect)


def _ref_tarball(rid: str) -> Path:
    return ROOT / "data" / "reference_agents" / "raw_outputs" / rid / "submission.tar.gz"


def _validate_tar_members(tarball: Path) -> bool:
    try:
        with tarfile.open(tarball, "r:gz") as t:
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    return False
                if m.issym() or m.islnk() or m.ischr() or m.isblk() or m.isfifo() or m.isdev():
                    return False
                if not (m.isfile() or m.isdir()):
                    return False
    except Exception:  # noqa: BLE001
        return False
    return True


def _safe_extract(tarball: Path, dest: Path) -> None:
    if (dest / "main.py").exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            t.extract(m, dest)


def _load_mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_extracted() -> tuple[Path, list[str], bool]:
    subj_dir = REF_WORK / SUBJECT
    if SUBJECT_TARBALL.exists() and _validate_tar_members(SUBJECT_TARBALL):
        _safe_extract(SUBJECT_TARBALL, subj_dir)
    ready: list[str] = []
    if READINESS.exists():
        try:
            ready = list(json.loads(READINESS.read_text(encoding="utf-8")).get(
                "ready_opponents") or [])
        except Exception:  # noqa: BLE001
            ready = []
    if not ready:
        ready = list(ALL_REFS)
    usable: list[str] = []
    for rid in ready:
        tb = _ref_tarball(rid)
        if tb.exists() and _validate_tar_members(tb):
            _safe_extract(tb, REF_WORK / rid)
            if (REF_WORK / rid / "main.py").exists():
                usable.append(rid)
    parent_ok = False
    if PARENT_TARBALL.exists() and _validate_tar_members(PARENT_TARBALL):
        _safe_extract(PARENT_TARBALL, REF_WORK / PARENT_ID)
        parent_ok = (REF_WORK / PARENT_ID / "main.py").exists()
    return subj_dir, usable, parent_ok


def _play_game(a_main: str, b_main: str, out_json: Path) -> dict:
    try:
        subprocess.run([sys.executable, str(TRACE_WORKER), a_main, b_main,
                        str(out_json), str(GAME_TIMEOUT)],
                       capture_output=True, text=True, timeout=GAME_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True, "error": "parent_timeout"}
    if not out_json.exists():
        return {"ok": False, "error": "no_output"}
    try:
        return json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"parse:{exc}"}


def _legal(idxs, n) -> bool:
    return isinstance(idxs, list) and all(isinstance(i, int) and 0 <= i < n for i in idxs)


def _compare_frame(m0, m1, obs: dict) -> dict | None:
    select = obs.get("select")
    board = obs.get("current")
    if not isinstance(select, dict):
        return None
    opts = select.get("option")
    if not isinstance(opts, list) or len(opts) < 2:
        return None
    n = len(opts)
    try:
        c0 = m0.choose_indices(select, board)
        c1 = m1.choose_indices(select, board)
        # context labels via v0 (shared dispatch); annotate plan for setup distinction.
        view0 = m0.make_board_view(select, board)
        plan0 = m0.make_turn_plan(view0)
        if callable(getattr(m0, "_annotate_plan", None)):
            m0._annotate_plan(plan0, view0)
        ctxs = [m0._context_of(o, select, board, plan0, None) for o in opts]
    except Exception as exc:  # noqa: BLE001
        return {"replay_error": repr(exc)}
    c0n = sorted(i for i in (c0 or []) if isinstance(i, int) and 0 <= i < n)
    c1n = sorted(i for i in (c1 or []) if isinstance(i, int) and 0 <= i < n)
    changed = c0n != c1n
    # contexts where the two picks differ (symmetric difference of chosen indices)
    diff_idx = sorted(set(c0n) ^ set(c1n))
    diff_ctxs = sorted({ctxs[i] for i in diff_idx}) if diff_idx else []
    attach_present = sum(1 for c in ctxs if c == "attach_energy") >= 2
    return {
        "n_options": n, "contexts_present": sorted(set(ctxs)),
        "v0_choice": c0n, "v1_choice": c1n, "changed": changed,
        "diff_contexts": diff_ctxs,
        "attach_multi_present": attach_present,
        "v0_legal": _legal(c0, n), "v1_legal": _legal(c1, n),
        "v1_fallback_empty": (c1 == []),
    }


def _extract_compare(m0, m1, rec: dict, seat: int) -> tuple[list, str]:
    steps = rec.get("steps") or []
    rewards = rec.get("rewards") or []
    rw = rewards[seat] if seat < len(rewards) else None
    outcome = ("win" if isinstance(rw, (int, float)) and rw > 0
               else "loss" if isinstance(rw, (int, float)) and rw < 0
               else "draw" if isinstance(rw, (int, float)) else "unknown")
    frames = []
    for fr in steps:
        if seat >= len(fr):
            continue
        cell = fr[seat]
        if cell.get("status") != "ACTIVE":
            continue
        obs = cell.get("observation") or {}
        cmp = _compare_frame(m0, m1, obs)
        if not cmp or cmp.get("replay_error"):
            continue
        frames.append(cmp)
        if len(frames) >= MAX_FRAMES_PER_GAME:
            break
    return frames, outcome


def _ledger_records() -> list:
    recs = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass
    return recs


def _planned_games(subj_dir: Path, opps: list[str]) -> list:
    subj_main = str(subj_dir / "main.py")
    games = []
    for oid in opps:
        opp_main = str(REF_WORK / oid / "main.py")
        for k in range(GAMES_PER_OPP):
            seat = k % 2
            a = subj_main if seat == 0 else opp_main
            b = opp_main if seat == 0 else subj_main
            games.append({"game_id": f"{oid}#s{seat}#g{k:02d}", "opp_id": oid,
                          "seat": seat, "a_main": a, "b_main": b})
    return games


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch-budget-seconds", type=float, default=110.0)
    ap.add_argument("--max-games-per-tick", type=int, default=2)
    a = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    subj_dir, refs, parent_ok = _ensure_extracted()
    if not (subj_dir / "main.py").exists():
        raise SystemExit("subject v0 not extracted")
    m0 = _load_mod(V0_SRC, "ds_v0_inert")
    m1 = _load_mod(V1_SRC, "ds_v1_inert")
    opps = list(refs) + ([PARENT_ID] if parent_ok else [])
    games = _planned_games(subj_dir, opps)

    done = {r["game_id"] for r in _ledger_records()}
    t0 = time.time()
    played = 0
    worst = GAME_TIMEOUT + 15 + 5
    for g in games:
        if played >= a.max_games_per_tick:
            break
        if time.time() - t0 > a.orch_budget_seconds - worst:
            break
        if g["game_id"] in done:
            continue
        out_json = RAW_DIR / f"{g['game_id']}.json"
        played += 1
        rec = _play_game(g["a_main"], g["b_main"], out_json)
        if not rec.get("ok"):
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"game_id": g["game_id"], "opp_id": g["opp_id"],
                                     "seat": g["seat"], "outcome": "error",
                                     "error": rec.get("error"), "frames": []}) + "\n")
        else:
            frames, outcome = _extract_compare(m0, m1, rec, g["seat"])
            with LEDGER.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"game_id": g["game_id"], "opp_id": g["opp_id"],
                                     "seat": g["seat"], "outcome": outcome,
                                     "n_frames": len(frames), "frames": frames}) + "\n")
        try:
            out_json.unlink()
        except Exception:  # noqa: BLE001
            pass

    recs = _ledger_records()
    ok_recs = [r for r in recs if r.get("outcome") != "error"]
    err_recs = [r for r in recs if r.get("outcome") == "error"]
    all_frames = [f for r in ok_recs for f in (r.get("frames") or [])]
    n = len(all_frames)
    changed = [f for f in all_frames if f.get("changed")]
    illegal_v1 = sum(1 for f in all_frames if not f.get("v1_legal"))
    fallback_v1 = sum(1 for f in all_frames if f.get("v1_fallback_empty"))
    by_ctx = Counter()
    for f in changed:
        for c in (f.get("diff_contexts") or []):
            by_ctx[c] += 1
    attach_frames = [f for f in all_frames if f.get("attach_multi_present")]
    attach_changed = sum(1 for f in attach_frames if f.get("changed"))

    planned_ids = {g["game_id"] for g in games}
    complete = planned_ids.issubset({r["game_id"] for r in recs})
    changed_rate = round(len(changed) / n, 4) if n else None
    attach_changed_rate = (round(attach_changed / len(attach_frames), 4)
                           if attach_frames else None)
    relevant = bool(by_ctx.get("attach_energy") or by_ctx.get("choose_active"))
    non_inert = bool(changed_rate is not None and changed_rate >= NON_INERT_MIN_RATE
                     and relevant and illegal_v1 == 0)

    data = {
        "pass": "46L", "part": "G", "read_only": True, "local_only": True, "no_upload": True,
        "reference_benchmark_only": True, "production_mutated": False,
        "subject_v0": SUBJECT, "candidate_v1": "cg_typed_diamond_specialist_planner_v1",
        "opponents": opps, "parent_runnable": parent_ok,
        "complete": complete, "games_ok": len(ok_recs), "games_error": len(err_recs),
        "frames": n,
        "changed_decisions": len(changed), "changed_decision_rate": changed_rate,
        "changed_by_context": dict(by_ctx.most_common()),
        "attach_multi_frames": len(attach_frames),
        "attach_multi_changed": attach_changed,
        "attach_multi_changed_rate": attach_changed_rate,
        "v1_illegal_decisions": illegal_v1,
        "v1_fallback_empty": fallback_v1,
        "non_inert_min_rate": NON_INERT_MIN_RATE,
        "changes_in_relevant_context": relevant,
        "non_inert_gate_pass": non_inert,
        "gate_interpretation": (
            "PROCEED to panels" if non_inert else
            "STOP -> diamond_v1_not_promising (changed-rate below threshold, no illegal "
            "decisions allowed, and changes must land in attach_energy/choose_active)"),
        "caveats": [
            "Changed decision = two deterministic visible-only planners picked different legal "
            "indices on the SAME real frame; NOT a win/strength/lethal/KO/best-action claim.",
            "References are benchmark-only and never a decision gate.",
            "Frames are drawn from the realized v0 trajectory; downstream play would diverge "
            "after the first changed decision (this is an argmax-divergence rate, by design).",
        ],
    }
    (EXP / "pass46l_non_inertness.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = ["# Pass 46L Part G — v1-vs-v0 non-inertness (blocking gate)", "",
          f"_Complete: {complete} | games ok/error: {len(ok_recs)}/{len(err_recs)} | "
          f"opponents: {', '.join(opps)} | parent runnable: {parent_ok}_", "",
          f"- frames examined (ACTIVE, >=2 options): **{n}**",
          f"- changed decisions: **{len(changed)}** -> changed-decision rate "
          f"**{changed_rate}** (gate threshold {NON_INERT_MIN_RATE})",
          f"- changed by context: {dict(by_ctx.most_common())}",
          f"- attach multi-option frames: {len(attach_frames)} | changed in those: "
          f"{attach_changed} (rate {attach_changed_rate})",
          f"- v1 illegal decisions: {illegal_v1} | v1 empty-fallback: {fallback_v1}",
          f"- changes land in a relevant context (attach/choose_active): {relevant}",
          "", f"## Gate: **{'PASS (non-inert)' if non_inert else 'FAIL (inert)'}** — "
          f"{data['gate_interpretation']}", "", "## Caveats"]
    md += [f"- {c}" for c in data["caveats"]]
    (EXP / "pass46l_non_inertness.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"complete": complete, "frames": n, "changed": len(changed),
                      "changed_rate": changed_rate, "changed_by_context": dict(by_ctx),
                      "attach_multi_frames": len(attach_frames),
                      "attach_multi_changed": attach_changed,
                      "v1_illegal": illegal_v1, "non_inert_gate_pass": non_inert}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
