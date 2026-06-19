#!/usr/bin/env python3
"""Pass 30 (Part I) — replay-derived meta sanity check (LOCAL, DIRECTIONAL ONLY).

NOT a Kaggle leaderboard and NOT a promotion gate. Plays our top portfolio
candidates (plus the Water benchmark and one Raging Bolt deck for an honest
collapse comparison) against the replay-derived opponent subfamilies, each piloted
by the same generic surrogate brain. Replays give us opponent DECK LISTS, never
their POLICIES, so every win rate here is surrogate-vs-surrogate and DIRECTIONAL
ONLY: it never equals a Kaggle result and is never sufficient to promote, upload,
or submit anything.

Gated on Part-F validation clean + Part-G tournament complete. Reuses the proven
Pass-18 meta-sanity machinery (subfamily loader, surrogate worker, weighted
score). Outputs data/experiments/pass30_meta_sanity.{json,md} +
pass30_meta_sanity_matrix.csv + sentinel pass30_meta_sanity.DONE. STRICT: no
upload, no submission, no candidate generation, no invented card ids.
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
CAND = REPO / "data" / "submissions" / "candidates_pass30"
OUT_JSON = EXP / "pass30_meta_sanity.json"
OUT_MD = EXP / "pass30_meta_sanity.md"
OUT_CSV = EXP / "pass30_meta_sanity_matrix.csv"
SENTINEL = EXP / "pass30_meta_sanity.DONE"
PROGRESS = EXP / "pass30_meta_sanity_progress.json"
VALIDATION = EXP / "pass30_candidate_validation.json"
TOURNAMENT_DONE = EXP / "pass30_portfolio_tournament.DONE"

GAMES_PER_SEAT = int(os.environ.get("P30_META_GAMES_PER_SEAT", "3"))
GLOBAL_BUDGET_S = int(os.environ.get("P30_META_GLOBAL_BUDGET_S", "1500"))
PER_CALL_BUDGET_S = int(os.environ.get("P30_PER_CALL_BUDGET_S", "70"))

# Top portfolio decks under inspection + Water benchmark + one RB collapse control.
OUR_DECKS = [
    {"id": "league_water_core_reference", "role": "water_benchmark"},
    {"id": "league_water_anti_disruption_pivot_v1", "role": "water_live_leader"},
    {"id": "league_dragapult_v1_search_only", "role": "dragapult_top_child"},
    {"id": "league_dragapult_v1_draw_only", "role": "dragapult_child"},
    {"id": "league_mega_charizard_x_burst", "role": "diagnostic_benchmark"},
    {"id": "league_raging_bolt_ogerpon", "role": "raging_bolt_collapse_control"},
]

DISCLAIMER = (
    "SANITY CHECK — SURROGATE-BASED, DIRECTIONAL ONLY. Opponent subfamilies are "
    "replay-derived DECK LISTS piloted by a generic surrogate brain, not the real "
    "opponent policies. Win rates are surrogate-vs-surrogate and never equal Kaggle "
    "results. This is NOT a Kaggle leaderboard and is never sufficient to promote, "
    "upload, or submit any candidate. No upload performed.")
COLLAPSE_THRESHOLD = 0.10


def _gate_clean() -> tuple[bool, list[str]]:
    notes, ok = [], True
    if VALIDATION.exists():
        v = json.loads(VALIDATION.read_text(encoding="utf-8"))
        if not v.get("all_non_blocked_eligible"):
            ok = False
            notes.append("Part-F validation not clean for all non-blocked candidates")
    else:
        ok = False
        notes.append("Part-F validation report missing")
    if not TOURNAMENT_DONE.exists():
        ok = False
        notes.append("Part-G tournament sentinel missing (run Stage 1 to completion)")
    return ok, notes


def run() -> dict:
    start = time.time()

    def budget_left():
        return min(GLOBAL_BUDGET_S - (time.time() - start),
                   PER_CALL_BUDGET_S - (time.time() - start))

    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else {})
    rep: dict = {"pass": "30", "part": "I", "local_only": True,
                 "upload_performed": False, "is_kaggle_leaderboard": False,
                 "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
                 "global_budget_s": GLOBAL_BUDGET_S}
    gate_ok, gate_notes = _gate_clean()
    rep["gate_clean"] = gate_ok
    rep["notes"] = list(gate_notes)
    if not gate_ok:
        rep["status"] = "blocked"
        rep["reason"] = "validator_or_tournament_not_clean"
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

    per_deck: dict = prog.get("per_deck", {})
    decks_this_call = 0
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        for d in OUR_DECKS:
            if d["id"] in per_deck:
                continue
            # Process exactly one new deck per call so every deck gets full,
            # uncorrupted subfamily coverage within the bash timeout.
            if decks_this_call >= 1:
                break
            tar = CAND / f"{d['id']}.tar.gz"
            if not (tar.exists() and _validate_tarball(tar)):
                rep["notes"].append(f"{d['id']}: tarball missing/invalid")
                per_deck[d["id"]] = {"id": d["id"], "role": d["role"],
                                     "per_archetype": {}, "weighted_meta_score": None,
                                     "error": "tarball_missing"}
                continue
            agent = _extract_agent(tar, tmp / d["id"])
            per_arch: dict = {}
            for opp in opponents:
                with tempfile.TemporaryDirectory() as od:
                    opp_agent = str(materialize_surrogate_agent(opp["deck"], od))
                    m = _matchup(agent, opp_agent, GAMES_PER_SEAT, budget_left)
                per_arch[opp["key"]] = {**m, "weight": opp["weight"],
                                        "confidence": opp["confidence"],
                                        "status": opp["status"]}
            per_deck[d["id"]] = {"id": d["id"], "role": d["role"],
                                 "per_archetype": per_arch,
                                 "weighted_meta_score": _weighted_meta_score(
                                     per_arch, weights)}
            decks_this_call += 1
            PROGRESS.write_text(json.dumps(
                {"per_deck": per_deck, "opponent_subfamilies":
                 rep["opponent_subfamilies"], "evaluation_weights": weights},
                indent=2, default=str), encoding="utf-8")

    rep["our_decks"] = list(per_deck.keys())
    rep["per_deck"] = per_deck
    done = all(d["id"] in per_deck for d in OUR_DECKS)
    rep["status"] = "ran" if done else "in_progress"
    rep["elapsed_s"] = round(time.time() - start, 1)
    if done:
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
        out["per_deck"][did] = {"weighted_meta_score": score, "collapses": collapses,
                                "vs_water": vs_water, "no_collapse": not collapses}
        if collapses and d.get("role") != "raging_bolt_collapse_control":
            all_ok = False
    out["sanity_passed"] = all_ok
    out["note_rb"] = ("Raging Bolt is included as an EXPECTED collapse control "
                      "(known generic-pilot mismatch); its collapse does not fail "
                      "the sanity verdict.")
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
    L = ["# Pass 30 — replay-derived meta sanity check (Part I)", "",
         f"> {rep.get('disclaimer','')}", "",
         f"- is Kaggle leaderboard: **{rep.get('is_kaggle_leaderboard')}**  "
         f"upload_performed: **{rep.get('upload_performed')}**",
         f"- status: **{rep.get('status')}**"
         + (f" (reason: {rep.get('reason')})" if rep.get("reason") else ""),
         f"- games per seat: {rep.get('games_per_seat')}  (elapsed "
         f"{rep.get('elapsed_s')}s)",
         f"- opponent subfamilies: "
         f"{', '.join(rep.get('opponent_subfamilies', [])) or 'none'}", ""]
    sv = rep.get("sanity") or {}
    if sv:
        L += ["## Sanity verdict",
              f"- sanity passed (no unexpected collapses): "
              f"**{sv.get('sanity_passed')}**",
              f"- water weighted meta score: {sv.get('water_weighted_meta_score')}",
              f"- {sv.get('note_rb','')}", "",
              "| deck | weighted_meta_score | vs water | collapses |",
              "|---|---|---|---|"]
        for did, v in sv.get("per_deck", {}).items():
            L.append(f"| {did} | {v['weighted_meta_score']} | {v['vs_water']} | "
                     f"{v['collapses'] or 'none'} |")
        L += ["", f"_{sv.get('interpretation','')}_", ""]
    pd = rep.get("per_deck") or {}
    if pd:
        L += ["## Per-subfamily win rates",
              "| deck | subfamily | confidence | weight | win_rate | W-L-D | "
              "crash/timeout/skip |", "|---|---|---|---|---|---|---|"]
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
        if PROGRESS.exists():
            PROGRESS.unlink()
    sv = rep.get("sanity") or {}
    print(f"meta sanity: status={rep.get('status')} "
          f"decks={len(rep.get('per_deck', {}))}/{len(OUR_DECKS)} "
          f"subfamilies={len(rep.get('opponent_subfamilies', []))} "
          f"sanity_passed={sv.get('sanity_passed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
