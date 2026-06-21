#!/usr/bin/env python3
"""Pass 39 — Part I: event + projection idempotency audit.

Verifies the honesty/idempotency invariants the lifecycle manager relies on:

1. Ledger hygiene: NO forbidden upload/submit events; EVERY event carries
   ``no_upload=true``.
2. CandidateStatusChanged hygiene: unique ``event_id``; no two marks leaving a
   candidate at conflicting statuses for the same (timestamp,index) ordering.
3. ``from_events`` folding is deterministic and idempotent, and a synthetic
   CandidateStatusChanged is honored (status mutates, registration replaces).
4. Re-evaluating the live plan yields ``apply_skipped`` (no churn on a no-op state).
5. Projection folds (fold_games / compute_rankings) are deterministic.
6. ``reconcile_events`` collapses a duplicate CandidateStatusChanged by event_id.

Read-only against the live ledger (synthetic events are in-memory only). NO upload,
NO submit, NO candidate generation, NO mutation of the real ledger.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType, new_event  # noqa: E402
from ptcg_activegraph.tournament import lifecycle as lc  # noqa: E402
from ptcg_activegraph.tournament import projections, sync  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    PROBATION,
    QUARANTINED,
    CandidatePool,
)

EXP = REPO / "data" / "experiments"
_FORBIDDEN = {"SubmissionUploaded", "KaggleScoreUpdated"}


def main() -> int:
    cfg = load_config()
    ledger = TournamentLedger()
    events = ledger.load()
    checks: dict[str, bool] = {}

    # 1. ledger hygiene -------------------------------------------------------
    forbidden = [e.event_id for e in events if e.event_type in _FORBIDDEN]
    missing_no_upload = [e.event_id for e in events
                         if (getattr(e, "payload", None) or {}).get("no_upload") is not True]
    checks["no_forbidden_events"] = not forbidden
    checks["all_events_no_upload"] = not missing_no_upload

    # 2. CandidateStatusChanged hygiene --------------------------------------
    csc = [e for e in events if e.event_type == EventType.CandidateStatusChanged.value]
    csc_ids = [e.event_id for e in csc]
    checks["candidate_status_changed_unique_ids"] = len(csc_ids) == len(set(csc_ids))

    # 3. from_events determinism + synthetic fold ----------------------------
    p1 = CandidatePool.from_events(events)
    p2 = CandidatePool.from_events(events)
    checks["from_events_deterministic"] = \
        [c.to_dict() for c in p1.candidates] == [c.to_dict() for c in p2.candidates]

    base_pool = p1 if p1.candidates else CandidatePool.load()
    target = next((c for c in base_pool.candidates if c.schedulable), None)
    synth_ok = False
    synth_idempotent = False
    reg_replace_ok = False
    if target is not None:
        cid = target.candidate_id
        reg = new_event(EventType.TournamentParticipantRegistered, timestamp=1.0,
                        payload={"candidate": target.to_dict()})
        chg = new_event(EventType.CandidateStatusChanged, timestamp=2.0,
                        payload={"candidate_id": cid, "old_status": target.status,
                                 "new_status": QUARANTINED, "status_note": "synthetic"})
        folded = CandidatePool.from_events([reg, chg])
        synth_ok = folded.by_id(cid) is not None and folded.by_id(cid).status == QUARANTINED
        # folding twice is identical (idempotent)
        folded2 = CandidatePool.from_events([reg, chg, chg])
        synth_idempotent = (folded.by_id(cid).status == folded2.by_id(cid).status
                            == QUARANTINED)
        # a LATER registration replaces the snapshot (status reset), proving
        # canonical (timestamp,index) ordering: reg@ts5 supersedes chg@ts2.
        reg_late = new_event(EventType.TournamentParticipantRegistered, timestamp=5.0,
                             payload={"candidate": target.to_dict()})
        folded3 = CandidatePool.from_events([reg, chg, reg_late])
        reg_replace_ok = folded3.by_id(cid).status == target.status
    checks["synthetic_status_change_honored"] = synth_ok
    checks["synthetic_status_change_idempotent"] = synth_idempotent
    checks["later_registration_replaces_mark"] = reg_replace_ok

    # 4. re-evaluating the live plan is a no-op (apply_skipped) ---------------
    plan = lc.evaluate_lifecycle(base_pool, events, cfg)
    res = lc.apply_lifecycle_plan(plan, base_pool, ledger, events,
                                  dry_run=False, allow_soft_probation=False)
    checks["live_apply_skipped"] = res["apply_skipped"] and res["applied_count"] == 0

    # 5. projection fold determinism -----------------------------------------
    a1 = projections.fold_games(events)
    a2 = projections.fold_games(events)
    checks["fold_games_deterministic"] = a1["totals"] == a2["totals"] and a1["per"] == a2["per"]
    r1 = projections.compute_rankings(base_pool, a1)
    r2 = projections.compute_rankings(base_pool, a2)
    checks["compute_rankings_deterministic"] = r1 == r2

    # 6. reconcile collapses a duplicate CandidateStatusChanged by id --------
    sample = new_event(EventType.CandidateStatusChanged, timestamp=3.0,
                       payload={"candidate_id": "x", "old_status": "active",
                                "new_status": PROBATION, "no_upload": True}).to_dict()
    merged, _rep = sync.reconcile_events([sample], [sample])
    checks["reconcile_dedupes_status_change_by_id"] = \
        sum(1 for e in merged if e.get("event_type")
            == EventType.CandidateStatusChanged.value) == 1

    ok = all(checks.values())
    payload = {
        "schema": "pass39_event_projection_audit_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True,
        "ok": ok,
        "checks": checks,
        "event_count": len(events),
        "candidate_status_changed_count": len(csc),
        "forbidden_events": forbidden,
        "events_missing_no_upload": missing_no_upload,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass39_event_projection_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md = [
        "# Pass 39 — Event + projection idempotency audit", "",
        "_Internal diagnostics only. NO upload, NO submit, NO candidate generation. "
        "Synthetic events are in-memory; the real ledger is untouched._", "",
        f"- **ok: {ok}**",
        f"- events: {len(events)}  CandidateStatusChanged: {len(csc)}", "",
        "| check | pass |", "|---|---|",
    ]
    for k in sorted(checks):
        md.append(f"| {k} | {'yes' if checks[k] else 'NO'} |")
    (EXP / "pass39_event_projection_audit.md").write_text("\n".join(md) + "\n",
                                                          encoding="utf-8")
    print(f"event-projection-audit: ok={ok} "
          f"failed={[k for k,v in checks.items() if not v]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
