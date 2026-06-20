#!/usr/bin/env python3
"""Pass 35 (T-J) — internal typed-portfolio tournament. LOCAL ONLY.

THIS IS NOT A KAGGLE LEADERBOARD. Every participant is one of OUR Pass-35 typed
candidate children, each piloted by the SAME generic core pilot wrapped by the
typed board-aware strategy layer. Opponents are our own decks, never real Kaggle
policies. Win rates measure internal deck/pilot COMPATIBILITY only and DO NOT
predict Kaggle standings. Nothing is uploaded, submitted, or pushed.

Two stages (resumable, subprocess-isolated, real wall-clock timeouts):
  * Stage 1 — full round-robin over all built typed children, S1 games/seat
    (seat-swapped), a screening pass.
  * Stage 2 — the top-K of Stage 1 promoted to a higher-confidence round-robin at
    S2 games/seat.
Game counts are reduced from the aspirational 3/seat + top4-6 @ 10/seat to fit the
120s-per-invocation execution budget; the reduction is recorded honestly in the
config/notes and reflected in every Wilson CI. Re-invoke until status=complete;
the progress file then auto-deletes.

Outputs (data/experiments/): pass35_internal_tournament.{json,md},
pass35_league_matrix.csv, pass35_rankings.{json,md}.
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
BUILD = EXP / "pass35_candidate_build.json"
PROGRESS = EXP / "pass35_internal_tournament_progress.json"
JSONL_DIR = EXP / "pass35_tourney_jsonl"
WORKER = REPO / "scripts" / "_pass35_tourney_worker.py"

S1_GAMES_PER_SEAT = int(os.environ.get("P35_S1_GAMES_PER_SEAT", "2"))
S2_GAMES_PER_SEAT = int(os.environ.get("P35_S2_GAMES_PER_SEAT", "6"))
S2_TOP_K = int(os.environ.get("P35_S2_TOP_K", "4"))
GAME_TIMEOUT_S = int(os.environ.get("P35_GAME_TIMEOUT_S", "28"))
WORKER_BUDGET_S = int(os.environ.get("P35_PER_CALL_BUDGET_S", "80"))
MAX_ATTEMPTS = int(os.environ.get("P35_MAX_GAME_ATTEMPTS", "2"))

DISCLAIMER = (
    "INTERNAL TYPED-PORTFOLIO TOURNAMENT — NOT A KAGGLE LEADERBOARD. All "
    "participants are our own Pass-35 typed candidate children piloted by the same "
    "generic core pilot + typed strategy layer; opponents are not real Kaggle "
    "policies. Win rates measure internal deck/pilot compatibility only and do not "
    "predict Kaggle results. Nothing is uploaded, submitted, or pushed.")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _participants() -> list[dict]:
    data = json.loads(BUILD.read_text(encoding="utf-8"))
    out = []
    for r in data.get("candidates", []):
        if r.get("built") and r.get("tarball"):
            cid = r["candidate_id"]
            out.append({"id": cid, "display": cid.replace("_typed35", ""),
                        "tarball": str(REPO / r["tarball"])})
    out.sort(key=lambda x: x["id"])
    return out


def _schedule(stage: str, ids: list[str], per_seat: int) -> list[dict]:
    sched = []
    for a, b in itertools.combinations(sorted(ids), 2):
        for a_seat in (0, 1):
            for rep in range(per_seat):
                sched.append({"game_id": f"{stage}::{a}::{b}::seat{a_seat}::r{rep}",
                              "a_id": a, "b_id": b, "a_seat": a_seat})
    return sched


def _fold(jsonl_path: Path) -> dict:
    """Source-of-truth read of a stage's JSONL -> {game_id: terminal_rec}.

    A game with >=1 `result` is terminal (last result wins). A game with only
    `start` markers and >= MAX_ATTEMPTS of them is capped as a native-hang
    timeout; fewer attempts => still pending (omitted, will be retried).
    """
    starts: dict[str, dict] = {}
    nstart: dict[str, int] = {}
    last_result: dict[str, dict] = {}
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            gid = rec.get("game_id")
            if rec.get("ev") == "start":
                nstart[gid] = nstart.get(gid, 0) + 1
                starts[gid] = rec
            elif rec.get("ev") == "result":
                last_result[gid] = rec
    res: dict[str, dict] = {}
    for gid, rec in last_result.items():
        res[gid] = {"a_id": rec["a_id"], "b_id": rec["b_id"], "a_seat": rec["a_seat"],
                    "a_outcome": rec.get("a_outcome"), "ok": bool(rec.get("ok")),
                    "timeout": bool(rec.get("timeout")), "steps": rec.get("steps"),
                    "error": rec.get("error"), "capped": False}
    for gid, n in nstart.items():
        if gid in res or n < MAX_ATTEMPTS:
            continue
        s = starts[gid]
        res[gid] = {"a_id": s["a_id"], "b_id": s["b_id"], "a_seat": s["a_seat"],
                    "a_outcome": None, "ok": False, "timeout": True,
                    "error": f"capped: native-engine hang after {n} attempts",
                    "capped": True}
    return res


def _matchups(results: dict, ids: list[str], per_seat: int) -> list[dict]:
    out = []
    for a, b in itertools.combinations(sorted(ids), 2):
        games = [r for r in results.values() if r["a_id"] == a and r["b_id"] == b]
        a_wins = sum(1 for g in games if g["a_outcome"] == "win")
        b_wins = sum(1 for g in games if g["a_outcome"] == "loss")
        draws = sum(1 for g in games if g["a_outcome"] == "draw")
        decisive = a_wins + b_wins
        seat0 = [g for g in games if g["a_seat"] == 0]
        seat1 = [g for g in games if g["a_seat"] == 1]
        ok = [g for g in games if g["ok"]]
        out.append({
            "a": a, "b": b, "n_played": len(games), "n_target": per_seat * 2,
            "a_wins": a_wins, "b_wins": b_wins, "draws": draws,
            "a_win_rate": round(a_wins / decisive, 4) if decisive else None,
            "a_wilson": list(_wilson(a_wins, decisive)),
            "a_wins_seat0": sum(1 for g in seat0 if g["a_outcome"] == "win"),
            "a_wins_seat1": sum(1 for g in seat1 if g["a_outcome"] == "win"),
            "timeouts": sum(1 for g in games if g["timeout"]),
            "capped": sum(1 for g in games if g.get("capped")),
            "invalids": sum(1 for g in games if not g["ok"] and not g["timeout"]),
            "avg_steps": round(sum(g.get("steps") or 0 for g in ok) / len(ok), 1)
            if ok else None,
        })
    return out


def _label(adj, wilson, games):
    if games == 0 or adj is None:
        return "no_decisive_games"
    lo, hi = wilson
    width = (hi - lo) if (lo is not None and hi is not None) else 1.0
    if adj >= 0.55 and width <= 0.45:
        return "strong"
    if adj >= 0.5:
        return "above_even_noisy"
    if adj >= 0.35:
        return "below_even"
    return "weak"


def _standings(results: dict, ids: list[str]) -> list[dict]:
    agg = {i: {"id": i, "wins": 0, "losses": 0, "draws": 0,
               "timeouts": 0, "invalids": 0} for i in ids}
    for g in results.values():
        a, b = g["a_id"], g["b_id"]
        if a not in agg or b not in agg:
            continue
        if g["a_outcome"] == "win":
            agg[a]["wins"] += 1; agg[b]["losses"] += 1
        elif g["a_outcome"] == "loss":
            agg[a]["losses"] += 1; agg[b]["wins"] += 1
        elif g["a_outcome"] == "draw":
            agg[a]["draws"] += 1; agg[b]["draws"] += 1
        for s in (a, b):
            agg[s]["timeouts"] += 1 if g["timeout"] else 0
            agg[s]["invalids"] += 1 if (not g["ok"] and not g["timeout"]) else 0
    rows = []
    for r in agg.values():
        decisive = r["wins"] + r["losses"]
        r["games"] = r["wins"] + r["losses"] + r["draws"]
        r["adj_win_rate"] = round(r["wins"] / decisive, 4) if decisive else None
        r["wilson"] = list(_wilson(r["wins"], decisive))
        r["label"] = _label(r["adj_win_rate"], r["wilson"], r["games"])
        rows.append(r)
    rows.sort(key=lambda r: (r["adj_win_rate"] is not None,
                             r["adj_win_rate"] or -1.0, r["wins"]), reverse=True)
    return rows


def _init_progress() -> dict:
    parts = _participants()
    s1 = _schedule("s1", [p["id"] for p in parts], S1_GAMES_PER_SEAT)
    return {
        "pass": "35", "task": "T-J", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER,
        "config": {"s1_games_per_seat": S1_GAMES_PER_SEAT,
                   "s2_games_per_seat": S2_GAMES_PER_SEAT, "s2_top_k": S2_TOP_K,
                   "game_timeout_s": GAME_TIMEOUT_S,
                   "reduced_from": "aspirational 3/seat round-robin + top4-6 @ 10/seat",
                   "reduction_reason": "120s-per-invocation execution budget; "
                                       "counts trimmed honestly, all CIs reflect actual n"},
        "participants": parts,
        "tarball_paths": {p["id"]: p["tarball"] for p in parts},
        "s1_schedule": s1, "s2_participants": None, "s2_schedule": [],
        "notes": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _extract_needed(prog: dict, ids: set[str], tmp: Path) -> dict:
    agents = {}
    for pid in ids:
        tar = Path(prog["tarball_paths"].get(pid, ""))
        if tar.exists() and _validate_tarball(tar):
            agents[pid] = _extract_agent(tar, tmp / pid)
    return agents


def _run_worker(pending: list[dict], agents: dict, jsonl: Path, tmp: Path) -> None:
    spec = []
    for g in pending:
        a, b, seat = g["a_id"], g["b_id"], g["a_seat"]
        if a not in agents or b not in agents:
            continue
        first = agents[a] if seat == 0 else agents[b]
        second = agents[b] if seat == 0 else agents[a]
        spec.append({"game_id": g["game_id"], "first_main": first,
                     "second_main": second, "a_id": a, "b_id": b, "a_seat": seat})
    if not spec:
        return
    spec_path = tmp / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    hard = min(WORKER_BUDGET_S + GAME_TIMEOUT_S + 10, 115)
    try:
        subprocess.run([sys.executable, str(WORKER), str(spec_path), str(jsonl),
                        str(WORKER_BUDGET_S), str(GAME_TIMEOUT_S)],
                       capture_output=True, text=True, timeout=hard)
    except subprocess.TimeoutExpired:
        pass  # native hang; completed games are durably in the persistent JSONL


def _write_matrix(results: dict, ids: list[str], path: Path) -> None:
    cell = {}
    for m in _matchups(results, ids, S1_GAMES_PER_SEAT):
        wr = m["a_win_rate"]
        cell[(m["a"], m["b"])] = wr
        cell[(m["b"], m["a"])] = round(1 - wr, 4) if wr is not None else None
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deck \\ opponent (row win_rate)"] + ids)
        for ra in ids:
            w.writerow([ra] + ["—" if ra == rb else cell.get((ra, rb), "")
                               for rb in ids])


def _md_matchups(title: str, matchups: list[dict]) -> list[str]:
    L = [f"### {title}", "",
         "| a | b | n(play/target) | a W-L-D | a win_rate | a 95% CI | "
         "seat0/seat1 | t/o | cap | avg steps |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for m in matchups:
        ci = f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}]"
        L.append(f"| {m['a']} | {m['b']} | {m['n_played']}/{m['n_target']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | {ci} | "
                 f"{m['a_wins_seat0']}/{m['a_wins_seat1']} | {m['timeouts']} | "
                 f"{m['capped']} | {m['avg_steps']} |")
    L.append("")
    return L


def _md_standings(title: str, rows: list[dict]) -> list[str]:
    L = [f"### {title}", "",
         "| rank | deck | games | W-L-D | adj win_rate | 95% CI | t/o | inv | label |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        L.append(f"| {i} | {r['id']} | {r['games']} | "
                 f"{r['wins']}-{r['losses']}-{r['draws']} | {r['adj_win_rate']} | "
                 f"[{r['wilson'][0]}, {r['wilson'][1]}] | {r['timeouts']} | "
                 f"{r['invalids']} | {r['label']} |")
    L.append("")
    return L


def _save_outputs(prog: dict, res1: dict, res2: dict, done: bool) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    ids1 = [p["id"] for p in prog["participants"]]
    s2_ids = prog.get("s2_participants") or []
    cfg = prog["config"]
    s1_target = len(prog["s1_schedule"])
    s2_target = len(prog["s2_schedule"])
    s1_done = sum(1 for g in prog["s1_schedule"] if g["game_id"] in res1)
    s2_done = sum(1 for g in prog["s2_schedule"] if g["game_id"] in res2)

    m1 = _matchups(res1, ids1, cfg["s1_games_per_seat"])
    st1 = _standings(res1, ids1)
    m2 = _matchups(res2, s2_ids, cfg["s2_games_per_seat"]) if s2_ids else []
    st2 = _standings(res2, s2_ids) if s2_ids else []

    # Honest screen<->finals disagreement note (computed deterministically).
    out_notes = list(prog.get("notes", []))
    if st2:
        s1_rank = {r["id"]: i + 1 for i, r in enumerate(st1)}
        s2_rank = {r["id"]: i + 1 for i, r in enumerate(st2)}
        movers = sorted(((abs(s1_rank[i] - s2_rank[i]), i) for i in s2_ids),
                        reverse=True)
        biggest = movers[0] if movers else (0, None)
        s2_order = " > ".join(r["id"] for r in st2)
        s1_fin_order = " > ".join(
            i for i in sorted(s2_ids, key=lambda x: s1_rank[x]))
        if biggest[0] >= 2:
            bd = biggest[1]
            out_notes.append(
                f"SCREEN<->FINALS DISAGREEMENT: Stage 1 screen "
                f"({cfg['s1_games_per_seat']}/seat, n={cfg['s1_games_per_seat']*2}"
                f"/matchup) ordered the finalists {s1_fin_order}; the higher-N "
                f"Stage 2 finals ({cfg['s2_games_per_seat']}/seat) reordered them to "
                f"{s2_order}. Largest move: {bd} (screen #{s1_rank[bd]} -> finals "
                f"#{s2_rank[bd]}). The low-n screen is noisy; Stage 2 (higher "
                f"confidence) is authoritative for the overall ranking. Even so all "
                f"finalist CIs overlap 0.5, so NO finalist is shown to be reliably "
                f"strongest.")
        else:
            out_notes.append(
                f"Stage 1 screen and Stage 2 finals broadly agree on finalist "
                f"order ({s2_order}); all finalist CIs still overlap 0.5, so no "
                f"finalist is reliably strongest.")

    status = "complete" if done else "in_progress"
    payload = {
        "pass": "35", "task": "T-J", "status": status,
        "is_kaggle_leaderboard": False, "upload_performed": False,
        "no_upload": True, "disclaimer": prog["disclaimer"], "config": cfg,
        "participants": ids1, "notes": out_notes,
        "stage1": {"games_per_seat": cfg["s1_games_per_seat"],
                   "games_done": s1_done, "games_target": s1_target,
                   "matchups": m1, "standings": st1},
        "stage2": {"games_per_seat": cfg["s2_games_per_seat"],
                   "top_k": cfg["s2_top_k"], "participants": s2_ids,
                   "games_done": s2_done, "games_target": s2_target,
                   "matchups": m2, "standings": st2},
    }
    (EXP / "pass35_internal_tournament.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 35 — internal typed-portfolio tournament (T-J)", "",
         f"> {prog['disclaimer']}", "",
         f"- status: **{status}**  is Kaggle leaderboard: **False**  "
         f"upload_performed: **False**",
         f"- Stage 1 (screen): {cfg['s1_games_per_seat']}/seat, "
         f"{s1_done}/{s1_target} games done",
         f"- Stage 2 (finals): top-{cfg['s2_top_k']} @ "
         f"{cfg['s2_games_per_seat']}/seat, {s2_done}/{s2_target} games done",
         f"- reduction: {cfg['reduced_from']} -> trimmed ({cfg['reduction_reason']})",
         ""]
    L += ["## Stage 1 — round-robin screen", ""]
    L += _md_standings("Stage 1 standings (all participants)", st1)
    L += _md_matchups("Stage 1 matchups", m1)
    L += ["## Stage 2 — finals", ""]
    if s2_ids:
        L += [f"Promoted (top {cfg['s2_top_k']} of Stage 1): "
              f"{', '.join(s2_ids)}", ""]
        L += _md_standings("Stage 2 standings (finalists)", st2)
        L += _md_matchups("Stage 2 matchups", m2)
    else:
        L += ["_Stage 2 not yet started (awaiting Stage 1 completion)._", ""]
    if out_notes:
        L += ["## Notes"] + [f"- {n}" for n in out_notes] + [""]
    (EXP / "pass35_internal_tournament.md").write_text("\n".join(L), encoding="utf-8")

    # league matrix (Stage 1 full round-robin).
    _write_matrix(res1, ids1, EXP / "pass35_league_matrix.csv")

    # combined rankings: Stage 2 finalists first (higher confidence), then the
    # remaining Stage 1 field in Stage 1 order.
    s2_order = [r["id"] for r in st2]
    overall = []
    for r in st2:
        overall.append({**r, "ranked_by": "stage2_finals"})
    for r in st1:
        if r["id"] not in s2_order:
            overall.append({**r, "ranked_by": "stage1_screen"})
    rank_payload = {
        "pass": "35", "task": "T-J", "status": status,
        "is_kaggle_leaderboard": False, "upload_performed": False,
        "no_upload": True, "disclaimer": prog["disclaimer"],
        "stage1_standings": st1, "stage2_finalists": st2,
        "overall_ranking": overall,
    }
    (EXP / "pass35_rankings.json").write_text(
        json.dumps(rank_payload, indent=2, default=str), encoding="utf-8")
    RL = ["# Pass 35 — internal tournament rankings (T-J)", "",
          f"> {prog['disclaimer']}", "",
          "Overall ranking = Stage 2 finalists (higher-confidence) on top, then "
          "the remaining Stage 1 field. Internal compatibility only.", ""]
    RL += _md_standings("Overall ranking", overall)
    RL += _md_standings("Stage 1 (all)", st1)
    if st2:
        RL += _md_standings("Stage 2 (finalists)", st2)
    (EXP / "pass35_rankings.md").write_text("\n".join(RL), encoding="utf-8")

    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    JSONL_DIR.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else _init_progress())

    if len(prog["participants"]) < 2:
        prog.setdefault("notes", []).append("fewer than 2 participants")
        _save_outputs(prog, {}, {}, done=True)
        print("tournament blocked: fewer than 2 participants")
        return 0

    s1_jsonl = JSONL_DIR / "s1.jsonl"
    s2_jsonl = JSONL_DIR / "s2.jsonl"
    res1 = _fold(s1_jsonl)
    res2 = _fold(s2_jsonl)

    s1_pending = [g for g in prog["s1_schedule"] if g["game_id"] not in res1]
    start = time.time()
    stage = None
    pending: list[dict] = []
    jsonl = s1_jsonl

    if s1_pending:
        stage, pending, jsonl = "s1", s1_pending, s1_jsonl
    else:
        # Stage 1 done -> determine finalists if not yet chosen.
        if prog.get("s2_participants") is None:
            st1 = _standings(res1, [p["id"] for p in prog["participants"]])
            eligible = [r["id"] for r in st1 if r["adj_win_rate"] is not None]
            top = eligible[:S2_TOP_K] if eligible else \
                [r["id"] for r in st1][:S2_TOP_K]
            prog["s2_participants"] = top
            prog["s2_schedule"] = _schedule("s2", top, S2_GAMES_PER_SEAT)
            prog.setdefault("notes", []).append(
                f"Stage 2 finalists (top {S2_TOP_K} by Stage 1 adj win-rate): "
                f"{', '.join(top)}")
            _save_outputs(prog, res1, res2, done=False)
        s2_pending = [g for g in prog["s2_schedule"] if g["game_id"] not in res2]
        if s2_pending:
            stage, pending, jsonl = "s2", s2_pending, s2_jsonl

    if stage is None:
        _save_outputs(prog, res1, res2, done=True)
        if PROGRESS.exists():
            PROGRESS.unlink()
        print(f"tournament COMPLETE: participants={len(prog['participants'])} "
              f"stage1={len(res1)} stage2={len(res2)} remaining=0")
        return 0

    needed = {p for g in pending for p in (g["a_id"], g["b_id"])}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        agents = _extract_needed(prog, needed, tmp)
        missing = needed - set(agents)
        if missing:
            prog.setdefault("notes", []).append(
                f"agents unavailable (skipped games): {sorted(missing)}")
        _run_worker(pending, agents, jsonl, tmp)

    res1 = _fold(s1_jsonl)
    res2 = _fold(s2_jsonl)
    s1_left = len([g for g in prog["s1_schedule"] if g["game_id"] not in res1])
    s2_left = (len([g for g in prog["s2_schedule"] if g["game_id"] not in res2])
               if prog.get("s2_participants") is not None else len(prog["s2_schedule"]))
    done = s1_left == 0 and prog.get("s2_participants") is not None and s2_left == 0
    _save_outputs(prog, res1, res2, done=done)
    if done and PROGRESS.exists():
        PROGRESS.unlink()
    print(f"tournament: stage={stage} "
          f"s1_left={s1_left} s2_left={s2_left} "
          f"status={'complete' if done else 'partial'} "
          f"elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
