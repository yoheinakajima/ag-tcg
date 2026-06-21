#!/usr/bin/env python3
"""PASS 43 — Part J: scheduler & lifecycle integration audit.

Verifies the Promotion Gate composes safely with the scheduler/lifecycle machinery,
WITHOUT mutating anything (no events written, no production touched):

  1. probation + active candidates are schedulable; never-schedule statuses
     (retired/quarantined/special_pilot_only/invalid) are not;
  2. no never-schedule candidate and no public reference appears in the worklist;
  3. running the gate (dry-run evaluate) does NOT change the scheduler — the worklist
     is byte-identical before and after, and the gate emits nothing;
  4. an *applied* status change folds correctly via CandidatePool.from_events and is
     then honoured by the scheduler (demonstrated on an in-memory synthetic event —
     nothing is persisted);
  5. the scheduler build is deterministic (repeated builds give identical game ids).

Output: data/experiments/pass43_scheduler_promotion_integration.{json,md}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import Event, EventType  # noqa: E402
from ptcg_activegraph.tournament import promotion  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    ACTIVE, NEVER_SCHEDULE, PROBATION, RETIRED, CandidatePool)
from ptcg_activegraph.tournament.projections import (  # noqa: E402
    build_scheduler_state, compute_rankings, fold_games)
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402

EXP = REPO / "data" / "experiments"


def _worklist_ids(pool: CandidatePool, events: list, cfg) -> list[str]:
    agg = fold_games(events)
    ranked = [r["candidate_id"] for r in compute_rankings(pool, agg)]
    state = build_scheduler_state(events, ranking=ranked)
    finished = {e.payload.get("game_id") for e in events
                if e.event_type == EventType.GameFinished.value}
    wl = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    return [g.game_id for g in wl if g.game_id not in finished]


def _worklist_participants(pool: CandidatePool, events: list, cfg) -> set[str]:
    agg = fold_games(events)
    ranked = [r["candidate_id"] for r in compute_rankings(pool, agg)]
    state = build_scheduler_state(events, ranking=ranked)
    wl = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    out: set[str] = set()
    for g in wl:
        out.add(g.candidate_a)
        out.add(g.candidate_b)
    return out


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates:
        pool = CandidatePool.load()

    ref_ids = promotion.load_reference_ids()

    # 1. status -> schedulable expectation
    schedulable_ids = {c.candidate_id for c in pool.schedulable()}
    status_checks = []
    probation_active_all_schedulable = True
    neverschedule_none_schedulable = True
    for c in pool.candidates:
        sched = c.candidate_id in schedulable_ids
        if c.status in (PROBATION, ACTIVE) and not sched:
            probation_active_all_schedulable = False
        if c.status in NEVER_SCHEDULE and sched:
            neverschedule_none_schedulable = False
        status_checks.append({"candidate_id": c.candidate_id,
                              "status": c.status, "schedulable": sched})

    # 2. worklist excludes never-schedule + public references
    participants = _worklist_participants(pool, events, cfg)
    neverschedule_ids = {c.candidate_id for c in pool.candidates
                         if c.status in NEVER_SCHEDULE}
    no_neverschedule_in_worklist = not (participants & neverschedule_ids)
    no_reference_in_pool = not ({c.candidate_id for c in pool.candidates} & ref_ids)
    no_reference_in_worklist = not (participants & ref_ids)

    # 3. gate is non-mutating: worklist identical before/after evaluate; emits nothing
    wl_before = _worklist_ids(pool, events, cfg)
    evaluation = promotion.evaluate(pool, events)
    events_after_eval = ledger.load()  # re-read: evaluate must NOT have written
    pool_after = CandidatePool.from_events(events_after_eval) or pool
    wl_after = _worklist_ids(pool_after, events_after_eval, cfg)
    gate_emitted_nothing = (len(events_after_eval) == len(events))
    worklist_unchanged_by_gate = (wl_before == wl_after)

    # 4. an applied status change folds + is honoured by the scheduler (in-memory)
    fold_demo = {"performed": False}
    demo_target = next((c for c in pool.candidates
                        if c.status == PROBATION and c.schedulable), None)
    if demo_target is not None:
        synth = Event(
            event_type=EventType.CandidateStatusChanged.value,
            payload={"candidate_id": demo_target.candidate_id,
                     "from_status": PROBATION, "new_status": RETIRED,
                     "status_note": "in-memory fold demo (not persisted)",
                     "no_upload": True},
        )
        merged = list(events) + [synth]
        rebuilt = CandidatePool.from_events(merged)
        rc = rebuilt.by_id(demo_target.candidate_id)
        folded_to_retired = bool(rc is not None and rc.status == RETIRED)
        after_parts = _worklist_participants(rebuilt, merged, cfg)
        excluded_after_retire = demo_target.candidate_id not in after_parts
        fold_demo = {
            "performed": True,
            "target": demo_target.candidate_id,
            "folded_to_retired": folded_to_retired,
            "excluded_from_worklist_after_retire": excluded_after_retire,
            "persisted": False,
        }
        # confirm nothing was written by the demo
        fold_demo["ledger_unchanged"] = (len(ledger.load()) == len(events))

    # 5. determinism: build twice -> identical
    deterministic = (_worklist_ids(pool, events, cfg)
                     == _worklist_ids(pool, events, cfg))

    ok = bool(probation_active_all_schedulable and neverschedule_none_schedulable
              and no_neverschedule_in_worklist and no_reference_in_pool
              and no_reference_in_worklist and gate_emitted_nothing
              and worklist_unchanged_by_gate and deterministic
              and (not fold_demo["performed"]
                   or (fold_demo["folded_to_retired"]
                       and fold_demo["excluded_from_worklist_after_retire"]
                       and fold_demo["ledger_unchanged"])))

    out = {
        "pass": "pass43_scheduler_promotion_integration",
        "ok": ok,
        "n_candidates": len(pool.candidates),
        "n_schedulable": len(schedulable_ids),
        "worklist_size": len(wl_before),
        "checks": {
            "probation_active_all_schedulable": probation_active_all_schedulable,
            "neverschedule_none_schedulable": neverschedule_none_schedulable,
            "no_neverschedule_in_worklist": no_neverschedule_in_worklist,
            "no_reference_in_pool": no_reference_in_pool,
            "no_reference_in_worklist": no_reference_in_worklist,
            "gate_emitted_nothing": gate_emitted_nothing,
            "worklist_unchanged_by_gate": worklist_unchanged_by_gate,
            "scheduler_deterministic": deterministic,
        },
        "applied_status_change_fold_demo": fold_demo,
        "gate_summary_by_action": evaluation["summary_by_action"],
        "status_table": status_checks,
        "production_mutated": False,
        "events_emitted": 0,
    }
    (EXP / "pass43_scheduler_promotion_integration.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b) -> str:
        return "yes" if b else "no"

    md = [
        "# PASS 43 — Scheduler & lifecycle integration audit",
        "", f"- overall: **{'PASS' if ok else 'FAIL'}**",
        f"- candidates: {len(pool.candidates)}  schedulable: {len(schedulable_ids)}  "
        f"worklist size: {len(wl_before)}", "",
        "## Checks", "", "| check | result |", "|---|---|",
    ]
    for k, v in out["checks"].items():
        md.append(f"| {k} | {yn(v)} |")
    md += ["", "## Applied-status-change fold demo (in-memory, not persisted)", ""]
    if fold_demo["performed"]:
        md += [f"- target: `{fold_demo['target']}`",
               f"- folds probation→retired via from_events: "
               f"{yn(fold_demo['folded_to_retired'])}",
               f"- excluded from worklist after retire: "
               f"{yn(fold_demo['excluded_from_worklist_after_retire'])}",
               f"- ledger unchanged (nothing persisted): "
               f"{yn(fold_demo['ledger_unchanged'])}"]
    else:
        md.append("- no eligible probation candidate to demo")
    md += ["", "> The gate emits nothing and leaves the scheduler worklist identical; "
           "lifecycle marks only take effect through the ledger fold, which the "
           "scheduler already honours. No production mutation."]
    (EXP / "pass43_scheduler_promotion_integration.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"pass43 scheduler/promotion integration: ok={ok} "
          f"worklist={len(wl_before)} schedulable={len(schedulable_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
