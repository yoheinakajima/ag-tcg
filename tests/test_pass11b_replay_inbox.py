"""ActiveGraph Pass 11B — replay inbox + meta pool automation tests.

Covers (Part K):
* the inbox accepts arbitrary numeric raw filenames; the real ``EpisodeId`` is
  read from the JSON ``info`` block, never from the filename;
* the registry deduplicates by episode id and by file hash;
* deck fingerprints are stable and match known baseline/candidate decks;
* extracted per-seat deck CSVs are exactly 60 integer rows;
* the archetype classifier only keys off ids in the deck handed to it
  (it never invents a card id);
* meta-pool coverage is incomplete with a single archetype and usable/partial
  with several confirmed archetypes;
* the replay-workflow doc exists and forbids manual renaming / committing raw
  payloads.

All tests read the lab's own artifacts; none run Kaggle or mutate root files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptcg_activegraph.meta.archetypes import classify_deck
from ptcg_activegraph.meta.scoring import weighted_meta_score
from ptcg_activegraph.replays import fingerprints as fp
from ptcg_activegraph.replays.inbox import parse_inbox_file, scan_inbox
from ptcg_activegraph.replays.registry import build_registry, load_known_own_decks

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "meta_replays" / "raw"
DECKS_DIR = REPO / "data" / "meta_replays" / "decks"
REGISTRY_JSON = REPO / "data" / "meta_replays" / "replay_registry.json"
WORKFLOW_DOC = REPO / "docs" / "REPLAY_WORKFLOW.md"
# A raw replay whose filename is a bare numeric episode name (no descriptive
# suffix) — proves arbitrary numeric filenames are accepted.
NUMERIC_RAW = RAW_DIR / "80503687.json"


# --------------------------------------------------------------------------- #
# Inbox — arbitrary numeric filenames + EpisodeId comes from JSON, not filename
# --------------------------------------------------------------------------- #
def test_inbox_accepts_arbitrary_numeric_filenames():
    if not RAW_DIR.exists():
        pytest.skip("raw inbox not present")
    entries = scan_inbox(RAW_DIR)
    assert entries, "expected at least one parsed inbox entry"
    # Every successfully parsed entry exposes an episode id and a filename.
    parsed = [e for e in entries if e["status"] != "failed_parse"]
    assert parsed, "expected at least one successfully parsed replay"
    for e in parsed:
        assert e["filename"].endswith(".json")
        assert e["episode_id"] is not None


def test_episode_id_is_read_from_json_not_filename():
    if not NUMERIC_RAW.exists():
        pytest.skip("numeric-named raw replay not present")
    entry = parse_inbox_file(NUMERIC_RAW)
    assert entry["status"] != "failed_parse"
    # The id parsed from the JSON info block is an int, independent of the name.
    assert isinstance(entry["episode_id"], int)
    # It must NOT be derived by string-stripping the filename: prove parity comes
    # from the payload by checking the type/identity is the JSON's, then mangle
    # the filename and confirm the parsed id is unchanged.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        renamed = Path(td) / "totally_unrelated_name.json"
        shutil.copyfile(NUMERIC_RAW, renamed)
        re_entry = parse_inbox_file(renamed)
    assert re_entry["episode_id"] == entry["episode_id"]


# --------------------------------------------------------------------------- #
# Registry — dedupe by episode id and by file hash
# --------------------------------------------------------------------------- #
def _entry(episode_id: int, sha: str, *, filename: str) -> dict:
    return {
        "status": "parsed",
        "filename": filename,
        "path": f"/raw/{filename}",
        "file_sha256": sha,
        "episode_id": episode_id,
        "agents": ["Opp", "Yohei Nakajima"],
        "rewards": [-1, 1],
        "statuses": ["DONE", "DONE"],
        "num_steps": 100,
        "decks": {},
        "our_seats_by_name": [1],
    }


def test_registry_dedupes_duplicate_episode_id():
    entries = [
        _entry(999001, "shaA", filename="a.json"),
        _entry(999001, "shaB", filename="b_same_episode.json"),
    ]
    reg = build_registry(entries, known_own={})
    assert reg["replays_total"] == 2
    assert reg["replays_registered"] == 1
    dups = reg["duplicates_skipped"]
    assert len(dups) == 1
    assert dups[0]["status"] == "duplicate_episode"
    assert dups[0]["episode_id"] == 999001


def test_registry_dedupes_duplicate_file_hash():
    entries = [
        _entry(999002, "sameSha", filename="a.json"),
        _entry(999003, "sameSha", filename="copy.json"),
    ]
    reg = build_registry(entries, known_own={})
    assert reg["replays_registered"] == 1
    assert reg["duplicates_skipped"][0]["status"] == "duplicate_file_hash"


def test_registry_records_failed_parse_as_error_not_record():
    entries = [{"status": "failed_parse", "filename": "bad.json",
                "path": "/raw/bad.json", "error": "boom", "file_sha256": "z"}]
    reg = build_registry(entries, known_own={})
    assert reg["replays_registered"] == 0
    assert reg["errors"] and reg["errors"][0]["error"] == "boom"


# --------------------------------------------------------------------------- #
# Fingerprints — stable + match known own decks
# --------------------------------------------------------------------------- #
def test_deck_fingerprint_is_order_independent_for_multiset():
    a = [1, 2, 2, 3]
    b = [3, 2, 1, 2]
    assert fp.multiset_deck_sha256(a) == fp.multiset_deck_sha256(b)
    # Ordered fingerprint distinguishes order; multiset does not.
    assert fp.ordered_deck_sha256(a) != fp.ordered_deck_sha256(b)
    assert fp.deck_fingerprint(a)["card_count"] == 4
    assert fp.deck_fingerprint(a)["unique_card_count"] == 3


def test_known_own_decks_match_an_extracted_replay_deck():
    known = load_known_own_decks(REPO)
    assert known, "expected at least one known own deck (v1/v2/root)"
    decks = sorted(DECKS_DIR.glob("*_deck.csv"))
    if not decks:
        pytest.skip("no extracted replay decks present")
    # At least one extracted seat deck must fingerprint-match a known own deck
    # (our self-mirror seats are our own v2 line).
    matched = []
    for deck in decks:
        ids = [int(x) for x in deck.read_text().split() if x.strip()]
        label = fp.match_multiset(ids, known)
        if label is not None:
            matched.append((deck.name, label))
    assert matched, "expected at least one extracted deck to match a known own deck"


# --------------------------------------------------------------------------- #
# Extracted deck CSVs — exactly 60 integer rows
# --------------------------------------------------------------------------- #
def test_extracted_deck_csvs_are_60_integer_rows():
    decks = sorted(DECKS_DIR.glob("*_deck.csv"))
    if not decks:
        pytest.skip("no extracted replay decks present")
    for deck in decks:
        rows = [r for r in deck.read_text().splitlines() if r.strip()]
        assert len(rows) == 60, f"{deck.name} has {len(rows)} rows, expected 60"
        for r in rows:
            int(r.strip())  # raises if any row is not an integer


# --------------------------------------------------------------------------- #
# Archetype classifier — never invents ids
# --------------------------------------------------------------------------- #
def test_classifier_evidence_is_subset_of_input_deck():
    """The classifier may only cite ids that are actually in the deck handed in;
    it must never surface an id that was not present (no invention)."""
    metal_deck = [336, 8, 547, 988, 695] + [1] * 55
    res = classify_deck(metal_deck, is_own_deck=False)
    assert res["archetype_id"] == "metal_ex_zacian_ramp"
    assert res["confidence"] == "confirmed"
    assert set(res["evidence_card_ids"]) <= set(metal_deck)


def test_classifier_maxbelt_vs_plain_water():
    base_water = [721, 722, 723] + [2] * 57
    maxbelt = [721, 722, 723, 1205, 1235] + [2] * 55
    assert classify_deck(base_water)["archetype_id"] == "water_kyogre_abomasnow"
    mb = classify_deck(maxbelt)
    assert mb["archetype_id"] == "water_kyogre_abomasnow_maxbelt"
    assert set(mb["evidence_card_ids"]) <= set(maxbelt)


def test_classifier_unknown_deck_invents_nothing():
    res = classify_deck([4242, 4243], is_own_deck=False)
    assert res["confidence"] in ("provisional", "unknown")
    assert set(res["evidence_card_ids"]) <= {4242, 4243}


# --------------------------------------------------------------------------- #
# Meta-pool coverage transitions (single vs several archetypes)
# --------------------------------------------------------------------------- #
def test_coverage_incomplete_with_single_archetype():
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    res = weighted_meta_score({"a": 0.6}, weights, available={"a"})
    assert res["complete"] is False
    assert res["coverage"] < 1.0
    assert set(res["missing_archetypes"]) == {"b", "c"}


def test_coverage_complete_with_all_archetypes_available():
    weights = {"a": 0.5, "b": 0.5}
    res = weighted_meta_score({"a": 0.6, "b": 0.4}, weights,
                              available={"a", "b"})
    assert res["complete"] is True
    assert abs(res["coverage"] - 1.0) < 1e-9


# --------------------------------------------------------------------------- #
# Workflow doc — no manual renaming, raw payloads not committed
# --------------------------------------------------------------------------- #
def test_workflow_doc_forbids_manual_renaming_and_commit():
    assert WORKFLOW_DOC.exists()
    low = WORKFLOW_DOC.read_text(encoding="utf-8").lower()
    assert "do not rename" in low
    assert "episodeid" in low
    assert "not be committed" in low
    # No affirmative upload/submit instruction in the inbox workflow.
    assert "kaggle competitions submit" not in low


def test_registry_artifact_matches_corpus_when_present():
    if not REGISTRY_JSON.exists():
        pytest.skip("registry artifact not built yet")
    reg = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
    assert reg["schema"].startswith("activegraph.replays.registry")
    # Every registered record carries an episode id and a perspective label.
    for rec in reg["records"]:
        assert rec["episode_id"] is not None
        assert "perspective" in rec
