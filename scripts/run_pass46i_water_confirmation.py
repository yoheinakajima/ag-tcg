#!/usr/bin/env python3
"""PASS 46I (Part D) — confirmation panel orchestrator (drives the batch worker).

Owns scheduling; the worker owns play. This orchestrator:

  1. extracts the EXISTING 46H water tarballs + the real parent tarball into a 46I-owned
     working dir (idempotent; NEVER mutates or overwrites the tarballs);
  2. materialises a DETERMINISTIC, resumable game plan (per panel, an ordered list of
     seat-alternating game stubs up to the panel's hard cap, with stable game_ids), so a
     killed run resumes exactly where it left off;
  3. repeatedly spawns the import-once worker under a HARD subprocess timeout, folding the
     flushed JSONL ledger back idempotently by game_id after each batch; any "poison" game
     (a `start` killed mid-play) is recorded once as an invalid/wedged result so it is
     never retried and is visible in the analysis;
  4. runs the self-mirror noise controls (parent-vs-parent, ov-vs-ov) ONLY if the
     practical arm (ov-vs-parent) appears to clear the parent (point estimate >=
     directional threshold), per the pre-registered plan;
  5. is itself bounded by an internal wall budget and is safe to re-invoke until it reports
     ``complete``.

LOCAL / READ-ONLY w.r.t. production: no Object Storage, no Kaggle, no events, no tarball
writes, no tournament ledger. Writes the raw ledger
data/experiments/pass46i_water_confirmation_games.jsonl and the rollup
data/experiments/pass46i_water_confirmation.{json,md}.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46i_eval_plan.json"
GAME_PLAN = EXP / "pass46i_game_plan.json"
JSONL = EXP / "pass46i_water_confirmation_games.jsonl"
WORK_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46i_work"
WORKER = ROOT / "scripts" / "_pass46i_batch_worker.py"

DIRECTIONAL_POINT = 0.60  # noise-control trigger: ov appears to clear parent
DRAW_BUFFER = 3           # schedule a few extra games per panel to absorb draws/invalids


def _extract(tarball: Path, dest: Path) -> None:
    if (dest / "main.py").exists() and (dest / "deck.csv").exists():
        return  # idempotent; do not re-extract
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue  # path-traversal guard (trusted tarball, belt-and-braces)
            t.extract(m, dest)


def _build_or_load_game_plan(plan: dict) -> dict:
    if GAME_PLAN.exists():
        return json.loads(GAME_PLAN.read_text(encoding="utf-8"))
    participants = plan["participants"]

    def pdir(cid: str) -> str:
        return str((WORK_DIR / cid).relative_to(ROOT))

    panels = {}
    for p in plan["panels"]:
        subj, opp = p["subject"], p["opponent"]
        cap = p["hard_cap_games"]
        games = [{"game_id": f"{p['panel_id']}#g{i:03d}", "subject_seat": i % 2}
                 for i in range(cap)]
        panels[p["panel_id"]] = {
            "panel_id": p["panel_id"], "arm": p["arm"], "gating": p["gating"],
            "subject_id": subj, "opponent_id": opp,
            "subject_dir": pdir(subj), "opponent_dir": pdir(opp),
            "target_decisive": p["target_decisive"], "hard_cap": cap,
            "required_for_completion": True, "games": games,
        }
    gp = {"panels": panels, "noise_controls_added": False,
          "conditional_specs": plan["conditional_noise_controls"]}
    GAME_PLAN.write_text(json.dumps(gp, indent=2) + "\n", encoding="utf-8")
    return gp


def _append_noise_controls(gp: dict) -> None:
    def pdir(cid: str) -> str:
        return str((WORK_DIR / cid).relative_to(ROOT))

    for p in gp["conditional_specs"]:
        if p["panel_id"] in gp["panels"]:
            continue
        cap = p["hard_cap_games"]
        games = [{"game_id": f"{p['panel_id']}#g{i:03d}", "subject_seat": i % 2}
                 for i in range(cap)]
        gp["panels"][p["panel_id"]] = {
            "panel_id": p["panel_id"], "arm": p["arm"], "gating": False,
            "subject_id": p["subject"], "opponent_id": p["opponent"],
            "subject_dir": pdir(p["subject"]), "opponent_dir": pdir(p["opponent"]),
            "target_decisive": p["target_decisive"], "hard_cap": cap,
            "required_for_completion": True, "games": games,
        }
    gp["noise_controls_added"] = True
    GAME_PLAN.write_text(json.dumps(gp, indent=2) + "\n", encoding="utf-8")


def _read_ledger() -> tuple[list, set]:
    results, started = [], set()
    if JSONL.exists():
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("type") == "result":
                results.append(r)
            elif r.get("type") == "start":
                started.add(r.get("game_id"))
    done = {r["game_id"] for r in results}
    orphans = started - done
    return results, orphans


def _record_orphans(gp: dict, orphans: set) -> int:
    if not orphans:
        return 0
    stub_index = {}
    for pid, pdata in gp["panels"].items():
        for g in pdata["games"]:
            stub_index[g["game_id"]] = (pdata, g)
    n = 0
    with JSONL.open("a", encoding="utf-8") as fh:
        for gid in sorted(orphans):
            if gid not in stub_index:
                continue
            pdata, g = stub_index[gid]
            rec = {"type": "result", "game_id": gid, "panel_id": pdata["panel_id"],
                   "subject_id": pdata["subject_id"],
                   "opponent_id": pdata["opponent_id"],
                   "subject_seat": g["subject_seat"], "winner": None,
                   "decisive": False, "invalid": True, "subject_error": False,
                   "steps": 0, "error": "orphan_wedged_killed", "ts": time.time()}
            fh.write(json.dumps(rec) + "\n")
            n += 1
    return n


def _panel_counts(results: list) -> dict:
    by: dict[str, dict] = {}
    for r in results:
        pid = r.get("panel_id")
        d = by.setdefault(pid, {"results": 0, "decisive": 0, "invalid": 0,
                                "draws": 0, "subj_wins": 0,
                                "seat": {0: {"decisive": 0, "wins": 0},
                                         1: {"decisive": 0, "wins": 0}}})
        d["results"] += 1
        if r.get("invalid"):
            d["invalid"] += 1
            continue
        if r.get("decisive"):
            d["decisive"] += 1
            seat = int(r.get("subject_seat", 0))
            d["seat"][seat]["decisive"] += 1
            if r.get("winner") == "subject":
                d["subj_wins"] += 1
                d["seat"][seat]["wins"] += 1
        else:
            d["draws"] += 1
    return by


def _compute_todo(gp: dict, results: list, orphans: set) -> list:
    counts = _panel_counts(results)
    done_ids = {r["game_id"] for r in results}
    # gating panels first so they finish even under a tight budget.
    order = sorted(gp["panels"].values(),
                   key=lambda p: (0 if p["gating"] else 1, p["panel_id"]))
    todo = []
    for pdata in order:
        c = counts.get(pdata["panel_id"], {"decisive": 0})
        needed = pdata["target_decisive"] - c["decisive"]
        if needed <= 0:
            continue
        avail = [g for g in pdata["games"]
                 if g["game_id"] not in done_ids and g["game_id"] not in orphans]
        for g in avail[:needed + DRAW_BUFFER]:
            todo.append({"game_id": g["game_id"], "panel_id": pdata["panel_id"],
                         "subject_id": pdata["subject_id"],
                         "opponent_id": pdata["opponent_id"],
                         "subject_dir": pdata["subject_dir"],
                         "opponent_dir": pdata["opponent_dir"],
                         "subject_seat": g["subject_seat"]})
    return todo


def _is_complete(gp: dict, results: list) -> bool:
    counts = _panel_counts(results)
    for pdata in gp["panels"].values():
        if not pdata.get("required_for_completion"):
            continue
        c = counts.get(pdata["panel_id"], {"decisive": 0, "results": 0})
        reached = c["decisive"] >= pdata["target_decisive"]
        exhausted = c.get("results", 0) >= pdata["hard_cap"]
        if not (reached or exhausted):
            return False
    return True


def _practical_clears_parent(results: list) -> bool:
    c = _panel_counts(results).get("ov_vs_parent")
    if not c or c["decisive"] == 0:
        return False
    return (c["subj_wins"] / c["decisive"]) >= DIRECTIONAL_POINT


def _spawn_worker(todo: list, budget: float) -> None:
    spec_path = EXP / "_pass46i_batch_spec.json"
    spec_path.write_text(json.dumps({"games": todo}), encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, str(WORKER), "--spec", str(spec_path),
             "--jsonl", str(JSONL), "--budget-seconds", str(budget)],
            capture_output=True, text=True, timeout=budget + 15)
    except subprocess.TimeoutExpired:
        pass  # native hang killed; orphan handled next loop


def _write_summary(gp: dict, results: list, complete: bool) -> dict:
    counts = _panel_counts(results)
    walls = [r.get("wall_s") for r in results if isinstance(r.get("wall_s"), (int, float))]
    panels_out = []
    for pid, pdata in sorted(gp["panels"].items()):
        c = counts.get(pid, {"results": 0, "decisive": 0, "invalid": 0, "draws": 0,
                             "subj_wins": 0,
                             "seat": {0: {"decisive": 0, "wins": 0},
                                      1: {"decisive": 0, "wins": 0}}})
        dec = c["decisive"]
        s0, s1 = c["seat"][0], c["seat"][1]
        panels_out.append({
            "panel_id": pid, "arm": pdata["arm"], "gating": pdata["gating"],
            "subject_id": pdata["subject_id"], "opponent_id": pdata["opponent_id"],
            "target_decisive": pdata["target_decisive"], "hard_cap": pdata["hard_cap"],
            "n_results": c["results"], "n_decisive": dec, "n_invalid": c["invalid"],
            "n_draws": c["draws"], "subject_wins": c["subj_wins"],
            "subject_win_rate": round(c["subj_wins"] / dec, 4) if dec else None,
            "seat0": {"decisive": s0["decisive"], "wins": s0["wins"],
                      "win_rate": round(s0["wins"] / s0["decisive"], 4)
                      if s0["decisive"] else None},
            "seat1": {"decisive": s1["decisive"], "wins": s1["wins"],
                      "win_rate": round(s1["wins"] / s1["decisive"], 4)
                      if s1["decisive"] else None},
            "reached_target": dec >= pdata["target_decisive"],
        })
    summary = {
        "pass": "46i", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "n_games_total": len(results),
        "n_invalid_total": sum(p["n_invalid"] for p in panels_out),
        "noise_controls_added": gp["noise_controls_added"],
        "practical_clears_parent_trigger": _practical_clears_parent(results),
        "wall_s_total": round(sum(walls), 2),
        "wall_s_mean": round(sum(walls) / len(walls), 3) if walls else None,
        "panels": panels_out,
        "complete": complete,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_water_confirmation.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46I (Part D) — water confirmation panels (raw rollup)", "",
        "_LOCAL / READ-ONLY. Import-once warm-engine games via a hang-safe resumable "
        "worker. Statistics + edge labels + the decision live in Parts E/G; this is the "
        "raw decisive-rate rollup only. Public references are NOT in these panels._", "",
        f"- **total games:** {len(results)} | invalid: "
        f"{sum(p['n_invalid'] for p in panels_out)} | mean wall/game: "
        f"{summary['wall_s_mean']}s",
        f"- **noise controls run:** {gp['noise_controls_added']} | practical-clears-parent "
        f"trigger: {summary['practical_clears_parent_trigger']}",
        f"- **complete:** {complete}", "",
        "| panel | arm | subject win rate | decisive | seat0 wr | seat1 wr | invalid | "
        "target | reached |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for p in panels_out:
        md.append(
            f"| `{p['panel_id']}` | {p['arm']} | {p['subject_win_rate']} | "
            f"{p['n_decisive']} | {p['seat0']['win_rate']} | {p['seat1']['win_rate']} | "
            f"{p['n_invalid']} | {p['target_decisive']} | {p['reached_target']} |")
    (EXP / "pass46i_water_confirmation.md").write_text("\n".join(md) + "\n",
                                                       encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch-budget-seconds", type=float, default=85.0)
    ap.add_argument("--worker-budget-seconds", type=float, default=70.0)
    a = ap.parse_args()

    if not PLAN_JSON.exists():
        raise SystemExit(f"missing eval plan: {PLAN_JSON} (run Part C first)")
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))

    # Extract participants (idempotent, no tarball mutation).
    for cid, pdata in plan["participants"].items():
        if not pdata.get("present"):
            raise SystemExit(f"participant tarball missing: {cid}")
        _extract(ROOT / pdata["tarball"], WORK_DIR / cid)

    gp = _build_or_load_game_plan(plan)

    t0 = time.time()
    no_progress = 0
    while True:
        results, orphans = _read_ledger()
        _record_orphans(gp, orphans)
        results, orphans = _read_ledger()  # reload after recording

        if _is_complete(gp, results):
            if (not gp["noise_controls_added"]
                    and _practical_clears_parent(results)):
                _append_noise_controls(gp)
                continue  # schedule the freshly-added noise panels
            break

        todo = _compute_todo(gp, results, orphans)
        if not todo:
            break
        remaining = a.orch_budget_seconds - (time.time() - t0)
        if remaining < 12:
            break
        wb = min(a.worker_budget_seconds, remaining - 8)
        before = len(results)
        _spawn_worker(todo, wb)
        after_results, _ = _read_ledger()
        if len(after_results) <= before:
            no_progress += 1
            if no_progress >= 2:
                break
        else:
            no_progress = 0

    results, orphans = _read_ledger()
    _record_orphans(gp, orphans)
    results, _ = _read_ledger()
    complete = _is_complete(gp, results)
    summary = _write_summary(gp, results, complete)

    print(json.dumps({"complete": complete, "n_games": len(results),
                      "n_invalid": summary["n_invalid_total"],
                      "noise_controls_added": gp["noise_controls_added"],
                      "panels": [{"panel": p["panel_id"],
                                  "decisive": p["n_decisive"],
                                  "wr": p["subject_win_rate"],
                                  "reached": p["reached_target"]}
                                 for p in summary["panels"]]}, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
