#!/usr/bin/env python3
"""Pass 19 (Part J) — replay-derived meta sanity check (LOCAL, DIRECTIONAL ONLY).

This is a *sanity* check, not a promotion gate. It plays our Dragapult lineage (parent,
child, and the Pass-19 targeted-revert refinement) plus the stable Water reference
against the Pass-13 replay-derived opponent subfamilies, each piloted by the same generic
surrogate brain. Replays give us opponent DECK LISTS, never their POLICIES, so every win
rate here is surrogate-vs-surrogate and DIRECTIONAL ONLY: it never equals a Kaggle result
and is never sufficient to promote, upload, or submit anything.

Only runs when validators + the mini-league are clean (Part H/I gate). Reuses the proven
Pass-18 meta-sanity machinery (subfamily loader, surrogate worker, weighted score) and
just widens the set of OUR decks under inspection to the parent/child/refinement lineage.

Outputs: data/experiments/pass19_meta_sanity.{json,md} + pass19_meta_sanity_matrix.csv
and a sentinel pass19_meta_sanity.DONE. STRICT: no upload, no submission, no candidate
generation, no invented card ids.
"""
from __future__ import annotations

import csv
import importlib.util as _ilu
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))


def _load(name: str, rel: str):
    spec = _ilu.spec_from_file_location(name, REPO / rel)
    mod = _ilu.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_M = _load("run_pass18_meta_sanity", "scripts/run_pass18_meta_sanity.py")
_MEV = _load("run_meta_pool_eval", "scripts/run_meta_pool_eval.py")
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_load_opponents = _M._load_opponents
_matchup = _M._matchup
_weighted_meta_score = _M._weighted_meta_score

from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent  # noqa: E402

EXP = REPO / "data" / "experiments"
OUT_JSON = EXP / "pass19_meta_sanity.json"
OUT_MD = EXP / "pass19_meta_sanity.md"
OUT_CSV = EXP / "pass19_meta_sanity_matrix.csv"
SENTINEL = EXP / "pass19_meta_sanity.DONE"
VALIDATION = EXP / "pass19_candidate_validation.json"
MINI_LEAGUE = EXP / "pass19_mini_league.DONE"

GAMES_PER_SEAT = int(os.environ.get("P19_META_GAMES_PER_SEAT", "3"))
GLOBAL_BUDGET_S = int(os.environ.get("P19_META_GLOBAL_BUDGET_S", "1500"))

OUR_DECKS = [
    {"id": "league_dragapult_spread", "role": "parent",
     "tarball": "data/submissions/candidates_pass17/league_dragapult_spread.tar.gz"},
    {"id": "league_dragapult_spread_v1", "role": "child",
     "tarball": "data/submissions/candidates_pass18/league_dragapult_spread_v1.tar.gz"},
    {"id": "league_dragapult_v1_search_only", "role": "pass19_targeted_revert",
     "tarball":
        "data/submissions/candidates_pass19/league_dragapult_v1_search_only.tar.gz"},
    {"id": "league_water_core_reference", "role": "stable_benchmark",
     "tarball": "data/submissions/candidates_pass17/league_water_core_reference.tar.gz"},
]

DISCLAIMER = (
    "SANITY CHECK — SURROGATE-BASED, DIRECTIONAL ONLY. Opponent subfamilies are "
    "replay-derived DECK LISTS piloted by a generic surrogate brain, not the real "
    "opponent policies. Win rates are surrogate-vs-surrogate and never equal Kaggle "
    "results. This is NOT a Kaggle leaderboard and is never sufficient to promote, "
    "upload, or submit any candidate. No upload performed."
)
COLLAPSE_THRESHOLD = 0.10


def _gate_clean() -> tuple[bool, list[str]]:
    notes = []
    ok = True
    if VALIDATION.exists():
        v = json.loads(VALIDATION.read_text(encoding="utf-8"))
        if not all(c.get("overall_ok") for c in v.get("candidates", {}).values()):
            ok = False
            notes.append("Part-H validation not clean for all candidates")
    else:
        ok = False
        notes.append("Part-H validation report missing")
    if MINI_LEAGUE.exists():
        ml = json.loads(MINI_LEAGUE.read_text(encoding="utf-8"))
        if ml.get("status") != "ran":
            ok = False
            notes.append(f"Part-I mini-league status={ml.get('status')}")
    else:
        ok = False
        notes.append("Part-I mini-league sentinel missing")
    return ok, notes


def run() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep: dict = {"pass": "19", "part": "J", "local_only": True, "upload_performed": False,
                 "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
                 "games_per_seat": GAMES_PER_SEAT, "global_budget_s": GLOBAL_BUDGET_S}
    gate_ok, gate_notes = _gate_clean()
    rep["gate_clean"] = gate_ok
    rep["notes"] = list(gate_notes)
    if not gate_ok:
        rep["status"] = "blocked"
        rep["reason"] = "validator_or_league_not_clean"
        rep["elapsed_s"] = round(time.time() - start, 1)
        return rep

    opponents, weights = _load_opponents()
    rep["evaluation_weights"] = weights
    rep["opponent_subfamilies"] = [o["key"] for o in opponents]
    if not opponents:
        rep["status"] = "blocked"
        rep["reason"] = "no_weighted_opponent_subfamilies"
        rep["elapsed_s"] = round(time.time() - start, 1)
        return rep

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        our: list[dict] = []
        for d in OUR_DECKS:
            tar = REPO / d["tarball"]
            if tar.exists() and _validate_tarball(tar):
                our.append({**d, "agent": _extract_agent(tar, tmp / d["id"])})
            else:
                rep["notes"].append(f"{d['id']}: tarball missing/invalid")
        rep["our_decks"] = [d["id"] for d in our]
        per_deck: dict = {}
        for d in our:
            per_arch: dict = {}
            for opp in opponents:
                with tempfile.TemporaryDirectory() as od:
                    opp_agent = str(materialize_surrogate_agent(opp["deck"], od))
                    m = _matchup(d["agent"], opp_agent, GAMES_PER_SEAT, budget_left)
                per_arch[opp["key"]] = {**m, "weight": opp["weight"],
                                        "confidence": opp["confidence"],
                                        "status": opp["status"]}
            per_deck[d["id"]] = {"id": d["id"], "role": d["role"],
                                 "per_archetype": per_arch,
                                 "weighted_meta_score": _weighted_meta_score(
                                     per_arch, weights)}
        rep["per_deck"] = per_deck
    rep["status"] = "ran"
    rep["elapsed_s"] = round(time.time() - start, 1)
    rep["budget_exhausted"] = budget_left() <= 0
    rep["sanity"] = _verdict(rep)
    return rep


def _verdict(rep: dict) -> dict:
    pd = rep.get("per_deck") or {}
    water = (pd.get("league_water_core_reference") or {}).get("weighted_meta_score")
    out = {"water_weighted_meta_score": water, "collapse_threshold": COLLAPSE_THRESHOLD,
           "per_deck": {}, "interpretation": (
               "DIRECTIONAL sanity only. A deck 'collapses' if its win rate vs any "
               "replay-derived subfamily is below %.0f%%. Scores are surrogate-vs-"
               "surrogate and are NOT a promotion or upload signal."
               % (COLLAPSE_THRESHOLD * 100))}
    all_ok = True
    for did, d in pd.items():
        collapses = [{"subfamily": k, "win_rate": m.get("win_rate")}
                     for k, m in d.get("per_archetype", {}).items()
                     if m.get("win_rate") is not None
                     and m["win_rate"] < COLLAPSE_THRESHOLD]
        score = d.get("weighted_meta_score")
        vs_water = (None if (score is None or water is None)
                    else round(score - water, 4))
        out["per_deck"][did] = {"weighted_meta_score": score,
                                "collapses": collapses, "vs_water": vs_water,
                                "no_collapse": not collapses}
        if collapses:
            all_ok = False
    out["sanity_passed"] = all_ok
    return out


def _write_csv(rep: dict) -> None:
    opps = rep.get("opponent_subfamilies", [])
    pd = rep.get("per_deck") or {}
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["our_deck \\ subfamily (win_rate)"] + opps + ["weighted_meta_score"])
        for did, d in pd.items():
            row = [did]
            for k in opps:
                wr = (d.get("per_archetype", {}).get(k) or {}).get("win_rate")
                row.append("—" if wr is None else wr)
            row.append(d.get("weighted_meta_score"))
            w.writerow(row)


def _md(rep: dict) -> str:
    L = ["# Pass 19 — replay-derived meta sanity check (Part J)", "",
         f"> {rep.get('disclaimer','')}", "",
         f"- is Kaggle leaderboard: **{rep.get('is_kaggle_leaderboard')}**  "
         f"upload_performed: **{rep.get('upload_performed')}**",
         f"- status: **{rep.get('status')}**"
         + (f" (reason: {rep.get('reason')})" if rep.get("reason") else ""),
         f"- games per seat: {rep.get('games_per_seat')}  "
         f"(elapsed {rep.get('elapsed_s')}s, budget_exhausted "
         f"{rep.get('budget_exhausted')})",
         f"- opponent subfamilies: "
         f"{', '.join(rep.get('opponent_subfamilies', [])) or 'none'}", ""]
    sv = rep.get("sanity") or {}
    if sv:
        L += ["## Sanity verdict",
              f"- sanity passed (no collapses): **{sv.get('sanity_passed')}**",
              f"- water weighted meta score: {sv.get('water_weighted_meta_score')}", "",
              "| deck | weighted_meta_score | vs water | collapses |",
              "|---|---|---|---|"]
        for did, v in sv.get("per_deck", {}).items():
            L.append(f"| {did} | {v['weighted_meta_score']} | {v['vs_water']} | "
                     f"{v['collapses'] or 'none'} |")
        L += ["", f"_{sv.get('interpretation','')}_", ""]
    pd = rep.get("per_deck") or {}
    if pd:
        L += ["## Per-subfamily win rates",
              "| deck | subfamily | confidence | weight | win_rate | W-L-D | crash/timeout/skip |",
              "|---|---|---|---|---|---|---|"]
        for did, d in pd.items():
            for k, m in d.get("per_archetype", {}).items():
                L.append(f"| {did} | {k} | {m.get('confidence')} | {m.get('weight')} "
                         f"| {m.get('win_rate')} | "
                         f"{m.get('wins')}-{m.get('losses')}-{m.get('draws')} | "
                         f"{m.get('crashes')}/{m.get('timeouts')}/{m.get('skipped')} |")
        L.append("")
    if rep.get("notes"):
        L += ["## Notes"] + [f"- {n}" for n in rep["notes"]] + [""]
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    if SENTINEL.exists():
        SENTINEL.unlink()
    rep = run()
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_md(rep), encoding="utf-8")
    if rep.get("status") == "ran":
        _write_csv(rep)
    sv = rep.get("sanity") or {}
    SENTINEL.write_text(json.dumps(
        {"status": rep.get("status"), "elapsed_s": rep.get("elapsed_s"),
         "sanity_passed": sv.get("sanity_passed"), "reason": rep.get("reason")},
        indent=2), encoding="utf-8")
    print(f"meta sanity: status={rep.get('status')} "
          f"subfamilies={len(rep.get('opponent_subfamilies', []))} "
          f"sanity_passed={sv.get('sanity_passed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
