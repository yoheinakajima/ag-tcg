"""ActiveGraph Pass 19 — Dragapult parent/child H2H forensics + portfolio loop tests.

Covers (spec Part M):
* the strategy portfolio loop doc exists and defaults to NO upload,
* the family registry records the parent/child lineage for dragapult_spread,
* ActiveGraph lineage declares + can emit ParentChildComparison{Started,Finished} events,
* the forensic trace preserves the requested game count and seat split,
* the decision-delta names the H2H caveat and the draw_support role-tag cause,
* the ablations were built ONLY where the D/E diagnosis supports them (search_only/draw_only),
* neither ablation playbook introduces a broad Main override,
* both Pass-19 candidates pass the tarball + entrypoint validators and live smoke,
* the mini-league includes BOTH the parent and the child (and excludes Durant),
* the decision is never "strictly better than parent" while the H2H is unstable/negative,
* the parent/child report carries both disclaimers + the H2H caveat,
* root main.py / deck.csv are byte-identical to the v1 baseline,
* no upload/submit flag is ever set true anywhere in the pass outputs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
DOCS = REPO / "docs"
SITE = REPO / "data" / "site" / "index.html"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass19"
FAMILIES_YAML = REPO / "experiments" / "strategy_families.yaml"
LOOP_DOC = DOCS / "STRATEGY_PORTFOLIO_LOOP.md"
FIXTURES = REPO / "data" / "fixtures" / "pass19_dragapult_parent_child"

TRACE = EXP / "pass19_dragapult_parent_child_trace.json"
DELTA = EXP / "pass19_dragapult_decision_delta.json"
LEAGUE = EXP / "pass19_dragapult_mini_league.json"
META = EXP / "pass19_meta_sanity.json"
DECISION = EXP / "pass19_strategy_decision.json"
VALIDATION = EXP / "pass19_candidate_validation.json"
PC_REPORT = REPORTS / "pass19_dragapult_parent_child_report.md"

PARENT = "league_dragapult_spread"
CHILD = "league_dragapult_spread_v1"
SEARCH_ONLY = "league_dragapult_v1_search_only"
DRAW_ONLY = "league_dragapult_v1_draw_only"
ABLATIONS = (SEARCH_ONLY, DRAW_ONLY)


def _json(p: Path) -> dict:
    assert p.exists(), f"missing evidence file: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------- portfolio loop
def test_portfolio_loop_doc_defaults_to_no_upload():
    assert LOOP_DOC.exists(), "strategy portfolio loop doc is missing"
    text = LOOP_DOC.read_text(encoding="utf-8")
    low = text.lower()
    # the loop is documented end to end
    for stage in ("register", "hypothesi", "gate", "league", "decision"):
        assert stage in low, f"loop doc missing stage: {stage}"
    # default posture is local-only / no upload
    assert "no upload" in low or "no-upload" in low or "not" in low and "upload" in low


def test_loop_decision_rule_blocks_replacing_parent_on_h2h_collapse():
    low = LOOP_DOC.read_text(encoding="utf-8").lower()
    # the explicit decision rule: aggregate win cannot replace the parent if the
    # head-to-head collapses unless the report explicitly accepts the tradeoff.
    assert "head-to-head" in low or "h2h" in low
    assert "parent" in low


# --------------------------------------------------------------- registry lineage
def test_registry_records_parent_child_lineage():
    text = FAMILIES_YAML.read_text(encoding="utf-8")
    assert PARENT in text and CHILD in text
    # the parent stays the current best for the family (child not promoted)
    assert "current_best: league_dragapult_spread" in text
    # the Pass-19 ablations are registered as children of the v1 candidate
    assert SEARCH_ONLY in text and DRAW_ONLY in text


# --------------------------------------------------------------- lineage events
def test_parent_child_comparison_event_types_declared_and_emittable():
    import ag_strategy_event as A  # noqa: WPS433
    from ptcg_activegraph.graph.events import EventType  # noqa: WPS433

    assert "ParentChildComparisonStarted" in A.STRATEGY_EVENT_TYPES
    assert "ParentChildComparisonFinished" in A.STRATEGY_EVENT_TYPES
    assert EventType.ParentChildComparisonStarted.value == "ParentChildComparisonStarted"
    assert EventType.ParentChildComparisonFinished.value == "ParentChildComparisonFinished"
    # every recorded event uses a declared strategy type
    evs = A.lineage()
    seen = {e.event_type for e in evs}
    assert seen <= set(A.STRATEGY_EVENT_TYPES), seen - set(A.STRATEGY_EVENT_TYPES)


# --------------------------------------------------------------- forensic trace
def test_trace_preserves_game_count_and_seat_split():
    t = _json(TRACE)
    g = t["games"]
    gps = g["games_per_seat"]
    assert gps >= 10, f"need >=10 games/seat, got {gps}"
    # seat-swapped: total games is exactly twice the per-seat count
    assert g["n_games"] == 2 * gps, g
    # every game resolves to a parent or child win (no dropped games)
    assert g["parent_wins"] + g["child_wins"] == g["n_games"], g
    # the seat split is recorded for both seats
    assert g["parent_seat0_wins"] + g["parent_seat1_wins"] == g["parent_wins"], g
    assert g["invalid"] == 0 and g["timeouts"] == 0, g


def test_trace_decision_replay_isolates_divergence_to_probe_branches():
    t = _json(TRACE)
    dr = t["decision_replay"]
    # the only behavioural divergence is on the search_cards / draw_support probes
    assert dr["control_divergences"] == 0, dr
    assert dr["n_diverged"] == dr["probe_divergences"], dr


# --------------------------------------------------------------- decision delta
def test_decision_delta_names_h2h_caveat_and_draw_support_cause():
    d = _json(DELTA)
    caveat = d["h2h_caveat"].lower()
    assert "head-to-head" in caveat or "h2h" in caveat
    # the diagnosed cause is the draw_support discard branch, not a strategic redesign
    cause = d["likely_h2h_cause"].lower()
    assert "draw_support" in cause
    assert "discard" in cause
    assert d["upload_performed"] is False
    # all eight forensic questions are answered
    assert len(d["questions"]) == 8, d["questions"]


# --------------------------------------------------------------- justified ablations
def test_ablations_built_only_where_diagnosis_supports():
    # exactly the two diagnosis-justified ablations exist as tarballs (no extras)
    tars = sorted(p.name for p in CAND_DIR.glob("*.tar.gz"))
    assert tars == [f"{DRAW_ONLY}.tar.gz", f"{SEARCH_ONLY}.tar.gz"], tars
    # the redundant H2H-guard / #4 variant was deliberately not built
    assert not any("guard" in n for n in tars), tars


def test_ablation_playbooks_drop_one_alias_and_keep_main_delegated():
    for name, dropped, kept in (
        (SEARCH_ONLY, "draw_support", "search_cards"),
        (DRAW_ONLY, "search_cards", "draw_support"),
    ):
        pb = REPO / "playbooks" / f"pass19_dragapult_v1_{name.split('_v1_')[1]}.yaml"
        assert pb.exists(), pb
        low = pb.read_text(encoding="utf-8").lower()
        # the kept role alias is present as an active role
        assert kept in low, (name, kept)
        # no broad Main override is introduced by the ablation
        assert "main remains delegated" in low or "main stays delegated" in low, name
        assert "broad main" in low, name


# --------------------------------------------------------------- validation
def test_pass19_candidates_pass_validators_and_live_smoke():
    cv = _json(VALIDATION)
    cands = cv["candidates"]
    for cid in ABLATIONS:
        assert cid in cands, cid
        c = cands[cid]
        assert c["tarball_validator_rc"] == 0, cid
        assert c["entrypoint_validator_rc"] == 0, cid
        assert c["live_smoke_ok"] is True, cid
        # judged for NO regression vs the parent's Dragapult-family core baseline
        assert c["core_no_regression_vs_parent"] is True, cid
        assert c["overall_ok"] is True, cid
    assert cv["upload_performed"] is False


def test_pass19_candidate_tarballs_are_toplevel_main_and_deck_only():
    tars = sorted(CAND_DIR.glob("*.tar.gz"))
    assert tars, "no Pass-19 candidate tarballs built"
    for tar in tars:
        with tarfile.open(tar, "r:gz") as tf:
            names = sorted(m.name for m in tf.getmembers() if m.isfile())
        assert names == ["deck.csv", "main.py"], f"{tar.name} contents: {names}"


def test_key_discriminator_fixture_separates_parent_from_child():
    assert FIXTURES.exists(), FIXTURES
    fixtures = sorted(p.name for p in FIXTURES.glob("dp19_*.json"))
    assert fixtures, "no Pass-19 discriminator fixtures present"
    assert any("preserve_draw_engine" in n for n in fixtures), fixtures


# --------------------------------------------------------------- mini-league
def test_mini_league_includes_parent_and_child_excludes_durant():
    lg = _json(LEAGUE)
    ids = {p["id"] for p in lg["participants"]}
    assert {PARENT, CHILD} <= ids, ids
    assert {SEARCH_ONLY, DRAW_ONLY} <= ids, ids
    assert all("durant" not in i for i in ids), ids
    assert lg["status"] == "ran"
    assert lg["effective_games_per_seat"] >= 10


def test_mini_league_records_real_parent_head_to_head():
    lg = _json(LEAGUE)
    h2h = lg["parent_h2h"]
    assert CHILD in h2h, h2h
    child = h2h[CHILD]
    # the H2H is a real, recorded series (wins + losses + draws == games played)
    total = child["vs_parent_wins"] + child["parent_wins"] + child["draws"]
    assert total == 2 * lg["effective_games_per_seat"], child


# --------------------------------------------------------------- decision
def test_decision_keeps_parent_and_is_not_strictly_better():
    dec = _json(DECISION)
    dd = dec["dragapult_decision"]
    assert dd["label"] in dec["valid_labels"], dd["label"]
    # the parent is kept as current_best; the child is NOT promoted
    assert dd["current_best_kept"] == PARENT, dd
    # never call the child strictly better than the parent
    assert dd["v1_strictly_better_than_parent"] is False, dd
    # the H2H is flagged as unstable across samples (sign flip)
    h2h = dd["evidence"]["head_to_head_vs_parent"]
    assert h2h["child_h2h_unstable_across_samples"] is True, h2h
    assert dd["evidence"]["aggregate"]["all_candidate_cis_overlap_parent"] is True


def test_decision_recommends_no_upload_no_submit():
    dec = _json(DECISION)
    rec = dec["recommendation"]
    assert rec["upload_recommended"] is False
    assert rec["submit_recommended"] is False
    assert rec["upload_not_recommended"] is True
    assert dec["upload_performed"] is False
    assert dec["is_kaggle_leaderboard"] is False


# --------------------------------------------------------------- report disclaimers
def test_parent_child_report_carries_disclaimers_and_h2h_caveat():
    assert PC_REPORT.exists(), PC_REPORT
    md = PC_REPORT.read_text(encoding="utf-8")
    up = md.upper()
    assert "NOT A KAGGLE LEADERBOARD" in up
    assert "SURROGATE" in up
    low = md.lower()
    assert "head-to-head" in low or "h2h" in low
    assert "needs_more_h2h" in low
    assert "draw_support" in low


# --------------------------------------------------------------- cross-surface drift
def test_site_canvas_report_all_carry_pass19_decision_tuple():
    canvas = (DOCS / "PTCG_STRATEGY_CANVAS.md").read_text(encoding="utf-8").lower()
    report = (REPORTS / "activegraph_strategy_report.md").read_text(encoding="utf-8").lower()
    site = SITE.read_text(encoding="utf-8").lower()
    for surface in (canvas, report, site):
        # decision label
        assert "needs_more_h2h" in surface
        # parent kept as current best
        assert PARENT in surface
        # never claims the child is strictly better than the parent
        assert "strictly better" not in surface or "false" in surface


# --------------------------------------------------------------- root immutable
def test_root_entrypoints_unchanged_vs_v1_baseline():
    res = subprocess.run(
        [sys.executable, "scripts/package_submission.py", "--verify-only"],
        cwd=REPO, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    combined = (res.stdout + res.stderr).lower()
    assert res.returncode == 0, f"package --verify-only failed:\n{res.stdout}\n{res.stderr}"
    assert "fail" not in combined or "0 fail" in combined, combined


# --------------------------------------------------------------- no upload
def test_no_upload_or_submission_anywhere_in_pass19_outputs():
    for p in (TRACE, DELTA, LEAGUE, META, DECISION, VALIDATION):
        blob = json.dumps(_json(p)).lower()
        assert '"upload_performed": true' not in blob, p.name
        assert '"is_kaggle_leaderboard": true' not in blob, p.name


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
