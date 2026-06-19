"""Pass 28 — Part N: cross-deck forensic trace integrity tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest, evidence-gated
findings of the cross-deck forensic trace pass. They read the committed Pass-28
artifacts, the card database, and the lab event store. Nothing here uploads,
submits, or pushes; the tests only verify on-disk state.

Checklist (from the spec):
- action trace schema has required fields
- no invented IDs
- root files unchanged
- raw replays gitignored
- Raging Bolt diagnosis is not inferred from win rate alone
- color energy gap requires trace evidence
- engine_card_play gap distinct from color energy gap
- mechanics coverage matrix includes 20 rows
- Durant invalid cause recorded
- fixture backlog items reference evidence or explain no source
- decision is evidence-gated
- no upload flag remains false / no_upload true
- report includes internal/surrogate caveat
- reports distinguish live score from internal league
"""

from __future__ import annotations

import csv
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
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
FIX = REPO / "data" / "fixtures" / "pass28_core_gameplay_backlog.yaml"
REPORT = REPO / "data" / "reports" / "pass28_cross_deck_forensic_report.md"
GITIGNORE = REPO / ".gitignore"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
ACTION_TRACE = EXP / "pass28_action_trace.jsonl"


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def diag():
    return _load("pass28_diagnostic_trace.json")


@pytest.fixture(scope="module")
def forensics():
    return _load("pass28_deck_forensics.json")


@pytest.fixture(scope="module")
def priority():
    return _load("pass28_core_gap_priority.json")


@pytest.fixture(scope="module")
def matrix():
    return _load("pass28_mechanics_coverage_matrix.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass28_strategy_decision.json")


@pytest.fixture(scope="module")
def live():
    return _load("pass28_live_score_status.json")


@pytest.fixture(scope="module")
def inventory():
    return _load("pass28_portfolio_inventory.json")


@pytest.fixture(scope="module")
def known_card_names() -> set[str]:
    names: set[str] = set()
    with CARD_DB.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("Card Name"):
                names.add(row["Card Name"].strip())
    return names


# ----------------------------- tests ---------------------------------------

def test_action_trace_schema_has_required_fields():
    assert ACTION_TRACE.exists(), "raw action trace must exist locally"
    with ACTION_TRACE.open(encoding="utf-8") as fh:
        first = fh.readline()
    assert first.strip(), "action trace must not be empty"
    rec = json.loads(first)
    required = {"run_id", "game_id", "candidate_id", "family_id", "seat", "step",
                "select_context", "select_type", "n_options", "selected_indices",
                "option_classes_present"}
    missing = required - set(rec)
    assert not missing, f"action trace row missing fields: {missing}"


def test_no_invented_candidate_ids(diag, inventory):
    # All candidate_ids in the diagnostic must come from the committed inventory,
    # i.e. no fabricated decks were introduced this pass.
    inv_ids = {d["candidate_id"] for d in inventory["decks"]}
    for cid in diag["per_deck"]:
        assert cid in inv_ids, f"diagnostic references unknown candidate {cid}"


def test_no_invented_card_names(forensics, known_card_names):
    # Every card NAME surfaced by the forensics (placed / attacked) must exist in
    # the real card DB — no invented cards. We check all decks, not just RB.
    seen = 0
    for fam in forensics["families"].values():
        ev = fam.get("evidence", {})
        for name in (ev.get("place_card_by_name") or {}):
            seen += 1
            assert name in known_card_names, f"invented card name surfaced: {name!r}"
        for pair in (ev.get("attach_active_color_pairs") or {}):
            mon = pair.split("|", 1)[0]
            if mon and mon != "None":
                assert mon in known_card_names, f"invented attacker name: {mon!r}"
    assert seen > 0, "expected at least one resolved placed-card name in evidence"


def test_raging_bolt_attach_colors_are_real(forensics):
    # Attach color codes must be single-letter energy types, not free text.
    rb = forensics["families"]["raging_bolt"]
    for color in rb["evidence"]["attach_colors"]:
        assert color in {"W", "R", "L", "G", "P", "F", "D", "M", "C", "N", "Y"}, color


def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


def test_raw_action_trace_is_gitignored():
    # Assert effective ignore behavior via git, not just .gitignore text.
    if not ACTION_TRACE.exists():
        pytest.skip("raw action trace not present")
    proc = subprocess.run(
        ["git", "check-ignore", str(ACTION_TRACE.relative_to(REPO))],
        cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.strip(), \
        "the large raw per-decision action trace must be effectively gitignored"


def test_raging_bolt_diagnosis_not_winrate_only(forensics):
    rb = forensics["families"]["raging_bolt"]
    # The diagnosis must rest on action-trace fields, not win rate.
    ev = rb["evidence"]
    assert "attacks_taken" in ev and "attach_off_deck_plan" in rb
    rationale = (rb.get("classification_rationale") or "").lower()
    assert "action trace" in rationale or "trace" in rationale
    # And it must explicitly refute the two naive hypotheses.
    assert rb["color_match_attach_REFUTED"] is True
    assert rb["attack_pressure_REFUTED"] is True


def test_color_energy_gap_requires_trace_evidence(priority):
    # color_match must be rejected (refuted) BECAUSE the trace shows 0 off-plan
    # attaches — i.e. the gap is gated on trace evidence, never asserted blindly.
    assert "color_match_attach" in priority["rejected_gaps"]
    color_gaps = [g for g in priority["gaps_ranked"]
                  if "color" in g["gap_id"].lower()]
    for g in color_gaps:
        assert g["confidence"].lower().startswith("rejected")
        assert g["evidence_against"], "rejection must cite trace evidence"


def test_engine_card_play_distinct_from_color_gap(priority, forensics):
    # engine-card play (Crispin/search) is recorded as UNOBSERVABLE / need-more,
    # which is a different category from the refuted color-match gap.
    need = " ".join(priority.get("need_more_diagnostics", [])).lower()
    assert "engine_card_play" in need or "engine" in need
    rb = forensics["families"]["raging_bolt"]
    rationale = (rb.get("classification_rationale") or "").lower()
    assert "unobserv" in rationale  # engine card play is unobservable, not color


def test_mechanics_matrix_has_20_rows(matrix):
    assert matrix["row_count"] == 20
    assert len(matrix["rows"]) == 20
    s = matrix["summary"]
    assert s["supported"] + s["partial"] + s["unsupported"] == 20


def test_durant_invalid_cause_recorded(forensics, diag):
    durant = forensics["families"]["durant"]
    cls = (durant.get("issue_classification") or "").lower()
    assert "legality" in cls or "init" in cls or "structural" in cls, \
        f"Durant cause must be recorded, got {cls!r}"


def test_fixtures_reference_evidence_or_explain(forensics):
    assert yaml is not None, "pyyaml required"
    doc = yaml.safe_load(FIX.read_text(encoding="utf-8"))
    fixtures = doc["fixtures"]
    assert fixtures, "fixture backlog must not be empty"
    for fx in fixtures:
        assert fx.get("source_run_replay_step"), \
            f"{fx['fixture_id']} must reference its trace evidence"
        if not fx["executable_now"]:
            assert fx.get("why_blocked"), \
                f"{fx['fixture_id']} non-executable must explain why"


def test_decision_is_evidence_gated(decision):
    assert decision.get("evidence_gated") is True
    # Forbidden choices must be explicitly recorded as refuted.
    forbidden = decision["forbidden_choices_and_why"]
    assert any("color" in k for k in forbidden)
    assert any("attack_pressure" in k for k in forbidden)
    # The decision label must be exactly one of the spec's allowed labels.
    assert decision["decision"] in {
        "build_chaos_special_pilot_next", "gather_more_traces",
        "expand_portfolio_first"}
    assert decision.get("no_candidate_built") is True


def test_no_upload_flags_remain_false():
    for name in ("pass28_deck_forensics.json", "pass28_core_gap_priority.json",
                 "pass28_strategy_decision.json", "pass28_diagnostic_trace.json",
                 "pass28_mechanics_coverage_matrix.json",
                 "pass28_implementation_roadmap.json"):
        d = _load(name)
        assert d.get("upload_performed") in (False, None), f"{name} upload_performed"
        if "no_upload" in d:
            assert d["no_upload"] is True, f"{name} no_upload must be True"
        assert d.get("is_kaggle_leaderboard") in (False, None), name


def test_pass28_events_all_no_upload():
    assert LAB_EVENTS.exists()
    seen = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass28" not in (ev.get("tags") or []):
            continue
        seen += 1
        assert ev.get("payload", {}).get("no_upload") is True, \
            f"pass28 event {ev.get('event_type')} must carry no_upload=True"
    assert seen >= 10, f"expected pass28 events emitted, saw {seen}"


def test_report_includes_surrogate_caveat():
    text = REPORT.read_text(encoding="utf-8")
    low = text.lower()
    assert "not the kaggle leaderboard" in low or "not a promotion signal" in low
    assert "diagnostic" in low


def test_reports_distinguish_live_score_from_internal(live):
    # The live-score artifact must keep the Kaggle live score distinct from the
    # internal-league reference.
    assert "live_score_leader" in live
    assert "portfolio_reference" in live
    assert live.get("is_promotion_decision") in (False, None)
    assert "internal_league_caveat" in live


def test_charizard_first_attack_timing_is_consistent_across_artifacts(
    forensics, matrix, priority):
    # Regression: first_attack_step is the MEDIAN of per-(run,game) first-attack
    # steps. The earlier global-min/outlier value (98) must not leak into any
    # downstream artifact, and the canonical forensics value must be propagated.
    ev = forensics["families"]["charizard"]["evidence"]
    median = ev["first_attack_step"]
    assert "first_attack_step_min" in ev
    assert ev["first_attack_step_min"] <= median
    assert ev.get("first_attack_step_semantics")

    median_s = str(median)
    # matrix evolution-sequencing row references the median, not the outlier.
    evo_rows = [r for r in matrix["rows"]
                if r.get("mechanic") == "evolution sequencing"]
    assert evo_rows, "expected an 'evolution sequencing' row in the matrix"
    for r in evo_rows:
        assert "98" not in str(r["evidence_decks"])
        assert median_s in str(r["evidence_decks"])
    # no matrix row anywhere should carry the stale outlier timing.
    for r in matrix["rows"]:
        assert "step 98" not in str(r.get("evidence_decks", ""))

    # priority evolution gap references the median, not the outlier.
    evo = [g for g in priority["gaps_ranked"]
           if g["gap_id"] == "evolution_sequencing_speed"]
    assert evo, "expected an evolution_sequencing_speed gap"
    assert "98" not in evo[0]["evidence_for"]
    assert median_s in evo[0]["evidence_for"]

    # NO generated artifact may carry the stale outlier timing in any phrasing
    # variant ('step 98' / 'step ~98'), across reports, docs, site, roadmap, and
    # fixtures.
    for path in (REPORT,
                 REPO / "docs" / "PTCG_STRATEGY_CANVAS.md",
                 REPO / "docs" / "CORE_GAMEPLAY_BACKLOG.md",
                 REPO / "data" / "site" / "index.html",
                 EXP / "pass28_implementation_roadmap.json",
                 FIX,
                 FIX.with_suffix(".md")):
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "step 98" not in text, f"stale 'step 98' in {path.name}"
            assert "step ~98" not in text, f"stale 'step ~98' in {path.name}"
            assert "~98" not in text, f"stale '~98' outlier timing in {path.name}"
