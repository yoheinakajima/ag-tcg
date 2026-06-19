#!/usr/bin/env python3
"""Pass 27 (Part I) — multi-archetype internal portfolio league. LOCAL ONLY.

THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR portfolio decks
piloted by the SAME generic core pilot; opponents are our own decks, not real
Kaggle policies. These win rates measure deck/pilot COMPATIBILITY internally —
they expose which archetypes the one generic pilot can and cannot drive — and do
NOT predict Kaggle standings.

Participants = the Part-G league-eligible candidates (smoke-clean, validators
pass, NOT blocked_from_league) plus the historical Water v2 yardstick. Durant is
EXCLUDED by design (deckout/mill win condition the generic pilot cannot pilot).

Every unordered pair plays GAMES_PER_SEAT games with each deck as seat 0 and again
as seat 1 (seat swap cancels first-player bias), using a per-game SIGALRM
watchdog. Games run IN-PROCESS (kaggle_environments imported once per call).

RESUMABLE: background jobs do not survive across tool calls in this environment,
and a single call is time-limited, so each invocation plays only as many matchups
as fit in P27_PER_CALL_BUDGET_S, persisting crash-safe progress to
data/experiments/pass27_portfolio_league_progress.json. Re-invoke until it prints
"remaining=0", at which point it finalizes standings/matrix/rankings and writes
the pass27_portfolio_league.DONE sentinel. Each call is a fresh process, which
also bounds memory growth.

Outputs (data/experiments/): pass27_portfolio_league.{json,md},
pass27_portfolio_matrix.csv, pass27_portfolio_rankings.{json,md}, sentinel
pass27_portfolio_league.DONE. No upload, no submission, no GitHub push.
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
CAND = REPO / "data" / "submissions" / "candidates_pass27"
V2_REF = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"
VALIDATION = EXP / "pass27_candidate_validation.json"
PROGRESS = EXP / "pass27_portfolio_league_progress.json"

EXCLUDED = {
    "league_durant_deckout_carousel":
        "chaos-research-only: the generic core pilot cannot legally pilot a "
        "deckout/mill win condition (Part-G smoke is INVALID); blocked_from_league "
        "by design and excluded from every league.",
}

GAMES_PER_SEAT = int(os.environ.get("P27_GAMES_PER_SEAT", "3"))
GAME_TIMEOUT_S = int(os.environ.get("P27_GAME_TIMEOUT_S", "60"))
PER_CALL_BUDGET_S = int(os.environ.get("P27_PER_CALL_BUDGET_S", "85"))

DISCLAIMER = (
    "INTERNAL LEAGUE — NOT A KAGGLE LEADERBOARD. All participants are our own "
    "portfolio decks piloted by the same generic core pilot; opponents are not "
    "real Kaggle policies. Win rates measure internal deck/pilot compatibility "
    "only and do not predict Kaggle results. No candidate is uploaded or submitted."
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
        statuses = [s.get("status") for s in env.state]
        legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
        last = env.steps[-1]
        return {"ok": legal, "steps": len(env.steps),
                "rewards": [s.get("reward") for s in last],
                "statuses": statuses, "timeout": False, "invalid": not legal}
    except _Timeout:
        return {"ok": False, "timeout": True, "invalid": False, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "invalid": False, "error": repr(exc)}
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


def _play_matchup(a_id, a_agent, b_id, b_agent, per_seat) -> dict:
    games = []
    for (first, second, a_seat) in [(a_agent, b_agent, 0), (b_agent, a_agent, 1)]:
        for _ in range(per_seat):
            g = _run_game(first, second)
            g["a_seat"] = a_seat
            g["a_outcome"] = _outcome_for_seat(g, a_seat) if g.get("ok") else None
            games.append(g)
    a_wins = sum(1 for g in games if g.get("a_outcome") == "win")
    a_losses = sum(1 for g in games if g.get("a_outcome") == "loss")
    draws = sum(1 for g in games if g.get("a_outcome") == "draw")
    decisive = a_wins + a_losses
    seat0 = [g for g in games if g.get("a_seat") == 0]
    seat1 = [g for g in games if g.get("a_seat") == 1]
    ok_games = [g for g in games if g.get("ok")]
    return {
        "a": a_id, "b": b_id, "n_games": len(games),
        "a_wins": a_wins, "b_wins": a_losses, "draws": draws,
        "a_win_rate": round(a_wins / decisive, 4) if decisive else None,
        "a_wilson": list(_wilson(a_wins, decisive)),
        "a_wins_as_seat0": sum(1 for g in seat0 if g.get("a_outcome") == "win"),
        "a_wins_as_seat1": sum(1 for g in seat1 if g.get("a_outcome") == "win"),
        "crashes": sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                       and not g.get("invalid")),
        "invalids": sum(1 for g in games if g.get("invalid")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "avg_steps": round(sum(g.get("steps", 0) for g in ok_games) / len(ok_games), 1)
        if ok_games else None,
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
    }


def _resolve_participants() -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    parts: list[dict] = []
    league_eligible: list[str] = []
    meta: dict[str, dict] = {}
    if VALIDATION.exists():
        val = json.loads(VALIDATION.read_text(encoding="utf-8"))
        league_eligible = list(val.get("league_eligible", []))
        meta = {r["candidate_id"]: r for r in val.get("candidates", [])}
    else:
        notes.append("Part-G validation report missing; cannot confirm eligibility")
    for cid in league_eligible:
        if cid in EXCLUDED:
            continue
        m = meta.get(cid, {})
        parts.append({"id": cid, "role": m.get("archetype") or "portfolio_deck",
                      "family": m.get("family")})
    if V2_REF.exists() and _validate_tarball(V2_REF):
        parts.append({"id": "core_pilot_water_v2_runtime",
                      "role": "historical_reference",
                      "family": "water_kyogre_abomasnow"})
    else:
        notes.append("core_pilot_water_v2_runtime reference missing/invalid")
    for cid, why in EXCLUDED.items():
        notes.append(f"EXCLUDED {cid}: {why}")
    return parts, notes


def _tarball_for(pid: str) -> Path:
    return V2_REF if pid == "core_pilot_water_v2_runtime" else CAND / f"{pid}.tar.gz"


def _init_progress() -> dict:
    parts, notes = _resolve_participants()
    keys = [f"{a['id']}__vs__{b['id']}"
            for a, b in itertools.combinations(parts, 2)]
    return {
        "pass": "27", "part": "I", "local_only": True, "upload_performed": False,
        "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
        "games_per_seat": GAMES_PER_SEAT, "game_timeout_s": GAME_TIMEOUT_S,
        "excluded": EXCLUDED, "participants": parts, "notes": notes,
        "all_matchup_keys": keys, "matchups": {},
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _key_parts(key: str) -> tuple[str, str]:
    a, b = key.split("__vs__", 1)
    return a, b


def build_standings(prog: dict) -> dict:
    agg: dict[str, dict] = {}
    for p in prog["participants"]:
        agg[p["id"]] = {"id": p["id"], "role": p["role"], "family": p.get("family"),
                        "wins": 0, "losses": 0, "draws": 0, "games": 0}
    for m in prog["matchups"].values():
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
    return {"pass": "27", "disclaimer": prog["disclaimer"],
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "standings": rows}


def _write_matrix(prog: dict, path: Path) -> None:
    ids = [p["id"] for p in prog["participants"]]
    cell: dict = {}
    for m in prog["matchups"].values():
        wr = m["a_win_rate"]
        cell[(m["a"], m["b"])] = wr
        cell[(m["b"], m["a"])] = (round(1 - wr, 4) if wr is not None else None)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deck \\ opponent (a_win_rate)"] + ids)
        for ra in ids:
            w.writerow([ra] + ["—" if ra == rb else cell.get((ra, rb)) for rb in ids])


def _md_league(prog: dict, done: bool) -> str:
    L = ["# Pass 27 — multi-archetype portfolio league (Part I)", "",
         f"> {prog['disclaimer']}", "",
         f"- status: **{'complete' if done else 'in_progress'}**  "
         f"games/seat: {prog['games_per_seat']} (seat-swapped)",
         f"- is Kaggle leaderboard: **{prog['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{prog['upload_performed']}**",
         f"- participants: {', '.join(p['id'] for p in prog['participants'])}",
         f"- matchups complete: {len(prog['matchups'])}/{len(prog['all_matchup_keys'])}",
         "", "## Matchups (a vs b, seat-swapped)",
         "| a | b | n | a W-L-D | a win_rate | a 95% CI | a seat0/seat1 wins | invalid | timeout | avg steps |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for key in prog["all_matchup_keys"]:
        m = prog["matchups"].get(key)
        if not m:
            a, b = _key_parts(key)
            L.append(f"| {a} | {b} | — | _pending_ |  |  |  |  |  |  |")
            continue
        ci = f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}]"
        L.append(f"| {m['a']} | {m['b']} | {m['n_games']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | {ci} | "
                 f"{m['a_wins_as_seat0']}/{m['a_wins_as_seat1']} | {m['invalids']} | "
                 f"{m['timeouts']} | {m['avg_steps']} |")
    if prog.get("excluded"):
        L += ["", "## Excluded by design"]
        for cid, why in prog["excluded"].items():
            L.append(f"- **{cid}** — {why}")
    if prog.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in prog["notes"]]
    L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 27 — portfolio league standings (Part I)", "",
         f"> {rank['disclaimer']}", "",
         f"- is Kaggle leaderboard: **{rank['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{rank['upload_performed']}**", "",
         "| rank | deck | role | family | games | W-L-D | adj win_rate | 95% CI |",
         "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["standings"], 1):
        L.append(f"| {i} | {r['id']} | {r['role']} | {r.get('family')} | "
                 f"{r['games']} | {r['wins']}-{r['losses']}-{r['draws']} | "
                 f"{r['adj_win_rate']} | [{r['wilson'][0]}, {r['wilson'][1]}] |")
    L.append("")
    return "\n".join(L)


def _save_outputs(prog: dict, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")
    (EXP / "pass27_portfolio_league.json").write_text(
        json.dumps({**prog, "status": "complete" if done else "in_progress",
                    "matchups": list(prog["matchups"].values())},
                   indent=2, default=str), encoding="utf-8")
    (EXP / "pass27_portfolio_league.md").write_text(
        _md_league(prog, done), encoding="utf-8")
    if prog["matchups"]:
        rank = build_standings(prog)
        (EXP / "pass27_portfolio_rankings.json").write_text(
            json.dumps(rank, indent=2, default=str), encoding="utf-8")
        (EXP / "pass27_portfolio_rankings.md").write_text(
            _md_rank(rank), encoding="utf-8")
        _write_matrix(prog, EXP / "pass27_portfolio_matrix.csv")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    if PROGRESS.exists():
        prog = json.loads(PROGRESS.read_text(encoding="utf-8"))
    else:
        prog = _init_progress()
    sentinel = EXP / "pass27_portfolio_league.DONE"
    if sentinel.exists():
        sentinel.unlink()

    if len(prog["participants"]) < 2:
        prog["status"] = "blocked"
        prog["reason"] = "fewer_than_2_participants"
        _save_outputs(prog, done=True)
        sentinel.write_text(json.dumps({"status": "blocked"}, indent=2),
                            encoding="utf-8")
        print("league blocked: fewer than 2 participants")
        return 0

    pending = [k for k in prog["all_matchup_keys"] if k not in prog["matchups"]]
    if not pending:
        _save_outputs(prog, done=True)
        sentinel.write_text(json.dumps(
            {"status": "complete", "participants": [p["id"] for p in prog["participants"]],
             "matchups": len(prog["matchups"])}, indent=2), encoding="utf-8")
        print(f"league COMPLETE: participants={len(prog['participants'])} "
              f"matchups={len(prog['matchups'])} remaining=0")
        return 0

    needed = {p for k in pending for p in _key_parts(k)}
    start = time.time()
    played = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        agents: dict[str, str] = {}
        for pid in needed:
            tar = _tarball_for(pid)
            if tar.exists() and _validate_tarball(tar):
                agents[pid] = _extract_agent(tar, tmp / pid)
        per_game = 1.3
        per_matchup_games = 2 * prog["games_per_seat"]
        for key in pending:
            if time.time() - start + per_matchup_games * per_game > PER_CALL_BUDGET_S \
                    and played > 0:
                break
            a, b = _key_parts(key)
            if a not in agents or b not in agents:
                prog.setdefault("notes", []).append(
                    f"{key}: agent missing/invalid -> skipped")
                continue
            prog["matchups"][key] = _play_matchup(
                a, agents[a], b, agents[b], prog["games_per_seat"])
            played += 1
            _save_outputs(prog, done=False)  # crash-safe after each matchup

    remaining = len([k for k in prog["all_matchup_keys"] if k not in prog["matchups"]])
    done = remaining == 0
    _save_outputs(prog, done=done)
    if done:
        sentinel.write_text(json.dumps(
            {"status": "complete", "participants": [p["id"] for p in prog["participants"]],
             "matchups": len(prog["matchups"])}, indent=2), encoding="utf-8")
    print(f"league: played_this_call={played} done_total={len(prog['matchups'])}"
          f"/{len(prog['all_matchup_keys'])} remaining={remaining} "
          f"elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
