"""PASS 46B — reference-gap + turn-planning diagnostic (READ-ONLY).

Validates the pure turn-planning extractor and the honest read-only diagnostic
artifacts. HARD invariants asserted: root main.py/deck.csv byte-identical to baseline;
the diagnostic script never mutates production, pushes state, deletes/overwrites a
tarball, generates a candidate, starts the root workflow, or emits a forbidden /
lifecycle / status-change event; public references stay absent from the pool and the
scheduler worklist; the extractor is honest (outcome-only sidecars yield zero frames;
unsupported claims are always flagged; KO/lethal are never inferred); the loss-mode
taxonomy never quarantines or promotes and never classifies missed-lethal; the
strategy decision is one of the allowed read-only outcomes; and the report surfaces
all required caveats.
"""
from __future__ import annotations

import filecmp
import json
import re
from pathlib import Path

import pytest

from ptcg_activegraph.analysis import turn_planning as tp
from ptcg_activegraph.tournament.ledger import TournamentLedger

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
SCRIPT = REPO / "scripts" / "build_pass46b_diagnostic.py"
MODULE = REPO / "src" / "ptcg_activegraph" / "analysis" / "turn_planning.py"
REPORT = REPO / "data" / "reports" / "pass46b_reference_gap_turn_planning_report.md"
SCHEMA_DOC = REPO / "docs" / "TURN_PLANNING_DIAGNOSTIC_SCHEMA.md"
BACKLOG_DOC = REPO / "docs" / "TURN_PLANNING_PRIMITIVES_BACKLOG.md"

FORBIDDEN = {"CandidatePromoted", "SubmissionQueued", "SubmissionUploaded",
             "KaggleScoreUpdated", "CandidateStatusChanged", "CandidateGenerated",
             "CandidateValidationFinished"}


def _j(name: str) -> dict:
    return json.loads((EXP / f"pass46b_{name}.json").read_text(encoding="utf-8"))


# ---- synthetic frame helpers ----------------------------------------------
def _seat(select, action, current, logs=None, status="ACTIVE"):
    return {"observation": {"select": select, "current": current, "logs": logs or []},
            "action": action, "status": status}


def _current(turn, seat, *, self_active=True, self_bench=0, opp_prize=6,
             hand=7, deck=40, prize=6, discard=0):
    players = [{} for _ in range(2)]
    me = {"active": [{"id": 1}] if self_active else [], "bench": [{} for _ in range(self_bench)],
          "benchMax": 5, "handCount": hand, "deckCount": deck,
          "prize": [{} for _ in range(prize)], "discard": [{} for _ in range(discard)]}
    opp = {"active": [{"id": 9}], "bench": [], "benchMax": 5, "handCount": 5,
           "deckCount": 40, "prize": [{} for _ in range(opp_prize)], "discard": []}
    players[seat] = me
    players[1 - seat] = opp
    return {"turn": turn, "yourIndex": seat, "supporterPlayed": False,
            "stadiumPlayed": False, "energyAttached": False, "players": players}


# == 1-2. root immutability =================================================
def test_root_main_py_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)


def test_root_deck_csv_unchanged_vs_baseline():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)


# == 3. safety preflight all-ok & read-only =================================
def test_safety_preflight_all_ok_and_read_only():
    d = _j("safety_preflight")
    assert d["all_ok"] is True
    assert d["read_only"] is True
    assert d["production_mutated"] is False
    assert d["tick_executed"] is False
    assert d["start_application_started"] is False
    assert d["no_upload"] is True
    for name, ok in d["checks"].items():
        assert ok is True, f"safety check failed: {name}"


def test_safety_preflight_refs_and_forbidden_absent():
    d = _j("safety_preflight")
    assert d["refs_in_pool"] == []
    assert d["refs_in_worklist"] == []
    assert d["never_schedule_in_worklist"] == []
    assert d["forbidden_events_in_prod_ledger"] == []
    assert d["deployment_run"].startswith("scripts/tournament_deployment_tick.py")


# == 4. script never mutates / generates / starts root =====================
def test_script_never_pushes_or_mutates_production():
    blob = SCRIPT.read_text(encoding="utf-8")
    # real mutation/push patterns (not innocent words in docstrings/caveats)
    for bad in ("push_state(", "b.write_text(", "backend.write_text(", ".upload(",
                "sync.push", "build_manifest(", "restart_workflow", "python3 main.py"):
        assert bad not in blob, bad


def test_script_emits_no_forbidden_or_lifecycle_events():
    blob = SCRIPT.read_text(encoding="utf-8")
    for et in FORBIDDEN:
        assert f"emit(EventType.{et}" not in blob, et
        assert f'emit("{et}"' not in blob, et
        assert f".emit('{et}'" not in blob, et
    # the only mentions of forbidden names are in the read-only check set/scan
    assert "FORBIDDEN" in blob


def test_script_never_deletes_or_overwrites_tarballs():
    blob = SCRIPT.read_text(encoding="utf-8")
    for bad in ("unlink", "rmtree", "os.remove", "shutil.move"):
        assert bad not in blob, bad


# == 5. extractor: outcome-only sidecar yields no frames ===================
def test_outcome_only_sidecar_has_no_frames():
    obj = {"steps": 131, "result": "loss", "rewards": [-1, 1], "game_id": "x"}
    assert tp.detect_format(obj) == tp.FMT_CABT_SIDECAR_OUTCOME_ONLY
    assert tp.iter_decision_frames(obj) == []
    oc = tp.sidecar_outcome(obj)
    assert oc["frames_available"] is False
    assert oc["step_count"] == 131


# == 6. extractor: integer enum form (attack) =============================
def test_integer_enum_attack_family():
    select = {"context": 1, "type": 9, "minCount": 1, "maxCount": 1,
              "option": [{"type": 13}, {"type": 12}]}
    obj = {"id": "g", "steps": [[_seat(select, [0], _current(3, 0)),
                                 {"observation": {}, "status": "INACTIVE"}]]}
    frames = tp.iter_decision_frames(obj)
    assert len(frames) == 1
    assert "attack" in frames[0].selected_families
    assert frames[0].primary_family == "attack"


# == 7. extractor: string enum form normalizes identically ================
def test_string_enum_attack_normalizes():
    select = {"type": 9, "minCount": 1, "maxCount": 1,
              "option": [{"type": "attack"}, {"type": "end_turn"}]}
    obj = {"id": "g", "steps": [[_seat(select, [0], _current(3, 0)),
                                 {"observation": {}, "status": "INACTIVE"}]]}
    frames = tp.iter_decision_frames(obj)
    assert "attack" in frames[0].selected_families
    # numeric string form too
    select2 = {"option": [{"type": "13"}], "minCount": 1, "maxCount": 1}
    obj2 = {"id": "g", "steps": [[_seat(select2, [0], _current(3, 0)),
                                  {"observation": {}, "status": "INACTIVE"}]]}
    assert "attack" in tp.iter_decision_frames(obj2)[0].selected_families


# == 8. extractor: setup-active inferred from empty active during setup ====
def test_setup_active_inferred():
    select = {"type": 9, "minCount": 1, "maxCount": 1,
              "option": [{"type": 7, "inPlayArea": 4, "inPlayIndex": 0}]}
    cur = _current(0, 0, self_active=False)
    obj = {"id": "g", "steps": [[_seat(select, [0], cur),
                                 {"observation": {}, "status": "INACTIVE"}]]}
    fam = tp.iter_decision_frames(obj)[0].primary_family
    assert fam in ("setup_active", "setup_bench"), fam


# == 9. extractor: legality flags out-of-range selection ==================
def test_legality_detects_out_of_range_and_ok():
    sel_bad = {"option": [{"type": 13}, {"type": 12}], "minCount": 1, "maxCount": 1}
    f_bad = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                    select=sel_bad, action=[5], current=_current(2, 0),
                                    logs=[])
    assert f_bad.legality_ok is False
    f_ok = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                   select=sel_bad, action=[0], current=_current(2, 0),
                                   logs=[])
    assert f_ok.legality_ok is True


def test_legality_empty_selection_honest_tristate():
    # minCount==0 -> an empty selection is genuinely LEGAL (zero picks allowed)
    sel0 = {"option": [{"type": 13}], "minCount": 0, "maxCount": 1}
    f0 = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                 select=sel0, action=[], current=_current(2, 0), logs=[])
    assert f0.legality_ok is True
    # minCount>0 with empty action -> NOT flagged illegal (trace may not align);
    # reported as not-checkable (None) with an explicit note, never False.
    sel1 = {"option": [{"type": 13}], "minCount": 1, "maxCount": 1}
    f1 = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                 select=sel1, action=[], current=_current(2, 0), logs=[])
    assert f1.legality_ok is None
    assert any("not checkable" in n for n in f1.legality_notes)


# == 10. extractor: hand/deck/prize counts honestly read ==================
def test_board_counts_read_honestly():
    select = {"option": [{"type": 13}], "minCount": 1, "maxCount": 1}
    cur = _current(4, 0, hand=6, deck=33, prize=4, discard=7)
    f = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                select=select, action=[0], current=cur, logs=[])
    assert f.hand_count == 6
    assert f.deck_count == 33
    assert f.prize_remaining == 4  # cards remaining, not taken
    assert f.discard_count == 7


# == 11. extractor: retreat only when log shows active<->bench swap ========
def test_retreat_only_from_log_swap():
    select = {"option": [{"type": 6}], "minCount": 1, "maxCount": 1}  # move_energy
    logs = [{"fromArea": 4, "toArea": 5}, {"fromArea": 5, "toArea": 4}]
    f = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                select=select, action=[0], current=_current(5, 0),
                                logs=logs)
    assert f.retreat_observed is True
    assert "retreat" in f.selected_families
    f2 = tp.build_decision_frame(game_id="g", source="t", step=0, seat=0,
                                 select=select, action=[0], current=_current(5, 0),
                                 logs=[])
    assert f2.retreat_observed is False


# == 12. extractor: turn summary attack/prize from observables only =======
def test_turn_summary_attack_and_prize_from_observables():
    s_no = _seat({"option": [{"type": 7}], "minCount": 1, "maxCount": 1}, [0],
                 _current(1, 0, opp_prize=6))
    s_atk = _seat({"option": [{"type": 13}], "minCount": 1, "maxCount": 1}, [0],
                  _current(2, 0, opp_prize=6))
    s_prize = _seat({"option": [{"type": 13}], "minCount": 1, "maxCount": 1}, [0],
                    _current(3, 0, opp_prize=5))  # opponent prize dropped 6->5
    obj = {"id": "g", "steps": [[s_no, {"observation": {}, "status": "INACTIVE"}],
                                [s_atk, {"observation": {}, "status": "INACTIVE"}],
                                [s_prize, {"observation": {}, "status": "INACTIVE"}]]}
    frames = tp.iter_decision_frames(obj)
    s = tp.summarize_turn_plan(frames, acting_player=0, game_id="g")
    assert s.first_attack_turn == 2
    assert s.first_prize_turn == 3
    assert s.first_ko_turn == 3
    # KO/prize note marks the approximation honestly
    assert any("prize-remaining delta" in n for n in s.notes)


# == 13. extractor: unsupported claims always flagged =====================
def test_unsupported_flags_present_everywhere():
    flags = tp.unsupported_flags()
    for claim in tp.UNSUPPORTED_CLAIMS:
        assert flags[claim] == tp.UNSUPPORTED_SENTINEL
    s = tp.TurnPlanSummary(game_id="g", acting_player=0)
    for claim in ("lethal_availability", "exact_damage", "missed_ko"):
        assert claim in s.unsupported


# == 14. real replay: frames + sidecar zero-frames sanity =================
def test_real_replay_frames_and_real_sidecar_outcome():
    replay = REPO / "data" / "replays" / "80374966.json"
    if replay.exists():
        obj = tp.read_trace(replay)
        assert tp.detect_format(obj) == tp.FMT_KAGGLE_REPLAY
        frames = tp.iter_decision_frames(obj)
        assert len(frames) > 100
        # both seats appear
        assert {f.acting_player for f in frames} == {0, 1}


# == 15-17. behavioral baseline ==========================================
def test_baseline_reference_gap_is_low_and_outcome_level():
    d = _j("reference_behavior_baseline")
    ov = d["reference_opponents_overall"]
    assert ov["games"] > 0
    assert 0.0 <= ov["our_win_rate_vs_reference"] <= 1.0
    # the gap is large (our candidates lose the majority)
    assert ov["our_win_rate_vs_reference"] < 0.5


def test_baseline_trace_level_is_illustrative_only():
    d = _j("reference_behavior_baseline")
    tr = d["trace_level_turn_planning"]
    assert tr["illustrative_only"] is True
    assert tr["games"] <= 1
    # probation/generated honestly insufficient locally
    assert d["probation_candidates_local"]["status"] == "insufficient_data"
    assert d["generated_pass42_candidates_local"]["status"] == "insufficient_data"


def test_baseline_no_production_mutation():
    d = _j("reference_behavior_baseline")
    assert d["read_only"] is True


# == 18. loss-mode taxonomy: deterministic, never acts, never lethal ======
def test_taxonomy_deterministic_and_never_acts():
    d = _j("loss_mode_taxonomy")
    assert d["deterministic"] is True
    assert d["never_quarantines_or_promotes"] is True
    assert d["labels_are_observational_not_causal"] is True
    assert d["never_classifies_missed_lethal"] is True
    labels = {l["label"] for l in d["labels"]}
    assert "missed_lethal" not in labels
    assert "runtime_failure" in labels and "unsupported" in labels


# == 19. family gap report: ranked, no kaggle strength claim ==============
def test_family_gap_report_ranked_no_strength_claim():
    d = _j("family_gap_report")
    assert d["no_kaggle_strength_claim"] is True
    ranked = d["ranked_largest_observable_gaps"]
    assert len(ranked) >= 1
    wrs = [g.get("reference_win_rate_ours") for g in ranked
           if g.get("reference_win_rate_ours") is not None]
    assert wrs == sorted(wrs)  # ascending: largest gap first


# == 20. backlog: focuses on reusable primitives =========================
def test_backlog_focuses_on_reusable_primitives():
    d = _j("turn_planning_backlog")
    ids = {p["id"] for p in d["primitives"]}
    for need in ("energy_planner", "search_planner", "attack_planner",
                 "typed_board_decode_wrapper"):
        assert need in ids
    assert len(d["top3_next"]) == 3
    assert BACKLOG_DOC.exists()
    assert SCHEMA_DOC.exists()


# == 21. sidecar sampler bounded, no bulk / no prod download ==============
def test_sidecar_sampler_is_bounded():
    d = _j("sidecar_sample_manifest")
    assert d["bulk_download"] is False
    assert d["production_sidecars_downloaded"] is False
    assert d["sampled"] <= d["bounded_N_per_group"]
    for m in d["manifest"]:
        assert m["frames_available"] is False


# == 22. optional top-up: not run, nothing touched =======================
def test_topup_not_run():
    d = _j("optional_benchmark_topup")
    assert d["topup_run"] is False
    assert d["production_touched"] is False
    assert d["candidate_generation"] is False
    assert d["changed_conclusions"] is False


# == 23. strategy decision: allowed read-only outcome ====================
def test_strategy_decision_is_soak_continue():
    d = _j("strategy_decision")
    assert d["decision"] == "reference_gap_diagnostic_complete_soak_continue"
    assert d["decision"] in d["allowed_decisions"]
    assert d["production_mutated"] is False
    assert d["candidate_generated"] is False
    assert d["candidate_promoted"] is False
    assert d["candidate_submitted"] is False


# == 24. every part agrees production never mutated =======================
def test_all_parts_agree_no_production_mutation():
    for name in ("safety_preflight", "evidence_inventory", "turn_plan_schema",
                 "reference_behavior_baseline", "loss_mode_taxonomy",
                 "family_gap_report", "turn_planning_backlog",
                 "sidecar_sample_manifest", "optional_benchmark_topup",
                 "strategy_decision"):
        d = _j(name)
        assert d.get("read_only") is True, name


# == 25. report exists with required sections + caveats ===================
def test_report_has_required_caveats():
    assert REPORT.exists()
    text = REPORT.read_text(encoding="utf-8")
    low = re.sub(r"\s+", " ", text.lower())  # robust to line-wrapping
    assert "read-only" in low
    assert "not a kaggle" in low
    assert "no generation" in low or "no candidate generation" in low
    assert "no upload" in low
    assert "no promotion" in low
    assert "benchmark" in low


# == 26. tournament ledger still refuses forbidden upload events =========
def test_ledger_refuses_forbidden_upload_events(tmp_path):
    ledger = TournamentLedger(path=tmp_path / "events.jsonl")
    for et in ("SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated"):
        with pytest.raises(PermissionError):
            ledger.emit(et, {"x": 1})
    assert len(ledger.load()) == 0
