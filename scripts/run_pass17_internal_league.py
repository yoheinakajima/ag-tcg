#!/usr/bin/env python3
"""Pass 17 (Part G) -- internal deck league (round-robin, seat-swapped).

LOCAL ONLY -- THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR
decks piloted by the SAME generic core pilot; opponents are our own decks, not
real Kaggle policies. These win rates measure deck/pilot COMPATIBILITY internally
and do NOT predict Kaggle standings.

Participants are the league-eligible candidates from Part F (validator-passing,
live-smoke-clean, not blocked) plus the historical Water reference
(core_pilot_water_v2_runtime) as a fixed yardstick. Durant is excluded (blocked).

Every unordered pair plays GAMES_PER_SEAT games with each deck as seat 0 and again
as seat 1 (seat swap cancels first-player bias). Each game has a SIGALRM watchdog
and the whole run honors a global time budget; on budget exhaustion remaining
games are skipped and reported (never silently dropped).

Outputs (data/experiments/):
  pass17_internal_league.{json,md}, pass17_league_matrix.csv,
  pass17_league_rankings.{json,md}, and a sentinel pass17_league.DONE on success.

No upload, no submission, no GitHub push.
"""

from __future__ import annotations

import csv
import importlib.util
import itertools
import json
import math
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass17"
VALIDATION = EXP / "pass17_candidate_validation.json"
V2_REF = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"

GAMES_PER_SEAT = int(os.environ.get("P17_GAMES_PER_SEAT", "5"))
FALLBACK_PER_SEAT = int(os.environ.get("P17_FALLBACK_PER_SEAT", "3"))
GAME_TIMEOUT_S = int(os.environ.get("P17_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P17_GLOBAL_BUDGET_S", "1500"))

DISCLAIMER = (
    "INTERNAL LEAGUE -- NOT A KAGGLE LEADERBOARD. All participants are our own "
    "decks piloted by the same generic core pilot; opponents are not real Kaggle "
    "policies. Win rates measure internal deck/pilot compatibility only and do "
    "not predict Kaggle results. No candidate is uploaded or submitted."
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")
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
        statuses = [s.get("status") for s in env.state]
        legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
        return {"ok": legal, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "timeout": False,
                "invalid": not legal}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _matchup(a_id: str, a_agent: str, b_id: str, b_agent: str,
             per_seat: int, budget_left) -> dict:
    games = []
    for (first, second, a_seat) in [(a_agent, b_agent, 0), (b_agent, a_agent, 1)]:
        for _ in range(per_seat):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted",
                              "a_seat": a_seat})
                continue
            g = _run_game(first, second)
            g["a_seat"] = a_seat
            g["a_outcome"] = _outcome_for_seat(g, a_seat)
            games.append(g)
    a_wins = sum(1 for g in games if g.get("a_outcome") == "win")
    a_losses = sum(1 for g in games if g.get("a_outcome") == "loss")
    draws = sum(1 for g in games if g.get("a_outcome") == "draw")
    decisive = a_wins + a_losses
    seat0 = [g for g in games if g.get("a_seat") == 0]
    seat1 = [g for g in games if g.get("a_seat") == 1]
    ok_games = [g for g in games if g.get("ok")]
    return {
        "a": a_id, "b": b_id,
        "n_games": len(games),
        "a_wins": a_wins, "b_wins": a_losses, "draws": draws,
        "a_win_rate": round(a_wins / decisive, 4) if decisive else None,
        "a_wilson": list(_wilson(a_wins, decisive)),
        "a_wins_as_seat0": sum(1 for g in seat0 if g.get("a_outcome") == "win"),
        "a_wins_as_seat1": sum(1 for g in seat1 if g.get("a_outcome") == "win"),
        "crashes": sum(1 for g in games if not g.get("ok")
                       and not g.get("timeout") and not g.get("skipped")
                       and not g.get("invalid")),
        "invalids": sum(1 for g in games if g.get("invalid")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
        "avg_steps": round(sum(g.get("steps", 0) for g in ok_games) / len(ok_games), 1)
        if ok_games else None,
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
    }


def _resolve_participants(tmp: Path) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    parts: list[dict] = []
    eligible: list[str] = []
    if VALIDATION.exists():
        v = json.loads(VALIDATION.read_text(encoding="utf-8"))
        eligible = list(v.get("league_eligible", []))
    else:
        notes.append("Part-F validation report missing; cannot confirm eligibility")
    for cid in eligible:
        tar = CAND_DIR / f"{cid}.tar.gz"
        if tar.exists() and _validate_tarball(tar):
            parts.append({"id": cid, "role": "league_candidate",
                          "agent": _extract_agent(tar, tmp / cid)})
        else:
            notes.append(f"{cid} eligible but tarball missing/invalid -> excluded")
    # historical reference yardstick
    if V2_REF.exists() and _validate_tarball(V2_REF):
        parts.append({"id": "core_pilot_water_v2_runtime", "role": "historical_reference",
                      "agent": _extract_agent(V2_REF, tmp / "v2_ref")})
    else:
        notes.append("core_pilot_water_v2_runtime reference missing/invalid")
    return parts, notes


def run_league() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep = {"pass": "17", "part": "G", "local_only": True, "disclaimer": DISCLAIMER,
           "games_per_seat": GAMES_PER_SEAT, "game_timeout_s": GAME_TIMEOUT_S,
           "global_budget_s": GLOBAL_BUDGET_S, "notes": [], "matchups": []}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts, notes = _resolve_participants(tmp)
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
            # downgrade to fallback games/seat if the budget is getting tight
            if budget_left() < GLOBAL_BUDGET_S * 0.35 and per_seat > FALLBACK_PER_SEAT:
                per_seat = FALLBACK_PER_SEAT
                rep["notes"].append(
                    f"budget tightening -> dropped to {per_seat} games/seat")
            m = _matchup(a["id"], a["agent"], b["id"], b["agent"],
                         per_seat, budget_left)
            rep["matchups"].append(m)
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
    return {"pass": "17", "disclaimer": rep.get("disclaimer"),
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "standings": rows}


def _write_matrix(rep: dict, path: Path) -> None:
    ids = [p["id"] for p in rep.get("participants", [])]
    cell = {(m["a"], m["b"]): m["a_win_rate"] for m in rep.get("matchups", [])}
    for m in rep.get("matchups", []):
        wr = m["a_win_rate"]
        cell[(m["b"], m["a"])] = (round(1 - wr, 4) if wr is not None else None)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deck \\ opponent (a_win_rate)"] + ids)
        for ra in ids:
            row = [ra]
            for rb in ids:
                row.append("—" if ra == rb else cell.get((ra, rb)))
            w.writerow(row)


def _md_league(rep: dict) -> str:
    if rep.get("status") != "ran":
        return (f"# Pass 17 internal league\n\n> {rep['disclaimer']}\n\n"
                f"- status: **{rep.get('status')}** (reason: {rep.get('reason')})\n")
    L = ["# Pass 17 — internal deck league (Part G)", "",
         f"> {rep['disclaimer']}", "",
         f"- status: **{rep['status']}**  games/seat: {rep['games_per_seat']} "
         f"(effective {rep.get('effective_games_per_seat')})",
         f"- participants: {', '.join(p['id'] for p in rep['participants'])}",
         f"- elapsed: {rep['elapsed_s']}s  budget_exhausted: {rep.get('budget_exhausted')}",
         "", "## Matchups (a vs b, seat-swapped)",
         "| a | b | n | a W-L-D | a win_rate | a 95% CI | a seat0/seat1 wins | invalid | timeout | skip | avg steps |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in rep["matchups"]:
        ci = f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}]"
        L.append(f"| {m['a']} | {m['b']} | {m['n_games']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | {ci} | "
                 f"{m['a_wins_as_seat0']}/{m['a_wins_as_seat1']} | {m['invalids']} | "
                 f"{m['timeouts']} | {m['skipped']} | {m['avg_steps']} |")
    if rep.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in rep["notes"]]
    L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 17 — internal league standings (Part G)", "",
         f"> {rank['disclaimer']}", "",
         f"- is Kaggle leaderboard: **{rank['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{rank['upload_performed']}**", "",
         "| rank | deck | role | games | W-L-D | adj win_rate | 95% CI |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["standings"], 1):
        L.append(f"| {i} | {r['id']} | {r['role']} | {r['games']} | "
                 f"{r['wins']}-{r['losses']}-{r['draws']} | {r['adj_win_rate']} | "
                 f"[{r['wilson'][0]}, {r['wilson'][1]}] |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    sentinel = EXP / "pass17_league.DONE"
    if sentinel.exists():
        sentinel.unlink()
    rep = run_league()
    rank = build_standings(rep)
    (EXP / "pass17_internal_league.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass17_internal_league.md").write_text(_md_league(rep), encoding="utf-8")
    (EXP / "pass17_league_rankings.json").write_text(
        json.dumps(rank, indent=2, default=str), encoding="utf-8")
    (EXP / "pass17_league_rankings.md").write_text(_md_rank(rank), encoding="utf-8")
    if rep.get("status") == "ran":
        _write_matrix(rep, EXP / "pass17_league_matrix.csv")
    sentinel.write_text(json.dumps(
        {"status": rep.get("status"), "elapsed_s": rep.get("elapsed_s"),
         "participants": [p["id"] for p in rep.get("participants", [])]},
        indent=2), encoding="utf-8")
    print(f"league: status={rep.get('status')} "
          f"participants={len(rep.get('participants', []))} "
          f"matchups={len(rep.get('matchups', []))} elapsed={rep.get('elapsed_s')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
