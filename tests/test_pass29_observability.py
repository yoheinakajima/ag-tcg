"""Pass 29 — Part P: observability ratchet + effect-loop feasibility tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest, evidence-gated
findings of the observability pass. They read the committed Pass-29 artifacts and
the lab event store. Nothing here uploads, submits, or pushes; the tests only
verify on-disk state.

Checklist (from the spec):
- root main.py / deck.csv byte-unchanged vs v1 baseline
- raw action trace effectively gitignored
- resolver dataset uses the documented confidence enum, no others
- resolved fraction matches the summary's by-confidence counts
- effect-loop is classified optional_loop_with_exit with an OBSERVED legal exit
- feasibility gate is evidence-gated (passes only because the exit is observable)
- AT MOST ONE candidate built; deck unchanged; no invented card IDs
- guard eval verdict is decisive and matches the recorded decision
- target / engine-card observability honestly report what is NOT observable
- fixture backlog splits executable-now from blocked, with evidence each
- decision is one of the documented enum values
- every pass29 event carries no_upload=true and no upload/submit/push happened
- the 10-section report exists with all ten numbered sections
"""

from __future__ import annotations

import filecmp
import json
import subprocess
from pathlib import Path

import pytest

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
FIX = REPO / "data" / "fixtures" / "pass29_observability_backlog.yaml"
REPORT = REPO / "data" / "reports" / "pass29_observability_ratchet_report.md"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
ACTION_TRACE = EXP / "pass28_action_trace.jsonl"
CANDIDATE_DIR = REPO / "data" / "submissions" / "candidates_pass29"

CONFIDENCE_ENUM = {
    "direct_option", "verified_by_following_log",
    "inferred_from_state_delta", "unresolved",
}
DECISION_ENUM = {
    "needs_more_observability", "build_effect_loop_exit_next",
    "effect_loop_exit_candidate_built", "effect_loop_exit_rejected",
    "keep_portfolio_reference", "expand_trace_coverage", "no_action",
}


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def resolve():
    return _load("pass29_action_resolution_summary.json")


@pytest.fixture(scope="module")
def valid():
    return _load("pass29_action_resolution_validation.json")


@pytest.fixture(scope="module")
def loops():
    return _load("pass29_effect_loop_analysis.json")


@pytest.fixture(scope="module")
def feas():
    return _load("pass29_effect_loop_feasibility.json")


@pytest.fixture(scope="module")
def tgt():
    return _load("pass29_target_observability.json")


@pytest.fixture(scope="module")
def eng():
    return _load("pass29_engine_card_observability.json")


@pytest.fixture(scope="module")
def eval_():
    return _load("pass29_effect_loop_guard_eval.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass29_strategy_decision.json")


@pytest.fixture(scope="module")
def backlog():
    assert yaml is not None, "pyyaml required"
    return yaml.safe_load(FIX.read_text(encoding="utf-8"))


# ----------------------------- safety --------------------------------------

def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


def test_raw_action_trace_is_gitignored():
    if not ACTION_TRACE.exists():
        pytest.skip("raw action trace not present")
    proc = subprocess.run(
        ["git", "check-ignore", str(ACTION_TRACE.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.strip(), \
        "the large raw per-decision action trace must be effectively gitignored"


# ----------------------------- resolver ------------------------------------

def test_resolver_uses_documented_confidence_enum(resolve):
    by_conf = resolve["by_confidence"]
    assert set(by_conf) <= CONFIDENCE_ENUM, \
        f"resolver emitted undocumented confidence tiers: {set(by_conf) - CONFIDENCE_ENUM}"


def test_resolved_fraction_matches_counts(resolve):
    by_conf = resolve["by_confidence"]
    total = resolve["total_rows"]
    resolved = total - by_conf.get("unresolved", 0)
    assert total == sum(by_conf.values()), "confidence counts must sum to total rows"
    assert abs(resolve["resolved_fraction"] - resolved / total) < 1e-3


def test_validation_agreement_is_real_fraction(valid):
    a = valid["agreement_among_checkable"]
    assert 0.0 <= a <= 1.0
    assert valid["checkable_rows"] > 0, "validation must check real rows, not zero"


# ----------------------------- effect loop ---------------------------------

def test_effect_loop_is_optional_with_observed_exit(loops, feas):
    # The corrected finding: optional_loop_with_exit, NOT forced.
    assert "optional_loop_with_exit" in loops["by_classification"]
    assert "forced_engine_loop" not in loops["by_classification"], \
        "the earlier forced-loop read was corrected; must not reappear"
    assert feas["loop_classification"] == "optional_loop_with_exit"


def test_feasibility_gate_is_evidence_gated(feas):
    # The gate may only pass because a legal exit is OBSERVED at the loop head.
    if feas["gate_passes"]:
        stats = feas.get("loop_head_stats", {})
        present = stats.get("ctx0_with_end_option")
        assert present and present > 0, \
            "gate passed without an observed legal exit option"


# ----------------------------- candidate -----------------------------------

def test_at_most_one_candidate_built():
    if not CANDIDATE_DIR.exists():
        pytest.skip("no candidate dir (gate may have blocked)")
    built = [p for p in CANDIDATE_DIR.iterdir() if p.is_dir()]
    assert len(built) <= 1, f"spec allows AT MOST ONE candidate, found {len(built)}"


def test_candidate_decision_consistent(decision, feas, eval_):
    if decision["decision"] == "effect_loop_exit_candidate_built":
        assert feas["gate_passes"] is True, "candidate built but gate did not pass"
        assert eval_["verdict"] == "effect_loop_exit_candidate_built"
        assert decision["candidate_built"] == "effect_loop_exit_guard_v1"


def test_candidate_not_uploaded_or_pushed(decision):
    assert decision.get("candidate_uploaded") is False
    assert decision.get("candidate_submitted") is False
    assert decision.get("github_pushed") is False
    assert decision.get("root_files_modified") is False


# ----------------------------- observability -------------------------------

def test_target_observability_is_honest(tgt):
    # attackId observable but defender identity NOT captured in the trace.
    assert tgt["attack_id_observable_fraction"] == pytest.approx(1.0)
    assert tgt["defender_active_identity_observable_fraction"] == pytest.approx(0.0)
    assert tgt["NOT_observable_yet"], "must list what is not observable"


def test_engine_card_observability_reports_gaps(eng):
    classes = eng["by_engine_class"]
    assert classes, "must analyse engine-class decisions"
    assert eng["NOT_observable_yet"], "must honestly list unobservable engine cards"


# ----------------------------- backlog & decision --------------------------

def test_backlog_splits_executable_from_blocked(backlog):
    fixtures = backlog["fixtures"]
    assert fixtures, "backlog must list fixtures"
    assert any(f["executable_now"] for f in fixtures), "need >=1 executable-now item"
    assert any(not f["executable_now"] for f in fixtures), "need >=1 blocked item"
    for f in fixtures:
        assert f.get("evidence"), f"fixture {f['fixture_id']} must cite evidence"


def test_decision_is_documented_enum(decision):
    assert decision["decision"] in DECISION_ENUM, \
        f"decision {decision['decision']!r} not in documented enum"


# ----------------------------- events & report -----------------------------

def test_pass29_events_are_no_upload():
    assert LAB_EVENTS.exists()
    seen = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass29" not in (ev.get("tags") or []):
            continue
        seen += 1
        payload = ev.get("payload") or {}
        assert payload.get("no_upload") is True, \
            f"pass29 event {ev.get('type')} missing no_upload=true"
        assert payload.get("uploaded", False) is False
        assert payload.get("submitted", False) is False
    assert seen >= 10, f"expected the pass29 event family to be emitted, saw {seen}"


def test_report_has_all_ten_sections():
    assert REPORT.exists(), "the 10-section final report must exist"
    text = REPORT.read_text(encoding="utf-8")
    for i in range(1, 11):
        assert f"\n{i}. " in ("\n" + text), f"report missing section {i}"
    assert "NOT the Kaggle leaderboard" in text or "NOT a promotion signal" in text
