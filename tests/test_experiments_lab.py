"""Tests for the ActiveGraph strategy lab (experiments package + scripts).

These avoid the heavy cabt engine: candidate generation, ranking, queueing and
reporting are all exercised on synthetic metrics / fixtures, so they run fast and
deterministically. The one cabt-dependent path (the runner's actual game loop) is
covered by the live batch run, not here.
"""

from __future__ import annotations

import json
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
    from collections import Counter

    counts = Counter(e.event_type for e in all_events)
    assert counts["IdeaGenerated"] == 2 and counts["BaselineRegistered"] == 1
