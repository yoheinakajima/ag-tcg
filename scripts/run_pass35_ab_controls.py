#!/usr/bin/env python3
"""Pass 35 (T-K control) — null A/B self-mirror controls. LOCAL ONLY.

T-K measures child(typed) vs its identical untyped parent, seat-swapped. To know
whether a non-0.5 child win-rate reflects the typed layer or just engine/RNG noise,
we run the SAME harness on two self-mirrors where, by construction, there is NO
strategy difference:
  * parent_mirror — parent vs parent (same tarball both sides)
  * child_mirror  — child  vs child  (same tarball both sides)
In a self-mirror the seat-swapped aggregate of the labelled "A" side must be ~0.5;
its Wilson CI is the noise floor for this many games. A T-K child win-rate is only
credited as a real typed-layer effect when its CI clears the parent_mirror CI; where
T-K shows a strong result that the control does NOT explain we keep the claim, and
where the control reproduces the swing we downgrade T-K to inconclusive (no claim).

Internal self-play only; nothing uploaded/submitted/pushed. Resumable: re-invoke until
status=complete. Output pass35_ab_controls.{json,md}.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
BUILD = EXP / "pass35_candidate_build.json"
PROGRESS = EXP / "pass35_ab_controls_progress.json"
JSONL = EXP / "pass35_ab_ctrl_jsonl" / "ctrl.jsonl"
WORKER = REPO / "scripts" / "_pass35_tourney_worker.py"

GAMES_PER_SEAT = int(os.environ.get("P35_CTRL_GAMES_PER_SEAT", "10"))
GAME_TIMEOUT_S = int(os.environ.get("P35_GAME_TIMEOUT_S", "28"))
WORKER_BUDGET_S = int(os.environ.get("P35_PER_CALL_BUDGET_S", "80"))

DISCLAIMER = (
    "NULL A/B SELF-MIRROR CONTROL — both sides are the SAME agent, so any non-0.5 "
    "result is pure engine/RNG noise, not strategy. Used to calibrate the T-K "
    "child-vs-parent A/B. Internal self-play only; nothing uploaded/submitted/pushed.")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_TJ = _load("run_pass35_internal_tournament")
_wilson = _TJ._wilson
_fold = _TJ._fold
_MEV = _TJ._MEV
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball


def _arms() -> list[dict]:
    data = json.loads(BUILD.read_text(encoding="utf-8"))
    arms = []
    for r in data.get("candidates", []):
        if not r.get("built") or not r.get("tarball"):
            continue
        par = r.get("parent_tarball")
        if not par or not (REPO / par).exists():
            continue
        deck = r["candidate_id"]
        arms.append({"deck": deck, "arm": "parent_mirror",
                     "tar": str(REPO / par)})
        arms.append({"deck": deck, "arm": "child_mirror",
                     "tar": str(REPO / r["tarball"])})
    arms.sort(key=lambda x: (x["deck"], x["arm"]))
    return arms


def _schedule(arms: list[dict]) -> tuple[list[dict], dict]:
    sched, paths = [], {}
    for a in arms:
        key = f"{a['deck']}::{a['arm']}"
        ta, tb = key + "::A", key + "::B"
        paths[ta] = a["tar"]
        paths[tb] = a["tar"]
        for a_seat in (0, 1):
            for rep in range(GAMES_PER_SEAT):
                sched.append({"game_id": f"{key}::seat{a_seat}::r{rep}",
                              "a_id": ta, "b_id": tb, "a_seat": a_seat,
                              "deck": a["deck"], "arm": a["arm"]})
    return sched, paths


def _init() -> dict:
    arms = _arms()
    sched, paths = _schedule(arms)
    return {"pass": "35", "task": "T-K control", "local_only": True,
            "no_upload": True, "upload_performed": False,
            "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
            "config": {"games_per_seat": GAMES_PER_SEAT,
                       "game_timeout_s": GAME_TIMEOUT_S},
            "schedule": sched, "tarball_paths": paths}


def _extract(paths: dict, ids: set, tmp: Path) -> dict:
    agents = {}
    for tok in ids:
        tar = Path(paths.get(tok, ""))
        if tar.exists() and _validate_tarball(tar):
            agents[tok] = _extract_agent(tar, tmp / tok.replace("::", "_"))
    return agents


def _run_worker(pending: list[dict], agents: dict, tmp: Path) -> None:
    spec = []
    for g in pending:
        a, b, seat = g["a_id"], g["b_id"], g["a_seat"]
        if a not in agents or b not in agents:
            continue
        first = agents[a] if seat == 0 else agents[b]
        second = agents[b] if seat == 0 else agents[a]
        spec.append({"game_id": g["game_id"], "first_main": first,
                     "second_main": second, "a_id": a, "b_id": b, "a_seat": seat})
    if not spec:
        return
    sp = tmp / "spec.json"
    sp.write_text(json.dumps(spec), encoding="utf-8")
    hard = min(WORKER_BUDGET_S + GAME_TIMEOUT_S + 10, 115)
    try:
        subprocess.run([sys.executable, str(WORKER), str(sp), str(JSONL),
                        str(WORKER_BUDGET_S), str(GAME_TIMEOUT_S)],
                       capture_output=True, text=True, timeout=hard)
    except subprocess.TimeoutExpired:
        pass


def _summ(games: list[dict]) -> dict:
    w = sum(1 for x in games if x["a_outcome"] == "win")
    l = sum(1 for x in games if x["a_outcome"] == "loss")
    d = sum(1 for x in games if x["a_outcome"] == "draw")
    dec = w + l
    lo, hi = _wilson(w, dec)
    return {"n": len(games), "A_w": w, "A_l": l, "draws": d, "decisive": dec,
            "A_win_rate": round(w / dec, 4) if dec else None, "wilson": [lo, hi]}


def _save(prog: dict, results: dict, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    by = {}
    for g in prog["schedule"]:
        r = results.get(g["game_id"])
        if not r:
            continue
        by.setdefault((g["deck"], g["arm"]), []).append(r)
    rows = []
    for (deck, arm), games in sorted(by.items()):
        rows.append({"deck": deck, "arm": arm, **_summ(games)})
    n_done = sum(1 for s in prog["schedule"] if s["game_id"] in results)
    payload = {"pass": "35", "task": "T-K control", "kind": "null_ab_controls",
               "status": "complete" if done else "in_progress",
               "is_kaggle_leaderboard": False, "upload_performed": False,
               "no_upload": True, "disclaimer": prog["disclaimer"],
               "config": prog["config"], "games_done": n_done,
               "games_target": len(prog["schedule"]), "arms": rows}
    (EXP / "pass35_ab_controls.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")
    L = ["# Pass 35 — null A/B self-mirror controls (T-K control)", "",
         f"> {prog['disclaimer']}", "",
         f"- status: **{payload['status']}**  games {n_done}/{len(prog['schedule'])}  "
         f"is Kaggle leaderboard: **False**  upload_performed: **False**",
         f"- each arm: both sides identical, so A win-rate ~0.5 is expected; the CI is "
         f"the {2 * prog['config']['games_per_seat']}-game noise floor.", "",
         "| deck | arm | n | A W-L-D | A win_rate | 95% CI |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        ci = f"[{r['wilson'][0]}, {r['wilson'][1]}]"
        L.append(f"| {r['deck']} | {r['arm']} | {r['n']} | "
                 f"{r['A_w']}-{r['A_l']}-{r['draws']} | {r['A_win_rate']} | {ci} |")
    L += ["", "## How to use", "",
          "- If a parent_mirror CI is roughly centred on 0.5, the harness/engine is "
          "fair for that deck and a T-K child win-rate whose CI sits ABOVE this "
          "control's CI is a genuine typed-layer effect.",
          "- If a parent_mirror arm is itself lopsided, that deck's engine/RNG is "
          "noisy and the matching T-K verdict must be downgraded to inconclusive.", ""]
    (EXP / "pass35_ab_controls.md").write_text("\n".join(L), encoding="utf-8")
    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else _init())
    results = _fold(JSONL)
    pending = [g for g in prog["schedule"] if g["game_id"] not in results]
    start = time.time()
    if not pending:
        _save(prog, results, done=True)
        if PROGRESS.exists():
            PROGRESS.unlink()
        print(f"ab-controls COMPLETE: games={len(results)} remaining=0")
        return 0
    needed = {p for g in pending for p in (g["a_id"], g["b_id"])}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        agents = _extract(prog["tarball_paths"], needed, tmp)
        _run_worker(pending, agents, tmp)
    results = _fold(JSONL)
    left = len([g for g in prog["schedule"] if g["game_id"] not in results])
    done = left == 0
    _save(prog, results, done=done)
    if done and PROGRESS.exists():
        PROGRESS.unlink()
    print(f"ab-controls: left={left} status={'complete' if done else 'partial'} "
          f"elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
