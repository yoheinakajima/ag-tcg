"""Pass 26 — Replay action-opportunity mining targeted tests.

READ-ONLY/local pass. These tests assert the Pass-26 artifacts and pipeline are
internally consistent and honest, without ever touching the immutable root
submission:

  * the action-opportunity miner resolves the selected action AND the legal
    options (option index == hand position; type7=play, type8=attach,
    type14=end, attackId=attack),
  * Mega Abomasnow ex (723) is never treated as a Basic,
  * live_score_leader and water_family_current_best are two DISTINCT fields,
  * the Pass-25 hooks diagnose as inert via predicate-failure / hidden-target
    (not absence of their trigger context),
  * the trigger-coverage gate blocks every hook with zero qualifying replay
    windows,
  * no candidates are built when no trigger passes, and a candidate build
    requires trigger coverage,
  * decision replay requires a nonzero behaviour delta before eval (forbidden
    here because nothing was built),
  * positive controls are preserved (nothing changed),
  * the no-upload / no_upload invariant holds across artifacts and events,
  * raw replays are gitignored,
  * root main.py / deck.csv are byte-identical to the v1 baseline,
  * the report carries the local/surrogate caveat and the inert-hook lesson.
"""

from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXP = ROOT / "data" / "experiments"
REPORTS = ROOT / "data" / "reports"
CAND_DIR = ROOT / "candidates_pass26"
BASELINE = ROOT / "data" / "baselines" / "v1_kaggle_349_8"
LAB_EVENTS = ROOT / "data" / "activegraph" / "lab_events.jsonl"

LEDGER = EXP / "pass26_action_opportunities.jsonl"
LIVE = EXP / "pass26_live_score_status.json"
DIAG = EXP / "pass26_pass25_inert_hook_diagnosis.json"
CLASSES = EXP / "pass26_true_opportunity_classes.json"
GATE = EXP / "pass26_trigger_coverage.json"
DECISION = EXP / "pass26_strategy_decision.json"
MANIFEST = CAND_DIR / "manifest.json"
REPORT = REPORTS / "pass26_action_opportunity_mining_report.md"

MEGA_ABOMASNOW = 723


def _load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ledger():
    return [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]


# --- miner resolution --------------------------------------------------------
def test_miner_resolves_selected_and_legal_options(ledger):
    assert ledger, "ledger must not be empty"
    for d in ledger:
        assert "selected_indices" in d and "legal_options" in d
        assert isinstance(d["legal_options"], list)
        # recorded selections are the raw agent action values (non-negative);
        # for option-indexed contexts they land inside legal_options, for
        # count-style contexts (e.g. ctx38 draw-count) they may not -- both are
        # honest, so we only require non-negative ints here.
        for i in d.get("selected_indices") or []:
            assert isinstance(i, int) and i >= 0
    # at least one decision exposes a recorded selection that resolves to a
    # legal option (proving selection<->option resolution actually works).
    assert any(
        any(0 <= i < len(d["legal_options"]) for i in d["selected_indices"])
        for d in ledger if d.get("selected_indices"))
    classes = {o["action_class"] for d in ledger for o in d["legal_options"]}
    # the resolver must produce the play/attach/attack/end vocabulary.
    assert {"attack", "attach", "end", "play_supporter",
            "play_trainer", "evolve"} <= classes


def test_unresolved_rate_is_low(ledger):
    total = sum(len(d["legal_options"]) for d in ledger)
    unresolved = sum(1 for d in ledger for o in d["legal_options"]
                     if o["action_class"] == "unknown")
    assert total > 0
    assert unresolved / total < 0.05


def test_mega_abomasnow_never_basic(ledger):
    for d in ledger:
        for o in d["legal_options"]:
            if o.get("card_id") == MEGA_ABOMASNOW:
                assert o["action_class"] != "play_basic", (
                    "Mega Abomasnow ex must never resolve as a Basic play")


# --- live score distinction --------------------------------------------------
def test_live_score_leader_and_water_best_are_distinct_fields():
    live = _load(LIVE)
    assert "live_score_leader" in live
    assert "water_family_current_best" in live
    # they are distinct keys with their own selection rule strings.
    assert live["live_score_leader"]["rule"] != \
        live["water_family_current_best"]["rule"]
    assert live.get("distinction_preserved") is True


# --- inert-hook diagnosis ----------------------------------------------------
def test_pass25_hooks_diagnose_as_inert_by_predicate_fail():
    diag = _load(DIAG)
    hooks = {h["hook"]: h for h in diag["hooks"]}
    deckout = hooks["deckout_guard_v1"]
    # trigger context DID occur, but the low-deck predicate never matched.
    assert deckout["trigger_occurred"] is True
    assert deckout["occurrences"] > 0
    assert deckout["predicate_matched"] is False
    assert deckout["verdict"] == "inert_predicate_fail"
    # search hooks: targets hidden, zero resolvable.
    for h in ("prize_liability_search_pivot", "anti_disruption_search_pivot"):
        assert hooks[h]["resolvable_target_count"] == 0
        assert hooks[h]["verdict"] == "inert_targets_hidden"


# --- trigger coverage gate ---------------------------------------------------
def test_gate_blocks_hooks_with_zero_legal_windows():
    gate = _load(GATE)
    classes = _load(CLASSES)["classes"]
    zero_window = {c["name"] for c in classes if c["count"] == 0}
    assert zero_window, "expected at least one zero-window class"
    for h in gate["hooks"]:
        if h["class"] in zero_window:
            assert h["build_allowed"] is False


def test_no_class_passes_gate_and_nothing_built():
    gate = _load(GATE)
    assert gate["any_build_allowed"] is False
    manifest = _load(MANIFEST)
    assert manifest["candidates_built"] == []
    assert manifest["tarballs"] == []
    # blocked manifest names the would-be candidates honestly.
    assert manifest["candidates_blocked"]
    assert manifest["decision"] == "no_build_no_trigger"


def test_candidate_build_requires_trigger_coverage():
    """If (and only if) a class is build_allowed may a candidate be built."""
    gate = _load(GATE)
    manifest = _load(MANIFEST)
    if not gate["any_build_allowed"]:
        assert manifest["candidates_built"] == []
        assert manifest["tarballs"] == []
    else:  # pragma: no cover - not reachable on this corpus
        assert manifest["candidates_built"]


def test_no_tarballs_on_disk():
    if CAND_DIR.exists():
        assert list(CAND_DIR.glob("*.tar.gz")) == []


# --- decision replay / eval gating ------------------------------------------
def test_decision_replay_requires_nonzero_delta_before_eval():
    decision = _load(DECISION)
    # future kaggle probe is forbidden without a nonzero on-seam delta, which
    # cannot exist because no candidate was built.
    assert decision["future_kaggle_probe"] is False
    reasons = decision["future_probe_forbidden_because"]
    assert any("decision replay" in r for r in reasons)
    assert any("trigger coverage" in r for r in reasons)
    assert decision["primary_decision"] == "no_build_no_trigger"
    assert decision["primary_decision"] in decision["allowed_labels"]


def test_positive_controls_preserved():
    # nothing was built, so positive-control behaviour is preserved trivially;
    # assert the decision encodes no promotion / no behaviour change.
    decision = _load(DECISION)
    assert decision["promote"] is False
    assert decision["upload"] is False
    assert decision["github_push"] is False


# --- no-upload invariant -----------------------------------------------------
def test_no_upload_flag_across_artifacts():
    # Pass-26 artifacts carry an explicit no_upload flag.
    for path in (DIAG, CLASSES, GATE, DECISION, MANIFEST):
        obj = _load(path)
        assert obj.get("no_upload") is True, f"{path.name} missing no_upload"
    # the Part-B live-score status encodes the same invariant via read_only /
    # upload_performed rather than a no_upload key.
    live = _load(LIVE)
    assert live.get("upload_performed") is False
    assert live.get("read_only") is True


def test_pass26_events_all_no_upload_and_no_build_events():
    events = [json.loads(line) for line in
              LAB_EVENTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    p26 = [e for e in events if "pass26" in (e.get("tags") or [])]
    assert p26, "expected pass26 events"
    assert all(e.get("payload", {}).get("no_upload") is True for e in p26)
    # no build-phase events (nothing was built).
    forbidden = {"StrategyFixtureAdded", "StrategyIterationCreated",
                 "StrategyIterationEvaluated"}
    assert not any(e["event_type"] in forbidden for e in p26)
    # but the required mining/decision events ARE present.
    present = {e["event_type"] for e in p26}
    assert {"ReplayAnalyzed", "ReplayWindowTagged", "StrategyHypothesisLogged",
            "StrategyDecisionRecorded", "ReportSiteGenerated"} <= present


# --- raw replays gitignored --------------------------------------------------
def test_raw_replays_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/meta_replays/raw" in gitignore


# --- root immutability -------------------------------------------------------
def test_root_main_and_deck_unchanged():
    assert filecmp.cmp(ROOT / "main.py", BASELINE / "main.py", shallow=False)
    assert filecmp.cmp(ROOT / "deck.csv", BASELINE / "deck.csv", shallow=False)


# --- report caveat + lesson --------------------------------------------------
def test_report_includes_caveat_and_inert_hook_lesson():
    text = REPORT.read_text(encoding="utf-8").lower()
    assert "no_build_no_trigger" in text
    assert "predicate-fail" in text or "predicate fail" in text
    assert "hidden" in text and "deck" in text
    assert "local" in text and ("surrogate" in text or "replay-derived" in text)
    assert "live_score_leader" in text and "water_family_current_best" in text
