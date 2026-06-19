#!/usr/bin/env python3
"""Pass 18 Part L -- replay-derived meta sanity check (LOCAL, DIRECTIONAL ONLY).

This is a *sanity* check, not a promotion gate. It plays our stable decks against
the Pass-13 replay-derived opponent subfamilies, each piloted by the same generic
surrogate brain (``sim/surrogate_agents.py``). Replays give us opponent *deck
lists*, never their *policies*, so every win rate here is surrogate-vs-surrogate
and DIRECTIONAL ONLY: it never equals a Kaggle result and is never sufficient to
promote, upload, or submit anything.

What it checks (and why it is only a sanity check):
  * our Pass-18 candidate (``league_dragapult_spread_v1``) and the stable Water
    reference (``league_water_core_reference``) do not catastrophically collapse
    against any replay-grounded subfamily; and
  * the candidate's weighted meta score is in a sane band relative to the Water
    reference -- a regression signal, not a leaderboard prediction.

Engine isolation: games run through the batched subprocess worker
(``scripts/_pass18_game_worker.py``) reused from Part K, so the cabt engine's
per-process memory growth never reaches the runaway regime, and each matchup-seat
batch has a real, enforceable timeout.

Inputs:
  experiments/pass13_refined_meta_pool.yaml   (opponent subfamilies + weights)
  data/submissions/candidates_pass18/league_dragapult_spread_v1.tar.gz
  data/submissions/candidates_pass17/league_water_core_reference.tar.gz

Outputs:
  data/experiments/pass18_meta_sanity.json / .md
  data/experiments/pass18_meta_sanity_matrix.csv

STRICT: no upload, no submission, no candidate generation, no invented card ids.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load_module("run_meta_pool_eval", "scripts/run_meta_pool_eval.py")
_LEAGUE = _load_module("run_pass18_internal_league", "scripts/run_pass18_internal_league.py")

_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_outcome_for_seat = _MEV._outcome_for_seat
_run_seat_batch = _LEAGUE._run_seat_batch

from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent  # noqa: E402

POOL = REPO / "experiments" / "pass13_refined_meta_pool.yaml"
OUT_JSON = REPO / "data" / "experiments" / "pass18_meta_sanity.json"
OUT_MD = REPO / "data" / "experiments" / "pass18_meta_sanity.md"
OUT_CSV = REPO / "data" / "experiments" / "pass18_meta_sanity_matrix.csv"

GAMES_PER_SEAT = int(os.environ.get("P18_META_GAMES_PER_SEAT", "3"))
GLOBAL_BUDGET_S = int(os.environ.get("P18_META_GLOBAL_BUDGET_S", "900"))

# Our decks under sanity check. Both are stable / carried artifacts; this pass
# does NOT generate new candidates here.
OUR_DECKS = [
    {"id": "league_dragapult_spread_v1", "role": "pass18_candidate",
     "tarball": "data/submissions/candidates_pass18/league_dragapult_spread_v1.tar.gz"},
    {"id": "league_water_core_reference", "role": "stable_benchmark",
     "tarball": "data/submissions/candidates_pass17/league_water_core_reference.tar.gz"},
]

DISCLAIMER = (
    "SANITY CHECK -- SURROGATE-BASED, DIRECTIONAL ONLY. Opponent subfamilies are "
    "replay-derived DECK LISTS piloted by a generic surrogate brain, not the real "
    "opponent policies. Win rates are surrogate-vs-surrogate and never equal Kaggle "
    "results. This is NOT a Kaggle leaderboard and is never sufficient to promote, "
    "upload, or submit any candidate. No upload performed."
)


def _load_opponents() -> tuple[list[dict], dict]:
    if yaml is None or not POOL.exists():
        return [], {}
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    weights = pool.get("evaluation_weights", {}) or {}
    opps = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours"):
            continue
        deck = a.get("surrogate_deck")
        w = weights.get(a["key"], 0.0)
        if deck and (REPO / deck).exists() and w > 0:
            opps.append({"key": a["key"], "deck": str(REPO / deck),
                         "confidence": a.get("confidence"),
                         "status": a.get("status"), "weight": w})
    return opps, weights


def _summarize(games: list[dict]) -> dict:
    wins = sum(1 for g in games if g.get("a_outcome") == "win")
    losses = sum(1 for g in games if g.get("a_outcome") == "loss")
    draws = sum(1 for g in games if g.get("a_outcome") == "draw")
    decisive = wins + losses
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "crashes": sum(1 for g in games if not g.get("ok")
                       and not g.get("timeout") and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
    }


def _matchup(our_agent: str, opp_agent: str, per_seat: int,
             budget_left) -> dict:
    games: list[dict] = []
    for (first, second, a_seat) in [(our_agent, opp_agent, 0),
                                    (opp_agent, our_agent, 1)]:
        if budget_left() <= 0:
            for _ in range(per_seat):
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted",
                              "a_seat": a_seat})
            continue
        for g in _run_seat_batch(first, second, per_seat):
            g["a_seat"] = a_seat
            g["a_outcome"] = _outcome_for_seat(g, a_seat)
            games.append(g)
    return _summarize(games)


def _weighted_meta_score(per_arch: dict, weights: dict):
    total_w = acc = 0.0
    for key, w in weights.items():
        wr = (per_arch.get(key) or {}).get("win_rate")
        if wr is None:
            continue
        acc += float(w) * float(wr)
        total_w += float(w)
    return round(acc / total_w, 4) if total_w > 0 else None


def run() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep: dict = {
        "pass": "18", "part": "L", "local_only": True,
        "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER,
        "games_per_seat": GAMES_PER_SEAT,
        "global_budget_s": GLOBAL_BUDGET_S,
        "pool": str(POOL.relative_to(REPO)),
    }
    opponents, weights = _load_opponents()
    rep["evaluation_weights"] = weights
    rep["opponent_subfamilies"] = [o["key"] for o in opponents]

    if not opponents:
        rep["status"] = "blocked"
        rep["reason"] = "no_weighted_opponent_subfamilies"
        return rep

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        # resolve our decks (extract validated tarballs to stable agent dirs).
        our: list[dict] = []
        notes: list[str] = []
        for d in OUR_DECKS:
            tar = REPO / d["tarball"]
            if tar.exists() and _validate_tarball(tar):
                agent = _extract_agent(tar, tmp / d["id"])
                our.append({**d, "agent": agent})
            else:
                notes.append(f"{d['id']}: tarball missing/invalid ({d['tarball']})")
        rep["our_decks"] = [d["id"] for d in our]
        rep["notes"] = notes

        per_deck: dict = {}
        for d in our:
            per_arch: dict = {}
            for opp in opponents:
                # materialize surrogate into a dir that stays alive across the
                # (blocking) batch call, then evaluate.
                with tempfile.TemporaryDirectory() as od:
                    opp_agent = str(materialize_surrogate_agent(opp["deck"], od))
                    m = _matchup(d["agent"], opp_agent, GAMES_PER_SEAT,
                                 budget_left)
                per_arch[opp["key"]] = {
                    **m, "weight": opp["weight"],
                    "confidence": opp["confidence"], "status": opp["status"],
                }
            per_deck[d["id"]] = {
                "id": d["id"], "role": d["role"],
                "per_archetype": per_arch,
                "weighted_meta_score": _weighted_meta_score(per_arch, weights),
            }
        rep["per_deck"] = per_deck

    rep["status"] = "ran"
    rep["elapsed_s"] = round(time.time() - start, 1)
    rep["budget_exhausted"] = budget_left() <= 0

    # sanity verdict: candidate must not collapse vs any subfamily and must not
    # regress badly vs the Water reference's weighted score.
    rep["sanity"] = _verdict(rep)
    return rep


COLLAPSE_THRESHOLD = 0.10  # win_rate below this vs a subfamily = collapse flag
REGRESSION_TOLERANCE = 0.15  # candidate weighted score may trail Water by <= this


def _verdict(rep: dict) -> dict:
    pd = rep.get("per_deck") or {}
    cand = pd.get("league_dragapult_spread_v1")
    water = pd.get("league_water_core_reference")
    collapses = []
    if cand:
        for key, m in cand.get("per_archetype", {}).items():
            wr = m.get("win_rate")
            if wr is not None and wr < COLLAPSE_THRESHOLD:
                collapses.append({"subfamily": key, "win_rate": wr})
    regression = None
    if cand and water:
        cs, ws = cand.get("weighted_meta_score"), water.get("weighted_meta_score")
        if cs is not None and ws is not None:
            regression = round(ws - cs, 4)
    ok = (not collapses) and (regression is None
                              or regression <= REGRESSION_TOLERANCE)
    return {
        "candidate": "league_dragapult_spread_v1",
        "collapses_vs_subfamilies": collapses,
        "candidate_weighted_meta_score": (cand or {}).get("weighted_meta_score"),
        "water_weighted_meta_score": (water or {}).get("weighted_meta_score"),
        "candidate_minus_water": (None if regression is None else -regression),
        "water_minus_candidate": regression,
        "collapse_threshold": COLLAPSE_THRESHOLD,
        "regression_tolerance": REGRESSION_TOLERANCE,
        "sanity_passed": ok,
        "interpretation": (
            "DIRECTIONAL sanity only. 'sanity_passed' means the candidate did not "
            "collapse (<%.0f%% win rate) against any replay-derived subfamily and "
            "its weighted surrogate score does not trail the Water reference by "
            "more than %.0f points. It is NOT a promotion or upload signal."
            % (COLLAPSE_THRESHOLD * 100, REGRESSION_TOLERANCE * 100)),
    }


def _write_csv(rep: dict) -> None:
    opps = rep.get("opponent_subfamilies", [])
    pd = rep.get("per_deck") or {}
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["our_deck \\ subfamily (win_rate)"] + opps
                   + ["weighted_meta_score"])
        for did, d in pd.items():
            row = [did]
            for k in opps:
                wr = (d.get("per_archetype", {}).get(k) or {}).get("win_rate")
                row.append("—" if wr is None else wr)
            row.append(d.get("weighted_meta_score"))
            w.writerow(row)


def _md(rep: dict) -> str:
    L = ["# Pass 18 — replay-derived meta sanity check (Part L)", "",
         f"> {rep.get('disclaimer','')}", "",
         f"- is Kaggle leaderboard: **{rep.get('is_kaggle_leaderboard')}**  "
         f"upload_performed: **{rep.get('upload_performed')}**",
         f"- status: **{rep.get('status')}**"
         + (f" (reason: {rep.get('reason')})" if rep.get("reason") else ""),
         f"- pool: `{rep.get('pool')}`",
         f"- games per seat: {rep.get('games_per_seat')}  "
         f"(elapsed {rep.get('elapsed_s')}s, budget_exhausted "
         f"{rep.get('budget_exhausted')})",
         f"- opponent subfamilies: {', '.join(rep.get('opponent_subfamilies', [])) or 'none'}",
         ""]
    sv = rep.get("sanity") or {}
    if sv:
        L += ["## Sanity verdict",
              f"- candidate: **{sv.get('candidate')}**",
              f"- sanity passed: **{sv.get('sanity_passed')}**",
              f"- candidate weighted meta score: {sv.get('candidate_weighted_meta_score')}",
              f"- water weighted meta score: {sv.get('water_weighted_meta_score')}",
              f"- candidate − water: {sv.get('candidate_minus_water')}",
              f"- collapses vs subfamilies: "
              f"{sv.get('collapses_vs_subfamilies') or 'none'}",
              f"- _{sv.get('interpretation','')}_", ""]
    pd = rep.get("per_deck") or {}
    if pd:
        L += ["## Weighted meta score by deck",
              "| deck | role | weighted_meta_score |", "|---|---|---|"]
        for did, d in pd.items():
            L.append(f"| {did} | {d.get('role')} | {d.get('weighted_meta_score')} |")
        L += ["", "## Per-subfamily win rates",
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
    rep = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_md(rep), encoding="utf-8")
    _write_csv(rep)
    sv = rep.get("sanity") or {}
    print(f"meta sanity: status={rep.get('status')} "
          f"subfamilies={len(rep.get('opponent_subfamilies', []))} "
          f"sanity_passed={sv.get('sanity_passed')}")
    for p in (OUT_JSON, OUT_MD, OUT_CSV):
        print(f"  -> {p.relative_to(REPO)}")
    # sentinel for out-of-band polling when run as a workflow.
    (REPO / "data" / "experiments" / "pass18_meta_sanity.DONE").write_text(
        json.dumps({"status": rep.get("status"),
                    "elapsed_s": rep.get("elapsed_s"),
                    "sanity_passed": sv.get("sanity_passed")}, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
