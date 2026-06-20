"""Projections folded from the tournament event log.

Everything here is derived purely from ``GameFinished`` (and pool) events, so the
projections are fully rebuildable from the ledger alone. Internal diagnostics
only — NOT a Kaggle leaderboard.
"""

from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path

from ..graph.events import Event, EventType
from .config import TournamentConfig
from .pool import CandidatePool
from .scheduler import SchedulerState

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJ_DIR = REPO_ROOT / "data" / "tournament" / "projections"

_INTERNAL_CAVEAT = ("Internal self-play diagnostics only. NOT a Kaggle leaderboard "
                    "and NOT predictive of leaderboard placement. NO upload.")


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    phat = wins / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _pair(x: str, y: str) -> tuple[str, str]:
    return (x, y) if x <= y else (y, x)


def fold_games(events: list[Event]) -> dict:
    """Aggregate per-candidate and per-matchup stats from GameFinished events."""
    per: dict[str, dict] = {}
    matchup: dict[str, dict] = {}
    directed: dict[str, int] = {}
    last_played: dict[str, float] = {}
    smoke_done: set[str] = set()
    totals = {"games": 0, "ok": 0, "invalid": 0, "timeout": 0, "error": 0, "draw": 0}
    last_event_id = None

    def slot(cid: str) -> dict:
        return per.setdefault(cid, {"wins": 0, "losses": 0, "draws": 0,
                                    "invalid": 0, "games": 0})

    for e in events:
        if e.event_type != EventType.GameFinished.value:
            continue
        last_event_id = e.event_id
        p = e.payload
        a, b = p.get("candidate_a"), p.get("candidate_b")
        if not a or not b:
            continue
        totals["games"] += 1
        result = p.get("result")
        lo, hi = _pair(a, b)
        mk = f"{lo}|{hi}"
        m = matchup.setdefault(mk, {"n": 0, "lo": lo, "hi": hi, "lo_wins": 0,
                                    "hi_wins": 0, "draws": 0, "invalid": 0})
        m["n"] += 1
        lo_seat = 0 if a == lo else 1
        directed[f"{lo}>{hi}@{lo_seat}"] = directed.get(f"{lo}>{hi}@{lo_seat}", 0) + 1
        ts = e.timestamp or 0.0
        last_played[a] = max(last_played.get(a, 0.0), ts)
        last_played[b] = max(last_played.get(b, 0.0), ts)
        sa, sb = slot(a), slot(b)
        sa["games"] += 1
        sb["games"] += 1
        if result in ("win", "loss", "draw"):
            totals["ok"] += 1
            smoke_done.add(a)
            smoke_done.add(b)
            if result == "win":      # candidate_a won
                sa["wins"] += 1
                sb["losses"] += 1
                (m.__setitem__("lo_wins", m["lo_wins"] + 1) if a == lo
                 else m.__setitem__("hi_wins", m["hi_wins"] + 1))
            elif result == "loss":
                sa["losses"] += 1
                sb["wins"] += 1
                (m.__setitem__("hi_wins", m["hi_wins"] + 1) if a == lo
                 else m.__setitem__("lo_wins", m["lo_wins"] + 1))
            else:
                sa["draws"] += 1
                sb["draws"] += 1
                m["draws"] += 1
                totals["draw"] += 1
        else:
            sa["invalid"] += 1
            sb["invalid"] += 1
            m["invalid"] += 1
            totals["invalid"] += 1
            if p.get("timeout"):
                totals["timeout"] += 1
            elif result == "error" or p.get("error"):
                totals["error"] += 1
    return {"per": per, "matchup": matchup, "directed": directed,
            "last_played": last_played, "smoke_done": smoke_done,
            "totals": totals, "last_event_id": last_event_id}


def build_scheduler_state(events: list[Event], ranking: list[str] | None = None) -> SchedulerState:
    agg = fold_games(events)
    games_per = {cid: s["games"] for cid, s in agg["per"].items()}
    matchup_counts = {k: v["n"] for k, v in agg["matchup"].items()}
    return SchedulerState(
        games_per_candidate=games_per,
        matchup_counts=matchup_counts,
        directed_counts=dict(agg["directed"]),
        last_played=dict(agg["last_played"]),
        ranking=ranking or [],
        smoke_done=set(agg["smoke_done"]),
    )


def compute_rankings(pool: CandidatePool, agg: dict) -> list[dict]:
    rows = []
    for c in pool.schedulable():
        s = agg["per"].get(c.candidate_id, {"wins": 0, "losses": 0, "draws": 0,
                                            "invalid": 0, "games": 0})
        decisive = s["wins"] + s["losses"]
        adj = (s["wins"] / decisive) if decisive else 0.0
        lo, hi = _wilson(s["wins"], decisive) if decisive else (0.0, 0.0)
        rows.append({
            "candidate_id": c.candidate_id, "family_id": c.family_id,
            "status": c.status, "games": s["games"], "wins": s["wins"],
            "losses": s["losses"], "draws": s["draws"], "invalid": s["invalid"],
            "adj_win_rate": round(adj, 4),
            "wilson_low": round(lo, 4), "wilson_high": round(hi, 4),
        })
    rows.sort(key=lambda r: (-r["adj_win_rate"], -r["games"], r["candidate_id"]))
    return rows


def write_projections(pool: CandidatePool, events: list[Event],
                      cfg: TournamentConfig, *, tick_status: dict | None = None) -> dict:
    """Fold events and write all projection files. Returns a summary dict."""
    PROJ_DIR.mkdir(parents=True, exist_ok=True)
    agg = fold_games(events)
    rankings = compute_rankings(pool, agg)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 1. tournament_state.json
    state = {
        "tournament_id": pool.tournament_id, "generated_at": now,
        "caveat": _INTERNAL_CAVEAT, "no_upload": True,
        "totals": agg["totals"], "last_event_id": agg["last_event_id"],
        "registered_candidates": len(pool.candidates),
        "schedulable_candidates": pool.active_count(),
        "tick_status": tick_status or {},
    }
    (PROJ_DIR / "tournament_state.json").write_text(json.dumps(state, indent=2))

    # 2. rankings.json/md
    (PROJ_DIR / "rankings.json").write_text(json.dumps(
        {"generated_at": now, "caveat": _INTERNAL_CAVEAT, "no_upload": True,
         "rankings": rankings}, indent=2))
    rlines = ["# Tournament Rankings (internal diagnostics only)", "",
              f"_{_INTERNAL_CAVEAT}_", "", f"- generated: {now}",
              f"- total games: {agg['totals']['games']} "
              f"(ok {agg['totals']['ok']}, invalid {agg['totals']['invalid']}, "
              f"timeout {agg['totals']['timeout']})", "",
              "| rank | candidate | family | status | games | W | L | D | adj_wr | wilson95 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rankings, 1):
        rlines.append(f"| {i} | {r['candidate_id']} | {r['family_id']} | {r['status']} "
                      f"| {r['games']} | {r['wins']} | {r['losses']} | {r['draws']} "
                      f"| {r['adj_win_rate']:.3f} | [{r['wilson_low']:.3f},{r['wilson_high']:.3f}] |")
    (PROJ_DIR / "rankings.md").write_text("\n".join(rlines) + "\n")

    # 3. matchups.csv
    with open(PROJ_DIR / "matchups.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate_lo", "candidate_hi", "n", "lo_wins", "hi_wins",
                    "draws", "invalid", "lo_win_rate"])
        for mk in sorted(agg["matchup"]):
            m = agg["matchup"][mk]
            dec = m["lo_wins"] + m["hi_wins"]
            lwr = round(m["lo_wins"] / dec, 4) if dec else ""
            w.writerow([m["lo"], m["hi"], m["n"], m["lo_wins"], m["hi_wins"],
                        m["draws"], m["invalid"], lwr])

    # 4. candidate_pool.json/md (status snapshot)
    (PROJ_DIR / "candidate_pool.json").write_text(json.dumps(
        {"generated_at": now, "no_upload": True, "caveat": _INTERNAL_CAVEAT,
         "status_counts": pool.stats(),
         "candidates": [c.to_dict() for c in pool.candidates]}, indent=2))
    plines = ["# Candidate Pool (projection)", "", f"_{_INTERNAL_CAVEAT}_", "",
              f"- status counts: {pool.stats()}", "",
              "| candidate | family | gen | parent | status | validation | games |",
              "|---|---|---|---|---|---|---|"]
    gmap = {cid: s["games"] for cid, s in agg["per"].items()}
    for c in sorted(pool.candidates, key=lambda c: (c.status, c.candidate_id)):
        plines.append(f"| {c.candidate_id} | {c.family_id} | {c.generation} "
                      f"| {c.parent_candidate_id or '—'} | {c.status} "
                      f"| {c.validation_status} | {gmap.get(c.candidate_id, 0)} |")
    (PROJ_DIR / "candidate_pool.md").write_text("\n".join(plines) + "\n")

    # 5. lineage.json/md
    by_fam = pool.by_family()
    rank_index = {r["candidate_id"]: r for r in rankings}
    lineage = {"generated_at": now, "no_upload": True, "families": {}}
    llines = ["# Lineage (parent → child by family)", "", f"_{_INTERNAL_CAVEAT}_", ""]
    for fam in sorted(by_fam):
        members = sorted(by_fam[fam], key=lambda c: (c.generation, c.candidate_id))
        best = None
        for c in members:
            r = rank_index.get(c.candidate_id)
            if r and r["games"] > 0 and (best is None or r["adj_win_rate"] > best[1]):
                best = (c.candidate_id, r["adj_win_rate"])
        lineage["families"][fam] = {
            "best_with_games": best[0] if best else None,
            "members": [{"candidate_id": c.candidate_id, "generation": c.generation,
                         "parent": c.parent_candidate_id, "status": c.status}
                        for c in members]}
        llines.append(f"## {fam}  (best-with-games: {best[0] if best else 'n/a'})")
        for c in members:
            llines.append(f"- gen{c.generation} `{c.candidate_id}` "
                          f"(parent: {c.parent_candidate_id or '—'}, status: {c.status})")
        llines.append("")
    (PROJ_DIR / "lineage.json").write_text(json.dumps(lineage, indent=2))
    (PROJ_DIR / "lineage.md").write_text("\n".join(llines) + "\n")

    # 6. non_inertness.json/md (parent-child evidence — NO improvement claims)
    ni = {"generated_at": now, "no_upload": True,
          "note": "Evidence sufficiency only. Pass 35 calibration: typed children "
                  "are NOT a proven win-rate gain. No improvement is claimed here.",
          "candidates": []}
    nlines = ["# Non-Inertness / Parent-Child Evidence", "", f"_{ni['note']}_", "",
              "| child | parent | child_games | parent_games | child_adj_wr "
              "| parent_adj_wr | delta | evidence |", "|---|---|---|---|---|---|---|---|"]
    min_need = cfg.min_parent_child_games_per_seat * 2
    for c in sorted(pool.schedulable(), key=lambda c: c.candidate_id):
        p = c.parent_candidate_id
        if not p or not pool.by_id(p):
            continue
        cr, pr = rank_index.get(c.candidate_id), rank_index.get(p)
        cg = cr["games"] if cr else 0
        pg = pr["games"] if pr else 0
        cwr = cr["adj_win_rate"] if cr else None
        pwr = pr["adj_win_rate"] if pr else None
        enough = cg >= min_need and pg >= min_need
        delta = round(cwr - pwr, 4) if (cwr is not None and pwr is not None) else None
        ev = "sufficient_calibration_required" if enough else "insufficient_evidence"
        ni["candidates"].append({"child": c.candidate_id, "parent": p,
                                 "child_games": cg, "parent_games": pg,
                                 "child_adj_wr": cwr, "parent_adj_wr": pwr,
                                 "delta": delta, "evidence": ev,
                                 "improvement_claimed": False})
        nlines.append(f"| {c.candidate_id} | {p} | {cg} | {pg} | "
                      f"{cwr if cwr is not None else '—'} | "
                      f"{pwr if pwr is not None else '—'} | "
                      f"{delta if delta is not None else '—'} | {ev} |")
    (PROJ_DIR / "non_inertness.json").write_text(json.dumps(ni, indent=2))
    (PROJ_DIR / "non_inertness.md").write_text("\n".join(nlines) + "\n")

    return {"rankings": rankings, "totals": agg["totals"],
            "last_event_id": agg["last_event_id"],
            "ranked_ids": [r["candidate_id"] for r in rankings]}


def write_scheduler_queue(worklist, cfg: TournamentConfig) -> None:
    """Persist the upcoming scheduled games (projection #7)."""
    PROJ_DIR.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items = [g.to_dict() for g in worklist]
    (PROJ_DIR / "scheduler_queue.json").write_text(json.dumps(
        {"generated_at": now, "no_upload": True, "count": len(items),
         "queue": items}, indent=2))
    qlines = ["# Scheduler Queue (next bounded tick)", "",
              f"_Internal only · generated {now} · {len(items)} games_", "",
              "| game_id | candidate_a (seat0) | candidate_b | priority | reason |",
              "|---|---|---|---|---|"]
    for it in items:
        qlines.append(f"| `{it['game_id']}` | {it['candidate_a']} | "
                      f"{it['candidate_b']} | {it['priority']} | {it['reason']} |")
    (PROJ_DIR / "scheduler_queue.md").write_text("\n".join(qlines) + "\n")
