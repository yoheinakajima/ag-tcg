#!/usr/bin/env python3
"""Pass 33 (Part I) — parent/child & reference head-to-head confirmations.

LOCAL ONLY / NOT A KAGGLE LEADERBOARD. Direct seat-swapped H2H between our own
decks under the same generic core pilot. Win rates are internal compatibility
signals only and never predict Kaggle standings or justify upload.

Pairs (parent/reference listed first, child/challenger second):
  1. Water best  vs water_basic_density_v1
  2. Water best  vs water_basic_density_v2
  3. Dragapult spread (parent) vs dragapult search_only
  4. Venusaur tank (parent)    vs effect_loop_exit_guard_v1
  5. Water best  vs Mega Charizard X burst
  6. Water best  vs best non-Water (by Stage-1 internal rank)

Budget: P33_PC_GAMES_PER_SEAT (default 10) seat-swapped games per pair. RESUMABLE:
each call plays as many pairs as fit in P33_PC_PER_CALL_BUDGET_S; re-invoke until
"remaining=0".

Verdicts (child = second deck): child_better, parent_better, inconclusive,
child_fixed_bug_but_weaker, needs_more_games.

Writes pass33_parent_child_confirmations.{json,md}.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass33"
RANKINGS = EXP / "pass33_composition_rankings.json"
PROGRESS = EXP / "pass33_parent_child_confirmations_progress.json"

WATER_BEST = "league_water_anti_disruption_pivot_v1"
GAMES_PER_SEAT = int(os.environ.get("P33_PC_GAMES_PER_SEAT", "10"))
GAME_TIMEOUT_S = int(os.environ.get("P33_PC_GAME_TIMEOUT_S", "60"))
PER_CALL_BUDGET_S = int(os.environ.get("P33_PC_PER_CALL_BUDGET_S", "95"))

DISCLAIMER = (
    "INTERNAL HEAD-TO-HEAD — NOT A KAGGLE LEADERBOARD. Both decks run the same "
    "generic core pilot; results are internal compatibility signals only and never "
    "predict Kaggle standings or justify upload.")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _run_game(a, b):
    _MEV.GAME_TIMEOUT_S = GAME_TIMEOUT_S
    return _MEV._run_game(a, b)


def _best_non_water() -> str | None:
    if not RANKINGS.exists():
        return None
    rk = json.loads(RANKINGS.read_text(encoding="utf-8"))
    for r in rk.get("standings", []):
        if r.get("family") != "water" and r.get("adj_win_rate") is not None:
            return r["id"]
    return None


def _pairs() -> list[dict]:
    bnw = _best_non_water()
    pairs = [
        {"key": "water_best__vs__density_v1", "parent": WATER_BEST,
         "child": "water_basic_density_v1", "kind": "parent_child",
         "rationale": "Does adding 4 Basics (Mantine #720) over the Basic-light "
                      "parent improve internal compatibility?"},
        {"key": "water_best__vs__density_v2", "parent": WATER_BEST,
         "child": "water_basic_density_v2", "kind": "parent_child",
         "rationale": "Does the aggressive 16-Basic build (Mantine+Alomomola) beat "
                      "the parent, and does it add over the moderate v1?"},
        {"key": "dragapult_spread__vs__search_only", "parent": "league_dragapult_spread",
         "child": "league_dragapult_v1_search_only", "kind": "parent_child",
         "rationale": "Dragapult spread parent vs its search-only sibling."},
        {"key": "venusaur_tank__vs__loop_guard", "parent": "league_mega_venusaur_tank",
         "child": "effect_loop_exit_guard_v1", "kind": "parent_child",
         "rationale": "Venusaur tank parent vs the loop/exit-guard reuse on the "
                      "same 4-Basic shell."},
        {"key": "water_best__vs__charizard", "parent": WATER_BEST,
         "child": "league_mega_charizard_x_burst", "kind": "reference_vs_challenger",
         "rationale": "High-ceiling Mega Charizard burst challenger vs Water best."},
    ]
    if bnw and bnw != WATER_BEST:
        pairs.append({
            "key": "water_best__vs__best_nonwater", "parent": WATER_BEST,
            "child": bnw, "kind": "reference_vs_challenger",
            "rationale": f"Best non-Water deck by Stage-1 internal rank ({bnw}) vs "
                         "Water best."})
    return pairs


def _play(parent_agent, child_agent, per_seat) -> dict:
    games = []
    # child is the "a" side; seat-swap: child seat0 then child seat1.
    for (first, second, child_seat) in [(child_agent, parent_agent, 0),
                                        (parent_agent, child_agent, 1)]:
        for _ in range(per_seat):
            g = _run_game(first, second)
            g["child_seat"] = child_seat
            g["child_outcome"] = (_MEV._outcome_for_seat(g, child_seat)
                                  if g.get("ok") else None)
            games.append(g)
    cw = sum(1 for g in games if g.get("child_outcome") == "win")
    cl = sum(1 for g in games if g.get("child_outcome") == "loss")
    dr = sum(1 for g in games if g.get("child_outcome") == "draw")
    decisive = cw + cl
    invalids = sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                   and not str(g.get("error", "")).startswith("watchdog"))
    timeouts = sum(1 for g in games if g.get("timeout"))
    lo, hi = _wilson(cw, decisive)
    return {
        "n_games": len(games), "parent_wins": cl, "child_wins": cw, "draws": dr,
        "child_adj_win_rate": round(cw / decisive, 4) if decisive else None,
        "child_wilson": [lo, hi],
        "child_wins_seat0": sum(1 for g in games if g.get("child_seat") == 0
                                and g.get("child_outcome") == "win"),
        "child_wins_seat1": sum(1 for g in games if g.get("child_seat") == 1
                                and g.get("child_outcome") == "win"),
        "invalids": invalids, "timeouts": timeouts,
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
    }


def _verdict(res: dict) -> str:
    awr = res["child_adj_win_rate"]
    lo, hi = res["child_wilson"]
    if awr is None:
        return "needs_more_games"
    if res["invalids"] or res["timeouts"]:
        if awr < 0.45:
            return "child_fixed_bug_but_weaker"
    if lo is not None and lo > 0.5:
        return "child_better"
    if hi is not None and hi < 0.5:
        return "parent_better"
    width = (hi - lo) if (lo is not None and hi is not None) else 1.0
    if width > 0.45:
        return "needs_more_games"
    if awr >= 0.55:
        return "child_better"
    if awr <= 0.45:
        return "parent_better"
    return "inconclusive"


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else {
                "pass": "33", "part": "I", "local_only": True, "no_upload": True,
                "upload_performed": False, "is_kaggle_leaderboard": False,
                "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
                "water_best": WATER_BEST, "pairs": _pairs(), "results": {}})

    pending = [p for p in prog["pairs"] if p["key"] not in prog["results"]]
    start = time.time()
    played = 0
    if pending:
        needed = {x for p in pending for x in (p["parent"], p["child"])}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            agents = {}
            for cid in needed:
                tar = CAND / f"{cid}.tar.gz"
                if tar.exists() and _MEV._validate_tarball(tar):
                    agents[cid] = _MEV._extract_agent(tar, tmp / cid)
            for p in pending:
                if time.time() - start + 2 * GAMES_PER_SEAT * 1.4 > PER_CALL_BUDGET_S \
                        and played > 0:
                    break
                if p["parent"] not in agents or p["child"] not in agents:
                    prog["results"][p["key"]] = {
                        **p, "skipped": True, "reason": "agent missing"}
                    continue
                res = _play(agents[p["parent"]], agents[p["child"]], GAMES_PER_SEAT)
                res.update({**p, "verdict": _verdict(res)})
                prog["results"][p["key"]] = res
                played += 1
                PROGRESS.write_text(json.dumps(prog, indent=2), encoding="utf-8")

    remaining = len([p for p in prog["pairs"] if p["key"] not in prog["results"]])
    done = remaining == 0
    PROGRESS.write_text(json.dumps(prog, indent=2), encoding="utf-8")

    ordered = [prog["results"][p["key"]] for p in prog["pairs"]
               if p["key"] in prog["results"]]
    rep = {**{k: prog[k] for k in ("pass", "part", "local_only", "no_upload",
                                   "upload_performed", "is_kaggle_leaderboard",
                                   "disclaimer", "games_per_seat", "water_best")},
           "status": "complete" if done else "in_progress",
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "confirmations": ordered}
    (EXP / "pass33_parent_child_confirmations.json").write_text(
        json.dumps(rep, indent=2), encoding="utf-8")

    L = ["# Pass 33 — Parent/Child & Reference Confirmations (Part I)", "",
         f"> {DISCLAIMER}", "",
         f"- status: **{rep['status']}**  games/seat: {GAMES_PER_SEAT} (seat-swapped)",
         f"- Water best (reference): `{WATER_BEST}`",
         "- is Kaggle leaderboard: **False**  upload_performed: **False**", "",
         "| pair | parent | child | P-C-D | child win_rate | child 95% CI | "
         "seat0/1 | inv/to | verdict | rationale |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in ordered:
        if r.get("skipped"):
            L.append(f"| {r['key']} | {r['parent']} | {r['child']} | — | — | — | "
                     f"— | — | skipped | {r.get('reason','')} |")
            continue
        ci = f"[{r['child_wilson'][0]}, {r['child_wilson'][1]}]"
        L.append(f"| {r['key']} | {r['parent']} | {r['child']} | "
                 f"{r['parent_wins']}-{r['child_wins']}-{r['draws']} | "
                 f"{r['child_adj_win_rate']} | {ci} | "
                 f"{r['child_wins_seat0']}/{r['child_wins_seat1']} | "
                 f"{r['invalids']}/{r['timeouts']} | **{r['verdict']}** | "
                 f"{r['rationale']} |")
    L += ["", "_'child' is the second deck in each pair. Verdicts are internal "
          "compatibility signals only; CIs are wide at this sample size and never "
          "predict Kaggle results._", ""]
    (EXP / "pass33_parent_child_confirmations.md").write_text("\n".join(L),
                                                              encoding="utf-8")

    for r in ordered:
        print(f"{r['key']}: verdict={r.get('verdict','skipped')} "
              f"child_awr={r.get('child_adj_win_rate')}")
    print(f"\nremaining={remaining} played_this_call={played}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
