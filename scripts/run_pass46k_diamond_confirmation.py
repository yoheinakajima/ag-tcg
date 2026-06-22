#!/usr/bin/env python3
"""PASS 46K (Part D) — larger-N diamond specialist confirmation runner.

Re-evaluates the EXISTING Pass-46J specialist (`cg_typed_diamond_specialist_planner_v0`) at
larger N WITHOUT rebuilding any tarball. It:

  1. extracts the participant tarballs into a 46K-owned working dir (idempotent; NEVER mutates a
     tarball);
  2. CARRIES the 46J decisive evidence forward ONCE: every 46J `result` row for a panel 46K
     reuses is copied into the 46K ledger with its game_id renamed to ``carry46j:<old_id>`` and
     tagged ``carried=true, source_pass='46j', source_game_id=<old_id>``. The batch worker does
     NOT seed by game_id (each game is an independent ``env.run``), so renaming carried rows and
     using fresh ids for new games yields genuinely independent plays; the rename only prevents
     id collision. Seeding is guarded by a sentinel so it happens exactly once;
  3. materialises a DETERMINISTIC, resumable, seat-alternating plan of NEW games (ids
     ``<panel>#g<NNN>``) up to each panel's new-game cap; a killed run resumes exactly where it
     stopped (results are flushed+fsync'd per game by the worker);
  4. repeatedly spawns the PROVEN 46I import-once warm-engine worker under a HARD subprocess
     timeout, folding the ledger by game_id; orphans (a `start` with no `result`) are recorded
     once as invalid/wedged so they are never retried;
  5. schedules the self-mirror noise controls ONLY if the practical arm (spec_vs_parent) clears
     the parent (combined point >= directional threshold);
  6. after EVERY tranche writes a summary that reports per-panel carried-vs-new-vs-combined
     counts (carried and new are NEVER silently mixed), Wilson95 CIs, seat splits, edge labels
     and the one-sided Fisher increment of the specialist's parent-beating rate over each generic
     scorer's parent-beating rate. The DECISION is Part H's; this part emits the raw + stat
     rollup only. Wall-budget bounded; safe to re-invoke until it reports ``complete``.

LOCAL / READ-ONLY w.r.t. production: no Object Storage, no Kaggle, no events, no tarball writes,
no tournament ledger, no promotion. Public references are benchmark-only and NOT scheduled here
(Part F plays them in their own ledger). Decisive win-rate is a LOCAL feasibility/ordering signal
only — NOT a Kaggle / leaderboard / strength / parity claim. Role buckets / contexts are
observable heuristic labels — no exact-damage / lethal / KO / missed-KO / Boss-gust / spread /
best-action claim.

Outputs: data/experiments/pass46k_diamond_confirmation.{json,md}
Ledger:  data/experiments/pass46k_diamond_confirmation_games.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import tarfile
import time
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46k_eval_plan.json"
GAME_PLAN = EXP / "pass46k_diamond_game_plan.json"
JSONL = EXP / "pass46k_diamond_confirmation_games.jsonl"
SRC_JSONL = EXP / "pass46j_diamond_eval_games.jsonl"
WORK_DIR = ROOT / "data" / "tournament" / "benchmark" / "_pass46k_eval_work"
WORKER = ROOT / "scripts" / "_pass46i_batch_worker.py"  # reuse the proven generic worker

PRACTICAL_PANEL = "spec_vs_parent"
CARRY_PREFIX = "carry46j:"
SEED_SENTINEL = "carry46j_seed_complete"
DIRECTIONAL_POINT = 0.60
DRAW_BUFFER = 4
WILSON_Z = 1.96
SEAT_HI, SEAT_LO = 0.60, 0.40
INVALID_ABS_TOL, INVALID_RATE_TOL = 2, 0.05
FISHER_ALPHA = 0.05


def _extract(tarball: Path, dest: Path) -> None:
    if (dest / "main.py").exists() and (dest / "deck.csv").exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            t.extract(m, dest)


def _pdir(cid: str) -> str:
    return str((WORK_DIR / cid).relative_to(ROOT))


# --------------------------- carry-forward seed -----------------------------
def _seed_state() -> tuple[bool, bool]:
    """(jsonl_exists, seed_sentinel_present)."""
    if not JSONL.exists():
        return False, False
    sentinel = False
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if r.get("type") == SEED_SENTINEL:
            sentinel = True
            break
    return True, sentinel


def _carry_seed(plan: dict) -> dict:
    """Copy 46J result rows ONCE into the 46K ledger (renamed + tagged). Idempotent.

    Seeding always happens BEFORE any new game is played, so an interrupted seed (sentinel
    absent) can be safely discarded and re-done — no new-game work can be lost."""
    exists, sentinel = _seed_state()
    if exists and sentinel:
        return {"seeded": False, "already": True}
    if exists and not sentinel:
        # interrupted seed (no new games yet by construction) -> discard and redo
        JSONL.unlink()
    carried_panels = set(plan.get("carry_forward", {}).get("carried_panels", []))
    n = 0
    by_panel: dict[str, int] = {}
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a", encoding="utf-8") as fh:
        if SRC_JSONL.exists():
            for line in SRC_JSONL.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if r.get("type") != "result":
                    continue
                pid = r.get("panel_id")
                if pid not in carried_panels:
                    continue
                old = r.get("game_id")
                rec = dict(r)
                rec["game_id"] = f"{CARRY_PREFIX}{old}"
                rec["carried"] = True
                rec["source_pass"] = "46j"
                rec["source_game_id"] = old
                fh.write(json.dumps(rec) + "\n")
                n += 1
                by_panel[pid] = by_panel.get(pid, 0) + 1
        fh.write(json.dumps({"type": SEED_SENTINEL, "ts": time.time(),
                             "carried_rows": n, "by_panel": by_panel}) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return {"seeded": True, "already": False, "carried_rows": n, "by_panel": by_panel}


# --------------------------- game plan --------------------------------------
def _panel_specs(plan: dict) -> dict:
    return {p["panel_id"]: p for p in plan["panels"]}


def _build_or_load_game_plan(plan: dict) -> dict:
    if GAME_PLAN.exists():
        return json.loads(GAME_PLAN.read_text(encoding="utf-8"))
    panels = {}
    for p in plan["panels"]:
        cap = p["new_cap"]
        games = [{"game_id": f"{p['panel_id']}#g{i:03d}", "subject_seat": i % 2}
                 for i in range(cap)]
        panels[p["panel_id"]] = {
            "panel_id": p["panel_id"], "arm": p["arm"], "gating": p["gating"],
            "subject_id": p["subject"], "opponent_id": p["opponent"],
            "subject_dir": _pdir(p["subject"]), "opponent_dir": _pdir(p["opponent"]),
            "target_decisive": p["target_decisive"],
            "min_acceptable_decisive": p["min_acceptable_decisive"], "new_cap": cap,
            "required_for_completion": True, "new_games": games}
    gp = {"panels": panels, "noise_controls_added": False,
          "conditional_specs": plan["conditional_noise_controls"]}
    GAME_PLAN.write_text(json.dumps(gp, indent=2) + "\n", encoding="utf-8")
    return gp


def _append_noise_controls(gp: dict) -> None:
    for p in gp["conditional_specs"]:
        if p["panel_id"] in gp["panels"]:
            continue
        cap = p["new_cap"]
        games = [{"game_id": f"{p['panel_id']}#g{i:03d}", "subject_seat": i % 2}
                 for i in range(cap)]
        gp["panels"][p["panel_id"]] = {
            "panel_id": p["panel_id"], "arm": p["arm"], "gating": False,
            "subject_id": p["subject"], "opponent_id": p["opponent"],
            "subject_dir": _pdir(p["subject"]), "opponent_dir": _pdir(p["opponent"]),
            "target_decisive": p["target_decisive"],
            "min_acceptable_decisive": p["min_acceptable_decisive"], "new_cap": cap,
            "required_for_completion": True, "new_games": games, "noise_control": True}
    gp["noise_controls_added"] = True
    GAME_PLAN.write_text(json.dumps(gp, indent=2) + "\n", encoding="utf-8")


def _new_stub_ids(gp: dict) -> set:
    ids = set()
    for pdata in gp["panels"].values():
        for g in pdata["new_games"]:
            ids.add(g["game_id"])
    return ids


# --------------------------- ledger -----------------------------------------
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
    return results, started - done


def _record_orphans(gp: dict, orphans: set) -> int:
    if not orphans:
        return 0
    idx = {}
    for pdata in gp["panels"].values():
        for g in pdata["new_games"]:
            idx[g["game_id"]] = (pdata, g)
    n = 0
    with JSONL.open("a", encoding="utf-8") as fh:
        for gid in sorted(orphans):
            if gid not in idx:
                continue
            pdata, g = idx[gid]
            fh.write(json.dumps({
                "type": "result", "game_id": gid, "panel_id": pdata["panel_id"],
                "subject_id": pdata["subject_id"], "opponent_id": pdata["opponent_id"],
                "subject_seat": g["subject_seat"], "winner": None, "decisive": False,
                "invalid": True, "subject_error": False, "steps": 0, "carried": False,
                "error": "orphan_wedged_killed", "ts": time.time()}) + "\n")
            n += 1
    return n


def _empty_counts() -> dict:
    return {"results": 0, "decisive": 0, "invalid": 0, "draws": 0, "subj_wins": 0,
            "carried_results": 0, "carried_decisive": 0, "carried_subj_wins": 0,
            "new_results": 0, "new_decisive": 0, "new_subj_wins": 0,
            "seat": {0: {"decisive": 0, "wins": 0}, 1: {"decisive": 0, "wins": 0}}}


def _fold(results: list) -> dict:
    """Per-panel COMBINED counts with carried-vs-new breakdown (never mixed)."""
    by: dict[str, dict] = {}
    for r in results:
        pid = r.get("panel_id")
        d = by.setdefault(pid, _empty_counts())
        carried = bool(r.get("carried"))
        d["results"] += 1
        d["carried_results" if carried else "new_results"] += 1
        if r.get("invalid"):
            d["invalid"] += 1
            continue
        if r.get("decisive"):
            d["decisive"] += 1
            d["carried_decisive" if carried else "new_decisive"] += 1
            seat = int(r.get("subject_seat", 0))
            d["seat"][seat]["decisive"] += 1
            if r.get("winner") == "subject":
                d["subj_wins"] += 1
                d["carried_subj_wins" if carried else "new_subj_wins"] += 1
                d["seat"][seat]["wins"] += 1
        else:
            d["draws"] += 1
    return by


def _compute_todo(gp: dict, results: list, orphans: set) -> list:
    counts = _fold(results)
    done_ids = {r["game_id"] for r in results}
    order = sorted(gp["panels"].values(),
                   key=lambda p: (0 if p["gating"] else 1, p["panel_id"]))
    todo = []
    for pdata in order:
        c = counts.get(pdata["panel_id"], _empty_counts())
        needed = pdata["target_decisive"] - c["decisive"]
        if needed <= 0:
            continue
        avail = [g for g in pdata["new_games"]
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
    counts = _fold(results)
    done_ids = {r["game_id"] for r in results}
    for pdata in gp["panels"].values():
        if not pdata.get("required_for_completion"):
            continue
        c = counts.get(pdata["panel_id"], _empty_counts())
        new_left = [g for g in pdata["new_games"] if g["game_id"] not in done_ids]
        if not (c["decisive"] >= pdata["target_decisive"] or not new_left):
            return False
    return True


def _practical_clears_parent(results: list) -> bool:
    c = _fold(results).get(PRACTICAL_PANEL)
    if not c or c["decisive"] == 0:
        return False
    return (c["subj_wins"] / c["decisive"]) >= DIRECTIONAL_POINT


def _spawn_worker(todo: list, budget: float) -> None:
    spec_path = EXP / "_pass46k_batch_spec.json"
    spec_path.write_text(json.dumps({"games": todo}), encoding="utf-8")
    with open(os.devnull, "wb") as dn:
        proc = subprocess.Popen(
            [sys.executable, str(WORKER), "--spec", str(spec_path),
             "--jsonl", str(JSONL), "--budget-seconds", str(budget)],
            stdout=dn, stderr=dn, start_new_session=True)
        try:
            proc.wait(timeout=budget + 15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass


# --------------------------- statistics -------------------------------------
def _wilson(w: int, n: int, z: float = WILSON_Z):
    if n == 0:
        return None, None
    p = w / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((centre - half) / d, 4), round((centre + half) / d, 4)


def _fisher_right(a: int, b: int, c: int, d: int):
    """One-sided (right-tail) Fisher exact p: row1 (a,b) has HIGHER success share."""
    n = a + b + c + d
    if n == 0:
        return None
    r1, c1, r2 = a + b, a + c, c + d
    denom = comb(n, c1)
    if denom == 0:
        return None
    hi = min(r1, c1)
    return round(sum(comb(r1, k) * comb(r2, c1 - k) for k in range(a, hi + 1)) / denom, 6)


def _edge_label(c: dict) -> dict:
    dec = c["decisive"]
    wins = c["subj_wins"]
    wl, wh = _wilson(wins, dec)
    point = round(wins / dec, 4) if dec else None
    s0, s1 = c["seat"][0], c["seat"][1]
    r0 = s0["wins"] / s0["decisive"] if s0["decisive"] else None
    r1 = s1["wins"] / s1["decisive"] if s1["decisive"] else None
    seat_conf = bool(
        r0 is not None and r1 is not None
        and ((r0 >= SEAT_HI and r1 <= SEAT_LO) or (r1 >= SEAT_HI and r0 <= SEAT_LO)))
    inv_rate = c["invalid"] / c["results"] if c["results"] else 0.0
    unsafe = bool(c["invalid"] > INVALID_ABS_TOL and inv_rate > INVALID_RATE_TOL)
    if unsafe:
        label = "unsafe_invalid"
    elif seat_conf:
        label = "seat_confounded"
    elif wl is not None and wl > 0.5:
        label = "confirmed_edge"
    elif point is not None and point >= DIRECTIONAL_POINT and (wl is None or wl <= 0.5):
        label = "directional_edge"
    else:
        label = "no_edge"
    noise_clean = (wl is not None and wh is not None and wl <= 0.5 <= wh)
    return {"point": point, "wilson_low": wl, "wilson_high": wh,
            "seat0_rate": round(r0, 4) if r0 is not None else None,
            "seat1_rate": round(r1, 4) if r1 is not None else None,
            "seat_confounded": seat_conf, "invalid_rate": round(inv_rate, 4),
            "unsafe_invalid": unsafe, "edge_label": label,
            "noise_ci_contains_half": noise_clean}


def _write_summary(gp: dict, results: list, complete: bool) -> dict:
    counts = _fold(results)
    walls = [r.get("wall_s") for r in results if isinstance(r.get("wall_s"), (int, float))]
    panels_out = []
    for pid, pdata in sorted(gp["panels"].items()):
        c = counts.get(pid, _empty_counts())
        lab = _edge_label(c)
        cp = round(c["carried_subj_wins"] / c["carried_decisive"], 4) if c["carried_decisive"] else None
        npt = round(c["new_subj_wins"] / c["new_decisive"], 4) if c["new_decisive"] else None
        panels_out.append({
            "panel_id": pid, "arm": pdata["arm"], "gating": pdata["gating"],
            "subject_id": pdata["subject_id"], "opponent_id": pdata["opponent_id"],
            "target_decisive": pdata["target_decisive"],
            "min_acceptable_decisive": pdata["min_acceptable_decisive"],
            "new_cap": pdata["new_cap"],
            "n_results": c["results"], "n_decisive": c["decisive"],
            "n_invalid": c["invalid"], "n_draws": c["draws"], "subject_wins": c["subj_wins"],
            "carried_results": c["carried_results"], "carried_decisive": c["carried_decisive"],
            "carried_subject_wins": c["carried_subj_wins"], "carried_win_rate": cp,
            "new_results": c["new_results"], "new_decisive": c["new_decisive"],
            "new_subject_wins": c["new_subj_wins"], "new_win_rate": npt,
            "subject_win_rate": lab["point"], "wilson_low": lab["wilson_low"],
            "wilson_high": lab["wilson_high"], "seat0_rate": lab["seat0_rate"],
            "seat1_rate": lab["seat1_rate"], "seat_confounded": lab["seat_confounded"],
            "invalid_rate": lab["invalid_rate"], "unsafe_invalid": lab["unsafe_invalid"],
            "edge_label": lab["edge_label"],
            "noise_ci_contains_half": lab["noise_ci_contains_half"],
            "reached_target": c["decisive"] >= pdata["target_decisive"],
            "reached_min_acceptable": c["decisive"] >= pdata["min_acceptable_decisive"]})

    by_id = {p["panel_id"]: p for p in panels_out}

    def _wl(pid):
        c = counts.get(pid, _empty_counts())
        return c["subj_wins"], c["decisive"] - c["subj_wins"]

    increments = {}
    if "spec_vs_parent" in by_id:
        sw, sl = _wl("spec_vs_parent")
        for gen in ("ov_vs_parent", "floor_vs_parent"):
            if gen in by_id and (sw + sl) > 0:
                gw, gl = _wl(gen)
                if (gw + gl) > 0:
                    p = _fisher_right(sw, sl, gw, gl)
                    increments[gen] = {
                        "spec_wins": sw, "spec_losses": sl,
                        "generic_wins": gw, "generic_losses": gl,
                        "fisher_right_p": p,
                        "significant": bool(p is not None and p < FISHER_ALPHA)}

    h2h_ov = by_id.get("spec_vs_generic_ov", {})
    h2h_ov_label = h2h_ov.get("edge_label")
    h2h_ov_point = h2h_ov.get("subject_win_rate")
    h2h_floor_label = by_id.get("spec_vs_generic_floor", {}).get("edge_label")
    fisher_ov_sig = increments.get("ov_vs_parent", {}).get("significant", False)
    attributable = bool(h2h_ov_label in ("confirmed_edge", "directional_edge") or fisher_ov_sig)
    attribution_negative = bool(
        h2h_ov_point is not None and h2h_ov_point < 0.5
        and by_id.get("spec_vs_generic_ov", {}).get("reached_min_acceptable"))

    attribution = {
        "head_to_head_vs_generic_ov": h2h_ov_label,
        "head_to_head_vs_generic_ov_win_rate": h2h_ov_point,
        "head_to_head_vs_generic_floor": h2h_floor_label,
        "fisher_increments_vs_parent": increments,
        "attributable_to_planner": attributable,
        "attribution_negative": attribution_negative,
        "rule": ("attributable if spec_vs_generic_ov is confirmed/directional edge OR the "
                 "one-sided Fisher increment vs ov_vs_parent is significant (p<0.05); negative "
                 "if spec_vs_generic_ov win rate < 0.5 at/above min_acceptable_decisive")}

    practical = by_id.get(PRACTICAL_PANEL, {})
    summary = {
        "pass": "46K", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "no_promotion": True,
        "subject_under_test": "cg_typed_diamond_specialist_planner_v0",
        "evaluates_existing_candidate": True, "rebuilds_candidate": False,
        "n_games_total": len(results),
        "n_carried_total": sum(p["carried_results"] for p in panels_out),
        "n_new_total": sum(p["new_results"] for p in panels_out),
        "n_invalid_total": sum(p["n_invalid"] for p in panels_out),
        "noise_controls_added": gp["noise_controls_added"],
        "practical_clears_parent_trigger": _practical_clears_parent(results),
        "wall_s_total": round(sum(walls), 2),
        "wall_s_mean": round(sum(walls) / len(walls), 3) if walls else None,
        "practical_arm": {"panel": PRACTICAL_PANEL,
                          "edge_label": practical.get("edge_label"),
                          "win_rate": practical.get("subject_win_rate"),
                          "wilson_low": practical.get("wilson_low"),
                          "wilson_high": practical.get("wilson_high"),
                          "reached_target": practical.get("reached_target"),
                          "reached_min_acceptable": practical.get("reached_min_acceptable")},
        "attribution": attribution,
        "panels": panels_out,
        "complete": complete,
        "note": ("Decisive win-rate is a LOCAL feasibility/ordering signal only — NOT a Kaggle "
                 "/ leaderboard / strength / parity claim. Carried (46J) and new (46K) counts "
                 "are reported separately and never silently mixed. Public references are "
                 "benchmark-only and NOT in these panels (Part F). The DECISION is Part H's; "
                 "this is the raw + statistical rollup. Role buckets / contexts are observable "
                 "heuristic labels (no exact-damage / lethal / KO / missed-KO / Boss-gust / "
                 "spread / best-action)."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46k_diamond_confirmation.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46K (Part D) — larger-N diamond specialist confirmation (raw + stat rollup)", "",
        "_LOCAL / READ-ONLY. Re-evaluates the EXISTING 46J specialist (rebuilds nothing). 46J "
        "evidence is CARRIED forward with explicit carried-vs-new accounting. Decisive win-rate "
        "is a LOCAL feasibility/ordering signal only — NOT a Kaggle / leaderboard / strength / "
        "parity claim. Public references are benchmark-only and NOT in these panels. The "
        "DECISION lives in Part H. Role buckets / contexts are observable heuristic labels — no "
        "exact-damage / lethal / KO / missed-KO / Boss-gust / spread / best-action claim._", "",
        f"- **total games:** {len(results)} (carried {summary['n_carried_total']} + new "
        f"{summary['n_new_total']}) | invalid: {summary['n_invalid_total']} | mean wall/game: "
        f"{summary['wall_s_mean']}s | complete: **{complete}**",
        f"- **practical arm** (`{PRACTICAL_PANEL}`): label "
        f"**{practical.get('edge_label')}**, win-rate {practical.get('subject_win_rate')} "
        f"(Wilson95 {practical.get('wilson_low')}..{practical.get('wilson_high')}), "
        f"reached target: {practical.get('reached_target')}",
        f"- **attributable to planner:** **{attributable}** "
        f"(H2H vs generic_ov: {h2h_ov_label} @ {h2h_ov_point}; Fisher increment vs "
        f"ov_vs_parent significant: {fisher_ov_sig}; attribution negative: "
        f"{attribution_negative})",
        f"- **noise controls run:** {gp['noise_controls_added']}", "",
        "| panel | gating | combined wr | Wilson95 | dec (carr+new) | seat0 | seat1 | inv | "
        "edge label | reached |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|:---:|",
    ]
    for p in panels_out:
        md.append(
            f"| `{p['panel_id']}` | {p['gating']} | {p['subject_win_rate']} | "
            f"{p['wilson_low']}..{p['wilson_high']} | {p['n_decisive']} "
            f"({p['carried_decisive']}+{p['new_decisive']}) | {p['seat0_rate']} | "
            f"{p['seat1_rate']} | {p['n_invalid']} | **{p['edge_label']}** | "
            f"{p['reached_target']} |")
    md += ["", "## Carried (46J) vs new (46K) win rates",
           "| panel | carried wr (dec) | new wr (dec) | combined wr (dec) |",
           "|---|:---:|:---:|:---:|"]
    for p in panels_out:
        md.append(f"| `{p['panel_id']}` | {p['carried_win_rate']} ({p['carried_decisive']}) | "
                  f"{p['new_win_rate']} ({p['new_decisive']}) | {p['subject_win_rate']} "
                  f"({p['n_decisive']}) |")
    md += ["", "## Attribution — Fisher increment vs parent (one-sided, combined)",
           "| generic baseline | spec W-L vs parent | generic W-L vs parent | Fisher p | "
           "significant |", "|---|:---:|:---:|:---:|:---:|"]
    for gen, inc in increments.items():
        md.append(f"| `{gen}` | {inc['spec_wins']}-{inc['spec_losses']} | "
                  f"{inc['generic_wins']}-{inc['generic_losses']} | "
                  f"{inc['fisher_right_p']} | {inc['significant']} |")
    (EXP / "pass46k_diamond_confirmation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orch-budget-seconds", type=float, default=95.0)
    ap.add_argument("--worker-budget-seconds", type=float, default=70.0)
    a = ap.parse_args()

    if not PLAN_JSON.exists():
        raise SystemExit(f"missing eval plan: {PLAN_JSON} (run Part C builder first)")
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    for cid, pdata in plan["participants"].items():
        if not pdata.get("present"):
            raise SystemExit(f"participant tarball missing: {cid}")
        _extract(ROOT / pdata["tarball"], WORK_DIR / cid)

    seed_info = _carry_seed(plan)
    gp = _build_or_load_game_plan(plan)

    t0 = time.time()
    no_progress = 0
    while True:
        results, orphans = _read_ledger()
        _record_orphans(gp, orphans)
        results, orphans = _read_ledger()

        if _is_complete(gp, results):
            if not gp["noise_controls_added"] and _practical_clears_parent(results):
                _append_noise_controls(gp)
                continue
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
        after, _ = _read_ledger()
        _write_summary(gp, after, _is_complete(gp, after))  # tranche checkpoint
        if len(after) <= before:
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
                      "carried": summary["n_carried_total"], "new": summary["n_new_total"],
                      "n_invalid": summary["n_invalid_total"], "seed": seed_info,
                      "noise_controls_added": gp["noise_controls_added"],
                      "practical": summary["practical_arm"],
                      "attributable": summary["attribution"]["attributable_to_planner"],
                      "attribution_negative": summary["attribution"]["attribution_negative"],
                      "panels": [{"panel": p["panel_id"], "dec": p["n_decisive"],
                                  "carr": p["carried_decisive"], "new": p["new_decisive"],
                                  "wr": p["subject_win_rate"], "label": p["edge_label"],
                                  "reached": p["reached_target"]}
                                 for p in summary["panels"]]}, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
