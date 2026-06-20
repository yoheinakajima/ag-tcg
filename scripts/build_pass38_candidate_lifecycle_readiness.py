#!/usr/bin/env python3
"""Pass 38 (Part I) — candidate lifecycle readiness (status-only, NO mutation).

OPS / read-only over the ledger. Reconstructs the candidate pool from the event
log and reports lifecycle *readiness* WITHOUT changing any candidate status and
WITHOUT generating any candidate. It verifies the status partition invariants the
engine relies on, then surfaces which candidates are ready for ranking confidence
and which parent-child pairs are ready for calibration.

HARD invariants (process exits non-zero on violation):
  * every candidate has a recognised status,
  * SCHEDULABLE and NEVER_SCHEDULE status sets are disjoint,
  * pool.schedulable() returns exactly the candidates whose status is schedulable,
  * no NEVER_SCHEDULE candidate (retired/quarantined/special_pilot_only/invalid)
    is schedulable,
  * every candidate is registered exactly once (no phantom/duplicate identity).

Readiness signals (informational; status-only):
  * placement readiness — candidates at/above the placement-games quota,
  * parent-child calibration readiness — both schedulable with each seat at/above
    the per-seat quota,
  * held_probe retention roster.

Writes data/experiments/pass38_candidate_lifecycle_readiness.{json,md}. NO upload,
NO submit, NO push, NO root mutation, NO candidate generation.
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

EXP = REPO / "data" / "experiments"


def main() -> int:
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    registry_source = "ledger"
    if not pool.candidates:
        pool = CandidatePool.load()
        registry_source = "seed_file"

    agg = projections.fold_games(events)
    games_per = {cid: s["games"] for cid, s in agg["per"].items()}
    directed = agg["directed"]

    # registration multiplicity (phantom/dup identity guard).
    reg_counts: dict[str, int] = {}
    for e in events:
        if e.event_type == "ParticipantRegistered":
            cid = (e.payload or {}).get("candidate_id")
            if cid:
                reg_counts[cid] = reg_counts.get(cid, 0) + 1
    dup_registrations = sorted(c for c, n in reg_counts.items() if n > 1)

    # --- hard partition invariants ----------------------------------------
    unknown_status = sorted(c.candidate_id for c in pool.candidates
                            if c.status not in poolmod.VALID_STATUSES)
    sets_disjoint = not (poolmod.SCHEDULABLE_STATUSES & poolmod.NEVER_SCHEDULE)
    sched_ids = {c.candidate_id for c in pool.schedulable()}
    sched_consistent = sched_ids == {c.candidate_id for c in pool.candidates
                                     if c.status in poolmod.SCHEDULABLE_STATUSES}
    never_scheduled_leak = sorted(
        c.candidate_id for c in pool.candidates
        if c.status in poolmod.NEVER_SCHEDULE and c.schedulable)

    hard = {
        "all_status_recognised": not unknown_status,
        "status_sets_disjoint": sets_disjoint,
        "schedulable_matches_status": sched_consistent,
        "no_never_schedule_leak": not never_scheduled_leak,
        "no_duplicate_registration": not dup_registrations,
    }
    audit_ok = all(hard.values())

    # --- readiness (status-only) ------------------------------------------
    min_place = cfg.min_placement_games_per_candidate
    min_seat = cfg.min_parent_child_games_per_seat
    roster = []
    placement_ready = placement_pending = 0
    for c in sorted(pool.schedulable(), key=lambda c: c.candidate_id):
        g = games_per.get(c.candidate_id, 0)
        ready = g >= min_place
        placement_ready += int(ready)
        placement_pending += int(not ready)
        roster.append({"candidate_id": c.candidate_id, "family_id": c.family_id,
                       "status": c.status, "generation": c.generation,
                       "parent": c.parent_candidate_id, "games": g,
                       "placement_ready": ready,
                       "games_needed": max(0, min_place - g)})

    calibration = []
    for c in sorted(pool.schedulable(), key=lambda c: c.candidate_id):
        p = c.parent_candidate_id
        if not p or not pool.by_id(p) or not pool.by_id(p).schedulable:
            continue
        lo, hi = (c.candidate_id, p) if c.candidate_id <= p else (p, c.candidate_id)
        s0 = directed.get(f"{lo}>{hi}@0", 0)
        s1 = directed.get(f"{lo}>{hi}@1", 0)
        ready = s0 >= min_seat and s1 >= min_seat
        calibration.append({"child": c.candidate_id, "parent": p,
                            "seat0_games": s0, "seat1_games": s1,
                            "calibration_ready": ready,
                            "improvement_claimed": False})

    held_probe = sorted(c.candidate_id for c in pool.candidates
                        if c.status == poolmod.HELD_PROBE)
    never_roster = {s: sorted(c.candidate_id for c in pool.candidates if c.status == s)
                    for s in sorted(poolmod.NEVER_SCHEDULE)}

    warn = {
        "all_schedulable_placement_ready": placement_pending == 0,
        "all_parent_child_calibrated": all(c["calibration_ready"] for c in calibration)
                                       if calibration else True,
    }

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "I", "read_only": True, "mutation": False,
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "registry_source": registry_source,
        "registered_candidates": len(pool.candidates),
        "status_counts": pool.stats(),
        "schedulable_count": len(sched_ids),
        "placement_quota": min_place, "per_seat_quota": min_seat,
        "placement_ready": placement_ready,
        "placement_pending": placement_pending,
        "calibration_pairs": len(calibration),
        "calibration_ready": sum(1 for c in calibration if c["calibration_ready"]),
        "held_probe_roster": held_probe,
        "never_schedule_roster": never_roster,
        "roster": roster, "calibration": calibration,
        "hard": hard, "warn": warn, "audit_ok": audit_ok,
        "unknown_status": unknown_status,
        "never_scheduled_leak": never_scheduled_leak,
        "duplicate_registration": dup_registrations,
    }
    (EXP / "pass38_candidate_lifecycle_readiness.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Candidate lifecycle readiness (Part I)", "",
        "> OPS / read-only. STATUS-ONLY: no candidate status is changed and NO "
        "candidate is generated. Verifies the lifecycle status partition and "
        "reports readiness for ranking confidence and parent-child calibration. "
        "No improvement is claimed. Internal diagnostics; NOT a Kaggle leaderboard.",
        "",
        f"- registry source: **{registry_source}**  registered: "
        f"**{len(pool.candidates)}**  schedulable: **{len(sched_ids)}**",
        f"- status counts: {pool.stats()}",
        f"- placement quota {min_place}: **{placement_ready}** ready, "
        f"**{placement_pending}** pending",
        f"- parent-child pairs: {len(calibration)} "
        f"({payload['calibration_ready']} calibration-ready, per-seat quota "
        f"{min_seat})",
        f"- held_probe retained: {held_probe or '—'}",
        f"- never-schedule roster: {never_roster}", "",
        "## Hard invariants",
        f"- all statuses recognised: **{yn(hard['all_status_recognised'])}**",
        f"- schedulable/never-schedule sets disjoint: "
        f"**{yn(hard['status_sets_disjoint'])}**",
        f"- schedulable() matches status: "
        f"**{yn(hard['schedulable_matches_status'])}**",
        f"- no never-schedule leak: **{yn(hard['no_never_schedule_leak'])}**",
        f"- no duplicate registration: **{yn(hard['no_duplicate_registration'])}**",
        "",
        "## Schedulable roster (readiness)",
        "| candidate | family | status | games | placement_ready | needed |",
        "|---|---|---|---|---|---|",
        *[f"| {r['candidate_id']} | {r['family_id']} | {r['status']} | {r['games']} "
          f"| {yn(r['placement_ready'])} | {r['games_needed']} |" for r in roster],
        "",
        "## Parent-child calibration readiness (no improvement claimed)",
        "| child | parent | seat0 | seat1 | calibration_ready |",
        "|---|---|---|---|---|",
        *[f"| {c['child']} | {c['parent']} | {c['seat0_games']} | {c['seat1_games']} "
          f"| {yn(c['calibration_ready'])} |" for c in calibration],
        "",
        f"## Verdict: audit_ok = **{yn(audit_ok)}**",
    ]
    (EXP / "pass38_candidate_lifecycle_readiness.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"lifecycle readiness: ok={audit_ok} registered={len(pool.candidates)} "
          f"schedulable={len(sched_ids)} placement_ready={placement_ready}/"
          f"{placement_ready + placement_pending} calib_ready="
          f"{payload['calibration_ready']}/{len(calibration)}")
    return 0 if audit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
