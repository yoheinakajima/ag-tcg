#!/usr/bin/env python3
"""Pass 34 (Part H) — internal new-deck tournament. LOCAL ONLY.

THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR decks piloted by
the SAME generic core pilot; opponents are our own decks, not real Kaggle
policies. Win rates measure internal deck/pilot COMPATIBILITY only and do NOT
predict Kaggle standings.

Participants:
  * NEW league-eligible normal-lane decks (Part E, not blocked_from_league):
    mono_lightning_miraidon_easy, diamond_toolbox_diancie.
  * BENCHMARKS: current Water best, water_basic_density_v1, Dragapult search-only,
    Mega Venusaur, Mega Charizard X, Mega Gardevoir.
Special-lane decks (Toxic, Durant) are EXCLUDED here by design (blocked_from_league;
the generic pilot mis-pilots them — see Part I diagnosis).

RESUMABLE: each call plays as many matchups as fit in P34_PER_CALL_BUDGET_S,
persisting crash-safe progress. Re-invoke until "remaining=0".

Outputs (data/experiments/): pass34_new_deck_tournament.{json,md},
pass34_new_deck_matrix.csv, pass34_new_deck_rankings.{json,md}.
No upload, no submission, no GitHub push.
"""
from __future__ import annotations

import csv
import importlib.util
import itertools
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
MANIFEST = EXP / "pass34_candidate_manifest.json"

GAMES_PER_SEAT = int(os.environ.get("P34_GAMES_PER_SEAT", "3"))
GAME_TIMEOUT_S = int(os.environ.get("P34_GAME_TIMEOUT_S", "60"))
PER_CALL_BUDGET_S = int(os.environ.get("P34_PER_CALL_BUDGET_S", "95"))

PROGRESS = EXP / "pass34_new_deck_tournament_progress.json"

DISCLAIMER = (
    "INTERNAL NEW-DECK TOURNAMENT — NOT A KAGGLE LEADERBOARD. All participants are "
    "our own decks piloted by the same generic core pilot; opponents are not real "
    "Kaggle policies. Win rates measure internal deck/pilot compatibility only and "
    "do not predict Kaggle results. Nothing is uploaded.")

# Benchmark tarballs (resolved paths) + family labels.
BENCHMARKS = {
    "league_water_anti_disruption_pivot_v1":
        ("data/submissions/candidates_pass22/league_water_anti_disruption_pivot_v1.tar.gz",
         "water"),
    "water_basic_density_v1":
        ("data/submissions/candidates_pass33/water_basic_density_v1.tar.gz", "water"),
    "league_dragapult_v1_search_only":
        ("data/submissions/candidates_pass19/league_dragapult_v1_search_only.tar.gz",
         "dragapult"),
    "league_mega_venusaur_tank":
        ("data/submissions/candidates_pass27/league_mega_venusaur_tank.tar.gz",
         "venusaur"),
    "league_mega_charizard_x_burst":
        ("data/submissions/candidates_pass27/league_mega_charizard_x_burst.tar.gz",
         "charizard"),
    "league_mega_gardevoir_psychic_ramp":
        ("data/submissions/candidates_pass27/league_mega_gardevoir_psychic_ramp.tar.gz",
         "gardevoir"),
}
NEW_FAMILY = {
    "mono_lightning_miraidon_easy": "miraidon_new",
    "diamond_toolbox_diancie": "diamond_new",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_outcome_for_seat = _MEV._outcome_for_seat


import subprocess

_WORKER = REPO / "scripts" / "_pass34_game_worker.py"


def _run_game(agent_a: str, agent_b: str) -> dict:
    """Run ONE game in an isolated subprocess with a HARD wall-clock timeout.

    The in-process SIGALRM watchdog cannot interrupt a hang inside native
    open_spiel C code, so we run each game in a child process and kill it on a
    hard timeout, recording the game as a timeout. This keeps the harness honest
    and non-hanging even when a specific deck pairing wedges the native engine.
    """
    hard = GAME_TIMEOUT_S + 15
    try:
        p = subprocess.run(
            [sys.executable, str(_WORKER), agent_a, agent_b, str(GAME_TIMEOUT_S)],
            capture_output=True, text=True, timeout=hard)
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True,
                "error": "watchdog: hard wall-clock timeout (native engine hang)"}
    out = (p.stdout or "").strip()
    if p.returncode != 0 or not out:
        return {"ok": False, "timeout": False,
                "error": f"worker rc={p.returncode}: {(p.stderr or '')[-200:]}"}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": f"worker parse: {exc!r}"}


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _matchup_schedule(per_seat):
    """Deterministic ordered list of (seat-role, a_seat) for resumable play."""
    sched = []
    for a_seat in (0, 1):
        for _ in range(per_seat):
            sched.append(a_seat)
    return sched


def _play_matchup(a_id, a_agent, b_id, b_agent, per_seat,
                  existing_games=None, deadline=None, checkpoint=None) -> dict:
    """Play (or resume) a matchup with per-game checkpointing.

    Returns a dict with key "complete": True when all games are played (full
    aggregate present), or False when the per-call deadline was hit mid-matchup
    (partial games saved via checkpoint, aggregate omitted).
    """
    games = list(existing_games or [])
    sched = _matchup_schedule(per_seat)
    for idx in range(len(games), len(sched)):
        if deadline is not None and time.time() >= deadline:
            return {"complete": False, "games": games}
        a_seat = sched[idx]
        first, second = (a_agent, b_agent) if a_seat == 0 else (b_agent, a_agent)
        g = _run_game(first, second)
        g["a_seat"] = a_seat
        g["a_outcome"] = _outcome_for_seat(g, a_seat) if g.get("ok") else None
        games.append(g)
        if checkpoint is not None:
            checkpoint(games)
    a_wins = sum(1 for g in games if g.get("a_outcome") == "win")
    a_losses = sum(1 for g in games if g.get("a_outcome") == "loss")
    draws = sum(1 for g in games if g.get("a_outcome") == "draw")
    decisive = a_wins + a_losses
    seat0 = [g for g in games if g.get("a_seat") == 0]
    seat1 = [g for g in games if g.get("a_seat") == 1]
    ok_games = [g for g in games if g.get("ok")]
    return {
        "complete": True,
        "a": a_id, "b": b_id, "n_games": len(games),
        "a_wins": a_wins, "b_wins": a_losses, "draws": draws,
        "a_win_rate": round(a_wins / decisive, 4) if decisive else None,
        "a_wilson": list(_wilson(a_wins, decisive)),
        "a_wins_as_seat0": sum(1 for g in seat0 if g.get("a_outcome") == "win"),
        "a_wins_as_seat1": sum(1 for g in seat1 if g.get("a_outcome") == "win"),
        "crashes": sum(1 for g in games if not g.get("ok") and not g.get("timeout")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "invalids": sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                        and not g.get("error", "").startswith("watchdog")),
        "avg_steps": round(sum(g.get("steps", 0) for g in ok_games) / len(ok_games), 1)
        if ok_games else None,
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
    }


def _resolve_paths() -> dict:
    """id -> (abs_path, family). NEW league-eligible decks + benchmarks."""
    out = {}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for r in manifest["results"]:
        if r.get("built") and not r.get("blocked_from_league"):
            cid = r["candidate_id"]
            out[cid] = (REPO / r["tarball"], NEW_FAMILY.get(cid, "new"))
    for cid, (rel, fam) in BENCHMARKS.items():
        p = REPO / rel
        if p.exists():
            out[cid] = (p, fam)
    return out


def _init_progress() -> dict:
    paths = _resolve_paths()
    parts = [{"id": cid, "family": fam} for cid, (_, fam) in sorted(paths.items())]
    keys = [f"{a['id']}__vs__{b['id']}"
            for a, b in itertools.combinations(parts, 2)]
    notes = ["Special-lane decks (toxic_trap_poison_lock, deckout_carousel_durant_v2) "
             "EXCLUDED: blocked_from_league; generic pilot mis-pilots them "
             "(see Part I diagnosis)."]
    missing = [cid for cid in (set(NEW_FAMILY) | set(BENCHMARKS))
               if cid not in paths]
    for cid in missing:
        notes.append(f"participant unavailable: {cid}")
    return {
        "pass": "34", "part": "H", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
        "game_timeout_s": GAME_TIMEOUT_S, "participants": parts, "notes": notes,
        "all_matchup_keys": keys, "matchups": {},
        "tarball_paths": {cid: str(p) for cid, (p, _) in paths.items()},
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _key_parts(key: str):
    a, b = key.split("__vs__", 1)
    return a, b


def _label(r: dict) -> str:
    awr = r["adj_win_rate"]
    lo, hi = r["wilson"]
    if r["games"] == 0 or awr is None:
        return "no_decisive_games"
    width = (hi - lo) if (lo is not None and hi is not None) else 1.0
    is_new = r.get("family", "").endswith("_new")
    if awr >= 0.55 and width <= 0.4:
        return "strong_new_candidate" if is_new else "strong_benchmark"
    if awr >= 0.5:
        return "promising_but_noisy"
    if awr >= 0.3:
        return "below_benchmark"
    return "legal_but_weak"


def build_standings(prog: dict) -> dict:
    agg = {p["id"]: {"id": p["id"], "family": p.get("family"), "wins": 0,
                     "losses": 0, "draws": 0, "games": 0, "invalids": 0,
                     "timeouts": 0, "crashes": 0} for p in prog["participants"]}
    for m in prog["matchups"].values():
        a, b = m["a"], m["b"]
        agg[a]["wins"] += m["a_wins"]; agg[a]["losses"] += m["b_wins"]
        agg[a]["draws"] += m["draws"]
        agg[b]["wins"] += m["b_wins"]; agg[b]["losses"] += m["a_wins"]
        agg[b]["draws"] += m["draws"]
        for s in (a, b):
            agg[s]["invalids"] += m.get("invalids", 0)
            agg[s]["timeouts"] += m.get("timeouts", 0)
            agg[s]["crashes"] += m.get("crashes", 0)
    rows = []
    for r in agg.values():
        decisive = r["wins"] + r["losses"]
        r["games"] = r["wins"] + r["losses"] + r["draws"]
        r["adj_win_rate"] = round(r["wins"] / decisive, 4) if decisive else None
        r["wilson"] = list(_wilson(r["wins"], decisive))
        r["compatibility_label"] = _label(r)
        rows.append(r)
    rows.sort(key=lambda r: (r["adj_win_rate"] is not None,
                             r["adj_win_rate"] or -1, r["wins"]), reverse=True)
    return {"pass": "34", "disclaimer": prog["disclaimer"],
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "no_upload": True, "standings": rows}


def _write_matrix(prog: dict, path: Path) -> None:
    ids = [p["id"] for p in prog["participants"]]
    cell = {}
    for m in prog["matchups"].values():
        wr = m["a_win_rate"]
        cell[(m["a"], m["b"])] = wr
        cell[(m["b"], m["a"])] = round(1 - wr, 4) if wr is not None else None
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deck \\ opponent (a_win_rate)"] + ids)
        for ra in ids:
            w.writerow([ra] + ["—" if ra == rb else cell.get((ra, rb)) for rb in ids])


def _md_tournament(prog: dict, done: bool) -> str:
    L = ["# Pass 34 — internal new-deck tournament (Part H)", "",
         f"> {prog['disclaimer']}", "",
         f"- status: **{'complete' if done else 'in_progress'}**  "
         f"games/seat: {prog['games_per_seat']} (seat-swapped)",
         f"- is Kaggle leaderboard: **{prog['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{prog['upload_performed']}**",
         f"- participants: {', '.join(p['id'] for p in prog['participants'])}",
         f"- matchups complete: {len(prog['matchups'])}/{len(prog['all_matchup_keys'])}",
         "", "## Matchups (a vs b, seat-swapped)",
         "| a | b | n | a W-L-D | a win_rate | a 95% CI | seat0/seat1 | inv | t/o | "
         "avg steps |", "|---|---|---|---|---|---|---|---|---|---|"]
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
    if prog.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in prog["notes"]]
    L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 34 — new-deck tournament standings (Part H)", "",
         f"> {rank['disclaimer']}", "",
         f"- is Kaggle leaderboard: **{rank['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{rank['upload_performed']}**", "",
         "| rank | deck | family | games | W-L-D | adj win_rate | 95% CI | "
         "inv/to/crash | label |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["standings"], 1):
        L.append(f"| {i} | {r['id']} | {r.get('family')} | {r['games']} | "
                 f"{r['wins']}-{r['losses']}-{r['draws']} | {r['adj_win_rate']} | "
                 f"[{r['wilson'][0]}, {r['wilson'][1]}] | "
                 f"{r['invalids']}/{r['timeouts']}/{r['crashes']} | "
                 f"{r['compatibility_label']} |")
    L.append("")
    return "\n".join(L)


def _save_outputs(prog: dict, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")
    (EXP / "pass34_new_deck_tournament.json").write_text(
        json.dumps({**prog, "status": "complete" if done else "in_progress",
                    "matchups": list(prog["matchups"].values())},
                   indent=2, default=str), encoding="utf-8")
    (EXP / "pass34_new_deck_tournament.md").write_text(
        _md_tournament(prog, done), encoding="utf-8")
    if prog["matchups"]:
        rank = build_standings(prog)
        (EXP / "pass34_new_deck_rankings.json").write_text(
            json.dumps(rank, indent=2, default=str), encoding="utf-8")
        (EXP / "pass34_new_deck_rankings.md").write_text(
            _md_rank(rank), encoding="utf-8")
        _write_matrix(prog, EXP / "pass34_new_deck_matrix.csv")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else _init_progress())
    sentinel = EXP / "pass34_new_deck_tournament.DONE"
    if sentinel.exists():
        sentinel.unlink()

    if len(prog["participants"]) < 2:
        prog["status"] = "blocked"; prog["reason"] = "fewer_than_2_participants"
        _save_outputs(prog, done=True)
        print("tournament blocked: fewer than 2 participants")
        return 0

    pending = [k for k in prog["all_matchup_keys"] if k not in prog["matchups"]]
    if not pending:
        _save_outputs(prog, done=True)
        sentinel.write_text(json.dumps(
            {"status": "complete", "matchups": len(prog["matchups"])}),
            encoding="utf-8")
        print(f"tournament COMPLETE: participants={len(prog['participants'])} "
              f"matchups={len(prog['matchups'])} remaining=0")
        return 0

    needed = {p for k in pending for p in _key_parts(k)}
    start = time.time()
    played = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        agents = {}
        for pid in needed:
            tar = Path(prog["tarball_paths"].get(pid, ""))
            if tar.exists() and _validate_tarball(tar):
                agents[pid] = _extract_agent(tar, tmp / pid)
        deadline = start + PER_CALL_BUDGET_S
        partial = prog.setdefault("_partial", {})
        for key in pending:
            if time.time() >= deadline:
                break
            a, b = _key_parts(key)
            if a not in agents or b not in agents:
                prog.setdefault("notes", []).append(f"{key}: agent missing -> skipped")
                prog["matchups"][key] = {"complete": True, "a": a, "b": b, "n_games": 0,
                                         "a_wins": 0, "b_wins": 0, "draws": 0,
                                         "a_win_rate": None, "a_wilson": [None, None],
                                         "a_wins_as_seat0": 0, "a_wins_as_seat1": 0,
                                         "crashes": 0, "timeouts": 0, "invalids": 0,
                                         "avg_steps": None, "errors": ["agent missing"]}
                partial.pop(key, None)
                continue

            def _checkpoint(games, _k=key):
                prog["_partial"][_k] = games
                PROGRESS.write_text(
                    json.dumps(prog, indent=2, default=str), encoding="utf-8")

            res = _play_matchup(
                a, agents[a], b, agents[b], prog["games_per_seat"],
                existing_games=partial.get(key), deadline=deadline,
                checkpoint=_checkpoint)
            if res.get("complete"):
                res.pop("complete", None)
                prog["matchups"][key] = res
                partial.pop(key, None)
                played += 1
                _save_outputs(prog, done=False)
            else:
                # deadline hit mid-matchup; partial already checkpointed
                break

    remaining = len([k for k in prog["all_matchup_keys"] if k not in prog["matchups"]])
    done = remaining == 0
    _save_outputs(prog, done=done)
    if done:
        sentinel.write_text(json.dumps(
            {"status": "complete", "matchups": len(prog["matchups"])}),
            encoding="utf-8")
    print(f"tournament: played_this_call={played} "
          f"done_total={len(prog['matchups'])}/{len(prog['all_matchup_keys'])} "
          f"remaining={remaining} elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
