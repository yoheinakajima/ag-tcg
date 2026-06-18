"""Tests for the ActiveGraph strategy lab (experiments package + scripts).

These avoid the heavy cabt engine: candidate generation, ranking, queueing and
reporting are all exercised on synthetic metrics / fixtures, so they run fast and
deterministically. The one cabt-dependent path (the runner's actual game loop) is
covered by the live batch run, not here.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from ptcg_activegraph.experiments import (
    branch as branch_mod,
    config as config_mod,
    generator,
    metrics as metrics_mod,
    queue as queue_mod,
    ranker,
    report,
    telemetry,
)

REPO = Path(__file__).resolve().parent.parent
BASELINE_MAIN = REPO / "main.py"
BASELINE_DECK = REPO / "deck.csv"


# --------------------------------------------------------------------------
# config / seam parsing
# --------------------------------------------------------------------------

def test_load_config_parses_plan_and_seams():
    cfg = config_mod.load_config()
    assert cfg.settings, "settings should load from experiment_plan.yaml"
    assert cfg.seams, "seams should load from strategy_seams.yaml"
    # Safety defaults must be present and conservative.
    assert cfg.setting("auto_submit_enabled") is False
    assert cfg.setting("require_manual_approval_for_submit") is True


def test_priority_override_beats_default():
    cfg = config_mod.load_config()
    # energy_trim is boosted to 90 in the plan.
    assert cfg.priority_for("deck.energy_trim") == 90


def test_is_testable_respects_capabilities():
    cfg = config_mod.load_config()
    # A seam requiring an impossible capability is not testable.
    fake = config_mod.Seam(id="x", family="f", requires=["does_not_exist"])
    ok, reason = cfg.is_testable(fake)
    assert not ok and "does_not_exist" in reason
    # A disabled seam is not testable.
    disabled = config_mod.Seam(id="y", family="f", enabled=False)
    ok2, reason2 = cfg.is_testable(disabled)
    assert not ok2 and "disabled" in reason2


# --------------------------------------------------------------------------
# candidate generation
# --------------------------------------------------------------------------

def _read(p: Path) -> str:
    return Path(p).read_text(encoding="utf-8")


def test_policy_candidate_does_not_mutate_baseline(tmp_path):
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    spec = next(s for s in generator.POLICY_SPECS if s["branch_id"] == "policy_attack_heavy")
    b = generator.generate_policy_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="t0"
    )
    # Baseline untouched.
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck
    # Candidate has both files and the injected override block.
    assert (Path(b.run_dir) / "main.py").exists()
    assert (Path(b.run_dir) / "deck.csv").exists()
    cand_src = _read(Path(b.run_dir) / "main.py")
    assert "EXPERIMENT OVERRIDE" in cand_src
    assert "_OPTION_TYPE_SCORES.update(" in cand_src


def test_generated_policy_candidate_verifies(tmp_path):
    from ptcg_activegraph.packaging.make_submission import verify_submission_inputs

    spec = next(s for s in generator.POLICY_SPECS if s["branch_id"] == "policy_pass_avoidant")
    b = generator.generate_policy_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="t1"
    )
    # Should import, expose a callable agent, and have a legal 60-card deck.
    verify_submission_inputs(Path(b.run_dir) / "main.py", Path(b.run_dir) / "deck.csv")


def test_deck_candidate_is_legal_and_diffed(tmp_path):
    from ptcg_activegraph.cards import load_card_db

    spec = next(s for s in generator.DECK_SPECS if s["branch_id"] == "deck_energy_trim_light")
    b = generator.generate_deck_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path,
        card_db=load_card_db(), ts="t2",
    )
    from ptcg_activegraph.decks.deck_io import load_deck

    ids = load_deck(Path(b.run_dir) / "deck.csv")
    assert len(ids) == 60
    # Diff records the energy trim and the bumps.
    assert b.deck_diff["3"]["delta"] == -4
    assert b.deck_diff["721"]["delta"] == 2


def test_apply_deck_deltas_rejects_negative():
    base = [3] * 60
    with pytest.raises(ValueError):
        generator.apply_deck_deltas(base, {3: -100})


def test_deck_candidate_hard_fails_on_illegal_copies(tmp_path):
    from ptcg_activegraph.cards import load_card_db

    # Trim 4 energy but bump a non-energy card (721 Kyogre) to 6 copies (>4).
    bad_spec = {
        "branch_id": "deck_bad_copies", "seam_id": "deck.energy_trim",
        "archetype": "", "hypothesis": "illegal",
        "deltas": {3: -4, 721: +4},  # 721 baseline is 2 -> 6
    }
    with pytest.raises(ValueError, match="exceeds 4 copies"):
        generator.generate_deck_candidate(
            bad_spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path,
            card_db=load_card_db(), ts="bad",
        )


def test_illegal_copy_counts_exempts_basic_energy():
    from ptcg_activegraph.cards import load_card_db

    # 33 basic energy (id 3) is legal; 6 of a non-energy id is not.
    ids = [3] * 54 + [721] * 6
    over = generator._illegal_copy_counts(ids, card_db=load_card_db())
    assert 3 not in over
    assert over.get(721) == 6


def test_deck_specs_are_count_neutral():
    # Every deck spec's deltas must sum to zero (stay at 60 cards).
    for spec in generator.DECK_SPECS:
        assert sum(spec["deltas"].values()) == 0, spec["branch_id"]


def test_plan_candidates_orders_by_priority_and_marks_blocked():
    cfg = config_mod.load_config()
    plan = generator.plan_candidates(cfg)
    prios = [p["priority"] for p in plan]
    assert prios == sorted(prios, reverse=True)
    blocked = [p for p in plan if not p["testable"]]
    assert any(p["branch_id"] == "deck_abomasnow_line_focus" for p in blocked)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def test_compute_metrics_basic():
    results = [
        {"completed": True, "candidate_won": True, "candidate_seat": 0, "steps": 40,
         "decisions": 10, "attacks": 6, "passes": 1, "attack_available": 8,
         "option_count_sum": 30, "type_counts": {"13": 6, "14": 1}},
        {"completed": True, "candidate_won": False, "candidate_seat": 1, "steps": 36,
         "decisions": 8, "attacks": 3, "passes": 2, "attack_available": 5,
         "option_count_sum": 24, "type_counts": {"13": 3, "14": 2}},
        {"completed": False, "error": "boom", "timeout": False},
    ]
    m = metrics_mod.compute_metrics(results)
    assert m["games_completed"] == 2
    assert m["wins"] == 1 and m["losses"] == 1
    assert m["win_rate"] == 0.5
    assert m["crashes"] == 1
    assert 0 < m["attack_rate"] <= 1
    assert m["decision_entropy"] > 0


# --------------------------------------------------------------------------
# ranker
# --------------------------------------------------------------------------

def _metric(branch_id, **kw):
    base = {
        "branch_id": branch_id, "seam_id": "policy.attack_priority", "kind": "policy",
        "package_ok": True, "smoke_ok": True, "crashes": 0, "timeouts": 0,
        "win_rate": 0.5, "attack_rate": 0.5, "pass_rate": 0.05, "fallbacks": 0,
        "decision_entropy": 1.0, "avg_steps": 40, "games_completed": 5,
    }
    base.update(kw)
    return base


def test_ranker_hard_rejects_failures(tmp_path):
    store_path = tmp_path / "ev.jsonl"
    from ptcg_activegraph.graph.event_store import EventStore

    cands = [
        _metric("good", win_rate=0.8),
        _metric("smoke_fail", smoke_ok=False),
        _metric("pkg_fail", package_ok=False),
        _metric("crashed", crashes=2),
        _metric("timed_out", timeouts=1),
    ]
    cands.append(_metric("fell_back", fallbacks=3, win_rate=0.9))
    ranked = ranker.rank(cands, event_store=EventStore(store_path))
    by_id = {e["branch_id"]: e for e in ranked}
    assert by_id["good"]["rejected"] is False
    for bad in ("smoke_fail", "pkg_fail", "crashed", "timed_out", "fell_back"):
        assert by_id[bad]["rejected"] is True
        assert by_id[bad]["score"] is None
        # Hard rejects never receive a soft score, even with a high win rate.
        assert by_id[bad]["base_score"] is None
    # The only survivor ranks first.
    assert ranked[0]["branch_id"] == "good"


def test_ranker_diversity_bonus_across_families(tmp_path):
    from ptcg_activegraph.graph.event_store import EventStore

    cands = [
        _metric("p1", seam_id="policy.attack_priority", win_rate=0.6),
        _metric("p2", seam_id="policy.attack_priority", win_rate=0.6),
        _metric("d1", seam_id="deck.energy_trim", win_rate=0.6, kind="deck"),
    ]
    ranked = ranker.rank(cands, event_store=EventStore(tmp_path / "e.jsonl"))
    by_id = {e["branch_id"]: e for e in ranked}
    # First of each family gets the bonus; the second policy does not.
    assert by_id["d1"]["diversity_bonus"] > 0
    assert (by_id["p1"]["diversity_bonus"] > 0) != (by_id["p2"]["diversity_bonus"] > 0)


# --------------------------------------------------------------------------
# Wilson CI + conservative promotion labels
# --------------------------------------------------------------------------

def test_wilson_interval_bounds_and_width():
    lo, hi = ranker.wilson_interval(5, 10, ranker.Z_80)
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    # 95% interval is strictly wider than the 80% interval for the same data.
    lo95, hi95 = ranker.wilson_interval(5, 10, ranker.Z_95)
    assert lo95 < lo and hi95 > hi
    # Zero games is a degenerate, maximally-uncertain interval.
    assert ranker.wilson_interval(0, 0, ranker.Z_80) == (0.0, 1.0)
    # More games at the same rate tightens the interval.
    lo_small, hi_small = ranker.wilson_interval(6, 10, ranker.Z_80)
    lo_big, hi_big = ranker.wilson_interval(60, 100, ranker.Z_80)
    assert (hi_big - lo_big) < (hi_small - lo_small)


def test_label_small_sample_not_promotable():
    # 3/5 = 60% raw, but the sample is tiny: cannot be promotable.
    cands = [
        _metric("control", kind="control", wins=10, draws=0, games_completed=20,
                adjusted_win_rate=0.5),
        _metric("tiny", wins=3, draws=0, games_completed=5, adjusted_win_rate=0.6),
    ]
    from ptcg_activegraph.graph.event_store import EventStore
    ranked = ranker.rank(cands, event_store=EventStore(REPO / "no.jsonl"),
                         min_games=20)
    Path(REPO / "no.jsonl").unlink(missing_ok=True)
    by_id = {e["branch_id"]: e for e in ranked}
    assert by_id["tiny"]["label"] != "promotable"
    assert by_id["tiny"]["rejected"] is False


def test_label_strong_enough_is_promotable():
    # Overwhelming, well-sampled candidate that beats the control: promotable.
    cands = [
        _metric("control", kind="control", wins=10, draws=0, games_completed=20,
                adjusted_win_rate=0.5),
        _metric("strong", wins=36, draws=0, games_completed=40,
                adjusted_win_rate=0.9),
    ]
    from ptcg_activegraph.graph.event_store import EventStore
    ranked = ranker.rank(cands, event_store=EventStore(REPO / "no2.jsonl"),
                         min_games=20)
    Path(REPO / "no2.jsonl").unlink(missing_ok=True)
    by_id = {e["branch_id"]: e for e in ranked}
    assert by_id["strong"]["label"] == "promotable"
    assert by_id["strong"]["wilson80"][0] > 0.50


def test_label_enough_games_but_wide_ci_is_confirmation():
    # 22/40 = 55% over enough games, but 80% lower bound does not clear 0.50.
    cands = [
        _metric("control", kind="control", wins=10, draws=0, games_completed=20,
                adjusted_win_rate=0.5),
        _metric("borderline", wins=22, draws=0, games_completed=40,
                adjusted_win_rate=0.55),
    ]
    from ptcg_activegraph.graph.event_store import EventStore
    ranked = ranker.rank(cands, event_store=EventStore(REPO / "no3.jsonl"),
                         min_games=20)
    Path(REPO / "no3.jsonl").unlink(missing_ok=True)
    by_id = {e["branch_id"]: e for e in ranked}
    assert by_id["borderline"]["label"] == "confirmation_promising"
    assert by_id["borderline"]["wilson80"][0] <= 0.50


def test_label_enough_games_not_beating_control_is_inconclusive():
    # Enough games, but tying or trailing the control must never be labelled
    # confirmation_promising — it is conservatively inconclusive.
    cands = [
        _metric("control", kind="control", wins=24, draws=0, games_completed=40,
                adjusted_win_rate=0.60),
        _metric("tie", wins=24, draws=0, games_completed=40, adjusted_win_rate=0.60),
        _metric("below", wins=17, draws=0, games_completed=40, adjusted_win_rate=0.425),
    ]
    from ptcg_activegraph.graph.event_store import EventStore
    ranked = ranker.rank(cands, event_store=EventStore(REPO / "no4.jsonl"),
                         min_games=30)
    Path(REPO / "no4.jsonl").unlink(missing_ok=True)
    by_id = {e["branch_id"]: e for e in ranked}
    assert by_id["tie"]["label"] == "inconclusive"
    assert by_id["below"]["label"] == "inconclusive"


def test_run_one_game_watchdog_timeout_is_classified_as_timeout(monkeypatch):
    # When the per-game watchdog fires (env.run raises _GameTimeout) the game is
    # recorded as an explicit timeout (a hard-reject), not a generic crash.
    from ptcg_activegraph.experiments import runner as runner_mod

    class _FakeEnv:
        steps: list = []

        def run(self, agents):
            raise runner_mod._GameTimeout()

    monkeypatch.setattr(runner_mod, "_make_cabt", lambda ke, decks: _FakeEnv())
    main_py = REPO / "main.py"
    res = runner_mod.run_one_game(main_py, [1], main_py, [1], candidate_seat=0)
    assert res["timeout"] is True
    assert res["completed"] is False
    assert "watchdog" in (res["error"] or "")


def test_metrics_handles_draws_and_seat_split():
    results = [
        {"completed": True, "candidate_won": True, "candidate_seat": 0},
        {"completed": True, "candidate_won": True, "candidate_seat": 0},
        {"completed": True, "candidate_won": None, "draw": True, "candidate_seat": 1},
        {"completed": True, "candidate_won": False, "candidate_seat": 1},
    ]
    m = metrics_mod.compute_metrics(results)
    # Two seats with two games each.
    assert m["candidate_as_p0_games"] == 2 and m["candidate_p0_win_rate"] == 1.0
    assert m["candidate_p1_win_rate"] == 0.0
    assert m["seat_balance_delta"] == 1.0
    # A draw is half a win in the adjusted rate (2 wins + 0.5 draw)/4.
    assert m["draws"] == 1
    assert m["adjusted_win_rate"] == pytest.approx((2 + 0.5) / 4)


def test_seat_swap_schedule_is_balanced():
    from ptcg_activegraph.experiments import runner as runner_mod
    sched = runner_mod._seat_schedule(0, games_per_seat=5, seat_swap=True)
    assert sched == [0] * 5 + [1] * 5
    assert sched.count(0) == sched.count(1)
    # Legacy alternating schedule when no seat-swap is requested.
    legacy = runner_mod._seat_schedule(4, games_per_seat=None, seat_swap=False)
    assert legacy == [0, 1, 0, 1]


# --------------------------------------------------------------------------
# generation-2 combination candidates
# --------------------------------------------------------------------------

def test_combo_candidate_merges_and_does_not_mutate_baseline(tmp_path):
    spec = generator.COMBO_SPECS[0]
    before_main = _read(BASELINE_MAIN)
    before_deck = _read(BASELINE_DECK)
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="c0"
    )
    # Root baseline is never touched.
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck
    # Combo branch carries the combo kind and both a policy block and deck diff.
    assert b.kind == "combo"
    run = Path(b.run_dir)
    assert (run / "main.py").exists() and (run / "deck.csv").exists()
    # The injected override block names the combo seam.
    assert spec["seam_id"] in (run / "main.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# queue
# --------------------------------------------------------------------------

def test_queue_respects_max_per_day_and_dry_run(tmp_path, monkeypatch):
    from ptcg_activegraph.graph.event_store import EventStore

    # Build three promotable candidates with real run dirs (so packaging works).
    runs_by_branch = {}
    specs = generator.POLICY_SPECS[:3]
    ranked = []
    for i, spec in enumerate(specs):
        b = generator.generate_policy_candidate(
            spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts=f"q{i}"
        )
        runs_by_branch[b.branch_id] = b.run_dir
        ranked.append({"branch_id": b.branch_id, "rank": i + 1, "score": 100 - i,
                       "rejected": False, "seam_id": b.seam_id,
                       "label": "promotable"})

    # Point the queue output + candidate tarballs at temp paths (hermetic).
    monkeypatch.setattr(queue_mod, "QUEUE_JSON", tmp_path / "queue.json")
    monkeypatch.setattr(queue_mod, "CANDIDATES_DIR", tmp_path / "candidates")

    cfg = config_mod.load_config()
    cfg.settings["auto_submit_enabled"] = False
    cfg.submission_queue["max_per_day"] = 2
    plan = queue_mod.build_queue(ranked, cfg, runs_by_branch,
                                 event_store=EventStore(tmp_path / "ev.jsonl"))
    assert plan["mode"] == "DRY-RUN"
    assert plan["will_upload"] is False
    assert len(plan["candidates"]) == 2  # capped by max_per_day
    assert (tmp_path / "queue.json").exists()


def test_queue_skips_rejected():
    rejected = {"branch_id": "x", "rejected": True, "score": None}
    assert queue_mod.is_promotable(rejected) is False
    ok = {"branch_id": "y", "rejected": False, "score": 10}
    assert queue_mod.is_promotable(ok) is True


# --------------------------------------------------------------------------
# report (empty + non-empty)
# --------------------------------------------------------------------------

def test_report_site_empty_state(tmp_path):
    data = {"events": [], "ranking": [], "queue": {}, "runs": [],
            "baseline_readme": tmp_path / "none.md"}
    files = report.write_site(data, site_dir=tmp_path / "site")
    names = {p.name for p in files}
    assert {"index.html", "candidates.html", "events.html", "style.css"} <= names
    idx = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "No ranking yet" in idx or "empty" in idx
    md = report.write_markdown(data, path=tmp_path / "r.md")
    assert "No ranking at this stage yet" in md.read_text(encoding="utf-8")


def test_report_site_nonempty(tmp_path):
    b = branch_mod.Branch(branch_id="demo", seam_id="policy.attack_priority",
                          family="policy", kind="policy", hypothesis="h")
    data = {
        "events": [{"event_type": "MetricsComputed", "timestamp": 1.0, "payload": {}}],
        "ranking": [{"rank": 1, "branch_id": "demo", "seam_id": "policy.attack_priority",
                     "score": 900.0, "win_rate": 0.8, "adjusted_win_rate": 0.8,
                     "wilson80": [0.55, 0.95], "wilson95": [0.45, 0.97],
                     "label": "promotable", "rejected": False}],
        "focused_ranking": [{"rank": 1, "branch_id": "demo",
                             "seam_id": "policy.attack_priority", "score": 950.0,
                             "win_rate": 0.82, "adjusted_win_rate": 0.82,
                             "wilson80": [0.6, 0.95], "wilson95": [0.5, 0.97],
                             "label": "promotable", "rejected": False,
                             "hypothesis": "demo hypothesis"}],
        "queue": {"mode": "DRY-RUN", "candidates": [], "auto_submit_enabled": False,
                  "require_manual_approval_for_submit": True},
        "runs": [{"branch": b, "metrics": {"win_rate": 0.8, "package_ok": True,
                                           "smoke_ok": True, "games_completed": 5},
                  "run_dir": str(tmp_path)}],
        "baseline_readme": tmp_path / "none.md",
    }
    report.write_site(data, site_dir=tmp_path / "site")
    idx = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "demo" in idx and "promotable" in idx
    md = report.write_markdown(data, path=tmp_path / "r.md").read_text(encoding="utf-8")
    assert "demo" in md and "Current interpretation" in md


def test_pass5_chaos_summary_does_not_fabricate_when_no_contract():
    # No chaos contract loaded must NOT assert "all blocked" — it must say uncertain.
    empty = report._chaos_summary({})
    assert "uncertain" in empty.lower()
    assert "all" not in empty.lower()
    # All-blocked contract yields the honest "all blocked" sentence derived from data.
    contract = {"seams": [{"telemetry_availability": "blocked"},
                          {"telemetry_availability": "blocked"}]}
    summary = report._chaos_summary(contract)
    assert "2 chaos seams remain blocked" in summary
    # Mixed availability must not over-claim "all".
    mixed = report._chaos_summary({"seams": [{"telemetry_availability": "blocked"},
                                             {"telemetry_availability": "partial"}]})
    assert "1 of 2" in mixed and "uncertain" in mixed.lower()


def test_pass5_markdown_section_degrades_without_replay():
    # With no replay artifact, the Pass 5 section must degrade, not fabricate findings.
    lines = report._pass5_md({"pass5_replay": {}})
    text = "\n".join(lines)
    assert "Pass 5" in text
    assert "No replay analysis artifact" in text
    # No fabricated findings/tables when the replay artifact is absent.
    assert "Apparent loss reason" not in text
    assert "### Deck-out evidence" not in text
    assert "Strongest failure tag" not in text


# --------------------------------------------------------------------------
# ag_event append / list / summary (via the script's store)
# --------------------------------------------------------------------------

def test_ag_event_append_list_summary(tmp_path, monkeypatch):
    from ptcg_activegraph.graph.event_store import EventStore
    from ptcg_activegraph.graph.events import EventType, new_event

    store = EventStore(tmp_path / "lab.jsonl")
    store.append(new_event(EventType.BaselineRegistered,
                           payload={"name": "v1"}, tags=["baseline"]))
    store.append(new_event(EventType.IdeaGenerated, payload={"x": 1}))
    store.append(new_event(EventType.IdeaGenerated, payload={"x": 2}))

    all_events = store.load()
    assert len(all_events) == 3
    ideas = store.query(event_type="IdeaGenerated")
    assert len(ideas) == 2
    counts = Counter(e.event_type for e in all_events)
    assert counts["IdeaGenerated"] == 2 and counts["BaselineRegistered"] == 1


# --------------------------------------------------------------------------
# Pass 4 — chaos metrics tolerance
# --------------------------------------------------------------------------

def test_metrics_tolerate_missing_chaos_fields():
    # The base runner does not surface chaos/board-state signals, so results
    # omit every chaos field. compute_metrics must not raise and must report
    # the chaos block as unavailable with an honest note (never a fabricated 0).
    results = [
        {"completed": True, "candidate_won": True, "candidate_seat": 0, "steps": 30},
        {"completed": True, "candidate_won": False, "candidate_seat": 1, "steps": 28},
    ]
    m = metrics_mod.compute_metrics(results)
    chaos = m["chaos"]
    assert chaos["available"] is False
    assert chaos["note"]  # explains why nothing was measured
    assert chaos["opp_hand_size"] is None
    assert chaos["opponent_deckouts"] is None


def test_metrics_aggregate_chaos_when_present():
    # When per-game results DO carry chaos signals, they are aggregated:
    # sizes/rates average, counts sum, and available flips True.
    results = [
        {"completed": True, "candidate_won": True, "candidate_seat": 0,
         "opp_hand_size": 8, "opponent_deckouts": 1, "status_conditions": 2},
        {"completed": True, "candidate_won": True, "candidate_seat": 1,
         "opp_hand_size": 6, "opponent_deckouts": 0, "status_conditions": 1},
    ]
    chaos = metrics_mod.compute_metrics(results)["chaos"]
    assert chaos["available"] is True
    assert chaos["opp_hand_size"] == 7.0          # averaged
    assert chaos["opponent_deckouts"] == 1         # summed count
    assert chaos["status_conditions"] == 3         # summed count
    assert chaos["note"] == ""


# --------------------------------------------------------------------------
# Pass 4 — Kaggle replay parser + analyzer
# --------------------------------------------------------------------------

def _fixture_replay_raw() -> dict:
    # Minimal cabt-shaped episode: two seats, two steps, seat 0 wins.
    return {
        "id": 80374966,
        "name": "ptcg",
        "version": "1.0",
        "configuration": {"actTimeout": 10, "runTimeout": 1200, "episodeSteps": 500},
        "rewards": [1, -1],
        "statuses": ["DONE", "DONE"],
        "steps": [
            [
                {"observation": {"select": {"context": "deck",
                                            "options": [{"card_id": 3}, {"card_id": 721}]}},
                 "action": [3, 721], "status": "ACTIVE", "reward": 0},
                {"observation": {}, "action": [], "status": "INACTIVE", "reward": 0},
            ],
            [
                {"observation": {"select": {"context": "attack",
                                            "options": [{"type": "attack", "card_id": 721}]}},
                 "action": [0], "status": "ACTIVE", "reward": 0},
                {"observation": {}, "action": [], "status": "INACTIVE", "reward": 0},
            ],
        ],
    }


def test_replay_parser_shape_and_final_result():
    from ptcg_activegraph.replays import analyze, parse_replay

    replay = parse_replay(_fixture_replay_raw(), source_path="fixture.json")
    assert replay.episode_id == 80374966
    assert replay.num_steps == 2
    fr = replay.final_result()
    assert fr["winner_seat"] == 0 and fr["draw"] is False

    analysis = analyze(replay)
    # Top-level analysis contract the report relies on.
    for key in ("episode", "decks", "telemetry", "effect_traces",
                "failure_tags", "source_path"):
        assert key in analysis
    assert analysis["episode"]["episode_id"] == 80374966
    assert analysis["episode"]["total_steps"] == 2


def test_replay_loader_raises_when_absent(tmp_path):
    from ptcg_activegraph.replays import ReplayNotFound, load_replay

    missing = tmp_path / "80374966.json"
    with pytest.raises(ReplayNotFound):
        load_replay(missing)


def test_replay_parser_robust_to_empty_episode():
    from ptcg_activegraph.replays import analyze, parse_replay

    # A completely empty / malformed episode must still analyze without raising.
    replay = parse_replay({})
    analysis = analyze(replay)
    assert analysis["episode"]["total_steps"] == 0
    assert analysis["episode"]["final_result"]["winner_seat"] is None


# --------------------------------------------------------------------------
# Pass 4 — card id/name confirmation
# --------------------------------------------------------------------------

def _norm_apostrophes(s: str) -> str:
    # Treat curly and straight apostrophes as equal (typographic-only diff).
    return s.replace("\u2019", "'").replace("\u2018", "'")


def test_pass4_card_id_confirmation_match_or_apostrophe_only():
    # Every id was checked against the metadata CSV. A MATCH means claimed ==
    # actual; the only tolerated MISMATCH is a purely typographic apostrophe
    # difference (straight ' vs curly ’). Anything else would be a real id/name
    # error and must fail.
    path = REPO / "data" / "cards" / "pass4_id_confirmation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data, "confirmation file should not be empty"
    seen = 0
    for archetype, entries in data.items():
        for e in entries:
            seen += 1
            assert e["status"] in ("MATCH", "MISMATCH")
            if e["status"] == "MATCH":
                assert e["claimed"] == e["actual"]
            else:
                # The mismatch must be apostrophe-only — not a wrong card.
                assert _norm_apostrophes(e["claimed"]) == _norm_apostrophes(e["actual"]), (
                    f"{archetype}: id {e['id']} is a real name mismatch "
                    f"({e['claimed']!r} != {e['actual']!r})")
    assert seen > 0


def test_pass4_confirmation_matches_card_db():
    # Re-derive the names straight from the card DB so the JSON cannot drift
    # from the source of truth without this test catching it.
    from ptcg_activegraph.cards import load_card_db

    db = load_card_db()
    path = REPO / "data" / "cards" / "pass4_id_confirmation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    checked = 0
    for entries in data.values():
        for e in entries:
            card = db.get(int(e["id"])) if hasattr(db, "get") else db[int(e["id"])]
            if card is None:
                continue
            name = getattr(card, "name", None) or (
                card.get("name") if isinstance(card, dict) else None)
            if name:
                checked += 1
                assert name == e["actual"], f"id {e['id']}: {name!r} != {e['actual']!r}"
    assert checked > 0


# --------------------------------------------------------------------------
# Pass 4 — blocked chaos candidates (metadata insufficient -> honest block)
# --------------------------------------------------------------------------

def test_blocked_chaos_records_reasons_and_confirmed_ids():
    confirmation = json.loads(
        (REPO / "data" / "cards" / "pass4_id_confirmation.json").read_text("utf-8")
    )
    # An id is "checked against metadata" if it appears in the confirmation
    # file at all (MATCH, or apostrophe-only MISMATCH). Blocked chaos specs may
    # only reference ids that were actually verified — never invented ones.
    checked_ids = {
        int(e["id"]) for entries in confirmation.values() for e in entries
    }
    for spec in generator.CHAOS_BLOCKED:
        assert spec["archetype"] == "chaos"
        assert spec["blocked_reason"], (
            f"{spec['branch_id']} needs an honest block reason")
        assert spec["core_card_ids"], spec["branch_id"]
        for cid in spec["core_card_ids"]:
            assert int(cid) in checked_ids, (
                f"{spec['branch_id']} references unverified id {cid}")


def test_blocked_candidates_file_mirrors_specs():
    on_disk = json.loads(
        (REPO / "data" / "experiments" / "pass4_blocked_candidates.json").read_text("utf-8")
    )
    disk_ids = {c["branch_id"] for c in on_disk}
    spec_ids = {s["branch_id"] for s in generator.CHAOS_BLOCKED}
    assert disk_ids == spec_ids


# --------------------------------------------------------------------------
# Pass 4 — effect-resolution policy candidate + combo on v2 deck
# --------------------------------------------------------------------------

def test_pass4_policy_candidate_does_not_mutate_baseline(tmp_path):
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    spec = next(s for s in generator.PASS4_POLICY_SPECS
                if s["branch_id"] == "policy_effect_resolution_v1")
    b = generator.generate_policy_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="p4"
    )
    # Root baseline untouched.
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck
    # Override block present and names the pass-4 seam.
    cand_src = _read(Path(b.run_dir) / "main.py")
    assert "EXPERIMENT OVERRIDE" in cand_src
    assert spec["seam_id"] in cand_src
    # Policy candidate keeps the v1 (root) deck unchanged.
    assert _read(Path(b.run_dir) / "deck.csv") == before_deck


def test_pass4_combo_uses_v2_deck_and_keeps_root_immutable(tmp_path):
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    spec = next(s for s in generator.PASS4_COMBO_SPECS
                if s["branch_id"] == "combo_v2_deck__effect_resolution_v1")
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="c4"
    )
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck

    from ptcg_activegraph.decks.deck_io import load_deck
    ids = load_deck(Path(b.run_dir) / "deck.csv")
    counts = Counter(ids)
    assert len(ids) == 60
    # v2 deck = trim 4 basic energy (id 3), +2 Kyogre (721), +2 Ultra Ball (1121).
    assert b.deck_diff["3"]["delta"] == -4
    assert b.deck_diff["721"]["delta"] == 2
    assert b.deck_diff["1121"]["delta"] == 2
    assert counts[721] == 4 and counts[1121] == 4


def test_pass4_anchor_is_pure_v2_control(tmp_path):
    # The anchor must carry NO policy override (pure v2 control mirror).
    spec = next(s for s in generator.PASS4_COMBO_SPECS
                if s["branch_id"] == "pass4_control_v2_anchor")
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="anchor"
    )
    cand_src = _read(Path(b.run_dir) / "main.py")
    # The anchor's override block carries NO actual policy mutation — it is an
    # empty marker block, so behaviour is pure baseline.
    assert "_OPTION_TYPE_SCORES.update(" not in cand_src
    assert ".update(" not in cand_src
    # but still the v2 deck.
    from ptcg_activegraph.decks.deck_io import load_deck
    counts = Counter(load_deck(Path(b.run_dir) / "deck.csv"))
    assert counts[721] == 4 and counts[1121] == 4


# --------------------------------------------------------------------------
# Pass 4 — submission tarball contains ONLY top-level main.py + deck.csv
# --------------------------------------------------------------------------

def test_pass4_candidate_tarball_is_main_and_deck_only(tmp_path):
    from ptcg_activegraph.cards import load_card_db
    from ptcg_activegraph.packaging.make_submission import (
        build_submission, inspect_tarball,
    )

    spec = next(s for s in generator.PASS4_POLICY_SPECS
                if s["branch_id"] == "policy_ultra_ball_v1")
    b = generator.generate_policy_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="tar"
    )
    out = tmp_path / "submission.tar.gz"
    build_submission(
        Path(b.run_dir) / "main.py", Path(b.run_dir) / "deck.csv",
        out_path=out, card_db=load_card_db(),
    )
    members = sorted(inspect_tarball(out)["members"])
    assert members == ["deck.csv", "main.py"]


# --------------------------------------------------------------------------
# Pass 6 (B): corrected opponent-observability telemetry contract
# --------------------------------------------------------------------------

def _synthetic_obs(your_index=0):
    """Mirror the verified cabt schema: own hand populated, opponent hand null,
    but opponent counts/board/discard/status observable (see replay 80374966)."""
    me = {
        "active": [{"id": 721, "playerIndex": your_index, "serial": 1}],
        "bench": [{"id": 721, "playerIndex": your_index, "serial": 2},
                  {"id": 722, "playerIndex": your_index, "serial": 3}],
        "benchMax": 5,
        "deckCount": 36,
        "discard": [{"id": 3, "playerIndex": your_index, "serial": 9}],
        "hand": [{"id": 1219, "playerIndex": your_index, "serial": 55},
                 {"id": 3, "playerIndex": your_index, "serial": 7}],
        "handCount": 6,
        "prize": [None, None, None, None, None],
        "asleep": False, "burned": False, "confused": False,
        "paralyzed": False, "poisoned": False,
    }
    opp = {
        "active": [{"id": 722, "playerIndex": 1 - your_index, "serial": 40}],
        "bench": [{"id": 721, "playerIndex": 1 - your_index, "serial": 41},
                  {"id": 722, "playerIndex": 1 - your_index, "serial": 42}],
        "benchMax": 5,
        "deckCount": 31,
        "discard": [{"id": 1121, "playerIndex": 1 - your_index, "serial": 5}],
        "hand": None,            # opponent hand CONTENTS hidden
        "handCount": 15,         # but the COUNT is observable
        "prize": [None, None, None, None, None],
        "asleep": False, "burned": True, "confused": False,
        "paralyzed": False, "poisoned": False,
    }
    players = [me, opp] if your_index == 0 else [opp, me]
    return {"current": {"yourIndex": your_index, "players": players}}


def test_telemetry_reads_own_contents_and_opponent_counts():
    v = telemetry.read_observation(_synthetic_obs(your_index=0))
    assert v.valid
    # Own contents fully observable.
    assert v.own_hand_count == 6
    assert v.own_deck_count == 36
    assert v.own_active_ids == [721]
    assert sorted(v.own_bench_ids) == [721, 722]
    # Opponent COUNTS + revealed BOARD + DISCARD + STATUS observable.
    assert v.opp_hand_count == 15
    assert v.opp_deck_count == 31
    assert v.opp_active_ids == [722]
    assert v.opp_bench_count == 2
    assert v.opp_discard_ids == [1121]
    assert v.opp_prize_count == 5
    assert v.opp_status_flags["burned"] is True


def test_telemetry_marks_opponent_contents_hidden():
    v = telemetry.read_observation(_synthetic_obs(your_index=0))
    # The opponent hand/deck/prize CONTENTS must be flagged hidden, never invented.
    assert v.uncertainty["opp_hand_contents_hidden"] is True
    assert v.uncertainty["opp_deck_contents_hidden"] is True
    assert v.uncertainty["opp_prize_contents_hidden"] is True


def test_telemetry_convenience_accessors_match_view():
    obs = _synthetic_obs(your_index=1)
    assert telemetry.opp_hand_count(obs) == 15
    assert telemetry.opp_bench_count(obs) == 2
    assert telemetry.opp_deck_count(obs) == 31
    assert telemetry.opp_status_flags(obs)["burned"] is True


def test_telemetry_robust_to_malformed_input():
    for bad in (None, {}, {"current": None}, {"current": {"players": None}},
                {"current": {"yourIndex": 5, "players": [{}, {}]}}, 42, "x"):
        v = telemetry.read_observation(bad)
        assert v.valid is False


def test_telemetry_facedown_board_entries_counted_not_invented():
    obs = _synthetic_obs(your_index=0)
    # Inject a face-down (null-id) bench entry on the opponent.
    obs["current"]["players"][1]["bench"].append(None)
    obs["current"]["players"][1]["bench"].append({"playerIndex": 1})  # no id
    v = telemetry.read_observation(obs)
    # Revealed ids stay 2; the 2 unrevealed entries are counted, not invented.
    assert v.opp_bench_ids == [721, 722]
    assert v.opp_bench_count == 4
    assert v.uncertainty["opp_bench_facedown"] == 2


def test_telemetry_contract_json_marks_triggers_observable():
    contract = json.loads(
        (REPO / "data" / "experiments" / "chaos_telemetry_contract.json").read_text()
    )
    assert contract["pass"] == 6
    by_id = {s["seam_id"]: s for s in contract["seams"]}
    # Seams whose trigger is a pure opponent count/board/status are observable now.
    for sid in ("chaos.hand_avalanche_froslass",
                "chaos.bench_bloat_punisher",
                "chaos.mill_resource_destruction"):
        assert by_id[sid]["policy_trigger_observable"] is True
        assert by_id[sid]["telemetry_availability"] == "available"
    # All seams remain enabled=False until a legal decklist passes the build gate.
    assert all(s["enabled"] is False for s in contract["seams"])


# --------------------------------------------------------------------------
# Pass 6 (C): killable subprocess-per-game runner (dummy child, no real cabt)
# --------------------------------------------------------------------------

from ptcg_activegraph.experiments import runner as runner_mod  # noqa: E402


def _write_child(tmp_path, body):
    p = tmp_path / "dummy_child.py"
    p.write_text("import json, sys\n" + body, encoding="utf-8")
    return str(p)


def test_subprocess_runner_parses_child_result(tmp_path):
    # Child echoes a completed-win result derived from the spec.
    child = _write_child(tmp_path, (
        "spec = json.loads(open(sys.argv[1]).read())\n"
        "res = {'candidate_seat': spec['candidate_seat'], 'completed': True,\n"
        "       'candidate_won': True, 'draw': False, 'steps': 42, 'error': None,\n"
        "       'timeout': False, 'decisions': 7}\n"
        "open(sys.argv[2], 'w').write(json.dumps(res))\n"
    ))
    r = runner_mod.run_one_game_subprocess(
        "ctrl.py", [1, 2], "cand.py", [3, 4],
        candidate_seat=1, timeout_seconds=20, child_script=child,
    )
    assert r["completed"] is True
    assert r["candidate_won"] is True
    assert r["steps"] == 42
    assert r["candidate_seat"] == 1
    assert r["decisions"] == 7
    assert r.get("timeout") in (False, None)


def test_subprocess_runner_kills_hung_child(tmp_path, monkeypatch):
    # Child IGNORES SIGTERM and sleeps far past the timeout, simulating a game
    # wedged in cabt's C-level env.run. The parent must escalate to SIGKILL.
    monkeypatch.setattr(runner_mod, "_KILL_GRACE_SECONDS", 1)
    child = _write_child(tmp_path, (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n"
    ))
    import time as _t
    t0 = _t.time()
    r = runner_mod.run_one_game_subprocess(
        "ctrl.py", [1], "cand.py", [2],
        candidate_seat=0, timeout_seconds=2, child_script=child,
    )
    elapsed = _t.time() - t0
    assert r["timeout"] is True
    assert r["completed"] is False
    assert "timeout" in (r["error"] or "").lower()
    # 2s budget + 1s SIGTERM grace + SIGKILL: must be reaped quickly, not 60s.
    assert elapsed < 15


def test_subprocess_runner_records_nonzero_exit(tmp_path):
    child = _write_child(tmp_path, "sys.exit(3)\n")
    r = runner_mod.run_one_game_subprocess(
        "ctrl.py", [1], "cand.py", [2],
        candidate_seat=0, timeout_seconds=20, child_script=child,
    )
    assert r["completed"] is False
    assert r["timeout"] is False
    assert "code 3" in (r["error"] or "")


def test_subprocess_runner_handles_missing_output(tmp_path):
    # Child exits 0 but writes no result file: recorded as an error, not a crash.
    child = _write_child(tmp_path, "pass\n")
    r = runner_mod.run_one_game_subprocess(
        "ctrl.py", [1], "cand.py", [2],
        candidate_seat=0, timeout_seconds=20, child_script=child,
    )
    assert r["completed"] is False
    assert "no parseable result" in (r["error"] or "")


# --------------------------------------------------------------------------
# Pass 6 (D): clean control / ranking semantics (roles + exclusions)
# --------------------------------------------------------------------------

def _d_metric(branch_id, kind, wins, games, **extra):
    losses = games - wins
    m = {
        "branch_id": branch_id, "kind": kind, "seam_id": extra.get("seam_id", "x.y"),
        "package_ok": True, "smoke_ok": True, "crashes": 0, "timeouts": 0,
        "fallbacks": 0, "games_completed": games, "wins": wins, "losses": losses,
        "draws": 0, "win_rate": wins / games if games else None,
        "adjusted_win_rate": wins / games if games else None,
        "attack_rate": 0.5, "pass_rate": 0.1, "avg_steps": 80.0,
        "stage": extra.get("stage", "pass6_focused"),
    }
    m.update({k: v for k, v in extra.items() if k not in ("seam_id", "stage")})
    return m


def test_control_role_classification():
    assert ranker.control_role("pass6_control_v2_anchor") == ranker.ROLE_ACTIVE_CONTROL
    assert ranker.control_role("pass5_control_v2_anchor") == ranker.ROLE_ACTIVE_CONTROL
    assert ranker.control_role("policy_conservative_baseline") == ranker.ROLE_LEGACY_BASELINE
    assert ranker.control_role("x", kind="control") == ranker.ROLE_LEGACY_BASELINE
    assert ranker.control_role("deck_baseline_consistency") == ranker.ROLE_INTEGRITY_ANCHOR
    # A real candidate whose name merely contains 'control' is NOT a control.
    assert ranker.control_role("policy_tempo_control_v3") is None
    assert ranker.control_role("policy_effect_resolution_v3") is None


def test_controls_excluded_from_candidate_topn_and_get_anchor_label(tmp_path):
    store = ranker.EventStore(tmp_path / "ev.jsonl")
    metrics = [
        _d_metric("pass6_control_v2_anchor", "combo", 12, 24),   # active control
        _d_metric("policy_conservative_baseline", "control", 9, 24),  # legacy
        _d_metric("deck_baseline_consistency", "deck", 12, 24),  # integrity anchor
        _d_metric("policy_effect_resolution_v3", "policy", 21, 24, seam_id="effect.res"),
        _d_metric("deck_no_secret_box_powerglass", "deck", 18, 24, seam_id="deck.box"),
    ]
    ranked = ranker.rank(metrics, event_store=store, min_games=20)
    by_id = {e["branch_id"]: e for e in ranked}
    # Controls/anchors carry the anchor label and have no candidate_rank.
    for cid in ("pass6_control_v2_anchor", "policy_conservative_baseline",
                "deck_baseline_consistency"):
        assert by_id[cid]["label"] == ranker.LABEL_ANCHOR
        assert by_id[cid]["is_control"] is True
        assert by_id[cid]["candidate_rank"] is None
        assert by_id[cid]["promotable"] is False
    # Real candidates ARE numbered as candidates.
    assert by_id["policy_effect_resolution_v3"]["candidate_rank"] == 1
    assert by_id["deck_no_secret_box_powerglass"]["is_control"] is False


def test_focused_gate_uses_v2_active_control_not_v1():
    # v2 active control wins 75%, v1 legacy wins 30%. A candidate at 60% beats v1
    # but NOT the v2 active control, so it must not be promotable.
    metrics = [
        _d_metric("pass6_control_v2_anchor", "combo", 18, 24),       # adj 0.75
        _d_metric("policy_conservative_baseline", "control", 7, 24),  # adj ~0.29
        _d_metric("policy_weak_edge_v3", "policy", 15, 24, seam_id="a.b"),  # adj 0.625
    ]
    adj = ranker._control_adjusted_win_rate(metrics)
    assert adj == pytest.approx(0.75, abs=1e-6)  # prefers the v2 active control
    ranked = ranker.rank(metrics, event_store=ranker.EventStore(), min_games=20)
    cand = next(e for e in ranked if e["branch_id"] == "policy_weak_edge_v3")
    assert cand["promotable"] is False  # 0.625 does not beat 0.75


def test_queue_never_selects_controls_or_anchors():
    ranked = [
        {"branch_id": "pass6_control_v2_anchor", "kind": "combo",
         "label": ranker.LABEL_ANCHOR, "rejected": False, "score": 999.0,
         "is_control": True, "role": ranker.ROLE_ACTIVE_CONTROL},
        {"branch_id": "policy_conservative_baseline", "kind": "control",
         "label": ranker.LABEL_ANCHOR, "rejected": False, "score": 900.0,
         "is_control": True, "role": ranker.ROLE_LEGACY_BASELINE},
        {"branch_id": "policy_effect_resolution_v3", "kind": "policy",
         "label": "promotable", "rejected": False, "score": 800.0,
         "is_control": False, "role": None},
    ]
    selected = queue_mod.select_for_queue(ranked, max_per_day=5)
    ids = [e["branch_id"] for e in selected]
    assert ids == ["policy_effect_resolution_v3"]
    assert not queue_mod.is_promotable(ranked[0])
    assert not queue_mod.is_promotable(ranked[1])
    assert queue_mod.is_promotable(ranked[2])


# --------------------------------------------------------------------------
# Part E: replay-derived decision fixtures (extract + candidate gate)
# --------------------------------------------------------------------------

import importlib.util as _ilu  # noqa: E402

_SCRIPTS = REPO / "scripts"


def _load_script(name: str):
    """Import a scripts/<name>.py module in isolation (adds scripts/ to path)."""
    import sys
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / f"{name}.py"
    spec = _ilu.spec_from_file_location(f"_script_{name}", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_to(tmp_path):
    extract = _load_script("extract_replay_fixtures")
    out = tmp_path / "fixtures"
    written = extract.extract_fixtures(extract.DEFAULT_REPLAY, str(out))
    return extract, out, written


def test_extract_produces_five_named_fixtures(tmp_path):
    _extract, out, written = _extract_to(tmp_path)
    ids = {f["id"] for f in written}
    assert ids == {
        "step11_secret_box_discard",
        "step17_mega_signal_search",
        "step28_ultra_ball_discard",
        "step112_low_deck_search",
        "setup_active_choice",
    }
    # Every fixture carries a real observation prompt and an index file exists.
    for f in written:
        assert isinstance(f["observation"], dict)
        assert (out / f"{f['id']}.json").exists()
    assert (out / "_index.json").exists()


def test_fixture_card_ids_match_confirmed_schema(tmp_path):
    _extract, _out, written = _extract_to(tmp_path)
    by_id = {f["id"]: f for f in written}
    # Resolved option cards verified against replay 80374966 (no invented ids).
    assert by_id["step11_secret_box_discard"]["option_cards"] == [3, 3, 722]
    assert by_id["step17_mega_signal_search"]["option_cards"] == [723, 723, 723]
    assert by_id["step28_ultra_ball_discard"]["option_cards"] == [723, 3, 1219, 3, 1262, 3]
    assert by_id["step112_low_deck_search"]["option_cards"] == [1227]
    assert by_id["setup_active_choice"]["option_cards"] == [722, 722, 721]
    # Effect cards are read from select.effect.id where present.
    assert by_id["step11_secret_box_discard"]["effect_card_id"] == 1092
    assert by_id["step28_ultra_ball_discard"]["effect_card_id"] == 1121


def test_min_count_equals_options_nuance_is_captured(tmp_path):
    """step11 secret box: minCount == maxCount == n_options -> forced discard."""
    _extract, _out, written = _extract_to(tmp_path)
    fx = next(f for f in written if f["id"] == "step11_secret_box_discard")
    assert fx["min_count"] == fx["n_options"] == 3
    assert fx["max_count"] == 3
    assert fx["check"]["preference"]["kind"] == "forced_all"
    # The forced set includes a setup piece (Snover 722) that cannot be spared.
    assert 722 in fx["option_cards"]


def test_legality_grader_respects_counts():
    runner = _load_script("test_candidate_on_fixtures")
    # min==max==n: only selecting all 3 is legal.
    assert runner.check_legality([0, 1, 2], 3, 3, 3)[0] is True
    assert runner.check_legality([2], 3, 3, 3)[0] is False           # too few
    assert runner.check_legality([0, 1, 2, 2], 3, 3, 3)[0] is False  # duplicate
    assert runner.check_legality([3], 3, 3, 3)[0] is False           # out of range
    assert runner.check_legality([True], 3, 1, 1)[0] is False        # bool not int
    # decline is legal when minCount 0.
    assert runner.check_legality([], 3, 0, 1)[0] is True


def test_preference_graders():
    runner = _load_script("test_candidate_on_fixtures")
    # decline: empty passes, a pick fails (minCount 0).
    fx_decline = {"min_count": 0, "option_cards": [723, 723, 723],
                  "check": {"preference": {"kind": "decline"}}}
    assert runner.evaluate_preference([], fx_decline)["result"] == "pass"
    assert runner.evaluate_preference([0], fx_decline)["result"] == "fail"
    # avoid_cards: selecting a flagged setup piece fails.
    fx_avoid = {"min_count": 2, "option_cards": [723, 3, 1219, 3, 1262, 3],
                "check": {"preference": {"kind": "avoid_cards", "cards": [721, 722, 723]}}}
    assert runner.evaluate_preference([1, 3], fx_avoid)["result"] == "pass"
    assert runner.evaluate_preference([0, 1], fx_avoid)["result"] == "fail"
    # prefer_cards: at least one preferred card passes.
    fx_prefer = {"min_count": 1, "option_cards": [722, 722, 721],
                 "check": {"preference": {"kind": "prefer_cards", "cards": [721, 722, 723]}}}
    assert runner.evaluate_preference([0], fx_prefer)["result"] == "pass"
    # forced_all is always na.
    fx_forced = {"min_count": 3, "option_cards": [3, 3, 722],
                 "check": {"preference": {"kind": "forced_all"}}}
    assert runner.evaluate_preference([0, 1, 2], fx_forced)["result"] == "na"


def test_candidate_runner_loads_run_dir_main_and_records_v2(tmp_path):
    """The runner loads a real run-dir main.py and records its behaviour."""
    _extract, out, _written = _extract_to(tmp_path)
    runner = _load_script("test_candidate_on_fixtures")
    v2_dir = REPO / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"
    result = runner.evaluate_candidate_on_fixtures(v2_dir, out)
    assert result["loaded"] is True
    assert result["load_error"] is None
    assert result["n_fixtures"] == 5
    # v2 produces a legal action on every fixture (hard gate passes).
    assert result["legality_gate"] is True
    for fx in result["fixtures"]:
        assert fx["legal"] is True
    # v2 is the *baseline*: it is expected to miss some advisory preferences
    # (e.g. it fetches Mega with no Snover line / discards a setup piece).
    by_id = {fx["id"]: fx for fx in result["fixtures"]}
    assert by_id["step17_mega_signal_search"]["preference"]["result"] == "fail"
    assert by_id["setup_active_choice"]["preference"]["result"] == "pass"
    assert by_id["step11_secret_box_discard"]["preference"]["result"] == "na"


def test_candidate_runner_handles_missing_and_crashing_agent(tmp_path):
    _extract, out, _written = _extract_to(tmp_path)
    runner = _load_script("test_candidate_on_fixtures")
    # Missing main.py: reported, not raised.
    empty = tmp_path / "empty_candidate"
    empty.mkdir()
    res_missing = runner.evaluate_candidate_on_fixtures(empty, out)
    assert res_missing["loaded"] is False
    assert "no main.py" in res_missing["load_error"]
    assert res_missing["legality_gate"] is False

    # A main.py whose agent always raises: every fixture recorded as a failure,
    # the run does not crash.
    crashing = tmp_path / "crashing_candidate"
    crashing.mkdir()
    (crashing / "main.py").write_text(
        "def agent(obs):\n    raise RuntimeError('boom')\n", encoding="utf-8"
    )
    res_crash = runner.evaluate_candidate_on_fixtures(crashing, out)
    assert res_crash["loaded"] is True
    assert res_crash["legality_gate"] is False
    assert all(fx["error"] for fx in res_crash["fixtures"])
    assert all(fx["legal"] is False for fx in res_crash["fixtures"])


# --------------------------------------------------------------------------
# Pass 6 — policy v3 (board-aware scoring + decline layer) + fixture gate
# --------------------------------------------------------------------------

_PASS6_IDS = {
    "pass6_control_v2_anchor",
    "policy_effect_resolution_v3",
    "policy_secret_box_safety_v1",
    "policy_deckout_guard_v2",
    "policy_attachment_targeting_v1",
    "combo_effect_resolution_v3__deckout_guard_v2",
    "combo_effect_resolution_v3__secret_box_safety",
    "combo_full_v3",
}


def test_plan_pass6_anchor_first_all_specs_generation_six():
    cfg = config_mod.load_config()
    plan = generator.plan_pass6(cfg)
    assert {p["branch_id"] for p in plan} == _PASS6_IDS
    # The v2 control anchor is always first; everything is generation 6, testable.
    assert plan[0]["branch_id"] == "pass6_control_v2_anchor"
    assert all(p["generation"] == 6 for p in plan)
    assert all(p["testable"] for p in plan)


def test_pass6_specs_are_v2_deck_combos_with_valid_rule_shapes():
    for spec in generator.PASS6_COMBO_SPECS:
        assert spec["deck_ref"] == generator._V2_DECK_REF
        assert spec.get("policy_refs") == []
        assert spec["hypothesis"]
        # decline rules, when present, only use the two confirmed knobs.
        for k in spec.get("p6_rules", {}):
            assert k in {"deckout_decline_threshold", "decline_mega_signal_no_snover"}


def test_pass6_anchor_is_pure_v2_control(tmp_path):
    spec = next(s for s in generator.PASS6_COMBO_SPECS
                if s["branch_id"] == "pass6_control_v2_anchor")
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="p6anchor"
    )
    cand_src = _read(Path(b.run_dir) / "main.py")
    # No scoring mutation, no p5/p6 blocks: behaviour is the pure v2 mirror.
    assert ".update(" not in cand_src
    assert "PASS5 BOARD-AWARE OVERRIDE" not in cand_src
    assert "PASS6 DECLINE OVERRIDE" not in cand_src
    from ptcg_activegraph.decks.deck_io import load_deck
    counts = Counter(load_deck(Path(b.run_dir) / "deck.csv"))
    assert counts[721] == 4 and counts[1121] == 4


def test_pass6_decline_candidate_injects_p6_block_and_records_rules(tmp_path):
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    spec = next(s for s in generator.PASS6_COMBO_SPECS
                if s["branch_id"] == "policy_effect_resolution_v3")
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="p6er3"
    )
    # Root files untouched.
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck
    cand_src = _read(Path(b.run_dir) / "main.py")
    assert "PASS6 DECLINE OVERRIDE" in cand_src
    assert "_embedded_agent = _p6_embedded" in cand_src
    # The recorded policy carries both the p5 scoring rules and the p6 decline rules.
    assert b.policy_overrides["p6_rules"]["decline_mega_signal_no_snover"] is True
    assert b.policy_overrides["p5_rules"]["discard_avoid_ids"] == [722, 723, 721]


def test_pass6_attachment_targeting_applies_inline_overrides(tmp_path):
    spec = next(s for s in generator.PASS6_COMBO_SPECS
                if s["branch_id"] == "policy_attachment_targeting_v1")
    b = generator.generate_combo_candidate(
        spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path, ts="p6att"
    )
    cand_src = _read(Path(b.run_dir) / "main.py")
    # Inline keyword/option-type overrides (no policy_refs) must still render.
    assert "_OPTION_TYPE_SCORES.update(" in cand_src
    assert "_POSITIVE.update(" in cand_src
    # It carries no decline layer (different seam).
    assert "PASS6 DECLINE OVERRIDE" not in cand_src


def test_pass6_candidates_pass_fixture_legality_gate(tmp_path):
    runner = _load_script("test_candidate_on_fixtures")
    _extract, out, _written = _extract_to(tmp_path)
    cfg = config_mod.load_config()
    runs = tmp_path / "runs"
    for item in generator.plan_pass6(cfg):
        spec = item["spec"]
        b = generator.generate_combo_candidate(
            spec, BASELINE_MAIN, BASELINE_DECK, runs_root=runs, ts="gate"
        )
        res = runner.evaluate_candidate_on_fixtures(b.run_dir, out)
        assert res["loaded"] is True, spec["branch_id"]
        # HARD gate: every Pass-6 candidate must be legal on every fixture.
        assert res["legality_gate"] is True, spec["branch_id"]
        for fx in res["fixtures"]:
            assert fx["legal"] is True, (spec["branch_id"], fx["id"])


def test_pass6_decline_layer_flips_replay_preferences(tmp_path):
    """The decline layer fixes the step-17 / step-112 failures the v2 anchor misses."""
    runner = _load_script("test_candidate_on_fixtures")
    _extract, out, _written = _extract_to(tmp_path)
    runs = tmp_path / "runs"

    def _grade(branch_id):
        spec = next(s for s in generator.PASS6_COMBO_SPECS
                    if s["branch_id"] == branch_id)
        b = generator.generate_combo_candidate(
            spec, BASELINE_MAIN, BASELINE_DECK, runs_root=runs, ts=branch_id[:6]
        )
        res = runner.evaluate_candidate_on_fixtures(b.run_dir, out)
        return {fx["id"]: fx["preference"]["result"] for fx in res["fixtures"]}

    # The v2 anchor reproduces the baseline failures.
    anchor = _grade("pass6_control_v2_anchor")
    assert anchor["step17_mega_signal_search"] == "fail"
    assert anchor["step112_low_deck_search"] == "fail"

    # effect_resolution_v3 declines the dead Mega fetch (step 17).
    er3 = _grade("policy_effect_resolution_v3")
    assert er3["step17_mega_signal_search"] == "pass"
    assert er3["step28_ultra_ball_discard"] == "pass"

    # deckout_guard_v2 declines the search-into-deckout (step 112).
    dg2 = _grade("policy_deckout_guard_v2")
    assert dg2["step112_low_deck_search"] == "pass"

    # The full combo flips every gradable preference (forced step 11 stays na).
    full = _grade("combo_full_v3")
    assert full["step17_mega_signal_search"] == "pass"
    assert full["step112_low_deck_search"] == "pass"
    assert full["step28_ultra_ball_discard"] == "pass"
    assert full["setup_active_choice"] == "pass"
    assert full["step11_secret_box_discard"] == "na"


# --------------------------------------------------------------------------
# Pass 6 — deck variants around v2 (single confirmed-id swaps)
# --------------------------------------------------------------------------

_PASS6_DECK_IDS = {
    "deck_v2_no_secret_box__powerglass",
    "deck_v2_no_secret_box__mega_signal",
    "deck_v2_no_secret_box__surfing_beach",
    "deck_v2_less_petrel__powerglass",
}


def test_plan_pass6_decks_lists_all_variants_generation_six():
    cfg = config_mod.load_config()
    plan = generator.plan_pass6_decks(cfg)
    assert {p["branch_id"] for p in plan} == _PASS6_DECK_IDS
    assert all(p["track"] == "deck" and p["generation"] == 6 for p in plan)
    # The v2 exact deck is an anchor and must NOT appear in the deck-variant plan.
    assert "deck_energy_trim_light" not in {p["branch_id"] for p in plan}


def test_pass6_deck_variants_are_legal_sixty_card_decks(tmp_path):
    from ptcg_activegraph.cards import load_card_db
    from ptcg_activegraph.decks.deck_io import load_deck
    cdb = load_card_db()
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    for spec in generator.PASS6_DECK_SPECS:
        # Deltas are zero-sum (60-card preserving) and only touch confirmed ids.
        assert sum(spec["deltas"].values()) == 0, spec["branch_id"]
        b = generator.generate_deck_candidate(
            spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path,
            card_db=cdb, ts="dv",
        )
        ids = load_deck(Path(b.run_dir) / "deck.csv")
        assert len(ids) == 60, spec["branch_id"]
        counts = Counter(ids)
        # No non-energy card exceeds 4 copies.
        over = {c: n for c, n in counts.items() if c != generator.ENERGY_ID and n > 4}
        assert not over, (spec["branch_id"], over)
        # Deck candidates reuse the exact baseline runtime policy (main unchanged).
        assert _read(Path(b.run_dir) / "main.py") == before_main
    # Root files never mutated.
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck


def test_pass6_secret_box_swaps_remove_secret_box_and_add_target(tmp_path):
    from ptcg_activegraph.cards import load_card_db
    from ptcg_activegraph.decks.deck_io import load_deck
    cdb = load_card_db()
    expected_add = {
        "deck_v2_no_secret_box__powerglass": 1163,
        "deck_v2_no_secret_box__mega_signal": 1145,
        "deck_v2_no_secret_box__surfing_beach": 1262,
    }
    for bid, add_id in expected_add.items():
        spec = next(s for s in generator.PASS6_DECK_SPECS if s["branch_id"] == bid)
        b = generator.generate_deck_candidate(
            spec, BASELINE_MAIN, BASELINE_DECK, runs_root=tmp_path,
            card_db=cdb, ts="sb",
        )
        counts = Counter(load_deck(Path(b.run_dir) / "deck.csv"))
        assert counts.get(1092, 0) == 0, bid          # Secret Box cut entirely
        assert counts[add_id] == 3, (bid, add_id)      # swap target now at 3


# --------------------------------------------------------------------------
# Pass 6 (Part H) — buildable chaos candidates + honest blocked entry
# --------------------------------------------------------------------------

def test_plan_pass6_chaos_lists_buildable_then_blocked():
    cfg = config_mod.load_config()
    plan = generator.plan_pass6_chaos(cfg)
    by_id = {p["branch_id"]: p for p in plan}
    assert {"chaos_v6_froslass_handcount", "chaos_v6_durant_mill"} <= set(by_id)
    # Buildable specs are testable; bench-bloat stays blocked with a real reason.
    assert by_id["chaos_v6_froslass_handcount"]["testable"] is True
    assert by_id["chaos_v6_durant_mill"]["testable"] is True
    blocked = by_id["chaos_v6_bench_bloat_punisher"]
    assert blocked["testable"] is False
    assert blocked["reason"] and "unconfirmed" in blocked["reason"]
    # Blocked entries always sort after the testable ones.
    assert all(p["generation"] == 6 for p in plan)
    testable_idx = [i for i, p in enumerate(plan) if p["testable"]]
    blocked_idx = [i for i, p in enumerate(plan) if not p["testable"]]
    assert max(testable_idx) < min(blocked_idx)


def test_pass6_chaos_specs_use_only_confirmed_ids_and_matching_energy():
    from ptcg_activegraph.cards import load_card_db
    cdb = load_card_db()
    for spec in generator.PASS6_CHAOS_SPECS:
        counts = spec["deck_counts"]
        assert sum(counts.values()) == 60, spec["branch_id"]
        for cid in counts:
            feats = cdb.basic_features(cid)
            # Every id must resolve in the confirmed card metadata (no invented ids).
            assert feats.get("found", False), (spec["branch_id"], cid)
        # At least one Basic Pokémon must be present (legal opening).
        assert any(
            cdb.basic_features(cid).get("is_basic", False) for cid in counts
        ), spec["branch_id"]


def test_generate_chaos_candidate_is_legal_and_leaves_root_untouched(tmp_path):
    from ptcg_activegraph.cards import load_card_db
    from ptcg_activegraph.decks.deck_io import load_deck
    cdb = load_card_db()
    before_main, before_deck = _read(BASELINE_MAIN), _read(BASELINE_DECK)
    for spec in generator.PASS6_CHAOS_SPECS:
        b = generator.generate_chaos_candidate(
            spec, BASELINE_MAIN, runs_root=tmp_path, card_db=cdb, ts="ch",
        )
        ids = load_deck(Path(b.run_dir) / "deck.csv")
        assert len(ids) == 60, spec["branch_id"]
        # No NON-basic-energy card exceeds 4 copies (basic energy is unlimited).
        over = generator._illegal_copy_counts(ids, cdb)
        assert not over, (spec["branch_id"], over)
        # Chaos candidates carry the exact baseline runtime policy.
        assert _read(Path(b.run_dir) / "main.py") == before_main
    assert _read(BASELINE_MAIN) == before_main
    assert _read(BASELINE_DECK) == before_deck


def test_basic_energy_copy_limit_recognizes_non_default_energy(tmp_path):
    from ptcg_activegraph.cards import load_card_db
    cdb = load_card_db()
    # Basic {G} Energy (id 1) is NOT the deck's default {W} energy (id 3); a stack
    # of 28 must still be allowed (regression: previously only id 3 was exempt).
    deck = [198] * 4 + [1] * 56
    assert generator._is_basic_energy(1, cdb) is True
    assert generator._illegal_copy_counts(deck, cdb) == {}


# --------------------------------------------------------------------------
# Part I/J: Pass 6 two-stage pipeline (pure pieces, no cabt)
# --------------------------------------------------------------------------
def test_pass6_plan_combines_tracks_and_excludes_blocked():
    from ptcg_activegraph.experiments import pass6_pipeline as p6
    testable = p6.pass6_testable_branch_ids()
    blocked = p6.pass6_blocked_branch_ids()
    # Each declared spec family is represented and the blocked chaos is NOT.
    assert "combo_full_v3" in testable
    assert "deck_v2_no_secret_box__powerglass" in testable
    assert "chaos_v6_froslass_handcount" in testable
    assert "chaos_v6_durant_mill" in testable
    assert "chaos_v6_bench_bloat_punisher" in blocked
    assert "chaos_v6_bench_bloat_punisher" not in testable
    assert set(testable).isdisjoint(set(blocked))


def test_stage0_gate_keys_by_branch_id_and_filters_survivors(tmp_path):
    from ptcg_activegraph.experiments import pass6_pipeline as p6
    # Two fake run dirs, each with a branch.yaml carrying the real branch_id.
    def _mk(name, bid):
        rd = tmp_path / name
        rd.mkdir()
        (rd / "branch.yaml").write_text(
            f"branch_id: {bid}\nname: {bid}\nparent: root\n"
            f"seam_id: seam_x\nfamily: fam_x\n", encoding="utf-8")
        return rd
    good = _mk("20260101_00_good", "cand_good")
    bad = _mk("20260101_01_bad", "cand_bad")

    def fake_eval(run_dir, fixtures_dir):
        passed = run_dir.name.endswith("good")
        return {"run_dir": str(run_dir), "legality_gate": passed,
                "preference_pass": 2, "preference_fail": 0, "preference_na": 3}

    gate = p6.stage0_fixture_gate([good, bad], tmp_path, evaluator=fake_eval)
    # Keyed by real branch_id (NOT the timestamped dir name).
    assert set(gate.keys()) == {"cand_good", "cand_bad"}
    assert p6.stage0_survivors(gate) == ["cand_good"]


def test_select_top3_excludes_controls_and_rejected():
    from ptcg_activegraph.experiments import pass6_pipeline as p6
    ranked = [
        {"branch_id": "v2_anchor", "is_control": True, "candidate_rank": None,
         "rejected": False},
        {"branch_id": "c1", "is_control": False, "candidate_rank": 1,
         "rejected": False},
        {"branch_id": "c2", "is_control": False, "candidate_rank": 2,
         "rejected": False},
        {"branch_id": "c3", "is_control": False, "candidate_rank": 3,
         "rejected": False},
        {"branch_id": "c4", "is_control": False, "candidate_rank": 4,
         "rejected": False},
        {"branch_id": "bad", "is_control": False, "candidate_rank": None,
         "rejected": True},
    ]
    top = p6.select_top3(ranked, n=3)
    assert [e["branch_id"] for e in top] == ["c1", "c2", "c3"]


def test_build_dry_run_queue_forces_max1_and_never_uploads(tmp_path, monkeypatch):
    from ptcg_activegraph.experiments import pass6_pipeline as p6
    from ptcg_activegraph.experiments import queue as queue_mod
    # Keep the queue output + tarballs hermetic so the real
    # data/submission_queue.json artifact is never clobbered by the suite.
    monkeypatch.setattr(queue_mod, "QUEUE_JSON", tmp_path / "queue.json")
    monkeypatch.setattr(queue_mod, "CANDIDATES_DIR", tmp_path / "candidates")
    cfg = config_mod.load_config()
    # Safety preconditions hold by default.
    assert not cfg.settings.get("auto_submit_enabled", False)
    ranked = [
        {"branch_id": "cand_a", "kind": "policy", "label": "promotable",
         "score": 0.9, "is_control": False, "rejected": False,
         "candidate_rank": 1, "games": 40, "win_rate": 0.6},
        {"branch_id": "cand_b", "kind": "policy", "label": "promotable",
         "score": 0.8, "is_control": False, "rejected": False,
         "candidate_rank": 2, "games": 40, "win_rate": 0.58},
    ]
    plan = p6.build_dry_run_queue(ranked, cfg, {}, max_per_day=1)
    assert plan["will_upload"] is False
    assert plan["mode"].upper().startswith("DRY")
    assert len(plan["candidates"]) <= 1


def test_build_dry_run_queue_refuses_when_auto_submit_enabled():
    from ptcg_activegraph.experiments import pass6_pipeline as p6
    cfg = config_mod.load_config()
    cfg.settings = {**dict(cfg.settings), "auto_submit_enabled": True}
    with pytest.raises(RuntimeError):
        p6.build_dry_run_queue([], cfg, {}, max_per_day=1)
