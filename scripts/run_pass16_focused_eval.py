#!/usr/bin/env python3
"""Pass 16 -- live cabt smoke (T-H) + real-sample focused eval (T-I). LOCAL ONLY.

SURROGATE-BASED AND DIRECTIONAL ONLY. The Pass 13 refined subfamilies give us
opponent DECK LISTS, not their real policies; each deck is piloted by the stable
generic surrogate brain (sim/surrogate_agents.py). These results never equal
Kaggle results and are NEVER sufficient on their own to promote/upload anything.

Modes
-----
  --smoke : quick health check. v3 vs AC (both seats), v3 self-mirror,
            v2 vs AC, clone(anchor) vs AC. Writes pass16_live_smoke.{json,md}.
  (default): full focused eval. Validator-passing candidates {v3, v2} vs each of
            the 6 weighted Pass 13 subfamilies + vs the entrypoint-safe anchor,
            seat-swapped, GAMES_PER_SEAT each, watchdog + global budget, Wilson
            CIs. Writes pass16_focused_eval.{json,md}, matchup_matrix.csv,
            ranking.{json,md}.

No upload, no submission, no candidate generation, no root edits.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
POOL = REPO / "experiments" / "pass13_refined_meta_pool.yaml"
VALIDATION = REPORTS / "pass16_validation.json"

CAND_V3 = REPO / "data" / "submissions" / "candidates_pass16" / "core_pilot_water_v3_context.tar.gz"
CAND_V2 = REPO / "data" / "submissions" / "candidates_pass14" / "core_pilot_water_v2_runtime.tar.gz"
ANCHOR_CLONE = REPO / "data" / "submissions" / "candidates_pass16" / "combo_full_safety_v3_entrypoint_safe_local.tar.gz"

GAME_TIMEOUT_S = int(os.environ.get("P16_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P16_GLOBAL_BUDGET_S", "1500"))
GAMES_PER_SEAT = int(os.environ.get("P16_GAMES_PER_SEAT", "10"))
SMOKE_GAMES_PER_SEAT = int(os.environ.get("P16_SMOKE_GAMES_PER_SEAT", "2"))

DISCLAIMER = (
    "SURROGATE-BASED AND DIRECTIONAL ONLY. Opponent subfamily decks are piloted "
    "by a generic surrogate policy, not the real opponent policy. These local "
    "results never equal Kaggle results and are not sufficient to promote or "
    "upload any candidate."
)


# ---- reuse proven primitives from run_meta_pool_eval ------------------------
def _load_meta_eval_mod():
    spec = importlib.util.spec_from_file_location(
        "run_meta_pool_eval", REPO / "scripts" / "run_meta_pool_eval.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load_meta_eval_mod()
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_outcome_for_seat = _MEV._outcome_for_seat


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _run_game(agent_a: str, agent_b: str) -> dict:
    from kaggle_environments import make
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run([agent_a, agent_b])
        last = env.steps[-1]
        rewards = [s.get("reward") for s in last]
        statuses = [s.get("status") for s in last]
        return {"ok": True, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "timeout": False}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _matchup(cand_agent: str, opp_agent: str, n_per_seat: int,
             budget_left, label: str) -> dict:
    games = []
    for (a, b, our) in [(cand_agent, opp_agent, 0), (opp_agent, cand_agent, 1)]:
        for _ in range(n_per_seat):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "our_seat": our})
                continue
            g = _run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = _outcome_for_seat(g, our)
            games.append(g)
    wins = sum(1 for g in games if g.get("outcome") == "win")
    losses = sum(1 for g in games if g.get("outcome") == "loss")
    draws = sum(1 for g in games if g.get("outcome") == "draw")
    decisive = wins + losses
    n = wins + losses + draws
    lo, hi = _wilson(wins, decisive)
    return {
        "label": label,
        "n_games": n, "wins": wins, "losses": losses, "draws": draws,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "wilson_low": lo, "wilson_high": hi,
        "crashes": sum(1 for g in games if not g.get("ok")
                       and not g.get("timeout") and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games
                          if not g.get("ok") and g.get("error")}),
    }


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


# ---- candidate / opponent resolution ---------------------------------------
def _resolve_candidates(tmp: Path) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    cands: list[dict] = []
    for cid, role, tar in [
        ("core_pilot_water_v3_context", "candidate_v3", CAND_V3),
        ("core_pilot_water_v2_runtime", "reference_v2", CAND_V2),
    ]:
        if tar.exists() and _validate_tarball(tar):
            cands.append({"id": cid, "role": role,
                          "agent": _extract_agent(tar, tmp / cid)})
        else:
            notes.append(f"{cid} tarball missing/invalid -> excluded")
    return cands, notes


def _resolve_anchor(tmp: Path) -> tuple[dict | None, list[str]]:
    notes: list[str] = []
    if ANCHOR_CLONE.exists() and _validate_tarball(ANCHOR_CLONE):
        return ({"id": "combo_full_safety_v3_entrypoint_safe_local",
                 "role": "entrypoint_safe_anchor",
                 "agent": _extract_agent(ANCHOR_CLONE, tmp / "anchor")}, notes)
    notes.append("entrypoint-safe anchor clone missing/invalid")
    return None, notes


def _load_subfamilies() -> list[dict]:
    if yaml is None or not POOL.exists():
        return []
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    out = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours"):
            continue
        if not (a.get("weight") or 0) > 0:
            continue
        deck = a.get("surrogate_deck")
        if deck and (REPO / deck).exists():
            out.append({"key": a["key"], "deck": str(REPO / deck),
                        "weight": float(a["weight"]),
                        "confidence": a.get("confidence"),
                        "status": a.get("status")})
    return out


def _weighted(per_sub: dict) -> float | None:
    acc = tw = 0.0
    for m in per_sub.values():
        wr = m.get("win_rate")
        w = m.get("weight") or 0.0
        if wr is None:
            continue
        acc += w * wr
        tw += w
    return round(acc / tw, 4) if tw > 0 else None


# ---- smoke (T-H) -----------------------------------------------------------
def run_smoke() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep = {"pass": "16", "mode": "smoke", "generated_at": time.time(),
           "disclaimer": DISCLAIMER, "games_per_seat": SMOKE_GAMES_PER_SEAT,
           "matchups": [], "notes": []}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cands, cnotes = _resolve_candidates(tmp)
        anchor, anotes = _resolve_anchor(tmp)
        rep["notes"] += cnotes + anotes
        by = {c["id"]: c for c in cands}
        v3 = by.get("core_pilot_water_v3_context")
        v2 = by.get("core_pilot_water_v2_runtime")
        plan = []
        if v3 and anchor:
            plan.append(("v3_vs_anchor", v3["agent"], anchor["agent"]))
        if v3:
            plan.append(("v3_self_mirror", v3["agent"], v3["agent"]))
        if v2 and anchor:
            plan.append(("v2_vs_anchor", v2["agent"], anchor["agent"]))
        if anchor:
            plan.append(("anchor_vs_anchor", anchor["agent"], anchor["agent"]))
        for label, a, b in plan:
            m = _matchup(a, b, SMOKE_GAMES_PER_SEAT, budget_left, label)
            rep["matchups"].append(m)
    rep["elapsed_s"] = round(time.time() - start, 1)
    total_crash = sum(m["crashes"] + m["timeouts"] for m in rep["matchups"])
    rep["healthy"] = total_crash == 0 and bool(rep["matchups"])
    rep["total_crashes_or_timeouts"] = total_crash
    return rep


def _md_smoke(rep: dict) -> str:
    L = ["# Pass 16 live cabt smoke (T-H)", "", f"> {rep['disclaimer']}", "",
         f"- mode: {rep['mode']}  games/seat: {rep['games_per_seat']}",
         f"- healthy (no crashes/timeouts): **{rep['healthy']}**",
         f"- total crashes+timeouts: {rep['total_crashes_or_timeouts']}",
         f"- elapsed: {rep['elapsed_s']}s", "",
         "| matchup | n | W-L-D | win_rate | crash | timeout |",
         "|---|---|---|---|---|---|"]
    for m in rep["matchups"]:
        L.append(f"| {m['label']} | {m['n_games']} | "
                 f"{m['wins']}-{m['losses']}-{m['draws']} | {m['win_rate']} | "
                 f"{m['crashes']} | {m['timeouts']} |")
    if rep.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in rep["notes"]]
    L.append("")
    return "\n".join(L)


# ---- focused eval (T-I) ----------------------------------------------------
def run_focused() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep = {"pass": "16", "mode": "focused_eval", "generated_at": time.time(),
           "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
           "game_timeout_s": GAME_TIMEOUT_S, "global_budget_s": GLOBAL_BUDGET_S,
           "notes": []}
    subs = _load_subfamilies()
    rep["subfamilies"] = [{"key": s["key"], "weight": s["weight"],
                           "confidence": s["confidence"]} for s in subs]
    if len(subs) < 2:
        rep["status"] = "blocked"
        rep["reason"] = "fewer_than_2_weighted_subfamilies"
        return rep

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cands, cnotes = _resolve_candidates(tmp)
        anchor, anotes = _resolve_anchor(tmp)
        rep["notes"] += cnotes + anotes
        rep["candidates_evaluated"] = [c["id"] for c in cands]
        rep["anchor"] = anchor["id"] if anchor else None
        if not cands:
            rep["status"] = "blocked"
            rep["reason"] = "no_validator_passing_candidates"
            return rep
        rep["status"] = "ran"
        per_candidate = {}
        from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent
        # Pre-materialize surrogate opponents once.
        surro = {}
        for s in subs:
            od = tmp / ("opp_" + s["key"])
            surro[s["key"]] = str(materialize_surrogate_agent(s["deck"], od))
        for c in cands:
            summary = {"id": c["id"], "role": c["role"], "per_subfamily": {},
                       "vs_anchor": None}
            for s in subs:
                m = _matchup(c["agent"], surro[s["key"]], GAMES_PER_SEAT,
                             budget_left, f"{c['id']}_vs_{s['key']}")
                m["weight"] = s["weight"]
                m["confidence"] = s["confidence"]
                summary["per_subfamily"][s["key"]] = m
            if anchor:
                va = _matchup(c["agent"], anchor["agent"], GAMES_PER_SEAT,
                              budget_left, f"{c['id']}_vs_anchor")
                summary["vs_anchor"] = va
            summary["weighted_meta_score"] = _weighted(summary["per_subfamily"])
            per_candidate[c["id"]] = summary
        rep["per_candidate"] = per_candidate
    rep["elapsed_s"] = round(time.time() - start, 1)
    rep["budget_exhausted"] = budget_left() <= 0
    return rep


def _write_matrix(rep: dict, path: Path) -> None:
    subs = [s["key"] for s in rep.get("subfamilies", [])]
    cols = ["candidate", "role", "weighted_meta_score"] + subs + ["vs_anchor"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for cid, c in (rep.get("per_candidate") or {}).items():
            row = [cid, c.get("role"), c.get("weighted_meta_score")]
            for k in subs:
                row.append((c["per_subfamily"].get(k) or {}).get("win_rate"))
            row.append((c.get("vs_anchor") or {}).get("win_rate"))
            w.writerow(row)


def build_ranking(rep: dict) -> dict:
    rows = []
    for cid, c in (rep.get("per_candidate") or {}).items():
        va = c.get("vs_anchor") or {}
        rows.append({
            "candidate": cid, "role": c.get("role"),
            "weighted_meta_score": c.get("weighted_meta_score"),
            "vs_anchor_win_rate": va.get("win_rate"),
            "vs_anchor_wilson": [va.get("wilson_low"), va.get("wilson_high")],
        })
    rows.sort(key=lambda r: (r["weighted_meta_score"] is not None,
                             r["weighted_meta_score"] or -1), reverse=True)
    return {
        "pass": "16", "disclaimer": rep.get("disclaimer"), "ranking": rows,
        "upload_ready": False,
        "reason_not_upload_ready": (
            "Surrogate eval is directional only; opponent subfamilies are piloted "
            "by a generic surrogate, not real policies. No candidate is "
            "promotable on this evidence."),
        "dry_run_queue": {
            "upload_performed": False, "auto_submit": False,
            "manual_approval": True, "human_review": True,
            "queued_candidates": [],
        },
    }


def _md_focused(rep: dict) -> str:
    if rep.get("status") != "ran":
        return (f"# Pass 16 focused eval\n\n> {rep.get('disclaimer','')}\n\n"
                f"- status: **{rep.get('status')}** (reason: {rep.get('reason')})\n")
    L = ["# Pass 16 real-sample focused eval (T-I)", "",
         f"> {rep['disclaimer']}", "",
         f"- status: **{rep['status']}**  games/seat: {rep['games_per_seat']}",
         f"- anchor: {rep.get('anchor')}",
         f"- candidates: {', '.join(rep.get('candidates_evaluated', []))}",
         f"- elapsed: {rep.get('elapsed_s')}s  budget_exhausted: {rep.get('budget_exhausted')}",
         "", "## Weighted meta score (Wilson CI on vs-anchor)",
         "| candidate | role | weighted_meta_score | vs_anchor win_rate | vs_anchor 95% CI |",
         "|---|---|---|---|---|"]
    for cid, c in rep["per_candidate"].items():
        va = c.get("vs_anchor") or {}
        ci = f"[{va.get('wilson_low')}, {va.get('wilson_high')}]"
        L.append(f"| {cid} | {c.get('role')} | {c.get('weighted_meta_score')} | "
                 f"{va.get('win_rate')} | {ci} |")
    L += ["", "## Per-subfamily win rates (Wilson 95% CI)",
          "| candidate | subfamily | conf | weight | win_rate | 95% CI | W-L-D | crash/timeout |",
          "|---|---|---|---|---|---|---|---|"]
    for cid, c in rep["per_candidate"].items():
        for k, m in c["per_subfamily"].items():
            ci = f"[{m.get('wilson_low')}, {m.get('wilson_high')}]"
            L.append(f"| {cid} | {k} | {m.get('confidence')} | {m.get('weight')} | "
                     f"{m.get('win_rate')} | {ci} | "
                     f"{m['wins']}-{m['losses']}-{m['draws']} | "
                     f"{m['crashes']}/{m['timeouts']} |")
    if rep.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in rep["notes"]]
    L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 16 candidate ranking (directional)", "",
         f"> {rank['disclaimer']}", "",
         "| rank | candidate | role | weighted_meta_score | vs_anchor | vs_anchor 95% CI |",
         "|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["ranking"], 1):
        ci = r.get("vs_anchor_wilson")
        L.append(f"| {i} | {r['candidate']} | {r.get('role')} | "
                 f"{r.get('weighted_meta_score')} | {r.get('vs_anchor_win_rate')} | "
                 f"{ci} |")
    q = rank["dry_run_queue"]
    L += ["", f"- upload ready: **{rank['upload_ready']}**",
          f"- reason: {rank['reason_not_upload_ready']}", "",
          "## Dry-run queue",
          f"- upload_performed: {q['upload_performed']}",
          f"- auto_submit: {q['auto_submit']}",
          f"- manual_approval: {q['manual_approval']}",
          f"- human_review: {q['human_review']}",
          f"- queued_candidates: {q['queued_candidates']}", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="run T-H smoke only")
    args = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        rep = run_smoke()
        (EXP / "pass16_live_smoke.json").write_text(
            json.dumps(rep, indent=2, default=str), encoding="utf-8")
        (EXP / "pass16_live_smoke.md").write_text(_md_smoke(rep), encoding="utf-8")
        print(f"smoke: healthy={rep['healthy']} "
              f"crashes+timeouts={rep['total_crashes_or_timeouts']} "
              f"elapsed={rep['elapsed_s']}s")
        return 0
    rep = run_focused()
    rank = build_ranking(rep)
    (EXP / "pass16_focused_eval.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass16_focused_eval.md").write_text(_md_focused(rep), encoding="utf-8")
    (EXP / "pass16_ranking.json").write_text(
        json.dumps(rank, indent=2, default=str), encoding="utf-8")
    (EXP / "pass16_ranking.md").write_text(_md_rank(rank), encoding="utf-8")
    if rep.get("status") == "ran":
        _write_matrix(rep, EXP / "pass16_matchup_matrix.csv")
    print(f"focused eval: status={rep.get('status')} "
          f"candidates={len(rep.get('candidates_evaluated', []))} "
          f"subfamilies={len(rep.get('subfamilies', []))} "
          f"elapsed={rep.get('elapsed_s')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
