"""Pass 39 — candidate lifecycle manager v0 + CandidateStatusChanged folding.

Pure in-memory tests (no storage, no network, no real ledger writes except one
tmp-path ledger test). They assert the lifecycle policy, the new
``CandidatePool.from_events`` folding of ``CandidateStatusChanged``, the apply
idempotency/skip semantics, and the scheduler's never-schedule defence in depth.
"""
from __future__ import annotations

import dataclasses

import pytest

from ptcg_activegraph.graph.events import EventType, new_event
from ptcg_activegraph.tournament import lifecycle as lc
from ptcg_activegraph.tournament import projections
from ptcg_activegraph.tournament.config import load_config
from ptcg_activegraph.tournament.ledger import TournamentLedger
from ptcg_activegraph.tournament.pool import (
    ACTIVE,
    HELD_PROBE,
    PROBATION,
    QUARANTINED,
    RETIRED,
    Candidate,
    CandidatePool,
)
from ptcg_activegraph.tournament.scheduler import build_worklist


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def cand(cid, family="f", status=ACTIVE, parent=None, tags=None) -> Candidate:
    return Candidate(candidate_id=cid, family_id=family, status=status,
                     parent_candidate_id=parent, tags=list(tags or []))


def reg(c: Candidate, ts: float):
    return new_event(EventType.TournamentParticipantRegistered, timestamp=ts,
                     payload={"candidate": c.to_dict()})


def chg(cid, old, new, ts, note="n"):
    return new_event(EventType.CandidateStatusChanged, timestamp=ts,
                     payload={"candidate_id": cid, "old_status": old,
                              "new_status": new, "status_note": note})


def gf(a, b, result, ts=1.0):
    return new_event(EventType.GameFinished, timestamp=ts,
                     payload={"candidate_a": a, "candidate_b": b, "result": result})


def cfg_threshold(n: int):
    return dataclasses.replace(load_config(), min_placement_games_per_candidate=n)


class FakeLedger:
    """Captures emits without touching disk; mirrors TournamentLedger.emit's no_upload."""

    def __init__(self):
        self.emitted = []

    def emit(self, event_type, payload, parent_event_ids=None, tags=None):
        body = {**payload, "no_upload": True}
        ev = new_event(event_type, payload=body,
                       parent_event_ids=list(parent_event_ids or []),
                       tags=list(tags or []))
        self.emitted.append(ev)
        return ev


# --------------------------------------------------------------------------- #
# from_events folding
# --------------------------------------------------------------------------- #
def test_from_events_folds_registration():
    pool = CandidatePool.from_events([reg(cand("a"), 1), reg(cand("b"), 2)])
    assert {c.candidate_id for c in pool.candidates} == {"a", "b"}


def test_from_events_folds_status_change():
    pool = CandidatePool.from_events([reg(cand("a"), 1), chg("a", ACTIVE, RETIRED, 2)])
    assert pool.by_id("a").status == RETIRED


def test_from_events_status_change_unknown_cid_ignored():
    pool = CandidatePool.from_events([reg(cand("a"), 1), chg("ghost", ACTIVE, RETIRED, 2)])
    assert pool.by_id("ghost") is None
    assert pool.by_id("a").status == ACTIVE


def test_from_events_invalid_status_ignored():
    # An invalid new_status must ignore the ENTIRE mark, including status_note.
    pool = CandidatePool.from_events(
        [reg(cand("a"), 1), chg("a", ACTIVE, "bogus", 2, note="should_not_apply")])
    a = pool.by_id("a")
    assert a.status == ACTIVE
    assert a.status_note != "should_not_apply"


def test_from_events_later_registration_replaces_mark():
    pool = CandidatePool.from_events(
        [reg(cand("a"), 1), chg("a", ACTIVE, RETIRED, 2), reg(cand("a"), 5)])
    assert pool.by_id("a").status == ACTIVE


def test_from_events_canonical_order_timestamp_then_index():
    # Supplied out of order; the latest-timestamp mark must win (probation@3 > retired@2).
    pool = CandidatePool.from_events(
        [chg("a", ACTIVE, PROBATION, 3), reg(cand("a"), 1), chg("a", ACTIVE, RETIRED, 2)])
    assert pool.by_id("a").status == PROBATION


def test_from_events_backward_compatible_without_status_events():
    only_reg = [reg(cand("a", status=HELD_PROBE), 1), reg(cand("b"), 2)]
    pool = CandidatePool.from_events(only_reg)
    assert pool.by_id("a").status == HELD_PROBE
    assert pool.by_id("b").status == ACTIVE


def test_from_events_status_note_updates():
    pool = CandidatePool.from_events(
        [reg(cand("a"), 1), chg("a", ACTIVE, RETIRED, 2, note="broken")])
    assert pool.by_id("a").status_note == "broken"


# --------------------------------------------------------------------------- #
# protection
# --------------------------------------------------------------------------- #
def test_protection_status():
    pool = CandidatePool([cand("a", status=HELD_PROBE)])
    assert lc.is_protected(pool.by_id("a"), pool)


def test_protection_tag():
    pool = CandidatePool([cand("a", tags=["live_control"])])
    reasons = lc.protection_reasons(pool.by_id("a"), pool)
    assert any(r.startswith("protected_tag:live_control") for r in reasons)


def test_protection_parent_of_active_child():
    pool = CandidatePool([cand("parent"), cand("child", parent="parent", status=ACTIVE)])
    reasons = lc.protection_reasons(pool.by_id("parent"), pool)
    assert any(r.startswith("parent_of_active_child:child") for r in reasons)


# --------------------------------------------------------------------------- #
# classification / evaluate
# --------------------------------------------------------------------------- #
def test_quarantine_all_invalid_no_decisive():
    pool = CandidatePool([cand("a"), cand("opp", status=HELD_PROBE)])
    events = [reg(cand("a"), 1), reg(cand("opp", status=HELD_PROBE), 1)]
    events += [gf("a", "opp", "invalid", ts=t) for t in (2, 3, 4)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.QUARANTINE and a["auto_apply_default"] is True


def test_quarantine_high_invalid_rate():
    pool = CandidatePool([cand("a"), cand("opp", status=HELD_PROBE)])
    events = [reg(cand("a"), 1), reg(cand("opp", status=HELD_PROBE), 1)]
    events += [gf("a", "opp", "invalid", 2), gf("a", "opp", "invalid", 3),
               gf("a", "opp", "win", 4), gf("a", "opp", "loss", 5)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.QUARANTINE and a["reason"] == "high_invalid_rate"


def test_invalid_plus_draws_below_rate_not_quarantined():
    # 3 invalid + 4 draws => 0 decisive but NOT all-invalid (draws present), and
    # invalid_rate 3/7 < 0.5 => must NOT auto-quarantine (regression guard).
    pool = CandidatePool([cand("a"), cand("opp", status=HELD_PROBE)])
    events = [reg(cand("a"), 1), reg(cand("opp", status=HELD_PROBE), 1)]
    events += [gf("a", "opp", "invalid", ts=t) for t in (2, 3, 4)]
    events += [gf("a", "opp", "draw", ts=t) for t in (5, 6, 7, 8)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.RETAIN
    assert a["proposed_status"] == ACTIVE


def test_under_sampled_active_is_soft_probation_not_quarantine():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1), gf("a", "x", "invalid", 2), gf("a", "x", "invalid", 3)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(20))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.ELIGIBLE_SOFT_PROBATION
    assert a["auto_apply_default"] is False


def test_protected_active_never_quarantined():
    # held_probe with all-invalid evidence stays retained (protection beats quarantine).
    pool = CandidatePool([cand("a", status=HELD_PROBE)])
    events = [reg(cand("a", status=HELD_PROBE), 1)]
    events += [gf("a", "x", "invalid", ts=t) for t in (2, 3, 4)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.RETAIN and a["protected"] is True


def test_well_sampled_active_retained():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1)]
    events += [gf("a", "x", "win", ts=t) for t in range(2, 6)]  # 4 decisive, 0 invalid
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(3))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.RETAIN


def test_never_schedule_status_retained():
    pool = CandidatePool([cand("a", status=RETIRED)])
    plan = lc.evaluate_lifecycle(pool, [reg(cand("a", status=RETIRED), 1)], cfg_threshold(2))
    a = next(x for x in plan["actions"] if x["candidate_id"] == "a")
    assert a["action"] == lc.RETAIN
    assert a["reason"].startswith("never_schedule_status_retained")


def test_evaluate_summary_counts_consistent():
    pool = CandidatePool([cand("a"), cand("b", status=HELD_PROBE), cand("c", status=RETIRED)])
    plan = lc.evaluate_lifecycle(pool, [reg(c, 1) for c in pool.candidates], cfg_threshold(20))
    s = plan["summary"]
    assert sum(s["action_counts"].values()) == len(pool.candidates) == 3
    assert s["protected"] == 1  # the held_probe


# --------------------------------------------------------------------------- #
# apply semantics
# --------------------------------------------------------------------------- #
def test_apply_dry_run_emits_nothing():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1)] + [gf("a", "x", "invalid", ts=t) for t in (2, 3, 4)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    led = FakeLedger()
    res = lc.apply_lifecycle_plan(plan, pool, led, events, dry_run=True)
    assert res["applied_count"] == 0 and led.emitted == []


def test_apply_real_quarantine_emits_and_mutates_pool():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1)] + [gf("a", "x", "invalid", ts=t) for t in (2, 3, 4)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(2))
    led = FakeLedger()
    res = lc.apply_lifecycle_plan(plan, pool, led, events, dry_run=False)
    assert res["applied_count"] == 1
    assert pool.by_id("a").status == QUARANTINED
    assert len(led.emitted) == 1
    assert led.emitted[0].payload["no_upload"] is True


def test_apply_idempotent_old_equals_new():
    pool = CandidatePool([cand("a", status=QUARANTINED)])
    plan = {"actions": [{"candidate_id": "a", "current_status": QUARANTINED,
                         "proposed_status": QUARANTINED, "action": lc.QUARANTINE,
                         "reason": "x", "evidence": {}}]}
    led = FakeLedger()
    res = lc.apply_lifecycle_plan(plan, pool, led, [], dry_run=False)
    assert res["applied_count"] == 0 and res["apply_skipped"] is True
    assert len(res["skipped_idempotent"]) == 1 and led.emitted == []


def test_apply_skipped_when_no_applicable():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1)]  # under-sampled active -> soft probation only
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(20))
    led = FakeLedger()
    res = lc.apply_lifecycle_plan(plan, pool, led, events, dry_run=False,
                                  allow_soft_probation=False)
    assert res["applicable_count"] == 0 and res["apply_skipped"] is True
    assert "No safe" in res["explanation"] and led.emitted == []


def test_soft_probation_applied_when_opted_in():
    pool = CandidatePool([cand("a")])
    events = [reg(cand("a"), 1)]
    plan = lc.evaluate_lifecycle(pool, events, cfg_threshold(20))
    led = FakeLedger()
    res = lc.apply_lifecycle_plan(plan, pool, led, events, dry_run=False,
                                  allow_soft_probation=True)
    assert res["applied_count"] == 1 and pool.by_id("a").status == PROBATION


# --------------------------------------------------------------------------- #
# scheduler defence in depth + real ledger no_upload
# --------------------------------------------------------------------------- #
def test_scheduler_never_schedules_quarantined():
    pool = CandidatePool([cand("a"), cand("q", status=QUARANTINED)])
    state = projections.build_scheduler_state([])
    wl = build_worklist(pool, state, cfg_threshold(20), max_games=20)
    appearing = {g.candidate_a for g in wl} | {g.candidate_b for g in wl}
    assert "q" not in appearing


def test_real_ledger_injects_no_upload(tmp_path):
    led = TournamentLedger(path=tmp_path / "events.jsonl")
    ev = led.emit(EventType.CandidateStatusChanged,
                  {"candidate_id": "a", "old_status": ACTIVE, "new_status": RETIRED})
    assert ev.payload["no_upload"] is True
    assert all(e.payload.get("no_upload") is True for e in led.load())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
