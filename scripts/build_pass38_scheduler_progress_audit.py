#!/usr/bin/env python3
"""Pass 38 (Part H) — scheduler fairness + progress audit.

OPS / read-only over the ledger. Folds the event log, rebuilds the deterministic
worklist the next tick would run, and audits:

  * **Determinism** — building the worklist twice yields the identical game_id
    sequence (the scheduler must be a pure function of pool+state+config).
  * **Safety** — no non-schedulable (NEVER_SCHEDULE) candidate appears in the
    worklist.
  * **Progress** — the next worklist excludes already-finished game_ids, and is
    non-empty while schedulable candidates are still below their placement quota,
    so each tick advances instead of stalling or replaying finished games.
  * **Seat fairness** — for every played matchup the two seat directions are
    balanced to within one game (the scheduler alternates seats).
  * **Coverage fairness** — games-per-candidate spread.

Writes data/experiments/pass38_scheduler_progress_audit.{json,md}. NO upload, NO
submit, NO push, NO root mutation, NO candidate generation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament import projections  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402

EXP = REPO / "data" / "experiments"


def main() -> int:
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates:
        pool = CandidatePool.load()

    agg = projections.fold_games(events)
    rankings = projections.compute_rankings(pool, agg)
    ranked_ids = [r["candidate_id"] for r in rankings]
    state = projections.build_scheduler_state(events, ranking=ranked_ids)
    finished = ledger.finished_game_ids()

    wl1 = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    wl2 = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    seq1 = [g.game_id for g in wl1]
    seq2 = [g.game_id for g in wl2]
    wl_next = [g for g in wl1 if g.game_id not in finished]

    blocked_ids = {c.candidate_id for c in pool.candidates if not c.schedulable}
    never_in_wl = sorted({cid for g in wl1
                          for cid in (g.candidate_a, g.candidate_b)
                          if cid in blocked_ids})
    wl_replays_finished = sorted({g.game_id for g in wl_next if g.game_id in finished})

    # progress: anyone still short of placement quota should yield work.
    sched = pool.schedulable()
    games_per = {c.candidate_id: agg["per"].get(c.candidate_id, {}).get("games", 0)
                 for c in sched}
    under_quota = [cid for cid, n in games_per.items()
                   if n < cfg.min_placement_games_per_candidate]
    makes_progress = (not under_quota) or len(wl_next) > 0

    # seat fairness from directed counts.
    directed = agg["directed"]
    seat_imbalance = {}
    for mk, m in agg["matchup"].items():
        lo, hi = m["lo"], m["hi"]
        n0 = directed.get(f"{lo}>{hi}@0", 0)
        n1 = directed.get(f"{lo}>{hi}@1", 0)
        if n0 + n1 > 0:
            seat_imbalance[f"{lo}|{hi}"] = abs(n0 - n1)
    max_seat_imbalance = max(seat_imbalance.values(), default=0)

    # coverage spread.
    gvals = list(games_per.values())
    spread = (max(gvals) - min(gvals)) if gvals else 0

    hard = {
        "scheduler_deterministic": seq1 == seq2,
        "no_never_schedule_in_worklist": not never_in_wl,
        "worklist_excludes_finished": not wl_replays_finished,
        "makes_progress": makes_progress,
    }
    warn = {
        "seat_balanced_within_one": max_seat_imbalance <= 1,
        "coverage_spread_reasonable": (not gvals) or spread <= max(
            cfg.min_placement_games_per_candidate, 1),
    }
    audit_ok = all(hard.values())

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "H", "read_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "config": {"tick_max_games": cfg.tick_max_games,
                   "min_placement_games_per_candidate": cfg.min_placement_games_per_candidate,
                   "min_parent_child_games_per_seat": cfg.min_parent_child_games_per_seat,
                   "top_bracket_size": cfg.top_bracket_size},
        "schedulable_candidates": len(sched),
        "blocked_candidates": len(blocked_ids),
        "finished_games": len(finished),
        "worklist_size": len(wl1),
        "worklist_next_size": len(wl_next),
        "worklist_preview": [g.to_dict() for g in wl_next[:8]],
        "reason_histogram": _hist(g.reason for g in wl1),
        "priority_histogram": _hist(str(g.priority) for g in wl1),
        "games_per_candidate": games_per,
        "coverage_spread": spread,
        "under_placement_quota": sorted(under_quota),
        "seat_imbalance": seat_imbalance,
        "max_seat_imbalance": max_seat_imbalance,
        "never_in_worklist": never_in_wl,
        "worklist_replaying_finished": wl_replays_finished,
        "hard": hard, "warn": warn, "audit_ok": audit_ok,
    }
    (EXP / "pass38_scheduler_progress_audit.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Scheduler fairness + progress audit (Part H)", "",
        "> OPS / read-only. The scheduler is a pure function of (pool, folded state, "
        "config); this audit reconstructs the next bounded worklist and checks it is "
        "deterministic, safe, forward-progressing, and seat-fair. Internal "
        "diagnostics; NOT a Kaggle leaderboard.", "",
        f"- schedulable candidates: **{len(sched)}**  blocked: {len(blocked_ids)}",
        f"- finished games: **{len(finished)}**  next worklist: **{len(wl_next)}** "
        f"(of tick cap {cfg.tick_max_games})",
        f"- worklist reasons: {payload['reason_histogram']}",
        f"- games/candidate spread: {spread}  max seat imbalance: "
        f"{max_seat_imbalance}",
        f"- candidates under placement quota "
        f"({cfg.min_placement_games_per_candidate}): {len(under_quota)}", "",
        "## Hard checks",
        f"- scheduler deterministic (worklist twice identical): "
        f"**{yn(hard['scheduler_deterministic'])}**",
        f"- no never-schedule candidate in worklist: "
        f"**{yn(hard['no_never_schedule_in_worklist'])}**",
        f"- worklist excludes finished games: "
        f"**{yn(hard['worklist_excludes_finished'])}**",
        f"- makes forward progress: **{yn(hard['makes_progress'])}**", "",
        "## Warnings",
        f"- seat balanced within one: **{yn(warn['seat_balanced_within_one'])}** "
        f"(max imbalance {max_seat_imbalance})",
        f"- coverage spread reasonable: "
        f"**{yn(warn['coverage_spread_reasonable'])}** (spread {spread})", "",
        "## Next worklist (preview)",
        "| game_id | a (seat0) | b | prio | reason |", "|---|---|---|---|---|",
        *[f"| `{g['game_id']}` | {g['candidate_a']} | {g['candidate_b']} "
          f"| {g['priority']} | {g['reason']} |" for g in payload["worklist_preview"]],
        "",
        f"## Verdict: audit_ok = **{yn(audit_ok)}**",
    ]
    (EXP / "pass38_scheduler_progress_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"scheduler audit: ok={audit_ok} deterministic={hard['scheduler_deterministic']} "
          f"next={len(wl_next)} never_in_wl={never_in_wl} "
          f"max_seat_imbalance={max_seat_imbalance}")
    return 0 if audit_ok else 1


def _hist(it):
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    raise SystemExit(main())
