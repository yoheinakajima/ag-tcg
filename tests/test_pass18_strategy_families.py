"""ActiveGraph Pass 18 — strategy family registry + targeted iteration tests.

Covers (spec Part O):
* the strategy family registry schema (5 families, statuses, current_best, no-upload),
* ActiveGraph iteration lineage emits the expected strategy event types,
* the Raging Bolt diagnosis records a deck/structural verdict (NOT energy/tempo),
* the Dragapult v1 playbook adds role recognition only (no aggro hook, no Play override),
* the targeted fixtures all pass and the candidate clears the no-regression-vs-parent gate,
* Durant is excluded from the league (chaos-research-only),
* candidate tarballs are top-level main.py + deck.csv only and pass the entrypoint gate,
* the league + meta sanity produce the recorded standings and the v1-vs-parent caveat,
* root main.py / deck.csv are byte-identical to the v1 baseline,
* no upload/submit flag is ever set true anywhere in the pass outputs,
* the league / meta / decisions / site all carry the explicit "not a Kaggle leaderboard" disclaimer.
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
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass18"
FAMILIES_YAML = REPO / "experiments" / "strategy_families.yaml"
PLAYBOOK = REPO / "playbooks" / "pass18_dragapult_spread_v1.yaml"
FIXTURES = REPO / "data" / "fixtures" / "pass18_dragapult_spread"

REG = EXP / "pass18_strategy_family_registry.json"
DIAG = EXP / "pass18_raging_bolt_diagnosis.json"
CV = EXP / "pass18_candidate_validation.json"
LG = EXP / "pass18_internal_league.json"
RK = EXP / "pass18_league_rankings.json"
MS = EXP / "pass18_meta_sanity.json"
DEC = EXP / "pass18_strategy_decisions.json"

CANDIDATE = "league_dragapult_spread_v1"
PARENT = "league_dragapult_spread"


def _json(p: Path) -> dict:
    assert p.exists(), f"missing evidence file: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------- registry schema
def test_registry_has_five_families_with_required_fields():
    reg = _json(REG)
    assert reg["family_count"] == 5
    fams = {f["family_id"]: f for f in reg["families"]}
    expected = {
        "water_kyogre_abomasnow",
        "dragapult_spread",
        "raging_bolt_ogerpon",
        "durant_deckout_carousel",
        "future_high_ceiling_evolution",
    }
    assert set(fams) == expected
    for f in fams.values():
        assert f["status"], f
        assert "hypothesis" in f and f["hypothesis"].strip()
        assert "next_experiment" in f
    assert reg["upload_performed"] is False
    # registry is sourced from the YAML registry-of-truth
    assert FAMILIES_YAML.exists()


def test_registry_statuses_match_decisions():
    reg = {f["family_id"]: f for f in _json(REG)["families"]}
    assert reg["water_kyogre_abomasnow"]["status"] == "active_reference"
    assert reg["dragapult_spread"]["current_best"].startswith(PARENT)
    assert reg["durant_deckout_carousel"]["status"] == "chaos_research_blocked"


# --------------------------------------------------------------- lineage events
def test_lineage_emits_expected_strategy_event_types():
    import ag_strategy_event as A  # noqa: WPS433

    evs = A.lineage()
    assert evs, "no ActiveGraph strategy events recorded"
    seen = {e.event_type for e in evs}
    required = {
        "StrategyFamilyRegistered",
        "StrategyHypothesisLogged",
        "StrategyDecisionRecorded",
        "StrategyPromotionDecision",
    }
    missing = required - seen
    assert not missing, f"missing strategy events: {missing}"
    # every emitted type is a declared strategy event type
    assert seen <= set(A.STRATEGY_EVENT_TYPES), seen - set(A.STRATEGY_EVENT_TYPES)
    # at least one family registration per registered family (events accumulate across runs)
    fam_regs = [e for e in evs if e.event_type == "StrategyFamilyRegistered"]
    fams = {e.payload.get("family_id") for e in fam_regs}
    assert len(fams) >= 5, fams


# --------------------------------------------------------------- diagnosis
def test_raging_bolt_diagnosis_is_deck_structural_not_energy_or_tempo():
    d = _json(DIAG)
    # explicit structured verdict: the failure is deck/structural ...
    assert "structural" in d["core_failure"].lower(), d["core_failure"]
    # ... NOT an energy color-matching gap (correct energy is reached) ...
    assert "correct energy" in d["energy_matching"].lower(), d["energy_matching"]
    # ... and NOT an attack-first pilot gap (attacks are taken when offered).
    assert "attack" in d["attack_first"].lower(), d["attack_first"]
    # therefore the aggro rescue (Parts E/F) is not justified
    assert d["rescue_justified"] is False
    assert d["upload_performed"] is False


# --------------------------------------------------------------- playbook (no aggro hook)
def test_dragapult_playbook_adds_roles_only_no_aggro_hook():
    assert PLAYBOOK.exists()
    text = PLAYBOOK.read_text(encoding="utf-8")
    low = text.lower()
    # the targeted refinement is role recognition only
    assert "search_cards" in low
    assert "draw_support" in low
    # no aggro runtime hook (Parts E/F were not built) and no Play override
    assert "aggro_energy_attach" not in low
    assert "attack_when_online" not in low


# --------------------------------------------------------------- fixtures + gate
def test_targeted_fixtures_present_and_pass():
    fixtures = sorted(FIXTURES.glob("dp_*.json"))
    assert len(fixtures) == 5, [f.name for f in fixtures]
    cv = _json(CV)
    cand = next(c for c in cv["candidates"] if c["candidate_id"] == CANDIDATE)
    tgt = cand["targeted_fixture_gate"]
    assert tgt["passed"] is True
    assert tgt["passed_count"] == tgt["total"] == 5, tgt


def test_candidate_clears_no_regression_vs_parent_gate():
    cv = _json(CV)
    cand = next(c for c in cv["candidates"] if c["candidate_id"] == CANDIDATE)
    # core fixtures: candidate must not regress vs parent
    core = cand["core_fixture_gate"]
    assert core["passed_count"] >= core["parent_passed_count"], core
    assert core["no_regression_vs_parent"] is True
    assert cand["core_no_regression_vs_parent"] is True
    assert cand["league_eligible"] is True
    assert CANDIDATE in cv["league_eligible"]


# --------------------------------------------------------------- tarball + entrypoint
def test_candidate_tarball_is_toplevel_main_and_deck_only():
    tars = sorted(CAND_DIR.glob("*.tar.gz"))
    assert tars, "no candidate tarballs built"
    for tar in tars:
        with tarfile.open(tar, "r:gz") as tf:
            names = sorted(m.name for m in tf.getmembers() if m.isfile())
        assert names == ["deck.csv", "main.py"], f"{tar.name} contents: {names}"


def test_candidate_passes_tarball_and_entrypoint_gates():
    cv = _json(CV)
    cand = next(c for c in cv["candidates"] if c["candidate_id"] == CANDIDATE)
    assert cand["tarball_gate"]["passed"]
    assert cand["entrypoint_gate"]["passed"]
    assert cand["live_smoke_self"]["ok"]


# --------------------------------------------------------------- durant excluded
def test_durant_is_excluded_from_league():
    lg = _json(LG)
    assert all("durant" not in p["id"] for p in lg["participants"])
    reg = {f["family_id"]: f for f in _json(REG)["families"]}
    assert reg["durant_deckout_carousel"]["status"] == "chaos_research_blocked"


# --------------------------------------------------------------- league standings
def test_league_standings_v1_first_but_loses_parent_head_to_head():
    rk = _json(RK)
    standings = rk["standings"]
    top = standings[0]
    assert top["id"] == CANDIDATE, top
    # v1 ranks #1 on aggregate adjusted win rate
    parent = next(s for s in standings if s["id"] == PARENT)
    assert top["adj_win_rate"] >= parent["adj_win_rate"]
    # critical nuance: v1 LOSES the direct head-to-head vs its parent
    lg = _json(LG)
    h2h = None
    for m in lg["matchups"]:
        if m["a"] == CANDIDATE and m["b"] == PARENT:
            h2h = m["a_win_rate"]
        elif m["a"] == PARENT and m["b"] == CANDIDATE:
            h2h = 1.0 - m["a_win_rate"]
    assert h2h is not None, "no v1-vs-parent matchup recorded"
    assert h2h < 0.5, f"v1 should lose the parent head-to-head, got {h2h}"


# --------------------------------------------------------------- meta sanity
def test_meta_sanity_passed_and_v1_does_not_trail_water():
    ms = _json(MS)
    assert ms["sanity"]["sanity_passed"] is True
    assert ms["sanity"]["candidate_weighted_meta_score"] >= ms["sanity"]["water_weighted_meta_score"]
    blob = json.dumps(ms).lower()
    assert '"upload_performed": true' not in blob


# --------------------------------------------------------------- decisions
def test_decisions_recommend_dry_run_only_no_upload():
    dec = _json(DEC)
    assert dec["upload_performed"] is False
    assert dec["is_kaggle_leaderboard"] is False
    rec = dec["recommendation"]
    assert rec["kind"] == "dry_run_only"
    assert rec["upload_recommended"] is False
    assert rec["submit_recommended"] is False
    assert rec["local_research_lead"] == CANDIDATE


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
def test_no_upload_or_submission_was_performed():
    for p in (REG, CV, LG, RK, MS, DEC):
        blob = json.dumps(_json(p)).lower()
        assert '"upload_performed": true' not in blob, p.name
        assert '"is_kaggle_leaderboard": true' not in blob, p.name


# --------------------------------------------------------------- disclaimers
def test_outputs_carry_not_a_kaggle_leaderboard_disclaimer():
    for p in (LG, RK):
        d = _json(p).get("disclaimer", "")
        assert "NOT A KAGGLE LEADERBOARD" in d.upper(), p.name
    md = (REPORTS / "pass18_strategy_family_iteration_report.md").read_text(encoding="utf-8")
    assert "NOT A KAGGLE LEADERBOARD" in md.upper()
    site = SITE.read_text(encoding="utf-8")
    assert "NOT A KAGGLE LEADERBOARD" in site.upper()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
