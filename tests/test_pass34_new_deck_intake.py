"""Pass 34 — Part O: new-deck intake + easy basic / chaos lane split tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest, evidence-gated
findings of the Pass-34 new-deck intake. They read the committed Pass-34 artifacts
and the lab event store. Nothing here uploads, submits, or pushes; the tests only
verify on-disk state.

Checklist (from the spec, Part O):
- all new card IDs validated against EN_Card_Data.csv
- energy IDs resolved from card DB, not user placeholders
- skeleton counts need not sum to 60 but built decklists must
- non-energy copy cap <= 4
- Basic Energy copies may exceed 4
- missing evolution prerequisites block or are explicitly fixed with verified IDs
- Mega Diancie stage is read from card DB
- Miraidon candidate is built only if legal
- Diamond candidate is built only if legal
- Toxic/Durant excluded from normal tournament if special pilot not executable
- Durant remains blocked unless smoke-valid
- tarballs top-level only
- entrypoint validators pass for eligible candidates
- internal tournament has is_kaggle_leaderboard=false
- dry-run queue max 1
- no upload flag false / no_upload true
- root files unchanged
- reports include normal lane / special lane distinction
- no opponent clones are built
- all new pass34 events carry no_upload=true
"""

from __future__ import annotations

import csv
import filecmp
import json
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
REPORT = REPO / "data" / "reports" / "pass34_new_deck_intake_tournament_report.md"
STRAT_REPORT = REPO / "data" / "reports" / "activegraph_strategy_report.md"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
QUEUE = REPO / "data" / "submission_queue.json"
CANDIDATE_DIR = REPO / "data" / "submissions" / "candidates_pass34"

MIRAIDON = "mono_lightning_miraidon_easy"
DIAMOND = "diamond_toolbox_diancie"
TOXIC = "toxic_trap_poison_lock"
DURANT = "deckout_carousel_durant_v2"
NORMAL_IDS = {MIRAIDON, DIAMOND}
SPECIAL_IDS = {TOXIC, DURANT}


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def live():
    return _load("pass34_live_score_status.json")


@pytest.fixture(scope="module")
def intake():
    return _load("pass34_deck_intake.json")


@pytest.fixture(scope="module")
def intake_by_id(intake):
    return {d["deck_id"]: d for d in intake.get("decks", [])}


@pytest.fixture(scope="module")
def builds():
    return _load("pass34_decklist_builds.json")


@pytest.fixture(scope="module")
def builds_by_id(builds):
    return {r["deck_id"]: r for r in builds.get("results", [])}


@pytest.fixture(scope="module")
def manifest():
    return _load("pass34_candidate_manifest.json")


@pytest.fixture(scope="module")
def manifest_by_id(manifest):
    return {r["candidate_id"]: r for r in manifest.get("results", [])}


@pytest.fixture(scope="module")
def valid():
    return _load("pass34_candidate_validation.json")


@pytest.fixture(scope="module")
def valid_by_id(valid):
    return {r["candidate_id"]: r for r in valid.get("results", [])}


@pytest.fixture(scope="module")
def smoke():
    return _load("pass34_live_smoke.json")


@pytest.fixture(scope="module")
def smoke_by_id(smoke):
    return {r["candidate_id"]: r for r in smoke.get("results", [])}


@pytest.fixture(scope="module")
def rankings():
    return _load("pass34_new_deck_rankings.json")


@pytest.fixture(scope="module")
def diag():
    return _load("pass34_special_lane_diagnosis.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass34_strategy_decision.json")


@pytest.fixture(scope="module")
def card_db_ids():
    ids = set()
    with CARD_DB.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                ids.add(int(row["Card ID"]))
            except (KeyError, ValueError, TypeError):
                continue
    return ids


# ----------------------------- safety --------------------------------------

def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


def test_card_db_not_committed():
    # EN_Card_Data.csv must never be committed (gitignored); it may exist locally.
    gi = (REPO / ".gitignore").read_text(encoding="utf-8") if (
        REPO / ".gitignore").exists() else ""
    assert "EN_Card_Data.csv" in gi or "EN_Card_Data" in gi, \
        "EN_Card_Data.csv must be gitignored (never committed)"


# ----------------------------- intake / ID validation ----------------------

def test_all_new_card_ids_exist_in_card_db(intake, card_db_ids):
    for d in intake.get("decks", []):
        for c in d.get("cards_validated", []):
            assert c.get("exists") is True, \
                f"{d['deck_id']} card {c.get('id')} marked non-existent"
            assert int(c["id"]) in card_db_ids, \
                f"{d['deck_id']} card id {c['id']} not found in EN_Card_Data.csv"


def test_no_invented_ids_no_missing(intake):
    for d in intake.get("decks", []):
        assert d.get("missing_ids") == [], \
            f"{d['deck_id']} has unresolved/missing ids {d.get('missing_ids')}"


def test_energy_ids_resolved_from_card_db(intake, card_db_ids):
    expected = {MIRAIDON: 4, DIAMOND: 5, TOXIC: 7, DURANT: 7}
    for d in intake.get("decks", []):
        er = d.get("energy_resolution") or []
        assert er, f"{d['deck_id']} must record energy resolution"
        for e in er:
            rid = e.get("resolved_card_id")
            assert rid in card_db_ids, \
                f"{d['deck_id']} energy id {rid} not in card DB"
            assert "not a user placeholder" in (e.get("note") or ""), \
                f"{d['deck_id']} energy id must be DB-resolved, not a placeholder"
        assert er[0]["resolved_card_id"] == expected[d["deck_id"]], \
            f"{d['deck_id']} expected basic energy id {expected[d['deck_id']]}"


def test_non_energy_copy_cap_respected(intake):
    for d in intake.get("decks", []):
        assert d.get("copy_cap_violations") == [], \
            f"{d['deck_id']} has non-energy copy-cap violations"
        for c in d.get("cards_validated", []):
            # Pokémon/Trainer (non Basic-energy) capped at 4.
            assert c.get("copy_cap_ok") is True, \
                f"{d['deck_id']} card {c.get('id')} exceeds the 4-copy cap"
            assert c.get("count", 0) <= 4, \
                f"{d['deck_id']} card {c.get('id')} has {c.get('count')} copies (>4)"


def test_mega_diancie_stage_read_from_card_db(intake_by_id):
    chk = intake_by_id[DIAMOND].get("mega_diancie_stage_check") or {}
    assert chk.get("stage_from_db"), "Mega Diancie stage must be read from the card DB"
    assert chk.get("is_basic") is True, \
        "Mega Diancie ex must be confirmed Basic per the DB (Diamond buildable)"


def test_missing_evolution_prereqs_fixed_with_verified_ids(builds_by_id, card_db_ids):
    # Toxic (Mismagius needs Misdreavus) and Durant (Whimsicott needs Cottonee)
    # must each carry an explicit correction adding a VERIFIED Basic id.
    for cid in SPECIAL_IDS:
        corr = builds_by_id[cid].get("corrections_applied", [])
        assert corr, f"{cid} must record an explicit evolution correction"
        for c in corr:
            assert int(c["added_basic_id"]) in card_db_ids, \
                f"{cid} correction adds non-verified id {c.get('added_basic_id')}"


# ----------------------------- decklist build ------------------------------

def test_skeletons_need_not_sum_to_60(intake):
    # At least one skeleton does NOT sum to 60 — the spec allows partial skeletons.
    assert any(d.get("skeleton_sums_to_60") is False for d in intake.get("decks", [])), \
        "skeletons are allowed to be partial (need not sum to 60)"


def test_built_decklists_are_exactly_60(builds):
    for r in builds.get("results", []):
        if r.get("built"):
            assert r.get("deck_size") == 60, \
                f"{r['deck_id']} built decklist must be exactly 60 cards"


def test_basic_energy_may_exceed_four(builds_by_id):
    # Basic Energy copies are allowed to exceed 4 (and in practice do).
    assert any(r.get("energy_copies", 0) > 4 for r in builds_by_id.values()), \
        "at least one built deck should run more than 4 Basic Energy"


def test_non_basic_energy_cap_respected(builds_by_id):
    for cid, r in builds_by_id.items():
        assert r.get("non_basic_energy_max_copies", 0) <= 4, \
            f"{cid} non-Basic energy must respect the 4-copy cap"


# ----------------------------- candidate / lane build ----------------------

def test_miraidon_built_only_if_legal(manifest_by_id, valid_by_id):
    m = manifest_by_id[MIRAIDON]
    assert m.get("built") is True
    v = valid_by_id[MIRAIDON]
    assert v.get("tarball_valid") is True and v.get("entrypoint_valid") is True, \
        "Miraidon may only be built/packaged if its tarball+entrypoint validate"


def test_diamond_built_only_if_legal(manifest_by_id, valid_by_id):
    m = manifest_by_id[DIAMOND]
    assert m.get("built") is True
    v = valid_by_id[DIAMOND]
    assert v.get("tarball_valid") is True and v.get("entrypoint_valid") is True, \
        "Diamond may only be built/packaged if its tarball+entrypoint validate"


def test_special_lane_blocked_from_league(manifest_by_id):
    for cid in SPECIAL_IDS:
        assert manifest_by_id[cid].get("blocked_from_league") is True, \
            f"{cid} must be blocked_from_league (special pilot not executable)"


def test_special_decks_excluded_from_tournament(rankings):
    eligible = {r["id"] for r in rankings.get("standings", [])}
    for cid in SPECIAL_IDS:
        assert cid not in eligible, \
            f"{cid} must be excluded from the normal tournament"


def test_durant_blocked_unless_smoke_valid(smoke_by_id, rankings):
    s = smoke_by_id[DURANT]
    assert s.get("clean") is not True, "Durant generic-pilot smoke must not be clean"
    eligible = {r["id"] for r in rankings.get("standings", [])}
    assert DURANT not in eligible, "Durant stays blocked while smoke-invalid"


def test_special_deck_is_legal_but_pilot_blocked(diag):
    # Honesty: the special decks are blocked by the PILOT, not the decklist.
    for d in diag.get("diagnoses", []):
        assert d.get("decklist_valid") is True, \
            f"{d['candidate_id']} decklist must be valid"
        assert d.get("built") is True
        assert d.get("smoke_valid") is False
        assert d.get("should_enter_special_pilot_sprint") is True


# ----------------------------- tarball hygiene -----------------------------

def test_candidate_tarballs_top_level_only():
    tarballs = list(CANDIDATE_DIR.glob("*.tar.gz"))
    assert tarballs, "expected staged pass34 candidate tarballs"
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

def test_entrypoint_validators_pass_for_all_candidates(valid_by_id):
    for cid, r in valid_by_id.items():
        assert r.get("tarball_valid") is True, f"{cid} tarball validator must pass"
        assert r.get("entrypoint_valid") is True, \
            f"{cid} entrypoint validator must pass"


def test_normal_lane_smoke_clean(smoke_by_id):
    for cid in NORMAL_IDS:
        assert smoke_by_id[cid].get("clean") is True, \
            f"{cid} normal-lane smoke must be clean"


# ----------------------------- tournament / queue --------------------------

def test_internal_tournament_not_kaggle(rankings):
    assert rankings.get("is_kaggle_leaderboard") is False
    assert rankings.get("no_upload") is True
    assert rankings.get("upload_performed") is False


def test_dry_run_queue_max_one():
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    assert q.get("max_queue_size") == 1
    assert len(q.get("queue", [])) <= 1, "dry-run queue must hold at most 1 entry"
    assert q.get("auto_submit_enabled") is False
    assert q.get("require_manual_approval_for_submit") is True
    assert q.get("upload_performed") is False


def test_decision_no_upload_flags(decision, manifest, live):
    assert decision.get("upload_performed") is False
    assert decision.get("no_upload") is True
    assert decision.get("is_kaggle_leaderboard") is False
    assert decision.get("auto_submit_enabled") is False
    assert decision.get("human_approval_required") is True
    assert manifest.get("upload_performed") is False
    assert live.get("upload_performed") is False


def test_new_decks_not_queued(decision):
    # New decks are candidate_for_confirmation, NOT auto-queued.
    ce = decision.get("candidate_evaluation") or {}
    for cid in NORMAL_IDS:
        assert ce.get(cid, {}).get("queue_eligible") is False, \
            f"{cid} must not be queue-eligible (candidate_for_confirmation only)"
    assert decision.get("any_new_candidate_displaces_held") is False


def test_held_probe_retention_requires_no_collapse(decision):
    # The held probe may only be retained when ALL retention gates hold,
    # including no meta collapse anywhere — gates must be a real conjunction.
    gates = decision.get("held_probe_gates")
    assert isinstance(gates, dict) and gates, "held_probe_gates must be persisted"
    assert "held_no_meta_collapse" in gates, \
        "retention must include the no-collapse gate"
    retained = decision.get("held_probe_retained")
    assert retained == all(gates.values()), \
        "held_probe_retained must equal the conjunction of all retention gates"
    if retained:
        assert gates["held_no_meta_collapse"] is True, \
            "a retained held probe must not collapse anywhere"
    # Re-affirmation (queue entry) must never happen without retention.
    if decision.get("held_probe_reaffirmed"):
        assert retained is True


def test_report_root_safety_is_evidence_derived():
    # Section 1 must reflect real byte-comparison vs baseline, not constants.
    main_ok = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_ok = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    text = REPORT.read_text(encoding="utf-8")
    sec1 = text.split("\n1. Root safety", 1)[1].split("\n2. ", 1)[0]
    exp_main = "yes" if main_ok else "no"
    exp_deck = "yes" if deck_ok else "no"
    assert f"root main.py unchanged: {exp_main}" in sec1
    assert f"root deck.csv unchanged: {exp_deck}" in sec1
    exp_pkg = "PASS" if (main_ok and deck_ok) else "FAIL"
    assert f"package verify: {exp_pkg}" in sec1


# ----------------------------- events / reports ----------------------------

def test_pass34_events_are_no_upload():
    assert LAB_EVENTS.exists(), "lab event store must exist"
    seen = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass34" not in (ev.get("tags") or []):
            continue
        seen += 1
        payload = ev.get("payload") or {}
        assert payload.get("no_upload") is True, \
            "every pass34 event must carry no_upload=true"
        assert payload.get("upload") is not True
        assert payload.get("submit") is not True
        assert payload.get("github_push") is not True
    assert seen > 0, "expected pass34-tagged events"


def test_no_opponent_clones_built(manifest):
    src = manifest.get("generic_pilot_source") or ""
    assert "candidates_pass" in src, \
        "generic pilot source must be one of OUR candidate tarballs"
    for r in manifest.get("results", []):
        # Every candidate is one of the four intake decks — no opponent clones.
        assert r.get("candidate_id") in (NORMAL_IDS | SPECIAL_IDS), \
            f"unexpected (possibly clone) candidate {r.get('candidate_id')}"


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
        "ActiveGraph Pass 34 New Deck Intake + Easy Basic / Chaos Lane Split Report")


def test_reports_include_lane_distinction_and_caveat():
    text = REPORT.read_text(encoding="utf-8")
    assert "normal-lane" in text and "special-lane" in text, \
        "report must distinguish the normal vs special lanes"
    assert "NOT the Kaggle leaderboard" in text or "NOT a promotion" in text, \
        "report must carry the internal/Kaggle caveat"
    strat = STRAT_REPORT.read_text(encoding="utf-8")
    assert "normal lane" in strat or "normal-lane" in strat
