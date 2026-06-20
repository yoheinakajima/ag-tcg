#!/usr/bin/env python3
"""Pass 33 (Part G) — internal composition tournament. LOCAL ONLY.

THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR portfolio decks
(or a composition variant of one) piloted by the SAME generic core pilot;
opponents are our own decks, not real Kaggle policies. Win rates measure internal
deck/pilot COMPATIBILITY and the directional effect of Basic-density composition;
they do NOT predict Kaggle standings.

Participants = Part-F tournament-eligible candidates (validators pass, smoke
clean, NOT blocked_from_league). Durant is EXCLUDED by design.

Two phases:
  * STAGE 1 (default): full round-robin, P33_GAMES_PER_SEAT (default 3) games,
    each deck seat 0 then seat 1 (seat swap cancels first-player bias).
  * STAGE 2 (P33_STAGE=2): focused round-robin among the Stage-1 top 4 at
    P33_GAMES_PER_SEAT (default 10), written to *_stage2.{json,md}.

RESUMABLE: each call plays as many matchups as fit in P33_PER_CALL_BUDGET_S,
persisting crash-safe progress. Re-invoke until "remaining=0".

Outputs (data/experiments/): pass33_composition_tournament.{json,md},
pass33_composition_matrix.csv, pass33_composition_rankings.{json,md} (+ *_stage2.*).
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
CAND = REPO / "data" / "submissions" / "candidates_pass33"
SMOKE = EXP / "pass33_live_smoke.json"
PLAN = EXP / "pass33_stress_test_plan.json"
AUDIT = EXP / "pass33_deck_composition_audit.json"

STAGE = int(os.environ.get("P33_STAGE", "1"))
GAMES_PER_SEAT = int(os.environ.get("P33_GAMES_PER_SEAT", "10" if STAGE == 2 else "3"))
GAME_TIMEOUT_S = int(os.environ.get("P33_GAME_TIMEOUT_S", "60"))
PER_CALL_BUDGET_S = int(os.environ.get("P33_PER_CALL_BUDGET_S", "95"))
TOP_N = int(os.environ.get("P33_TOP_N", "4"))

SUFFIX = "_stage2" if STAGE == 2 else ""
PROGRESS = EXP / f"pass33_composition_tournament{SUFFIX}_progress.json"
RANKINGS_STAGE1 = EXP / "pass33_composition_rankings.json"

DISCLAIMER = (
    "INTERNAL COMPOSITION TOURNAMENT — NOT A KAGGLE LEADERBOARD. All participants "
    "are our own portfolio decks (or composition variants) piloted by the same "
    "generic core pilot; opponents are not real Kaggle policies. Win rates measure "
    "internal deck/pilot compatibility and the directional effect of Basic-density "
    "composition only, and do not predict Kaggle results. Nothing is uploaded.")

FAMILY = {
    "league_water_anti_disruption_pivot_v1": "water",
    "league_water_core_reference": "water",
    "core_pilot_water_v2_runtime": "water",
    "water_basic_density_v1": "water",
    "water_basic_density_v2": "water",
    "league_dragapult_spread": "dragapult",
    "league_dragapult_v1_search_only": "dragapult",
    "league_mega_venusaur_tank": "venusaur",
    "effect_loop_exit_guard_v1": "venusaur",
    "league_raging_bolt_ogerpon": "raging_bolt",
    "league_mega_charizard_x_burst": "charizard",
    "league_mega_gardevoir_psychic_ramp": "gardevoir",
}
REFERENCE_IDS = {"league_water_core_reference",
                 "league_water_anti_disruption_pivot_v1",
                 "core_pilot_water_v2_runtime"}
VARIANT_IDS = {"water_basic_density_v1", "water_basic_density_v2"}
DIAGNOSTIC_IDS = {"league_mega_charizard_x_burst", "league_mega_gardevoir_psychic_ramp"}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_outcome_for_seat = _MEV._outcome_for_seat


def _run_game(agent_a: str, agent_b: str) -> dict:
    _MEV.GAME_TIMEOUT_S = GAME_TIMEOUT_S
    return _MEV._run_game(agent_a, agent_b)


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _seat_first(metric: dict, seat) -> int | None:
    if not isinstance(metric, dict):
        return None
    return metric.get(seat, metric.get(str(seat)))


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

    a_first_attacks, a_attacks, a_first_evos = [], [], []
    for g in ok_games:
        seat = g.get("a_seat", 0)
        fa = _seat_first(g.get("first_attack_step") or {}, seat)
        if fa is not None:
            a_first_attacks.append(fa)
        ac = _seat_first(g.get("attack_count") or {}, seat)
        if ac is not None:
            a_attacks.append(ac)
        fe = _seat_first(g.get("first_evolution_step") or {}, seat)
        if fe is not None:
            a_first_evos.append(fe)

    def _avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
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
        "a_avg_first_attack_step": _avg(a_first_attacks),
        "a_avg_attack_count": _avg(a_attacks),
        "a_avg_first_evolution_step": _avg(a_first_evos),
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
    }


def _participants_stage1() -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    if not SMOKE.exists():
        return [], ["Part-F smoke report missing; cannot confirm eligibility"]
    smoke = json.loads(SMOKE.read_text(encoding="utf-8"))
    elig = smoke.get("tournament_eligible") or []
    blocked = [cid for cid, r in (smoke.get("results") or {}).items()
               if r.get("blocked_from_league")]
    for cid in blocked:
        notes.append(f"EXCLUDED {cid}: blocked_from_league (by design)")
    parts = [{"id": cid, "family": FAMILY.get(cid, "unknown")} for cid in elig]
    return parts, notes


def _participants_stage2() -> tuple[list[dict], list[str]]:
    if not RANKINGS_STAGE1.exists():
        return [], ["Stage-1 rankings missing; run Stage 1 first"]
    rk = json.loads(RANKINGS_STAGE1.read_text(encoding="utf-8"))
    top = rk.get("standings", [])[:TOP_N]
    parts = [{"id": r["id"], "family": r.get("family")} for r in top]
    note = (f"Stage 2 focused: Stage-1 top {TOP_N} "
            f"({', '.join(p['id'] for p in parts)}) at {GAMES_PER_SEAT} games/seat.")
    return parts, [note]


def _init_progress() -> dict:
    parts, notes = (_participants_stage2() if STAGE == 2 else _participants_stage1())
    keys = [f"{a['id']}__vs__{b['id']}"
            for a, b in itertools.combinations(parts, 2)]
    return {
        "pass": "33", "part": "G", "stage": STAGE, "local_only": True,
        "no_upload": True, "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
        "game_timeout_s": GAME_TIMEOUT_S, "participants": parts, "notes": notes,
        "all_matchup_keys": keys, "matchups": {},
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _key_parts(key: str) -> tuple[str, str]:
    a, b = key.split("__vs__", 1)
    return a, b


def _label(r: dict) -> str:
    cid, awr = r["id"], r["adj_win_rate"]
    lo, hi = r["wilson"]
    fam = r.get("family")
    if awr is None:
        return "legal_but_weak"
    width = (hi - lo) if (lo is not None and hi is not None) else 1.0
    if cid in VARIANT_IDS:
        return "density_variant_under_test"
    if cid in REFERENCE_IDS and awr >= 0.55:
        return "strong_reference"
    if fam == "raging_bolt" and awr <= 0.15:
        return "needs_special_pilot"
    if cid in DIAGNOSTIC_IDS:
        return "keep_as_benchmark"
    if awr >= 0.55 and width <= 0.35:
        return "candidate_for_confirmation"
    if awr >= 0.5:
        return "promising_but_noisy"
    return "legal_but_weak"


def build_standings(prog: dict) -> dict:
    agg: dict[str, dict] = {}
    for p in prog["participants"]:
        agg[p["id"]] = {"id": p["id"], "family": p.get("family"),
                        "wins": 0, "losses": 0, "draws": 0, "games": 0,
                        "invalids": 0, "timeouts": 0, "crashes": 0}
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
        lo, hi = _wilson(r["wins"], decisive)
        r["wilson"] = [lo, hi]
        r["compatibility_label"] = _label(r)
        rows.append(r)
    rows.sort(key=lambda r: (r["adj_win_rate"] is not None,
                             r["adj_win_rate"] or -1, r["wins"]), reverse=True)
    fam_agg: dict[str, dict] = {}
    for r in rows:
        f = r.get("family") or "unknown"
        fa = fam_agg.setdefault(f, {"family": f, "wins": 0, "losses": 0, "draws": 0})
        fa["wins"] += r["wins"]; fa["losses"] += r["losses"]; fa["draws"] += r["draws"]
    for fa in fam_agg.values():
        dec = fa["wins"] + fa["losses"]
        fa["adj_win_rate"] = round(fa["wins"] / dec, 4) if dec else None
    fam_rows = sorted(fam_agg.values(),
                      key=lambda r: (r["adj_win_rate"] is not None,
                                     r["adj_win_rate"] or -1), reverse=True)
    return {"pass": "33", "stage": STAGE, "disclaimer": prog["disclaimer"],
            "is_kaggle_leaderboard": False, "upload_performed": False,
            "no_upload": True, "standings": rows, "family_standings": fam_rows}


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


def _md_tournament(prog: dict, done: bool) -> str:
    L = [f"# Pass 33 — internal composition tournament (Part G, stage {prog['stage']})",
         "", f"> {prog['disclaimer']}", "",
         f"- status: **{'complete' if done else 'in_progress'}**  "
         f"games/seat: {prog['games_per_seat']} (seat-swapped)",
         f"- is Kaggle leaderboard: **{prog['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{prog['upload_performed']}**",
         f"- participants: {', '.join(p['id'] for p in prog['participants'])}",
         f"- matchups complete: {len(prog['matchups'])}/{len(prog['all_matchup_keys'])}",
         "", "## Matchups (a vs b, seat-swapped)",
         "| a | b | n | a W-L-D | a win_rate | a 95% CI | seat0/seat1 | inv | t/o | "
         "avg steps | a 1st atk | a atk# | a 1st evo |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in prog["all_matchup_keys"]:
        m = prog["matchups"].get(key)
        if not m:
            a, b = _key_parts(key)
            L.append(f"| {a} | {b} | — | _pending_ |  |  |  |  |  |  |  |  |  |")
            continue
        ci = f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}]"
        L.append(f"| {m['a']} | {m['b']} | {m['n_games']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | {ci} | "
                 f"{m['a_wins_as_seat0']}/{m['a_wins_as_seat1']} | {m['invalids']} | "
                 f"{m['timeouts']} | {m['avg_steps']} | "
                 f"{m['a_avg_first_attack_step']} | {m['a_avg_attack_count']} | "
                 f"{m['a_avg_first_evolution_step']} |")
    if prog.get("notes"):
        L += ["", "## Notes"] + [f"- {n}" for n in prog["notes"]]
    L += ["", "_Behavioral metrics are best-effort from cabt logs; deeper board "
          "metrics (no-bench/deckout) are not robustly decodable and are reported "
          "elsewhere as not_measured._", ""]
    return "\n".join(L)


def _md_rank(rank: dict) -> str:
    L = [f"# Pass 33 — composition tournament standings (Part G, stage {rank['stage']})",
         "", f"> {rank['disclaimer']}", "",
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
    L += ["", "## Family standings", "",
          "| family | W-L-D | adj win_rate |", "|---|---|---|"]
    for r in rank["family_standings"]:
        L.append(f"| {r['family']} | {r['wins']}-{r['losses']}-{r['draws']} | "
                 f"{r['adj_win_rate']} |")
    L.append("")
    return "\n".join(L)


def _save_outputs(prog: dict, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")
    (EXP / f"pass33_composition_tournament{SUFFIX}.json").write_text(
        json.dumps({**prog, "status": "complete" if done else "in_progress",
                    "matchups": list(prog["matchups"].values())},
                   indent=2, default=str), encoding="utf-8")
    (EXP / f"pass33_composition_tournament{SUFFIX}.md").write_text(
        _md_tournament(prog, done), encoding="utf-8")
    if prog["matchups"]:
        rank = build_standings(prog)
        (EXP / f"pass33_composition_rankings{SUFFIX}.json").write_text(
            json.dumps(rank, indent=2, default=str), encoding="utf-8")
        (EXP / f"pass33_composition_rankings{SUFFIX}.md").write_text(
            _md_rank(rank), encoding="utf-8")
        _write_matrix(prog, EXP / f"pass33_composition_matrix{SUFFIX}.csv")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else _init_progress())
    sentinel = EXP / f"pass33_composition_tournament{SUFFIX}.DONE"
    if sentinel.exists():
        sentinel.unlink()

    if len(prog["participants"]) < 2:
        prog["status"] = "blocked"; prog["reason"] = "fewer_than_2_participants"
        _save_outputs(prog, done=True)
        sentinel.write_text(json.dumps({"status": "blocked"}), encoding="utf-8")
        print("tournament blocked: fewer than 2 participants")
        return 0

    pending = [k for k in prog["all_matchup_keys"] if k not in prog["matchups"]]
    if not pending:
        _save_outputs(prog, done=True)
        sentinel.write_text(json.dumps(
            {"status": "complete", "participants": [p["id"] for p in prog["participants"]],
             "matchups": len(prog["matchups"])}), encoding="utf-8")
        print(f"tournament COMPLETE (stage {STAGE}): "
              f"participants={len(prog['participants'])} "
              f"matchups={len(prog['matchups'])} remaining=0")
        return 0

    needed = {p for k in pending for p in _key_parts(k)}
    start = time.time()
    played = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        agents: dict[str, str] = {}
        for pid in needed:
            tar = CAND / f"{pid}.tar.gz"
            if tar.exists() and _validate_tarball(tar):
                agents[pid] = _extract_agent(tar, tmp / pid)
        per_game = 1.4
        per_matchup_games = 2 * prog["games_per_seat"]
        for key in pending:
            if time.time() - start + per_matchup_games * per_game > PER_CALL_BUDGET_S \
                    and played > 0:
                break
            a, b = _key_parts(key)
            if a not in agents or b not in agents:
                prog.setdefault("notes", []).append(f"{key}: agent missing -> skipped")
                continue
            prog["matchups"][key] = _play_matchup(
                a, agents[a], b, agents[b], prog["games_per_seat"])
            played += 1
            _save_outputs(prog, done=False)

    remaining = len([k for k in prog["all_matchup_keys"] if k not in prog["matchups"]])
    done = remaining == 0
    _save_outputs(prog, done=done)
    if done:
        sentinel.write_text(json.dumps(
            {"status": "complete", "participants": [p["id"] for p in prog["participants"]],
             "matchups": len(prog["matchups"])}), encoding="utf-8")
    print(f"tournament stage{STAGE}: played_this_call={played} "
          f"done_total={len(prog['matchups'])}/{len(prog['all_matchup_keys'])} "
          f"remaining={remaining} elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
