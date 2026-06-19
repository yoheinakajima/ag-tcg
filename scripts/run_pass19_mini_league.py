#!/usr/bin/env python3
"""Pass 19 (Part I) — controlled Dragapult parent/child mini-league.

LOCAL ONLY — THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR decks
piloted by the SAME generic core pilot. Win rates measure internal deck/pilot
compatibility only and do NOT predict Kaggle standings.

Participants (Durant EXCLUDED by design — chaos-research-only):
  * league_dragapult_spread          — parent (the H2H anchor)
  * league_dragapult_spread_v1       — child (Pass-18 aggregate winner, H2H loser)
  * league_dragapult_v1_search_only  — Pass-19 targeted revert (drops draw_support)
  * league_dragapult_v1_draw_only    — Pass-19 diagnostic (drops search_cards)
  * league_water_core_reference      — stable Water benchmark
  * core_pilot_water_v2_runtime      — optional historical Water anchor

Round-robin, seat-swapped, batched subprocess worker, global budget. Reuses the proven
Pass-18 league helpers verbatim (_matchup/_wilson/build_standings/_head_to_head/etc.).

Required reporting: direct parent H2H, aggregate league score, confidence intervals,
seat split, invalid/crash/timeout, and whether the child/refinement actually improves
the parent head-to-head.

Outputs (data/experiments/): pass19_dragapult_mini_league.{json,md},
pass19_dragapult_mini_matrix.csv, pass19_dragapult_mini_rankings.{json,md}, and a
sentinel pass19_mini_league.DONE. No upload, no submission, no GitHub push.
"""
from __future__ import annotations

import importlib.util as _ilu
import itertools
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
CAND17 = REPO / "data" / "submissions" / "candidates_pass17"
CAND18 = REPO / "data" / "submissions" / "candidates_pass18"
CAND19 = REPO / "data" / "submissions" / "candidates_pass19"
V2_REF = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"


def _load(name: str):
    spec = _ilu.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = _ilu.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


# Reuse the Pass-18 league machinery verbatim (single source of truth).
_L = _load("run_pass18_internal_league")
_matchup = _L._matchup
_wilson = _L._wilson
_extract_agent = _L._extract_agent
_validate_tarball = _L._validate_tarball
_write_matrix = _L._write_matrix
_head_to_head = _L._head_to_head

GAMES_PER_SEAT = int(os.environ.get("P19_GAMES_PER_SEAT", "10"))
FALLBACK_PER_SEAT = int(os.environ.get("P19_FALLBACK_PER_SEAT", "10"))
GAME_TIMEOUT_S = int(os.environ.get("P19_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P19_GLOBAL_BUDGET_S", "2400"))
# Keep the Pass-18 helpers' env knobs aligned so _matchup honours our budget.
os.environ.setdefault("P18_GAME_TIMEOUT_S", str(GAME_TIMEOUT_S))
_L.GAME_TIMEOUT_S = GAME_TIMEOUT_S

PARTICIPANT_SPECS = [
    ("league_dragapult_spread", "parent", CAND17),
    ("league_dragapult_spread_v1", "child", CAND18),
    ("league_dragapult_v1_search_only", "pass19_targeted_revert", CAND19),
    ("league_dragapult_v1_draw_only", "pass19_diagnostic", CAND19),
    ("league_water_core_reference", "water_benchmark", CAND17),
]
EXCLUDED = {
    "league_durant_deckout_carousel":
        "chaos-research-only: the generic pilot cannot legally pilot a mill deck; "
        "excluded from every league by design.",
}
DISCLAIMER = (
    "INTERNAL LEAGUE — NOT A KAGGLE LEADERBOARD. All participants are our own decks "
    "piloted by the same generic core pilot; opponents are not real Kaggle policies. "
    "Win rates measure internal deck/pilot compatibility only and do not predict "
    "Kaggle results. No candidate is uploaded or submitted."
)


def _resolve(tmp: Path):
    notes, parts = [], []
    for cid, role, cdir in PARTICIPANT_SPECS:
        tar = cdir / f"{cid}.tar.gz"
        if tar.exists() and _validate_tarball(tar):
            parts.append({"id": cid, "role": role,
                          "agent": _extract_agent(tar, tmp / cid)})
        else:
            notes.append(f"{cid} tarball missing/invalid -> excluded")
    if V2_REF.exists() and _validate_tarball(V2_REF):
        parts.append({"id": "core_pilot_water_v2_runtime", "role": "historical_anchor",
                      "agent": _extract_agent(V2_REF, tmp / "v2_ref")})
    else:
        notes.append("core_pilot_water_v2_runtime anchor missing/invalid")
    for cid, why in EXCLUDED.items():
        notes.append(f"EXCLUDED {cid}: {why}")
    return parts, notes


def run_league() -> dict:
    import tempfile
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep = {"pass": "19", "part": "I", "local_only": True, "upload_performed": False,
           "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
           "game_timeout_s": GAME_TIMEOUT_S, "global_budget_s": GLOBAL_BUDGET_S,
           "excluded": EXCLUDED, "notes": [], "matchups": []}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts, notes = _resolve(tmp)
        rep["notes"] += notes
        rep["participants"] = [{"id": p["id"], "role": p["role"]} for p in parts]
        if len(parts) < 2:
            rep["status"] = "blocked"
            rep["reason"] = "fewer_than_2_participants"
            rep["elapsed_s"] = round(time.time() - start, 1)
            return rep
        rep["status"] = "ran"
        per_seat = GAMES_PER_SEAT
        for a, b in itertools.combinations(parts, 2):
            if budget_left() < GLOBAL_BUDGET_S * 0.30 and per_seat > FALLBACK_PER_SEAT:
                per_seat = FALLBACK_PER_SEAT
                rep["notes"].append(f"budget tightening -> {per_seat} games/seat")
            rep["matchups"].append(
                _matchup(a["id"], a["agent"], b["id"], b["agent"], per_seat, budget_left))
        rep["effective_games_per_seat"] = per_seat
    rep["elapsed_s"] = round(time.time() - start, 1)
    rep["budget_exhausted"] = budget_left() <= 0
    return rep


def build_standings(rep: dict) -> dict:
    agg: dict[str, dict] = {}
    for p in rep.get("participants", []):
        agg[p["id"]] = {"id": p["id"], "role": p["role"], "wins": 0, "losses": 0,
                        "draws": 0, "games": 0}
    for m in rep.get("matchups", []):
        a, b = m["a"], m["b"]
        agg[a]["wins"] += m["a_wins"]; agg[a]["losses"] += m["b_wins"]
        agg[a]["draws"] += m["draws"]
        agg[b]["wins"] += m["b_wins"]; agg[b]["losses"] += m["a_wins"]
        agg[b]["draws"] += m["draws"]
    rows = []
    for r in agg.values():
        decisive = r["wins"] + r["losses"]
        r["games"] = r["wins"] + r["losses"] + r["draws"]
        r["adj_win_rate"] = round(r["wins"] / decisive, 4) if decisive else None
        lo, hi = _wilson(r["wins"], decisive)
        r["wilson"] = [lo, hi]
        rows.append(r)
    rows.sort(key=lambda r: (r["adj_win_rate"] is not None,
                             r["adj_win_rate"] or -1, r["wins"]), reverse=True)
    return {"pass": "19", "disclaimer": rep.get("disclaimer"),
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "standings": rows}


def _h2h_summary(rep: dict) -> dict:
    parent = "league_dragapult_spread"
    out = {}
    for other in ("league_dragapult_spread_v1", "league_dragapult_v1_search_only",
                  "league_dragapult_v1_draw_only"):
        h = _head_to_head(rep, other, parent)
        if h:
            out[other] = {
                "vs_parent_wins": h["a_wins"], "parent_wins": h["b_wins"],
                "draws": h["draws"], "win_rate_vs_parent": h["a_win_rate"],
                "improves_parent_h2h": (h["a_win_rate"] is not None
                                        and h["a_win_rate"] > 0.5)}
    return out


def _md(rep: dict, rank: dict, h2h: dict) -> str:
    if rep.get("status") != "ran":
        return (f"# Pass 19 — Dragapult mini-league (Part I)\n\n> {rep['disclaimer']}\n\n"
                f"- status: **{rep.get('status')}** (reason: {rep.get('reason')})\n")
    L = ["# Pass 19 — controlled Dragapult mini-league (Part I)", "",
         f"> {rep['disclaimer']}", "",
         f"- status: **{rep['status']}**  games/seat: {rep['games_per_seat']} "
         f"(effective {rep.get('effective_games_per_seat')})",
         f"- participants: {', '.join(p['id'] for p in rep['participants'])}",
         f"- elapsed: {rep['elapsed_s']}s  budget_exhausted: {rep.get('budget_exhausted')}",
         "", "## Standings (aggregate, adjusted win rate)",
         "| rank | deck | role | games | W-L-D | adj win_rate | 95% CI |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["standings"], 1):
        L.append(f"| {i} | {r['id']} | {r['role']} | {r['games']} | "
                 f"{r['wins']}-{r['losses']}-{r['draws']} | {r['adj_win_rate']} | "
                 f"[{r['wilson'][0]}, {r['wilson'][1]}] |")
    L += ["", "## Direct head-to-head vs parent (league_dragapult_spread)",
          "| candidate | W-L-D vs parent | win_rate vs parent | improves parent H2H? |",
          "|---|---|---|---|"]
    for cid, h in h2h.items():
        L.append(f"| {cid} | {h['vs_parent_wins']}-{h['parent_wins']}-{h['draws']} | "
                 f"{h['win_rate_vs_parent']} | "
                 f"{'YES' if h['improves_parent_h2h'] else 'no'} |")
    L += ["", "## Matchups (a vs b, seat-swapped)",
          "| a | b | n | a W-L-D | a win_rate | a 95% CI | a seat0/seat1 | invalid | timeout | skip | avg steps |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in rep["matchups"]:
        ci = f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}]"
        L.append(f"| {m['a']} | {m['b']} | {m['n_games']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | {ci} | "
                 f"{m['a_wins_as_seat0']}/{m['a_wins_as_seat1']} | {m['invalids']} | "
                 f"{m['timeouts']} | {m['skipped']} | {m['avg_steps']} |")
    if rep.get("excluded"):
        L += ["", "## Excluded by design"]
        for cid, why in rep["excluded"].items():
            L.append(f"- **{cid}** — {why}")
    if rep.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in rep["notes"]]
    L.append("")
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    sentinel = EXP / "pass19_mini_league.DONE"
    if sentinel.exists():
        sentinel.unlink()
    rep = run_league()
    rank = build_standings(rep)
    h2h = _h2h_summary(rep) if rep.get("status") == "ran" else {}
    rep["parent_h2h"] = h2h
    (EXP / "pass19_dragapult_mini_league.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass19_dragapult_mini_league.md").write_text(
        _md(rep, rank, h2h), encoding="utf-8")
    (EXP / "pass19_dragapult_mini_rankings.json").write_text(
        json.dumps(rank, indent=2, default=str), encoding="utf-8")
    rank_md = ["# Pass 19 — mini-league standings (Part I)", "",
               f"> {rank['disclaimer']}", "",
               f"- is Kaggle leaderboard: **{rank['is_kaggle_leaderboard']}**  "
               f"upload_performed: **{rank['upload_performed']}**", "",
               "| rank | deck | role | games | W-L-D | adj win_rate | 95% CI |",
               "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["standings"], 1):
        rank_md.append(f"| {i} | {r['id']} | {r['role']} | {r['games']} | "
                       f"{r['wins']}-{r['losses']}-{r['draws']} | {r['adj_win_rate']} | "
                       f"[{r['wilson'][0]}, {r['wilson'][1]}] |")
    (EXP / "pass19_dragapult_mini_rankings.md").write_text(
        "\n".join(rank_md) + "\n", encoding="utf-8")
    if rep.get("status") == "ran":
        _write_matrix(rep, EXP / "pass19_dragapult_mini_matrix.csv")
    sentinel.write_text(json.dumps(
        {"status": rep.get("status"), "elapsed_s": rep.get("elapsed_s"),
         "participants": [p["id"] for p in rep.get("participants", [])],
         "parent_h2h": h2h}, indent=2, default=str), encoding="utf-8")
    print(f"mini-league: status={rep.get('status')} "
          f"participants={len(rep.get('participants', []))} "
          f"matchups={len(rep.get('matchups', []))} elapsed={rep.get('elapsed_s')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
