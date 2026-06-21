#!/usr/bin/env python3
"""PASS 44 — Part G: scheduler / lifecycle follow-up audit (post prod registration).

Read-only. Rebuilds the scheduler worklist from the PRODUCTION ledger exactly as the
deployed daemon would (fold events -> rankings -> scheduler state -> worklist) and
asserts the lifecycle invariants now that the 3 Pass-42 probation candidates are
registered in prod:

  * probation candidates are schedulable AND actually placed in the worklist;
  * worklist construction is deterministic (two builds are identical);
  * public reference candidates are benchmark-only -> absent from the main queue;
  * never-schedule statuses (special_pilot_only / retired / quarantined / invalid)
    present in the pool are absent from the worklist;
  * protected statuses (family_champion / portfolio_anchor / held_probe) are present
    and were not demoted;
  * no active-cap replacement was forced by adding probation candidates;
  * no promotion / retirement / forbidden events exist in the prod ledger.

To avoid polluting local diagnostics, projection writes are redirected to a temp dir.
Production is never mutated. Output:
  data/experiments/pass44_scheduler_lifecycle_after_prod_registration.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import build_pass43_production_probation_registration as R  # noqa: E402
from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament import projections as projmod  # noqa: E402
from ptcg_activegraph.tournament import promotion, sync  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
RETIREMENT_EVENTS = {"CandidateRetired", "CandidatePromoted"}
NEVER_SCHEDULE = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED,
                  poolmod.QUARANTINED, poolmod.INVALID}
PROTECTED = {poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR, poolmod.HELD_PROBE}


def _load_prod():
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    if not backend.exists(sync.EVENTS_KEY):
        raise SystemExit("prod ledger not reachable")
    txt = backend.read_text(sync.EVENTS_KEY)
    tmp = Path(tempfile.mkdtemp(prefix="pass44_sched_prod_")) / "events.jsonl"
    tmp.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmp).load()
    pool = CandidatePool.from_events(events)
    return pool, events


def _build(pool, events, cfg) -> list:
    prior = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
    return build_worklist(pool, state, cfg)


def _ids_in_worklist(worklist) -> set[str]:
    ids: set[str] = set()
    for g in worklist:
        d = g.to_dict()
        ids.add(d["candidate_a"])
        ids.add(d["candidate_b"])
    return ids


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    # redirect all projection writes to a throwaway dir (no local pollution)
    projmod.PROJ_DIR = Path(tempfile.mkdtemp(prefix="pass44_proj_"))

    pool, events = _load_prod()
    cfg = load_config()

    targets = set(R._target_ids())
    ref_ids = set(promotion.load_reference_ids())
    by_status: dict[str, list[str]] = {}
    status_of: dict[str, str] = {}
    for c in pool.candidates:
        by_status.setdefault(c.status, []).append(c.candidate_id)
        status_of[c.candidate_id] = c.status

    wl1 = _build(pool, events, cfg)
    wl2 = _build(pool, events, cfg)
    sig1 = [g.to_dict() for g in wl1]
    sig2 = [g.to_dict() for g in wl2]
    deterministic = sig1 == sig2
    wl_ids = _ids_in_worklist(wl1)

    # probation schedulability + placement
    probation_ids = set(by_status.get(poolmod.PROBATION, []))
    targets_in_pool = sorted(t for t in targets if t in status_of)
    targets_probation = sorted(t for t in targets if status_of.get(t) == poolmod.PROBATION)
    targets_in_worklist = sorted(t for t in targets if t in wl_ids)

    # never-schedule statuses present must be absent from worklist
    never_ids = {cid for cid, st in status_of.items() if st in NEVER_SCHEDULE}
    never_in_worklist = sorted(never_ids & wl_ids)

    # public refs absent from main queue
    refs_present = sorted(ref_ids & set(status_of))
    refs_in_worklist = sorted(ref_ids & wl_ids)

    # protected present + not demoted (no demotion event targeting them)
    protected_ids = {cid for cid, st in status_of.items() if st in PROTECTED}
    demotion_hits = []
    for e in events:
        if e.event_type == "CandidateStatusChanged":
            p = e.payload or {}
            if p.get("candidate_id") in protected_ids and \
                    p.get("new_status") not in PROTECTED:
                demotion_hits.append({"candidate_id": p.get("candidate_id"),
                                      "from": p.get("from_status"),
                                      "to": p.get("new_status")})

    forbidden_present = sorted({e.event_type for e in events
                               if e.event_type in FORBIDDEN})
    retirement_present = sorted({e.event_type for e in events
                                if e.event_type in RETIREMENT_EVENTS})

    # active-cap: adding probation must not have forced a replacement/demotion of
    # an existing active candidate. We assert no active->(retired/quarantined)
    # demotion events exist at all (registration emitted only CandidateRegistered/
    # CandidateStatusChanged to probation for the 3 targets).
    cap_replacements = []
    for e in events:
        if e.event_type == "CandidateStatusChanged":
            p = e.payload or {}
            if p.get("from_status") == poolmod.ACTIVE and \
                    p.get("new_status") in (poolmod.RETIRED, poolmod.QUARANTINED):
                cap_replacements.append({"candidate_id": p.get("candidate_id"),
                                         "to": p.get("new_status")})

    checks = {
        "deterministic_worklist": deterministic,
        "probation_targets_all_in_pool": len(targets_in_pool) == len(targets),
        "probation_targets_all_probation_status":
            len(targets_probation) == len(targets),
        "probation_targets_placed_in_worklist":
            len(targets_in_worklist) == len(targets),
        "no_never_schedule_in_worklist": not never_in_worklist,
        "no_public_ref_in_worklist": not refs_in_worklist,
        "protected_present": bool(protected_ids),
        "no_protected_demotion": not demotion_hits,
        "no_active_cap_replacement": not cap_replacements,
        "no_forbidden_events": not forbidden_present,
        "no_retirement_or_promotion_events": not retirement_present,
    }
    all_ok = all(checks.values())

    out = {
        "pass": "pass44_scheduler_lifecycle_after_prod_registration",
        "all_ok": all_ok,
        "checks": checks,
        "worklist_size": len(wl1),
        "schedulable_candidates": pool.active_count(),
        "registered_candidates": len(pool.candidates),
        "status_histogram": {k: len(v) for k, v in sorted(by_status.items())},
        "targets": {
            "ids": sorted(targets),
            "in_pool": targets_in_pool,
            "probation_status": targets_probation,
            "placed_in_worklist": targets_in_worklist,
        },
        "never_schedule_present": sorted(never_ids),
        "never_schedule_in_worklist": never_in_worklist,
        "public_refs_present_in_pool": refs_present,
        "public_refs_in_worklist": refs_in_worklist,
        "protected_present": sorted(protected_ids),
        "protected_demotions_detected": demotion_hits,
        "active_cap_replacements_detected": cap_replacements,
        "forbidden_events_present": forbidden_present,
        "retirement_or_promotion_events_present": retirement_present,
        "production_mutated": False,
    }
    (EXP / "pass44_scheduler_lifecycle_after_prod_registration.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 44 — Part G: scheduler / lifecycle audit (post prod registration)", "",
        f"- **all checks pass: {yn(all_ok)}**",
        f"- worklist size: **{len(wl1)}**  · schedulable: "
        f"**{pool.active_count()}**  · registered: **{len(pool.candidates)}**",
        f"- status histogram: `{json.dumps({k: len(v) for k, v in sorted(by_status.items())})}`",
        "", "## Checks", "", "| check | pass |", "|---|---|",
    ]
    for k, v in checks.items():
        md.append(f"| {k} | {yn(v)} |")
    md += [
        "", "## Probation targets", "",
        f"- in pool: `{targets_in_pool}`",
        f"- probation status: `{targets_probation}`",
        f"- placed in worklist: `{targets_in_worklist}`",
        "", "## Lifecycle protections", "",
        f"- never-schedule statuses present: `{sorted(never_ids)}` "
        f"(in worklist: `{never_in_worklist}`)",
        f"- public refs present: `{refs_present}` (in worklist: `{refs_in_worklist}`)",
        f"- protected present: `{sorted(protected_ids)}` "
        f"(demotions: `{demotion_hits}`)",
        f"- active-cap replacements: `{cap_replacements}`",
        f"- forbidden events: `{forbidden_present}`  · retirement/promotion: "
        f"`{retirement_present}`",
        "", "> Read-only audit. Production not mutated. Projection writes redirected "
        "to a temp dir.",
    ]
    (EXP / "pass44_scheduler_lifecycle_after_prod_registration.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass44 partG: all_ok={all_ok} worklist={len(wl1)} "
          f"targets_placed={len(targets_in_worklist)}/{len(targets)} "
          f"never_in_wl={never_in_worklist} refs_in_wl={refs_in_worklist} "
          f"protected_demotions={len(demotion_hits)} forbidden={forbidden_present}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
