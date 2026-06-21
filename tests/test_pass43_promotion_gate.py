"""PASS 43 — Promotion Gate v1 + production-registration safety tests.

Covers the locked gate semantics (raw win-rate never promotes, sample-size minimums,
Wilson margins, seat balance, anchor non-inferiority, deck-delta requirement,
quarantine/retire, protected/never-schedule/public-reference handling), the apply
guardrails (no forbidden events, idempotency, no tarball deletion), scheduler/
lifecycle integration, manifest lockstep, and root immutability. Pure/in-memory —
no production mutation, no upload.
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pytest

from ptcg_activegraph.graph.events import Event, EventType
from ptcg_activegraph.tournament import promotion
from ptcg_activegraph.tournament.ledger import TournamentLedger
from ptcg_activegraph.tournament.pool import (ACTIVE, FAMILY_CHAMPION, HELD_PROBE,
                                              PORTFOLIO_ANCHOR, PROBATION,
                                              QUARANTINED, RETIRED,
                                              SPECIAL_PILOT_ONLY, Candidate,
                                              CandidatePool)
from ptcg_activegraph.tournament.promotion import (ACTIVATE, BLOCKED_INVALIDITY,
                                                   BLOCKED_PROTECTED_STATUS,
                                                   BLOCKED_PUBLIC_REFERENCE,
                                                   INSUFFICIENT_EVIDENCE,
                                                   PROMOTE_FAMILY_CHAMPION,
                                                   QUARANTINE, RETIRE_TO_RETIRED,
                                                   STAY_PROBATION,
                                                   DEFAULT_THRESHOLDS, classify,
                                                   build_evidence)

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"

TH = DEFAULT_THRESHOLDS


# -- synthetic event helpers -------------------------------------------------
def _game(a: str, b: str, result: str, i: int, *, invalid_kind: str | None = None,
          ts: float = 0.0) -> Event:
    payload = {"candidate_a": a, "candidate_b": b, "result": result,
               "game_id": f"g|{a}>{b}|{i}", "no_upload": True}
    if invalid_kind == "timeout":
        payload["timeout"] = True
    elif invalid_kind == "error":
        payload["error"] = "boom"
    return Event(event_type=EventType.GameFinished.value, payload=payload,
                 timestamp=ts)


def _h2h(c: str, opp: str, wins: int, losses: int, *, balance_seats: bool = True,
         start: int = 0) -> list[Event]:
    """`wins`/`losses` for `c` vs `opp`, alternating seats when balanced."""
    evs: list[Event] = []
    n = 0
    for k in range(wins):
        a, b, res = (c, opp, "win")
        if balance_seats and k % 2 == 1:
            a, b, res = (opp, c, "loss")  # c at seat b still wins
        evs.append(_game(a, b, res, start + n, ts=float(start + n)))
        n += 1
    for k in range(losses):
        a, b, res = (c, opp, "loss")
        if balance_seats and k % 2 == 1:
            a, b, res = (opp, c, "win")  # c at seat b loses
        evs.append(_game(a, b, res, start + n, ts=float(start + n)))
        n += 1
    return evs


def _pool(cands: list[Candidate]) -> CandidatePool:
    return CandidatePool(cands, tournament_id="t_test")


def _ev_for(pool, events, cid, **kw):
    evs = build_evidence(pool, events, **kw)
    return next(e for e in evs if e.candidate_id == cid)


def _strong_activate_events(c="cand", parent="par", anchor="anc", other="oth"):
    evs = []
    evs += _h2h(c, parent, 18, 6)         # 24 H2H, seat-balanced
    evs += _h2h(c, anchor, 16, 4)         # 20 anchor games, decisive
    evs += _h2h(c, other, 8, 2)           # padding -> total 54
    return evs


# -- 1. root immutability ----------------------------------------------------
def test_root_main_py_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_csv_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# -- 2-4. status-based blocks -------------------------------------------------
def test_public_reference_blocked():
    pool = _pool([Candidate(candidate_id="public_ref_x", family_id="f",
                            status=PROBATION)])
    ev = _ev_for(pool, [], "public_ref_x", reference_ids={"public_ref_x"})
    assert classify(ev)["action"] == BLOCKED_PUBLIC_REFERENCE
    assert classify(ev)["actionable"] is False


def test_special_pilot_only_blocked_invalidity():
    pool = _pool([Candidate(candidate_id="sp", family_id="f",
                            status=SPECIAL_PILOT_ONLY)])
    ev = _ev_for(pool, [], "sp", reference_ids=set())
    assert classify(ev)["action"] == BLOCKED_INVALIDITY


def test_retired_and_quarantined_blocked_invalidity():
    pool = _pool([Candidate(candidate_id="r", family_id="f", status=RETIRED),
                  Candidate(candidate_id="q", family_id="f", status=QUARANTINED)])
    for cid in ("r", "q"):
        ev = _ev_for(pool, [], cid, reference_ids=set())
        assert classify(ev)["action"] == BLOCKED_INVALIDITY


def test_protected_never_demoted_even_with_bad_record():
    # a protected candidate that loses everything is still never demoted
    pool = _pool([Candidate(candidate_id="champ", family_id="f",
                            status=FAMILY_CHAMPION)])
    evs = _h2h("champ", "rival", 0, 40)
    ev = _ev_for(pool, evs, "champ", reference_ids=set())
    assert classify(ev)["action"] == BLOCKED_PROTECTED_STATUS


def test_held_probe_and_anchor_protected():
    pool = _pool([Candidate(candidate_id="hp", family_id="f", status=HELD_PROBE),
                  Candidate(candidate_id="pa", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    for cid in ("hp", "pa"):
        ev = _ev_for(pool, [], cid, reference_ids=set())
        assert classify(ev)["action"] == BLOCKED_PROTECTED_STATUS


# -- 5. probation with no games ----------------------------------------------
def test_probation_no_games_insufficient_evidence():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="p")])
    ev = _ev_for(pool, [], "c", reference_ids=set())
    assert classify(ev)["action"] == INSUFFICIENT_EVIDENCE


# -- 6-8. registration/visibility artifacts ----------------------------------
def test_visibility_audit_detects_local_only():
    data = json.loads((EXP / "pass43_probation_visibility_audit.json").read_text())
    blob = json.dumps(data)
    assert "local_only_needs_republish" in blob


def test_registration_refuses_unsafe_apply_skipped():
    data = json.loads((EXP / "pass43_production_probation_registration.json").read_text())
    assert data["apply_skipped"] is True
    assert data["guardrails"]["production_mutated"] is False


def test_deployment_decision_is_fail_closed_on_prod_mutation():
    # Safety invariant (survives the Pass-44 republish that flipped this SHARED
    # artifact to case_1): production mutation is only ever permitted once the
    # tarballs are proven present in the deploy image. While a republish is still
    # required, the decision MUST fail closed (no prod mutation).
    data = json.loads((EXP / "pass43_deployment_availability_decision.json").read_text())
    dec = data["decision"]
    if dec.get("republish_required"):
        assert dec["mutate_prod_os"] is False
    if dec["mutate_prod_os"] is True:
        # mutation only with a deploy-visible case and never while stopped
        assert str(data["case"]).startswith("case_1")
        assert dec.get("republish_required") is False
        assert dec.get("stop") is False


# -- 9. dry-run / evaluate is pure -------------------------------------------
def test_evaluate_emits_no_events_and_is_pure():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION)])
    before = list_pool_state(pool)
    out = promotion.evaluate(pool, [], reference_ids=set())
    assert out["n_actionable"] == 0
    assert list_pool_state(pool) == before  # pool object untouched


def list_pool_state(pool):
    return [(c.candidate_id, c.status) for c in pool.candidates]


# -- 10-11. sample size gates ------------------------------------------------
def test_insufficient_total_games():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="p")])
    evs = _h2h("c", "p", 8, 2)  # only 10 games -> below 40
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    assert classify(ev)["action"] == INSUFFICIENT_EVIDENCE


def test_insufficient_anchor_games():
    # enough total/decisive/parent but no anchor games -> insufficient
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="p")])
    evs = _h2h("c", "p", 30, 14)  # 44 H2H, decisive, but anchor_games == 0
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["action"] == INSUFFICIENT_EVIDENCE
    assert res["checks"]["enough_anchor"] is False


# -- 12-13. Wilson margin / raw win-rate -------------------------------------
def test_wilson_lower_bound_must_clear_baseline_margin():
    # full evidence but ~52% raw WR -> Wilson lower bound below 0.53 -> stay
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _h2h("c", "par", 13, 11)      # 24 H2H
    evs += _h2h("c", "anc", 11, 9, start=100)   # 20 anchor games ~0.55
    evs += _h2h("c", "oth", 5, 5, start=300)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["enough_total"] and res["checks"]["enough_decisive"]
    assert res["checks"]["wilson_clears_parent_baseline"] is False
    assert res["action"] == STAY_PROBATION


def test_noisy_high_raw_winrate_small_n_cannot_promote():
    # 100% raw win rate but tiny N -> blocked by sample size, never activate
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="p")])
    evs = _h2h("c", "p", 6, 0)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    assert ev.win_rate == 1.0
    assert classify(ev)["action"] == INSUFFICIENT_EVIDENCE


def test_high_aggregate_winrate_but_loses_parent_h2h_stays_probation():
    # The aggregate Wilson bound clears the baseline (the candidate farms wins vs
    # weak opponents), but it LOSES head-to-head to its parent. Activation must
    # require direct parent-H2H superiority, so this stays on probation.
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _h2h("c", "par", 8, 16)                  # LOSES parent H2H badly
    evs += _h2h("c", "anc", 18, 2, start=200)      # strong vs anchor
    evs += _h2h("c", "oth", 30, 2, start=400)      # farms weak opponents
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["enough_parent_h2h"] is True
    assert res["checks"]["wilson_clears_parent_baseline"] is True   # aggregate strong
    assert res["checks"]["parent_h2h_superiority"] is False         # but loses parent
    assert res["action"] == STAY_PROBATION
    assert res["actionable"] is False


# -- 14. invalid/error rate blocks activation --------------------------------
def test_high_hardfail_rate_blocks_activation():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _strong_activate_events("c", "par", "anc", "oth")
    # add ~10% invalid games -> exceeds max_hardfail_rate 0.05
    for i in range(8):
        evs.append(_game("c", "x", "invalid", 900 + i, invalid_kind="error"))
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["hardfail_ok"] is False
    assert res["action"] in (INSUFFICIENT_EVIDENCE, QUARANTINE)
    assert res["action"] != ACTIVATE


# -- 15. activate happy path (positive control) ------------------------------
def test_activate_happy_path():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _strong_activate_events("c", "par", "anc", "oth")
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["action"] == ACTIVATE
    assert res["actionable"] is True


# -- 16. deck-delta / non-inertness required ---------------------------------
def test_activate_requires_deck_delta_or_noninert():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _strong_activate_events("c", "par", "anc", "oth")
    # no non_inert flag and no CandidateGenerated deck-delta -> cannot activate
    ev = _ev_for(pool, evs, "c", reference_ids=set())
    res = classify(ev)
    assert res["checks"]["deck_delta_or_noninert_proven"] is False
    assert res["action"] == STAY_PROBATION


# -- 17. anchor non-inferiority required -------------------------------------
def test_activate_requires_anchor_noninferiority():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _h2h("c", "par", 22, 2)                 # crushes parent
    evs += _h2h("c", "anc", 4, 12, start=200)     # but loses badly to anchor
    evs += _h2h("c", "oth", 8, 2, start=400)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["anchor_noninferior"] is False
    assert res["action"] == STAY_PROBATION


# -- 18. seat balance required -----------------------------------------------
def test_activate_requires_seat_balance():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _h2h("c", "par", 18, 6, balance_seats=False)   # all one seat
    evs += _h2h("c", "anc", 16, 4, start=200)
    evs += _h2h("c", "oth", 8, 2, start=400)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["seat_balanced"] is False
    assert res["action"] == INSUFFICIENT_EVIDENCE


# -- 19. benchmark collapse is diagnostic only -------------------------------
def test_activation_independent_of_external_benchmark():
    # the gate uses only internal evidence; there is no benchmark field that can
    # block a candidate meeting all internal gates.
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _strong_activate_events("c", "par", "anc", "oth")
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    fields = set(ev.to_dict().keys())
    assert not any("benchmark" in f for f in fields)
    assert classify(ev)["action"] == ACTIVATE


# -- 20. family-champion stricter gate ---------------------------------------
def test_family_champion_gate_stricter_than_activate():
    # an active candidate meeting activate-level but not champion-level N
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=ACTIVE,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR),
                  Candidate(candidate_id="oldchamp", family_id="f",
                            status=FAMILY_CHAMPION)])
    evs = _strong_activate_events("c", "par", "anc", "oth")   # ~54 games < 80
    evs += _h2h("oldchamp", "x", 10, 10, start=500)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["action"] == INSUFFICIENT_EVIDENCE
    assert res["checks"]["champ_total"] is False


def test_family_champion_promotion_when_strong():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=ACTIVE,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR),
                  Candidate(candidate_id="oldchamp", family_id="f",
                            status=FAMILY_CHAMPION)])
    evs = _h2h("c", "par", 40, 8)                  # large N, strong
    evs += _h2h("c", "anc", 20, 4, start=200)
    evs += _h2h("c", "fampeer", 15, 5, start=400)  # family games
    evs += _h2h("oldchamp", "x", 10, 12, start=600)  # weak champion baseline
    evs += _h2h("c", "oldchamp", 22, 2, start=800)   # BEATS the incumbent H2H
    pool.candidates.append(Candidate(candidate_id="fampeer", family_id="f",
                                     status=ACTIVE))
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["champ_baseline_exists"] is True
    assert res["checks"]["champ_h2h_ok"] is True
    assert res["action"] == PROMOTE_FAMILY_CHAMPION


def test_active_strong_aggregate_but_loses_champion_h2h_not_promoted():
    # the aggregate margin gate would pass, but the candidate LOSES head-to-head to
    # the incumbent champion -> the direct champion-H2H superiority gate blocks it.
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=ACTIVE,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR),
                  Candidate(candidate_id="oldchamp", family_id="f",
                            status=FAMILY_CHAMPION)])
    evs = _h2h("c", "par", 40, 8)
    evs += _h2h("c", "anc", 20, 4, start=200)
    evs += _h2h("c", "fampeer", 15, 5, start=400)
    evs += _h2h("c", "oldchamp", 10, 14, start=600)   # LOSES H2H to the champion
    evs += _h2h("oldchamp", "y", 2, 12, start=900)    # champion weak overall
    pool.candidates.append(Candidate(candidate_id="fampeer", family_id="f",
                                     status=ACTIVE))
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"]["champ_margin_ok"] is True       # aggregate gate would pass
    assert res["checks"]["champ_h2h_ok"] is False         # but loses the incumbent H2H
    assert res["action"] == INSUFFICIENT_EVIDENCE
    assert "champ_h2h_ok" in res["reasons"][0]


# -- 21-22. quarantine -------------------------------------------------------
def test_quarantine_only_on_complete_hardfail():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION)])
    evs = [_game("c", "x", "invalid", i, invalid_kind="error") for i in range(12)]
    ev = _ev_for(pool, evs, "c", reference_ids=set())
    assert classify(ev)["action"] == QUARANTINE


def test_draws_only_is_not_quarantine():
    # all draws -> decisive==0 but NOT a hard failure -> not quarantine
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="p")])
    evs = [_game("c", "p", "draw", i) for i in range(12)]
    ev = _ev_for(pool, evs, "c", reference_ids=set())
    res = classify(ev)
    assert res["action"] != QUARANTINE
    assert res["action"] == INSUFFICIENT_EVIDENCE


# -- 23. retire path ---------------------------------------------------------
def test_retire_when_clearly_worse_with_full_evidence():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION,
                            parent_candidate_id="par"),
                  Candidate(candidate_id="anc", family_id="f",
                            status=PORTFOLIO_ANCHOR)])
    evs = _h2h("c", "par", 5, 19)                  # 24 H2H, ~21% WR
    evs += _h2h("c", "anc", 4, 16, start=200)      # anchor decisive
    evs += _h2h("c", "oth", 2, 8, start=400)
    ev = _ev_for(pool, evs, "c", reference_ids=set(), non_inert_ids={"c"})
    res = classify(ev)
    assert res["checks"].get("clearly_worse_than_parent") is True
    assert res["action"] == RETIRE_TO_RETIRED


# -- 24. no tarball deletion in source --------------------------------------
def test_promotion_module_never_deletes_tarballs():
    src = (REPO / "src" / "ptcg_activegraph" / "tournament" / "promotion.py").read_text()
    runner = (REPO / "scripts" / "run_tournament_promotion_gate.py").read_text()
    for blob in (src, runner):
        assert "unlink" not in blob
        assert "rmtree" not in blob
        assert "os.remove" not in blob
        assert ".tar.gz" not in blob  # never references tarball files at all


# -- 25. CandidateStatusChanged folds correctly ------------------------------
def test_status_change_folds_via_from_events():
    reg = Event(event_type=EventType.TournamentParticipantRegistered.value,
                payload={"candidate": {"candidate_id": "c", "family_id": "f",
                                       "status": PROBATION}}, timestamp=1.0)
    chg = Event(event_type=EventType.CandidateStatusChanged.value,
                payload={"candidate_id": "c", "new_status": ACTIVE,
                         "status_note": "x"}, timestamp=2.0)
    pool = CandidatePool.from_events([reg, chg])
    assert pool.by_id("c").status == ACTIVE


# -- 26-27. apply behaviour --------------------------------------------------
def test_apply_no_op_when_no_eligible_recs():
    pool = _pool([Candidate(candidate_id="c", family_id="f", status=PROBATION)])
    evaluation = promotion.evaluate(pool, [], reference_ids=set())
    assert promotion.recommended_status_changes(evaluation) == []


def test_apply_artifact_reports_skipped():
    data = json.loads((EXP / "pass43_promotion_gate_apply.json").read_text())
    assert data["apply_skipped"] is True
    assert data["guardrails"]["mutated_production"] is False
    assert data["guardrails"]["no_kaggle_or_promotion_events"] is True


# -- 28. forbidden events -----------------------------------------------------
def test_ledger_refuses_forbidden_upload_events(tmp_path):
    # Use an ISOLATED ledger path: the standing-tournament ledger refuses every
    # upload/submit/Kaggle-queue/promotion event at emit time. The tournament
    # engine expresses lifecycle purely via CandidateStatusChanged, so none of
    # these have a legitimate producer on this ledger.
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    for et in ("SubmissionUploaded", "KaggleScoreUpdated", "SubmissionQueued",
               "CandidatePromoted"):
        with pytest.raises(PermissionError):
            ledger.emit(et, {"x": 1})
    assert len(ledger.load()) == 0  # refused emits never appended


def test_ledger_allows_status_change_but_not_promotion(tmp_path):
    # CandidateStatusChanged is the legitimate lifecycle event; CandidatePromoted
    # (a Kaggle-promotion marker) is refused even though both are "promotions".
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    ledger.emit(EventType.CandidateStatusChanged.value,
                {"candidate_id": "c", "new_status": ACTIVE})
    assert len(ledger.load()) == 1
    with pytest.raises(PermissionError):
        ledger.emit(EventType.CandidatePromoted.value, {"candidate_id": "c"})
    assert len(ledger.load()) == 1  # promotion event never appended


def test_no_forbidden_events_in_pass43_artifacts():
    forbidden = ("SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                 "CandidatePromoted")
    for name in ("pass43_promotion_gate_dry_run.json",
                 "pass43_promotion_gate_apply.json",
                 "pass43_production_probation_registration.json"):
        blob = (EXP / name).read_text()
        for f in forbidden:
            assert f not in blob, f"{f} found in {name}"


# -- 29. scheduler integration / determinism ---------------------------------
def test_scheduler_integration_audit_passes():
    data = json.loads((EXP / "pass43_scheduler_promotion_integration.json").read_text())
    assert data["ok"] is True
    assert data["checks"]["worklist_unchanged_by_gate"] is True
    assert data["checks"]["scheduler_deterministic"] is True
    assert data["checks"]["no_reference_in_worklist"] is True


# -- 30. manifest lockstep ----------------------------------------------------
def test_local_storage_manifest_event_count_lockstep():
    tdir = REPO / "data" / "tournament"
    manifest = json.loads((tdir / "storage_manifest.json").read_text())
    ledger = TournamentLedger(path=tdir / "events.jsonl")
    assert manifest["event_count"] == len(ledger.load())
    assert manifest["no_upload"] is True
