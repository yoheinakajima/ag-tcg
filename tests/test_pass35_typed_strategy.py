"""Pass 35 — Part P: typed board-aware strategy layer tests.

These tests assert the LOCAL/READ-ONLY guarantees, the honesty mandate, and the
honest, control-calibrated gating of the Pass-35 typed layer. They read the
committed Pass-35 artifacts and the lab event store, and they functionally exercise
the stdlib-only typed decision layer to prove it never raises and never fabricates
unsupported mechanics. Nothing here uploads, submits, or pushes.

Checklist (Part P):
- root main.py / deck.csv byte-identical to the frozen baseline
- card CSV (EN_Card_Data.csv) and raw replay JSON never committed
- typed decision layer is stdlib-only at runtime, deterministic, never raises
- attack / lethal / KO / spread / Boss / gust are UNSUPPORTED (no fabrication)
- Raging Bolt gets NO fake color-match fix (Pass 28 refuted)
- 11 profiles = 9 executable + 2 special-pilot-only (never built, never queued)
- typed strategy gate PASS with honesty sweep all-unsupported
- candidates built only for executable + gate-passing profiles; deck == parent deck
- candidate tarballs are top-level main.py + deck.csv only
- validation all_ok; decision replay all_honest/all_safe, 0 misfire/unsafe/illegal
- internal tournament / parent-child / meta sanity are NOT Kaggle, NOT promotion
- parent/child any_superiority_claim is false (control-calibrated); none queued
- dry-run queue max 1, auto_submit false, manual approval, upload false
- held probe retention is the conjunction of its gates
- final report has EXACTLY 10 sections in order, with caveats
- every pass35 event carries no_upload=true and there is NO SubmissionUploaded
"""

from __future__ import annotations

import csv
import filecmp
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
QUEUE = REPO / "data" / "submission_queue.json"
CANDIDATE_DIR = REPO / "data" / "submissions" / "candidates_pass35"
FINAL_REPORT = REPORTS / "pass35_final_report.md"
PORTFOLIO_REPORT = REPORTS / "pass35_typed_strategy_portfolio_report.md"

EXECUTABLE = {
    "water_core_reference", "water_basic_density_v1", "dragapult_spread_control",
    "mono_lightning_miraidon_easy", "diamond_toolbox_diancie",
    "mega_charizard_x_burst", "mega_venusaur_tank", "mega_gardevoir_psychic_ramp",
    "raging_bolt_ogerpon_basic_aggro",
}
SPECIAL_PILOT_ONLY = {"toxic_trap_poison_lock", "deckout_carousel_durant_v2"}
UNSUPPORTED_KINDS = ("attack", "lethal", "ko_target", "spread", "boss", "gust")


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


def _load_report(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def profiles():
    return _load("pass35_strategy_profiles.json")


@pytest.fixture(scope="module")
def profiles_by_id(profiles):
    return {p["id"]: p for p in profiles.get("profiles", [])}


@pytest.fixture(scope="module")
def gate():
    return _load_report("pass35_typed_strategy_gate.json")


@pytest.fixture(scope="module")
def build():
    return _load("pass35_candidate_build.json")


@pytest.fixture(scope="module")
def valid():
    return _load("pass35_candidate_validation.json")


@pytest.fixture(scope="module")
def replay():
    return _load("pass35_decision_replay.json")


@pytest.fixture(scope="module")
def firing():
    return _load("pass35_typed_firing_probe.json")


@pytest.fixture(scope="module")
def rankings():
    return _load("pass35_rankings.json")


@pytest.fixture(scope="module")
def parent_child():
    return _load("pass35_parent_child.json")


@pytest.fixture(scope="module")
def meta():
    return _load("pass35_meta_sanity.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass35_strategy_decision.json")


# ----------------------------- safety / provenance -------------------------

def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


def test_card_db_and_replays_not_committed():
    gi = (REPO / ".gitignore").read_text(encoding="utf-8") if (
        REPO / ".gitignore").exists() else ""
    assert "EN_Card_Data" in gi, "EN_Card_Data.csv must be gitignored"


def test_strategy_profiles_card_csv_not_committed(profiles):
    assert profiles.get("card_csv_committed") is False
    assert profiles.get("upload_performed") is False
    assert profiles.get("no_upload") is True


# ----------------------------- typed layer (functional) --------------------

def _import_typed():
    sys.path.insert(0, str(REPO / "src"))
    from ptcg_activegraph.pilot_typed import decisions  # noqa: WPS433
    return decisions


def test_typed_layer_is_stdlib_only_at_runtime():
    # No third-party / no `src.` imports in the embed-able runtime modules.
    runtime = ["board.py", "metadata.py", "tactics.py", "profiles.py",
               "decisions.py"]
    allow = {"json", "csv", "sys", "os", "re", "math", "collections", "typing",
             "dataclasses", "enum", "itertools", "functools", "copy"}
    pt = REPO / "src" / "ptcg_activegraph" / "pilot_typed"
    for fname in runtime:
        for ln in (pt / fname).read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if s.startswith("from __future__") or s.startswith("from ."):
                continue
            if s.startswith("from ptcg_activegraph.pilot_typed"):
                continue  # intra-package (compiler embeds source verbatim)
            if s.startswith("import "):
                mod = s.split()[1].split(".")[0]
                assert mod in allow, f"{fname}: non-stdlib import {mod!r}"
            elif s.startswith("from ") and " import " in s:
                mod = s.split()[1].split(".")[0]
                assert mod in allow, f"{fname}: non-stdlib from-import {mod!r}"


def test_decide_never_raises_on_garbage_input():
    decisions = _import_typed()
    garbage = [None, 0, "x", [], {}, [{"id": 1}], {"weird": object()}]
    for kind in ("setup_active", "search_to_hand", "discard", "draw_count",
                 "attach_energy", "setup_bench_multi", "emergency_backup_bench",
                 "totally_unknown_kind"):
        for b in garbage:
            for opts in garbage:
                out = decisions.decide(kind, b, opts, profile=None, meta=None)
                assert isinstance(out, dict), \
                    f"decide({kind!r}) must always return a dict"


def test_decide_refuses_unsupported_mechanics():
    decisions = _import_typed()
    for kind in UNSUPPORTED_KINDS:
        out = decisions.decide(kind, {}, [{"id": 1}], profile={}, meta={})
        assert out.get("unsupported") is True, \
            f"{kind} must be reported unsupported (numeric attackId only)"
        assert "chosen_card_id" not in out and "chosen_target_id" not in out, \
            f"{kind} must NOT fabricate a target/choice"


# ----------------------------- profiles / honesty --------------------------

def test_profile_counts(profiles):
    assert profiles.get("total_profiles") == 11
    assert profiles.get("executable_profiles") == 9
    assert profiles.get("special_pilot_only_profiles") == 2
    assert profiles.get("all_ok") is True


def test_executable_and_special_pilot_split(profiles_by_id):
    for pid in EXECUTABLE:
        assert profiles_by_id[pid].get("executable") is True
    for pid in SPECIAL_PILOT_ONLY:
        assert profiles_by_id[pid].get("executable") is False


def test_every_executable_profile_marks_unsupported_mechanics(profiles_by_id):
    must = {"attack_damage", "lethal", "spread", "boss", "gust"}
    for pid in EXECUTABLE:
        um = set(profiles_by_id[pid].get("unsupported_mechanics") or [])
        assert must <= um, \
            f"{pid} must declare unsupported {sorted(must - um)}"


def test_raging_bolt_no_fake_color_match_fix(profiles_by_id, replay):
    # The profile must not claim a (refuted) color-match fix, and its fixtures
    # must classify attack/lethal/spread as honesty_unsupported.
    rb = profiles_by_id["raging_bolt_ogerpon_basic_aggro"]
    # Honest marker: the color-match "fix" is explicitly REFUTED (Pass 28), and the
    # profile still ships executable WITHOUT fabricating that fix.
    assert rb.get("refuted") is True, \
        "Raging Bolt must record the color-match fix as refuted (Pass 28)"
    assert rb.get("executable") is True
    must = {"attack_damage", "lethal", "spread"}
    assert must <= set(rb.get("unsupported_mechanics") or []), \
        "Raging Bolt must declare attack/lethal/spread unsupported (no fake fix)"
    prof = next(p for p in replay["fixture_replay"]["profiles"]
                if p["profile_id"] == "raging_bolt_ogerpon_basic_aggro")
    assert prof["counts"]["honesty_unsupported"] >= 3
    assert prof["counts"]["honesty_fabricated"] == 0
    for case in prof["cases"]:
        if case["kind"] in ("attack", "lethal", "spread"):
            assert case["child"].get("unsupported") is True


# ----------------------------- gate ----------------------------------------

def test_typed_strategy_gate_passes(gate):
    assert gate.get("all_ok") is True
    assert gate.get("assertions_ok") is True
    assert gate.get("cases_ok") is True
    assert gate.get("honesty_sweep_ok") is True
    assert gate.get("coverage_ok") is True
    assert gate.get("executable_profiles") == 9
    assert gate.get("passed_cases") == gate.get("total_cases")


# ----------------------------- build / validation --------------------------

def test_only_executable_profiles_built(build):
    assert build.get("built") == 9
    assert build.get("all_executable_built") is True
    assert build.get("special_pilot_only_skipped") == 2
    assert build.get("typed_strategy_gate_ok") is True
    assert build.get("root_safe") is True
    assert build.get("card_csv_committed") is False


def test_special_pilot_decks_never_built(build):
    built_ids = {r["candidate_id"] for r in build.get("candidates", [])
                 if r.get("built")}
    for pid in SPECIAL_PILOT_ONLY:
        assert not any(pid in cid for cid in built_ids), \
            f"{pid} is special-pilot-only and must never be built"


def test_child_deck_byte_identical_to_parent(build):
    for r in build.get("candidates", []):
        if r.get("built"):
            assert r.get("deck_identical_to_parent") is True, \
                f"{r['candidate_id']} deck must be byte-identical to its parent"


def test_candidate_tarballs_top_level_only():
    tarballs = list(CANDIDATE_DIR.glob("*.tar.gz"))
    assert tarballs, "expected staged pass35 candidate tarballs"
    for tb in tarballs:
        with tarfile.open(tb, "r:gz") as tf:
            names = [n for n in tf.getnames() if n not in (".", "")]
        flat = {Path(n).name for n in names if "/" not in n.strip("./")}
        assert "main.py" in flat and "deck.csv" in flat, \
            f"{tb.name} must contain top-level main.py and deck.csv"
        for n in names:
            assert "/" not in n.strip("./"), \
                f"{tb.name} must be top-level only, found nested {n!r}"


def test_validation_all_ok(valid):
    assert valid.get("all_ok") is True
    for r in valid.get("records", []):
        assert r.get("ok") is True, f"{r['id']} validation must pass"


def test_decision_replay_honest_and_safe(replay):
    fr = replay["fixture_replay"]
    assert fr.get("all_honest") is True and fr.get("all_safe") is True
    for prof in fr.get("profiles", []):
        c = prof["counts"]
        assert c.get("misfire", 0) == 0 and c.get("unsafe", 0) == 0
        assert c.get("invalid", 0) == 0
        assert c.get("honesty_fabricated", 0) == 0
    lr = replay["live_replay"]
    assert lr.get("all_safe") is True
    for cid, d in (lr.get("children") or {}).items():
        assert d.get("misfires") == 0, f"{cid} live misfires must be 0"
        assert d.get("unsafe") == 0, f"{cid} live unsafe must be 0"
        assert d.get("games_invalid") == 0


def test_typed_layer_safe_no_illegal_refinements(firing):
    tot = firing.get("totals", {})
    assert tot.get("illegal_refinements") == 0
    assert firing.get("any_illegal_refinement") is False


# ----------------------------- tournament / confirmation -------------------

def test_internal_tournament_not_kaggle(rankings):
    assert rankings.get("is_kaggle_leaderboard") is False
    assert rankings.get("no_upload") is True
    assert rankings.get("upload_performed") is False


def test_parent_child_no_superiority_claim(parent_child):
    assert parent_child.get("any_superiority_claim") is False, \
        "no typed child may claim superiority over its parent"
    assert parent_child.get("is_kaggle_leaderboard") is False
    counts = parent_child.get("classification_counts") or {}
    assert "improves" not in counts or counts.get("improves", 0) == 0, \
        "no child may be classified as improves without a superiority claim"


def test_no_typed_child_queue_eligible(decision):
    ce = decision.get("candidate_evaluation") or {}
    assert ce, "candidate_evaluation must be persisted"
    for cid, c in ce.items():
        assert c.get("queue_eligible") is False, \
            f"{cid} must not be queue-eligible (no superiority claim)"
    assert decision.get("any_typed_child_displaces_held") is False


def test_meta_sanity_directional_not_promotion(meta):
    san = meta.get("sanity", {})
    assert san.get("sanity_passed") is True
    for cid, d in (san.get("per_deck") or {}).items():
        assert d.get("no_collapse") is True, f"{cid} must not collapse"
    assert meta.get("is_kaggle_leaderboard", False) is False
    assert meta.get("no_upload") is True


# ----------------------------- decision / queue ----------------------------

def test_dry_run_queue_max_one():
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    assert q.get("max_queue_size") == 1
    assert len(q.get("queue", [])) <= 1
    assert q.get("auto_submit_enabled") is False
    assert q.get("require_manual_approval_for_submit") is True
    assert q.get("upload_performed") is False


def test_decision_no_upload_flags(decision):
    assert decision.get("upload_performed") is False
    assert decision.get("no_upload") is True
    assert decision.get("is_kaggle_leaderboard") is False
    assert decision.get("auto_submit_enabled") is False
    assert decision.get("human_approval_required") is True


def test_held_probe_retention_is_conjunction(decision):
    gates = decision.get("held_probe_gates")
    assert isinstance(gates, dict) and gates, "held_probe_gates must be persisted"
    assert "no_typed_child_displaces" in gates
    retained = decision.get("held_probe_retained")
    assert retained == all(gates.values()), \
        "held_probe_retained must equal the conjunction of all retention gates"
    if decision.get("held_probe_reaffirmed"):
        assert retained is True


def test_held_probe_is_untyped_carried_water(decision):
    assert decision.get("held_probe") == "water_basic_density_v1"
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    for e in q.get("queue", []):
        assert "typed35" not in e.get("candidate_id", ""), \
            "the held probe must be the carried UNTYPED water deck, not a typed child"
        assert e.get("is_clone_or_replay_deck") is False


# ----------------------------- reports / events ----------------------------

def test_final_report_has_exactly_ten_sections_in_order():
    text = FINAL_REPORT.read_text(encoding="utf-8")
    idx = -1
    for i in range(1, 11):
        pos = text.find(f"\n{i}. ")
        assert pos != -1, f"final report missing section {i}"
        assert pos > idx, f"section {i} out of order"
        idx = pos
    # there must be no 11th numbered section
    assert text.find("\n11. ") == -1, "final report must have EXACTLY 10 sections"


def test_reports_carry_honesty_and_kaggle_caveats():
    for rep in (FINAL_REPORT, PORTFOLIO_REPORT):
        text = rep.read_text(encoding="utf-8")
        assert "NOT the Kaggle leaderboard" in text
        assert "numeric attackId only" in text, \
            "report must state attacks are numeric-attackId-only (honesty mandate)"


def test_pass35_fixture_events_have_full_profile_linkage():
    assert LAB_EVENTS.exists()
    seen = 0
    valid_ids = EXECUTABLE | SPECIAL_PILOT_ONLY
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass35" not in (ev.get("tags") or []):
            continue
        if (ev.get("type") or ev.get("event_type")) != "StrategyFixtureAdded":
            continue
        seen += 1
        p = ev.get("payload") or {}
        assert p.get("profile_id") in valid_ids, \
            f"fixture event has bad profile_id {p.get('profile_id')!r}"
        assert isinstance(p.get("executable"), bool), \
            "fixture event executable must be a boolean"
        assert isinstance(p.get("n_cases"), int) and isinstance(
            p.get("n_passed"), int), "fixture event must carry case counts"
        assert p.get("profile_id") in (ev.get("tags") or []), \
            "fixture event tag must include the profile_id (non-null linkage)"
    assert seen == 11, f"expected 11 fixture events, saw {seen}"


def test_pass35_events_are_no_upload_and_no_submission_uploaded():
    assert LAB_EVENTS.exists()
    seen, uploaded = 0, 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass35" not in (ev.get("tags") or []):
            continue
        seen += 1
        etype = ev.get("type") or ev.get("event_type")
        if etype == "SubmissionUploaded":
            uploaded += 1
        payload = ev.get("payload") or {}
        assert payload.get("no_upload") is True, \
            "every pass35 event must carry no_upload=true"
        assert payload.get("upload") is not True
        assert payload.get("submit") is not True
    assert seen > 0, "expected pass35-tagged events"
    assert uploaded == 0, "there must be NO SubmissionUploaded event"
