#!/usr/bin/env python3
"""Pass 18 (Part K) -- internal deck league v2 (round-robin, seat-swapped).

LOCAL ONLY -- THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR
decks piloted by the SAME generic core pilot; opponents are our own decks, not
real Kaggle policies. These win rates measure deck/pilot COMPATIBILITY internally
and do NOT predict Kaggle standings.

Participant set (Durant is EXCLUDED by design -- chaos-research-only, cannot be
piloted legally by the generic pilot):

  * league_water_core_reference   -- stable Water benchmark (Pass-17, unchanged)
  * league_dragapult_spread_v1    -- NEW Pass-18 refinement (league-eligible)
  * league_dragapult_spread       -- parent, included for a direct v1-vs-parent
                                     head-to-head (promotion evidence for Part M)
  * league_raging_bolt_ogerpon    -- carried forward unchanged (diagnosis showed
                                     its 0-30 is deck/structural, not pilot fit)
  * core_pilot_water_v2_runtime   -- historical Water yardstick (Pass-14)

Every unordered pair plays GAMES_PER_SEAT games with each deck as seat 0 and again
as seat 1 (seat swap cancels first-player bias). Each game has a SIGALRM watchdog
and the whole run honours a global time budget; on budget exhaustion remaining
games are skipped and reported (never silently dropped).

Outputs (data/experiments/):
  pass18_internal_league.{json,md}, pass18_league_matrix.csv,
  pass18_league_rankings.{json,md}, and a sentinel pass18_league.DONE on success.

No upload, no submission, no GitHub push.
"""

from __future__ import annotations

import csv
import importlib.util
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKER = Path(__file__).resolve().parent / "_pass18_game_worker.py"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
CAND17 = REPO / "data" / "submissions" / "candidates_pass17"
CAND18 = REPO / "data" / "submissions" / "candidates_pass18"
V2_REF = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"
VALIDATION = EXP / "pass18_candidate_validation.json"

# (id, role, tarball path). Durant is intentionally absent (excluded by design).
PARTICIPANT_SPECS = [
    ("league_water_core_reference", "stable_benchmark", CAND17),
    ("league_dragapult_spread_v1", "pass18_candidate", CAND18),
    ("league_dragapult_spread", "parent_for_comparison", CAND17),
    ("league_raging_bolt_ogerpon", "carried_unchanged", CAND17),
]
EXCLUDED = {
    "league_durant_deckout_carousel":
        "chaos-research-only: generic pilot cannot legally pilot a mill deck "
        "(INVALID smoke); excluded from every league by design.",
}

GAMES_PER_SEAT = int(os.environ.get("P18_GAMES_PER_SEAT", "5"))
FALLBACK_PER_SEAT = int(os.environ.get("P18_FALLBACK_PER_SEAT", "3"))
GAME_TIMEOUT_S = int(os.environ.get("P18_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P18_GLOBAL_BUDGET_S", "1500"))

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


def _run_seat_batch(agent_first: str, agent_second: str, count: int) -> list[dict]:
    """Play ``count`` games (seat 0 = ``agent_first``) in one FRESH subprocess.

    Batching amortises the worker's import cost while keeping memory isolation
    and a real, enforceable timeout. The worker flushes partial results after
    each game, so on a parent-side timeout the games that did finish are still
    recovered; any missing games are reported as watchdog timeouts.
    """
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    timed_out = False
    try:
        subprocess.run(
            [sys.executable, str(WORKER), agent_first, agent_second,
             str(count), out_path],
            timeout=GAME_TIMEOUT_S * count + 30, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        timed_out = True
    except Exception:  # noqa: BLE001
        pass
    results: list[dict] = []
    try:
        with open(out_path, encoding="utf-8") as fh:
            results = json.load(fh)
    except Exception:  # noqa: BLE001 (no/partial file => worker crashed or was killed)
        results = []
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)
    while len(results) < count:
        results.append({"ok": False, "timeout": timed_out,
                        "error": "watchdog" if timed_out else "worker_no_result"})
    return results[:count]


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _matchup(a_id, a_agent, b_id, b_agent, per_seat, budget_left) -> dict:
    games = []
    for (first, second, a_seat) in [(a_agent, b_agent, 0), (b_agent, a_agent, 1)]:
        if budget_left() <= 0:
            for _ in range(per_seat):
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "a_seat": a_seat})
            continue
        batch = _run_seat_batch(first, second, per_seat)
        for g in batch:
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
        "a": a_id, "b": b_id, "n_games": len(games),
        "a_wins": a_wins, "b_wins": a_losses, "draws": draws,
        "a_win_rate": round(a_wins / decisive, 4) if decisive else None,
        "a_wilson": list(_wilson(a_wins, decisive)),
        "a_wins_as_seat0": sum(1 for g in seat0 if g.get("a_outcome") == "win"),
        "a_wins_as_seat1": sum(1 for g in seat1 if g.get("a_outcome") == "win"),
        "crashes": sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                       and not g.get("skipped") and not g.get("invalid")),
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
        eligible = list(json.loads(VALIDATION.read_text(encoding="utf-8"))
                        .get("league_eligible", []))
    else:
        notes.append("Part-J validation report missing; cannot confirm eligibility")
    for cid, role, cdir in PARTICIPANT_SPECS:
        tar = cdir / f"{cid}.tar.gz"
        # Pass-18 candidates must be confirmed league-eligible by Part J.
        if role == "pass18_candidate" and cid not in eligible:
            notes.append(f"{cid} not league-eligible per Part J -> excluded")
            continue
        if tar.exists() and _validate_tarball(tar):
            parts.append({"id": cid, "role": role,
                          "agent": _extract_agent(tar, tmp / cid)})
        else:
            notes.append(f"{cid} tarball missing/invalid -> excluded")
    if V2_REF.exists() and _validate_tarball(V2_REF):
        parts.append({"id": "core_pilot_water_v2_runtime", "role": "historical_reference",
                      "agent": _extract_agent(V2_REF, tmp / "v2_ref")})
    else:
        notes.append("core_pilot_water_v2_runtime reference missing/invalid")
    for cid, why in EXCLUDED.items():
        notes.append(f"EXCLUDED {cid}: {why}")
    return parts, notes


def run_league() -> dict:
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    rep = {"pass": "18", "part": "K", "local_only": True, "upload_performed": False,
           "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
           "game_timeout_s": GAME_TIMEOUT_S, "global_budget_s": GLOBAL_BUDGET_S,
           "excluded": EXCLUDED, "notes": [], "matchups": []}
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
            if budget_left() < GLOBAL_BUDGET_S * 0.35 and per_seat > FALLBACK_PER_SEAT:
                per_seat = FALLBACK_PER_SEAT
                rep["notes"].append(
                    f"budget tightening -> dropped to {per_seat} games/seat")
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
    return {"pass": "18", "disclaimer": rep.get("disclaimer"),
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "standings": rows}


def _head_to_head(rep: dict, a: str, b: str) -> dict | None:
    for m in rep.get("matchups", []):
        if {m["a"], m["b"]} == {a, b}:
            if m["a"] == a:
                return {"a": a, "b": b, "a_wins": m["a_wins"], "b_wins": m["b_wins"],
                        "draws": m["draws"], "a_win_rate": m["a_win_rate"]}
            wr = m["a_win_rate"]
            return {"a": a, "b": b, "a_wins": m["b_wins"], "b_wins": m["a_wins"],
                    "draws": m["draws"],
                    "a_win_rate": round(1 - wr, 4) if wr is not None else None}
    return None


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
            w.writerow([ra] + ["—" if ra == rb else cell.get((ra, rb)) for rb in ids])


def _md_league(rep: dict) -> str:
    if rep.get("status") != "ran":
        return (f"# Pass 18 internal league v2 (Part K)\n\n> {rep['disclaimer']}\n\n"
                f"- status: **{rep.get('status')}** (reason: {rep.get('reason')})\n")
    L = ["# Pass 18 — internal deck league v2 (Part K)", "",
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
    h2h = _head_to_head(rep, "league_dragapult_spread_v1", "league_dragapult_spread")
    if h2h:
        L += ["", "## v1 vs parent (head-to-head)",
              f"- league_dragapult_spread_v1 vs league_dragapult_spread: "
              f"{h2h['a_wins']}-{h2h['b_wins']}-{h2h['draws']} "
              f"(v1 win_rate {h2h['a_win_rate']})"]
    if rep.get("excluded"):
        L += ["", "## Excluded by design"]
        for cid, why in rep["excluded"].items():
            L.append(f"- **{cid}** — {why}")
    if rep.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in rep["notes"]]
    L.append("")
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = ["# Pass 18 — internal league standings (Part K)", "",
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
    sentinel = EXP / "pass18_league.DONE"
    if sentinel.exists():
        sentinel.unlink()
    rep = run_league()
    rank = build_standings(rep)
    (EXP / "pass18_internal_league.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass18_internal_league.md").write_text(_md_league(rep), encoding="utf-8")
    (EXP / "pass18_league_rankings.json").write_text(
        json.dumps(rank, indent=2, default=str), encoding="utf-8")
    (EXP / "pass18_league_rankings.md").write_text(_md_rank(rank), encoding="utf-8")
    if rep.get("status") == "ran":
        _write_matrix(rep, EXP / "pass18_league_matrix.csv")
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
