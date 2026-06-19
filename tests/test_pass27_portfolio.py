"""Pass 27 — Part N: portfolio integrity tests.

These tests assert the LOCAL/READ-ONLY guarantees and the honest findings of the
multi-archetype portfolio pass. They read the committed Pass-27 artifacts, the
packaged candidate tarballs, the playbooks, and the card database. Nothing here
uploads, submits, or pushes; the tests only verify on-disk state.
"""

from __future__ import annotations

import csv
import filecmp
import json
import tarfile
from pathlib import Path

import pytest

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
TARBALL_DIR = REPO / "data" / "submissions" / "candidates_pass27"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
REPORT = REPO / "data" / "reports" / "pass27_multi_archetype_portfolio_report.md"


def _load(name: str) -> dict:
    return json.loads((EXP / name).read_text(encoding="utf-8"))


# ----------------------------- fixtures ------------------------------------

@pytest.fixture(scope="module")
def registry():
    return _load("pass27_portfolio_registry.json")


@pytest.fixture(scope="module")
def manifest():
    return _load("pass27_candidate_manifest.json")


@pytest.fixture(scope="module")
def validation():
    return _load("pass27_candidate_validation.json")


@pytest.fixture(scope="module")
def smoke():
    return _load("pass27_live_smoke.json")


@pytest.fixture(scope="module")
def rankings():
    return _load("pass27_portfolio_rankings.json")


@pytest.fixture(scope="module")
def gap():
    return _load("pass27_core_gameplay_gap_analysis.json")


@pytest.fixture(scope="module")
def decision():
    return _load("pass27_strategy_decision.json")


@pytest.fixture(scope="module")
def taxonomy():
    return _load("pass27_role_taxonomy.json")


@pytest.fixture(scope="module")
def card_db():
    """Map card_id -> row (col0=id, col1=name, col4=stage/type, col6=category)."""
    rows = {}
    with CARD_DB.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for r in reader:
            if not r or not r[0].strip().isdigit():
                continue
            rows[int(r[0])] = r
    return rows


# ----------------------------- ID validity ----------------------------------

def _deck_card_counts(deck) -> dict:
    """Return {card_id: count} from a registry deck entry.

    `cards` is a list of {"id", "count", "is_basic_energy", ...} dicts.
    """
    counts = {}
    for c in deck.get("cards", []):
        cid = int(c["id"])
        counts[cid] = counts.get(cid, 0) + int(c.get("count", 1))
    return counts


def test_all_deck_ids_validate_against_card_db(registry, card_db):
    for deck in registry["decks"]:
        for cid in _deck_card_counts(deck):
            assert cid in card_db, (
                f"{deck['key']}: card id {cid} not in EN_Card_Data.csv")


def test_no_invented_ids_flag(manifest):
    assert manifest["no_invented_ids"] is True


# ----------------------------- 60-card legality -----------------------------

def _is_basic_energy(row) -> bool:
    return "basic energy" in (row[4] or "").strip().lower()


def test_every_deck_is_legal_60_with_copy_caps(registry, card_db):
    for deck in registry["decks"]:
        counts = _deck_card_counts(deck)
        total = sum(counts.values())
        assert total == 60, f"{deck['key']} is not 60 cards ({total})"
        assert deck.get("valid") is True, f"{deck['key']} marked invalid"
        for cid, n in counts.items():
            if _is_basic_energy(card_db[cid]):
                continue  # basic energy: unlimited copies allowed
            assert n <= 4, (
                f"{deck['key']}: card {cid} appears {n}>4 (non-basic-energy)")


def test_basic_energy_can_exceed_four(registry, card_db):
    """Any deck with >4 of one card may only do so for a basic-energy card."""
    for deck in registry["decks"]:
        for cid, n in _deck_card_counts(deck).items():
            if n > 4:
                assert _is_basic_energy(card_db[cid]), (
                    f"{deck['key']}: non-basic card {cid} appears {n}>4")


# ----------------------------- taxonomy -------------------------------------

def test_taxonomy_has_required_fields(taxonomy):
    for key in ("role_vocabulary", "unsupported_runtime_roles", "decks"):
        assert key in taxonomy, f"taxonomy missing {key}"
    assert taxonomy["cards_without_mapped_role"] in ([], None) or \
        len(taxonomy["cards_without_mapped_role"]) == 0


def test_taxonomy_maps_every_registry_deck(taxonomy, registry):
    tax_decks = {d.get("key") or d.get("id") or d.get("candidate_id")
                 for d in (taxonomy["decks"] if isinstance(taxonomy["decks"], list)
                           else taxonomy["decks"].keys())} \
        if isinstance(taxonomy["decks"], list) else set(taxonomy["decks"].keys())
    reg_decks = {d["key"] for d in registry["decks"]}
    # every registry deck should appear in the taxonomy mapping
    assert reg_decks.issubset(tax_decks), (reg_decks - tax_decks)


# ----------------------------- playbook role names --------------------------

@pytest.mark.skipif(yaml is None, reason="pyyaml not available")
def test_playbook_roles_reference_real_deck_cards(manifest, registry):
    """Each playbook `roles` entry must map a non-empty role token to card ids
    that actually appear in that deck, and `basic_energy` roles must only hold
    basic-energy ids. This is a real integrity check (no vacuous asserts)."""
    deck_cards = {d["candidate_id"]: _deck_card_counts(d) for d in registry["decks"]}
    checked = 0
    for c in manifest["candidates_built"]:
        pb = REPO / c["playbook"]
        if not pb.exists():
            continue
        doc = yaml.safe_load(pb.read_text(encoding="utf-8")) or {}
        roles = doc.get("roles")
        if not isinstance(roles, dict) or not roles:
            continue
        cards_in_deck = set(deck_cards.get(c["candidate_id"], {}))
        assert cards_in_deck, f"{c['candidate_id']}: no deck cards in registry"
        for token, ids in roles.items():
            assert isinstance(token, str) and token.strip(), \
                f"{pb.name}: empty role token"
            assert isinstance(ids, list) and ids, f"{pb.name}: role {token} empty"
            for cid in ids:
                assert int(cid) in cards_in_deck, (
                    f"{pb.name}: role {token} references card {cid} "
                    "not present in the deck")
        checked += 1
    assert checked > 0, "no playbooks with roles were checked"


@pytest.mark.skipif(yaml is None, reason="pyyaml not available")
def test_playbook_basic_energy_role_only_holds_basic_energy(manifest, card_db):
    for c in manifest["candidates_built"]:
        pb = REPO / c["playbook"]
        if not pb.exists():
            continue
        roles = (yaml.safe_load(pb.read_text(encoding="utf-8")) or {}).get("roles", {})
        for cid in roles.get("basic_energy", []) if isinstance(roles, dict) else []:
            assert _is_basic_energy(card_db[int(cid)]), (
                f"{pb.name}: basic_energy role contains non-basic card {cid}")


# ----------------------------- tarball shape --------------------------------

def test_tarballs_contain_only_top_level_main_and_deck():
    tarballs = sorted(TARBALL_DIR.glob("*.tar.gz"))
    assert tarballs, "no pass27 tarballs found"
    for tb in tarballs:
        with tarfile.open(tb, "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
        base = sorted(Path(n).name for n in names)
        assert base == ["deck.csv", "main.py"], f"{tb.name}: members={names}"
        for n in names:
            assert "/" not in n.strip("./"), f"{tb.name}: non-top-level {n}"


def test_entrypoint_present_in_each_tarball():
    for tb in TARBALL_DIR.glob("*.tar.gz"):
        with tarfile.open(tb, "r:gz") as tf:
            main = next((m for m in tf.getmembers()
                         if Path(m.name).name == "main.py"), None)
            assert main is not None, f"{tb.name}: no main.py"
            data = tf.extractfile(main).read().decode("utf-8", "replace")
        assert "def" in data and len(data) > 100, f"{tb.name}: main.py looks empty"


# ----------------------------- league eligibility ---------------------------

def test_blocked_decks_not_in_league(manifest, rankings):
    blocked = set(manifest.get("league_blocked", []))
    participants = {s["id"] for s in rankings["standings"]}
    assert blocked.isdisjoint(participants), (
        f"blocked decks in league: {blocked & participants}")


def test_durant_blocked_and_smoke_invalid(manifest, smoke):
    durant = "league_durant_deckout_carousel"
    assert durant in manifest.get("league_blocked", []), "Durant must be league-blocked"
    res = smoke.get("results", {}).get(durant, {})
    # Durant is only allowed into the league if it became smoke-valid; it did not.
    assert res.get("clean") is not True, "Durant unexpectedly smoke-valid"


# ----------------------------- no-upload / kaggle flags ----------------------

def test_is_kaggle_leaderboard_false_everywhere(validation, smoke, rankings):
    assert validation.get("is_kaggle_leaderboard") is False
    assert smoke.get("is_kaggle_leaderboard") is False
    assert rankings.get("is_kaggle_leaderboard") is False


def test_no_upload_flags(manifest, validation, smoke, decision):
    assert manifest.get("upload_performed") is False
    assert validation.get("upload_performed") is False
    assert smoke.get("upload_performed") is False
    assert decision.get("upload_performed") is False
    assert decision.get("submit") is False
    assert decision.get("github_push") is False


# ----------------------------- root safety ----------------------------------

def test_root_files_byte_identical_to_baseline():
    for name in ("main.py", "deck.csv"):
        root = REPO / name
        base = BASELINE / name
        assert root.exists() and base.exists(), f"missing {name}"
        assert filecmp.cmp(root, base, shallow=False), (
            f"root {name} differs from baseline v1_kaggle_349_8")


def test_manifest_records_root_untouched(manifest):
    assert manifest.get("root_main_py_untouched") is True
    assert manifest.get("root_deck_csv_untouched") is True


# ----------------------------- report caveat --------------------------------

def test_report_states_internal_not_kaggle():
    text = REPORT.read_text(encoding="utf-8").lower()
    assert "not the kaggle leaderboard" in text or \
        ("not" in text and "kaggle" in text and "promotion signal" in text)


def test_report_has_all_ten_sections():
    text = REPORT.read_text(encoding="utf-8")
    for n, title in [
        (1, "Root safety"), (2, "Live score state"), (3, "Portfolio registry"),
        (4, "Candidates"), (5, "Validation / smoke"), (6, "Internal league"),
        (7, "Core gameplay gaps"), (8, "Strategy decision"),
        (9, "Report site / ActiveGraph"), (10, "Next recommendation")]:
        assert f"{n}. {title}" in text, f"missing section {n}. {title}"


# ----------------------------- core findings --------------------------------

def _comp(gap, name):
    return next(c for c in gap["competencies"] if c["name"] == name)


def test_raging_bolt_aggro_gap_is_failing(gap, rankings):
    c = _comp(gap, "color-matched energy attachment")
    assert c["status"] == "FAIL"
    rb = next((s for s in rankings["standings"]
               if s["id"] == "league_raging_bolt_ogerpon"), None)
    assert rb is not None and rb["adj_win_rate"] == 0.0, "raging_bolt should be 0-win"


def test_dragapult_spread_targeting_gap(gap):
    c = _comp(gap, "spread/bench target planning")
    assert c["status"] == "FAIL"
    assert c["scope"] == "deck-specific"


def test_chaos_not_promotable(decision, gap):
    # deckout/chaos must be a recognized failing competency and the decision must
    # NOT promote / probe anything.
    c = _comp(gap, "mill/deckout win condition")
    assert c["status"] == "FAIL"
    assert decision.get("future_kaggle_probe") is False
    assert decision.get("submit") is False


def test_highest_priority_gap_is_deck_agnostic(gap):
    top = gap["summary"]["highest_priority_generic_gap"]
    agnostic = gap["summary"]["deck_agnostic_failures"]
    assert top in agnostic, "the headline gap must be deck-agnostic"
