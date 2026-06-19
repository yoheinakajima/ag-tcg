"""Pass 30 — Part N: existing-portfolio hardening tournament tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest, evidence-gated
findings of the hardening pass. They read the committed Pass-30 artifacts and the
lab event store. Nothing here uploads, submits, or pushes; the tests only verify
on-disk state.

Checklist (from the spec):
- no opponent deck clones are built
- all candidates are from the existing portfolio or variants of it
- Raging Bolt hardening variants use only known user deck idea IDs (no invented IDs)
- root main.py / deck.csv byte-unchanged vs the v1 baseline
- candidate tarballs are top-level only (main.py + deck.csv)
- entrypoint validators pass for eligible candidates
- invalid candidates are excluded from the tournament
- Durant is excluded unless smoke-valid
- the internal tournament has is_kaggle_leaderboard false
- the dry-run queue holds at most 1 entry
- no upload flag false / no_upload true
- reports include the internal/Kaggle caveat
- parent/child confirmation artifacts exist
- the Venusaur loop guard is evaluated if present
- the Dragapult parent / search_only comparison is recorded
- Water is kept as the benchmark unless clearly beaten
- every pass30 event carries no_upload=true and no upload/submit/push happened
- the 10-section report exists with all ten numbered sections
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
REPORT = REPO / "data" / "reports" / "pass30_existing_portfolio_hardening_report.md"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
QUEUE = REPO / "data" / "submission_queue.json"
CANDIDATE_DIR = REPO / "data" / "submissions" / "candidates_pass30"

DURANT = "league_durant_deckout_carousel"


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def live():
    return _load("pass30_live_score_status.json")


@pytest.fixture(scope="module")
def registry():
    return _load("pass30_existing_portfolio_registry.json")


@pytest.fixture(scope="module")
def plan():
    return _load("pass30_hardening_plan.json")


@pytest.fixture(scope="module")
def manifest():
    return _load("pass30_candidate_manifest.json")


@pytest.fixture(scope="module")
def valid():
    return _load("pass30_candidate_validation.json")


@pytest.fixture(scope="module")
def smoke():
    return _load("pass30_live_smoke.json")


@pytest.fixture(scope="module")
def rank1():
    return _load("pass30_portfolio_rankings.json")


@pytest.fixture(scope="module")
def pc():
    return _load("pass30_parent_child_confirmations.json")


@pytest.fixture(scope="module")
def diag():
    return _load("pass30_hardening_diagnosis.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass30_strategy_decision.json")


# ----------------------------- safety --------------------------------------

def test_root_main_py_unchanged():
    assert filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False), \
        "root main.py must be byte-identical to the v1 baseline"


def test_root_deck_csv_unchanged():
    assert filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False), \
        "root deck.csv must be byte-identical to the v1 baseline"


def test_manifest_declares_root_untouched(manifest):
    assert manifest.get("root_main_py_untouched") is True
    assert manifest.get("root_deck_csv_untouched") is True


# ----------------------------- portfolio provenance ------------------------

def test_no_opponent_clones(manifest, registry):
    assert manifest.get("no_opponent_clones") is True
    assert registry.get("no_opponent_clones") is True


def test_all_candidates_from_existing_portfolio(manifest, registry):
    # Every registry candidate is one of OUR existing decks or a variant of one.
    fam_cands = {c.get("candidate_id")
                 for f in registry.get("families", [])
                 for c in f.get("candidates", [])}
    assert fam_cands, "registry must list portfolio candidates"
    for r in manifest.get("results", []):
        kind = r.get("kind", "")
        assert kind in {"reused_prior_candidate", "new_portfolio_variant",
                        "built_new_variant"} or r.get("built") is not None, \
            f"candidate {r.get('candidate_id')} has unexpected provenance {kind!r}"
        # parent (if any) must be an existing portfolio deck.
        parent = r.get("parent_id")
        if parent:
            assert parent in fam_cands or parent.startswith("league_") \
                or parent.startswith("core_pilot"), \
                f"{r.get('candidate_id')} parent {parent} is not from the portfolio"


def test_hardening_plan_respects_max_tracks(plan):
    tracks = plan.get("tracks", [])
    max_v = plan.get("max_variants")
    assert max_v == 5, "spec caps hardening variant tracks at 5"
    assert len(tracks) <= max_v, \
        f"plan has {len(tracks)} tracks, exceeding max_variants={max_v}"


def test_plan_new_builds_are_at_most_two_raging_bolt(plan):
    new_rb = plan.get("new_raging_bolt_builds", [])
    assert plan.get("new_builds_total", 0) <= 2, \
        "at most 2 NEW builds allowed (all Raging Bolt)"
    assert all("raging_bolt" in c for c in new_rb), \
        "only Raging Bolt may be newly built per the plan"
    assert len(new_rb) <= 2


def test_only_two_new_raging_bolt_builds(manifest):
    built = manifest.get("candidates_built", [])
    assert len(built) <= 2, f"spec allows AT MOST 2 NEW RB builds, found {len(built)}"
    for cid in built:
        assert "raging_bolt" in cid, \
            f"only Raging Bolt may be newly built; got {cid}"


def test_no_invented_card_ids(manifest):
    assert manifest.get("no_invented_ids") is True


# ----------------------------- tarball hygiene -----------------------------

def test_candidate_tarballs_top_level_only():
    if not CANDIDATE_DIR.exists():
        pytest.skip("no pass30 candidate dir")
    tarballs = list(CANDIDATE_DIR.glob("*.tar.gz"))
    assert tarballs, "expected built/staged pass30 candidate tarballs"
    for tb in tarballs:
        with tarfile.open(tb, "r:gz") as tf:
            names = [n for n in tf.getnames() if n not in (".", "")]
        flat = {Path(n).name for n in names if "/" not in n.strip("./")}
        assert "main.py" in flat and "deck.csv" in flat, \
            f"{tb.name} must contain top-level main.py and deck.csv"
        for n in names:
            depth = n.strip("./").count("/")
            assert depth == 0, f"{tb.name} contains nested entry {n!r} (must be flat)"


# ----------------------------- validation / smoke --------------------------

def test_entrypoint_validators_pass_for_eligible(valid):
    elig = valid.get("tournament_eligible", [])
    assert elig, "expected tournament-eligible candidates"
    by_id = {c.get("candidate_id"): c for c in valid.get("candidates", [])}
    for cid in elig:
        c = by_id.get(cid, {})
        assert c.get("entrypoint_valid") is not False, \
            f"eligible candidate {cid} failed entrypoint validation"


def test_invalid_candidates_excluded_from_tournament(valid, rank1):
    elig = set(valid.get("tournament_eligible", []))
    standings_ids = {s.get("id") for s in rank1.get("standings", [])}
    assert standings_ids <= elig, \
        f"tournament included non-eligible candidates: {standings_ids - elig}"


def test_durant_excluded_unless_smoke_valid(valid, rank1, smoke):
    elig = set(valid.get("tournament_eligible", []))
    standings_ids = {s.get("id") for s in rank1.get("standings", [])}
    durant_res = (smoke.get("results", {}) or {}).get(DURANT, {})
    durant_smoke_ok = bool(durant_res.get("smoke_clean") or durant_res.get("valid"))
    if not durant_smoke_ok:
        assert DURANT not in elig, "Durant must not be eligible without a clean smoke"
        assert DURANT not in standings_ids, "Durant must be excluded from tournament"


# ----------------------------- tournament ----------------------------------

def test_internal_tournament_not_kaggle(rank1):
    assert rank1.get("is_kaggle_leaderboard") is False
    assert rank1.get("no_upload") is True
    assert rank1.get("upload_performed") is False


# ----------------------------- parent/child --------------------------------

def test_parent_child_artifacts_exist(pc):
    pairs = {p.get("id") for p in pc.get("pairs", [])}
    assert pairs, "parent/child confirmation pairs must exist"


def test_dragapult_parent_search_only_comparison_recorded(pc):
    ids = {p.get("id") for p in pc.get("pairs", [])}
    assert "dragapult_parent_vs_search_only" in ids, \
        "the Dragapult parent vs search_only comparison must be recorded"


def test_venusaur_loop_guard_evaluated(pc, diag):
    pair = next((p for p in pc.get("pairs", [])
                 if p.get("id") == "venusaur_parent_vs_loop_guard"), None)
    guard_in_registry = pair is not None
    if guard_in_registry:
        assert pair.get("child") == "effect_loop_exit_guard_v1"
        ven = diag.get("families", {}).get("venusaur", {})
        assert ven.get("hardening_helped") is not None, \
            "Venusaur loop guard must be evaluated (helped verdict present)"


# ----------------------------- decision / queue ----------------------------

def test_water_kept_as_benchmark_unless_beaten(diag, decision):
    water = diag.get("families", {}).get("water", {})
    assert water.get("stay_active") is True, "Water must stay active as benchmark"
    probe = decision.get("recommended_probe_candidate", "")
    # Water is the control, not the probe, unless it clearly wins.
    assert not probe.startswith("league_water") or water.get("hardening_helped"), \
        "Water should remain the benchmark, not be promoted as the probe"


def test_dry_run_queue_max_one(decision):
    assert decision.get("queue_max") == 1
    assert decision.get("queued_candidate_count", 0) <= 1
    if QUEUE.exists():
        q = json.loads(QUEUE.read_text(encoding="utf-8"))
        entries = q if isinstance(q, list) else q.get("queue", q.get("entries", []))
        assert len(entries) <= 1, \
            f"dry-run queue must hold at most 1 entry, found {len(entries)}"
        if isinstance(q, dict):
            assert q.get("max_queue_size", 1) <= 1
            assert q.get("auto_submit_enabled") is False
            assert q.get("upload_performed") is False


def test_no_upload_flags(decision, manifest, live):
    assert decision.get("auto_submit_enabled") is False
    assert decision.get("human_approval_required") is True
    assert decision.get("upload_performed", False) is False
    assert manifest.get("upload_performed") is False
    assert manifest.get("github_push_performed") is False
    assert live.get("upload_performed") is False


# ----------------------------- events & report -----------------------------

def test_pass30_events_are_no_upload():
    assert LAB_EVENTS.exists()
    seen = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if "pass30" not in (ev.get("tags") or []):
            continue
        seen += 1
        payload = ev.get("payload") or {}
        assert payload.get("no_upload") is True, \
            f"pass30 event {ev.get('type')} missing no_upload=true"
        assert payload.get("uploaded", False) is False
        assert payload.get("submitted", False) is False
        assert payload.get("is_kaggle_leaderboard", False) is False
    assert seen >= 10, f"expected the pass30 event family to be emitted, saw {seen}"


SECTION_HEADERS = [
    "1. Root safety",
    "2. Live score state",
    "3. Portfolio / hardening plan",
    "4. Validation / smoke",
    "5. Internal tournament",
    "6. Parent/child confirmations",
    "7. Meta sanity",
    "8. Compatibility diagnosis",
    "9. Strategy decision / ActiveGraph",
    "10. Next recommendation",
]


def test_report_has_all_ten_sections_in_order():
    assert REPORT.exists(), "the 10-section final report must exist"
    text = REPORT.read_text(encoding="utf-8")
    last = -1
    for header in SECTION_HEADERS:
        idx = text.find("\n" + header)
        assert idx != -1, f"report missing exact section header {header!r}"
        assert idx > last, f"section {header!r} is out of order"
        last = idx


def test_reports_include_internal_kaggle_caveat():
    assert REPORT.exists()
    text = REPORT.read_text(encoding="utf-8")
    assert "NOT the Kaggle leaderboard" in text, \
        "report must carry the internal/Kaggle caveat"
