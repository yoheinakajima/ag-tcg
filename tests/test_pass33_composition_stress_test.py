"""Pass 33 — Part N: deck composition stress test tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest, evidence-gated
findings of the composition stress test. They read the committed Pass-33 artifacts
and the lab event store. Nothing here uploads, submits, or pushes; the tests only
verify on-disk state.

Checklist (from the spec):
- no opponent deck clones are built
- only existing portfolio or our own deck variants are used
- water basic-density variants, if built, increase Basic count and reduce no-Basic prob
- new variants use only verified card IDs
- root files unchanged
- candidate tarballs top-level only
- entrypoint validators pass for eligible candidates
- invalid candidates excluded from tournament
- Durant excluded unless smoke-valid
- internal tournament has is_kaggle_leaderboard false
- dry-run queue max 1
- no upload flag false / no_upload true
- reports include internal/Kaggle caveat
- composition audit computes Basic count and Energy count
- Dragapult live score above/below Water is read from fresh status, not hardcoded
- Water, Dragapult, live leader fields remain distinct
"""

from __future__ import annotations

import filecmp
import json
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
REPORT = REPO / "data" / "reports" / "pass33_deck_composition_stress_test_report.md"
STRAT_REPORT = REPO / "data" / "reports" / "activegraph_strategy_report.md"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
QUEUE = REPO / "data" / "submission_queue.json"
CANDIDATE_DIR = REPO / "data" / "submissions" / "candidates_pass33"

DURANT = "league_durant_deckout_carousel"
WATER_CONTROL = "league_water_anti_disruption_pivot_v1"
DENSITY_VARIANTS = ("water_basic_density_v1", "water_basic_density_v2")


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def live():
    return _load("pass33_live_score_status.json")


@pytest.fixture(scope="module")
def audit():
    return _load("pass33_deck_composition_audit.json")


@pytest.fixture(scope="module")
def plan():
    return _load("pass33_stress_test_plan.json")


@pytest.fixture(scope="module")
def manifest():
    return _load("pass33_composition_variants_manifest.json")


@pytest.fixture(scope="module")
def valid():
    return _load("pass33_candidate_validation.json")


@pytest.fixture(scope="module")
def smoke():
    return _load("pass33_live_smoke.json")


@pytest.fixture(scope="module")
def rank1():
    return _load("pass33_composition_rankings.json")


@pytest.fixture(scope="module")
def pc():
    return _load("pass33_parent_child_confirmations.json")


@pytest.fixture(scope="module")
def meta():
    return _load("pass33_meta_sanity.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass33_strategy_decision.json")


@pytest.fixture(scope="module")
def audit_by_id(audit):
    return {d["candidate_id"]: d for d in audit.get("decks", [])}


# ----------------------------- safety --------------------------------------

def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


# ----------------------------- portfolio provenance ------------------------

def test_no_opponent_clones(manifest, plan):
    # Every built/reused candidate is one of OUR decks; nothing is an opponent clone.
    for r in manifest.get("results", []):
        assert r.get("kind") in {"reused", "built"}, \
            f"{r.get('candidate_id')} has unexpected provenance {r.get('kind')!r}"
    for c in plan.get("candidates", []):
        assert c.get("disposition") in {"existing_reuse", "build_variant", "blocked"}, \
            f"{c.get('candidate_id')} has non-portfolio disposition"


def test_only_existing_portfolio_or_our_variants(manifest):
    for r in manifest.get("results", []):
        if r.get("kind") == "reused":
            src = r.get("source_tarball") or ""
            assert "candidates_pass" in src, \
                f"{r.get('candidate_id')} reused from non-portfolio source {src!r}"
        elif r.get("kind") == "built":
            assert r.get("disposition") == "build_variant"


def test_only_water_density_variants_built(manifest):
    built = [r["candidate_id"] for r in manifest.get("results", [])
             if r.get("kind") == "built"]
    assert set(built) <= set(DENSITY_VARIANTS), \
        f"only Water Basic-density variants may be built; got {built}"
    assert len(built) <= 4, "at most 4 NEW variants per the plan"


def test_density_variants_increase_basics_and_reduce_no_basic(audit_by_id):
    parent = audit_by_id.get(WATER_CONTROL)
    assert parent, "Water control must be audited"
    p_basics = parent["basic_pokemon"]
    p_nobasic = parent["opening_no_basic_probability"]
    for v in DENSITY_VARIANTS:
        d = audit_by_id.get(v)
        if not d:
            continue
        assert d["basic_pokemon"] > p_basics, \
            f"{v} must have MORE Basics than the {p_basics}-Basic parent"
        assert d["opening_no_basic_probability"] < p_nobasic, \
            f"{v} must reduce opening no-Basic probability below {p_nobasic}"


def test_density_ladder_monotonic(audit_by_id):
    v1 = audit_by_id.get("water_basic_density_v1")
    v2 = audit_by_id.get("water_basic_density_v2")
    if v1 and v2:
        assert v2["basic_pokemon"] >= v1["basic_pokemon"]
        assert v2["opening_no_basic_probability"] <= v1["opening_no_basic_probability"]


def test_new_variants_use_only_verified_card_ids(audit_by_id):
    for v in DENSITY_VARIANTS:
        d = audit_by_id.get(v)
        if not d:
            continue
        assert d.get("unknown_card_ids") == [], \
            f"{v} must use only verified card ids; unknown={d.get('unknown_card_ids')}"


def test_core_engine_preserved(manifest):
    core = manifest.get("core_preserved") or {}
    assert core.get("721") == 4 and core.get("722") == 4
    assert core.get("723") == 4 and core.get("1121") == 4


# ----------------------------- tarball hygiene -----------------------------

def test_candidate_tarballs_top_level_only():
    if not CANDIDATE_DIR.exists():
        pytest.skip("no pass33 candidate dir")
    tarballs = list(CANDIDATE_DIR.glob("*.tar.gz"))
    assert tarballs, "expected staged pass33 candidate tarballs"
    for tb in tarballs:
        with tarfile.open(tb, "r:gz") as tf:
            names = [n for n in tf.getnames() if n not in (".", "")]
        flat = {Path(n).name for n in names if "/" not in n.strip("./")}
        assert "main.py" in flat and "deck.csv" in flat, \
            f"{tb.name} must contain top-level main.py and deck.csv"
        for n in names:
            assert "/" not in n.strip("./"), \
                f"{tb.name} must be top-level only, found nested {n!r}"


# ----------------------------- validation / smoke --------------------------

def test_entrypoint_validators_pass_for_eligible(valid, smoke):
    results = valid.get("results", {})
    for cid in smoke.get("tournament_eligible", []):
        r = results.get(cid, {})
        assert r.get("tarball_rc") == 0, f"{cid} tarball validator must pass"
        assert r.get("entrypoint_rc") == 0, f"{cid} entrypoint validator must pass"
        assert r.get("passed") is True, f"{cid} must be validated"


def test_invalid_candidates_excluded_from_tournament(valid, rank1):
    eligible = {r["id"] for r in rank1.get("standings", [])}
    for cid, r in valid.get("results", {}).items():
        if r.get("blocked_from_league"):
            assert cid not in eligible, f"blocked {cid} must not be in the tournament"


def test_durant_excluded_unless_smoke_valid(valid, rank1, smoke):
    eligible = {r["id"] for r in rank1.get("standings", [])}
    assert DURANT not in eligible, "Durant must be excluded from the tournament"
    assert DURANT not in set(smoke.get("tournament_eligible", []))


def test_internal_tournament_not_kaggle(rank1):
    assert rank1.get("is_kaggle_leaderboard") is False
    assert rank1.get("no_upload") is True
    assert rank1.get("upload_performed") is False


# ----------------------------- audit ---------------------------------------

def test_composition_audit_computes_basic_and_energy(audit_by_id):
    assert audit_by_id, "audit must contain decks"
    for cid, d in audit_by_id.items():
        assert isinstance(d.get("basic_pokemon"), int), \
            f"{cid} must have a Basic count"
        assert isinstance(d.get("energy_total"), int), \
            f"{cid} must have an Energy count"


# ----------------------------- live score distinctions ---------------------

def test_dragapult_above_water_read_from_fresh_status(live):
    dra = (live.get("dragapult_family_best") or {}).get("publicScore")
    wat = (live.get("water_family_current_best") or {}).get("publicScore")
    assert dra is not None and wat is not None
    # The recorded flag must MATCH the fresh scores, not a hardcoded value.
    assert live.get("dragapult_above_water") == (float(dra) > float(wat))


def test_water_dragapult_leader_fields_distinct(live):
    leader = (live.get("live_score_leader") or {}).get("fileName")
    water = (live.get("water_family_current_best") or {}).get("fileName")
    dra = (live.get("dragapult_family_best") or {}).get("fileName")
    portref = (live.get("portfolio_reference") or {}).get("fileName")
    names = [leader, water, dra, portref]
    assert all(names), "all four live reference fields must be populated"
    assert water != dra, "Water best and Dragapult best must be distinct files"
    assert live.get("distinction_preserved") is True


# ----------------------------- decision / queue ----------------------------

def test_dry_run_queue_max_one():
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    assert q.get("max_queue_size") == 1
    assert len(q.get("queue", [])) <= 1, "dry-run queue must hold at most 1 entry"
    assert q.get("auto_submit_enabled") is False
    assert q.get("require_manual_approval_for_submit") is True
    assert q.get("upload_performed") is False


def test_all_gates_passed_is_conjunction(decision):
    gates = decision.get("gates") or {}
    assert gates, "decision must record per-gate results"
    assert decision.get("all_gates_passed") == all(gates.values()), \
        "all_gates_passed must be the conjunction of the individual gates"


def test_not_clone_gate_is_evidence_derived(decision, manifest, audit_by_id):
    # The not_clone_or_invented_ids gate must reflect ACTUAL evidence (manifest
    # provenance + audit verified ids), not a hardcoded constant.
    probe = decision["recommended_probe_candidate"]
    gate = decision["gates"]["not_clone_or_invented_ids"]
    mrow = next((r for r in manifest.get("results", [])
                 if r.get("candidate_id") == probe), {})
    own_provenance = (
        mrow.get("disposition") in {"build_variant", "existing_reuse"}
        and mrow.get("kind") in {"built", "reused"}
        and "candidates_pass" in (mrow.get("parent_tarball") or "")
    )
    ids_verified = audit_by_id.get(probe, {}).get("unknown_card_ids") == []
    assert gate == (own_provenance and ids_verified), \
        "not_clone_or_invented_ids gate must match manifest+audit evidence"
    assert gate is True


def test_decision_no_upload_flags(decision, manifest, live):
    assert decision.get("upload_performed") is False
    assert decision.get("no_upload") is True
    assert decision.get("is_kaggle_leaderboard") is False
    assert decision.get("auto_submit_enabled") is False
    assert decision.get("human_approval_required") is True
    assert manifest.get("upload_performed") is False
    assert live.get("upload_performed") is False


def test_pass33_events_are_no_upload():
    assert LAB_EVENTS.exists(), "lab event store must exist"
    seen = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass33" not in (ev.get("tags") or []):
            continue
        seen += 1
        payload = ev.get("payload") or {}
        assert payload.get("no_upload") is True, \
            f"pass33 event {ev.get('type')} must carry no_upload=true"
        assert payload.get("upload") is not True
        assert payload.get("submit") is not True
        assert payload.get("github_push") is not True
    assert seen > 0, "expected pass33-tagged events"


# ----------------------------- reports -------------------------------------

def test_report_has_all_ten_sections_in_order():
    text = REPORT.read_text(encoding="utf-8")
    idx = -1
    for i in range(1, 11):
        marker = f"\n{i}. "
        pos = text.find(marker)
        assert pos != -1, f"report missing section {i}"
        assert pos > idx, f"section {i} out of order"
        idx = pos
    assert text.startswith(
        "ActiveGraph Pass 33 Deck Composition Stress Test Report")


def test_reports_include_internal_kaggle_caveat():
    for p in (REPORT, STRAT_REPORT):
        text = p.read_text(encoding="utf-8")
        assert "NOT the Kaggle leaderboard" in text or \
            "NOT a promotion" in text, \
            f"{p.name} must carry the internal/Kaggle caveat"
