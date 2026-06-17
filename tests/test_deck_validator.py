"""Tests for deck IO, validation and features."""

from ptcg_activegraph.decks.deck_io import parse_deck_text, save_deck, load_deck
from ptcg_activegraph.decks.validator import validate_deck


def test_rejects_non_60_card_deck():
    result = validate_deck([1, 2, 3])
    assert result.valid is False
    assert any("60" in e for e in result.errors)


def test_accepts_60_integer_ids():
    deck = [i % 15 + 1 for i in range(60)]
    result = validate_deck(deck)
    assert result.valid is True
    assert result.size == 60


def test_rejects_non_integer_entries():
    deck = ["x"] + [1] * 59
    result = validate_deck(deck)
    assert result.valid is False
    assert any("not an integer" in e for e in result.errors)


def test_summarizes_counts():
    deck = [1, 1, 2] + [3] * 57
    result = validate_deck(deck)
    assert result.counts[1] == 2
    assert result.counts[2] == 1
    assert result.counts[3] == 57


def test_max_copies_warning_without_db():
    # 60 copies of one id: a copy-count warning but still structurally valid.
    result = validate_deck([7] * 60)
    assert result.valid is True
    assert any("appears" in w for w in result.warnings)


def test_parse_deck_text_tolerant():
    text = "# header\nid\n1\n2,3\n\n4\n"
    assert parse_deck_text(text) == [1, 2, 3, 4]


def test_save_and_load_roundtrip(tmp_path):
    deck = [i % 15 + 1 for i in range(60)]
    path = save_deck(tmp_path / "deck.csv", deck)
    loaded = load_deck(path)
    assert loaded == deck
