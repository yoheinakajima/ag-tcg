"""Tests for deck resolution, placeholder detection, and baseline generation."""

import csv

from ptcg_activegraph.decks.baseline_decks import generate_baseline_deck_from_records
from ptcg_activegraph.decks.resolve_deck import (
    is_placeholder_deck,
    resolve_deck,
)


def test_placeholder_all_identical():
    assert is_placeholder_deck([1] * 60) is True


def test_placeholder_known_seed():
    seed = [c for c in range(1, 16) for _ in range(4)]
    assert is_placeholder_deck(seed) is True


def test_placeholder_meta_overrides_true():
    real_looking = [1000 + i for i in range(60)]
    assert is_placeholder_deck(real_looking, meta={"placeholder": False}) is False
    assert is_placeholder_deck(real_looking, meta={"placeholder": True}) is True


def test_non_placeholder_large_ids():
    deck = [1000 + (i % 20) for i in range(60)]
    assert is_placeholder_deck(deck) is False


def _write_60_deck(path, base=2000):
    ids = [base + (i % 20) for i in range(60)]
    path.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")


def test_resolve_adopts_valid_existing(tmp_path):
    deck = tmp_path / "deck.csv"
    _write_60_deck(deck)
    result = resolve_deck(root=tmp_path, deck_path=deck)
    assert result.ok
    assert result.source == "existing"
    assert len(result.card_ids) == 60


def test_resolve_copies_sample(tmp_path):
    # Placeholder deck.csv present, but a valid sample submission exists.
    deck = tmp_path / "deck.csv"
    deck.write_text("\n".join(["1"] * 60) + "\n", encoding="utf-8")
    sample_dir = tmp_path / "sample_submission"
    sample_dir.mkdir()
    _write_60_deck(sample_dir / "deck.csv", base=3000)

    result = resolve_deck(root=tmp_path, deck_path=deck)
    assert result.ok
    assert result.source == "sample"
    assert len(result.card_ids) == 60


def test_resolve_fails_loudly_when_nothing(tmp_path):
    deck = tmp_path / "deck.csv"
    deck.write_text("\n".join(["1"] * 60) + "\n", encoding="utf-8")
    result = resolve_deck(root=tmp_path, deck_path=deck)
    assert not result.ok
    assert result.source == "none"
    assert any("sample_submission" in e for e in result.errors)


def _synthetic_card_records():
    records = []
    for i in range(1, 6):
        records.append({
            "Card ID": str(100 + i), "Card Name": f"Mon{i}", "Category": "Pokémon",
            "Stage (Pokémon) / Type (Energy and Trainer)": "Basic",
            "Previous stage": "", "HP": str(60 + i * 10), "Type": "Water",
            "Retreat": "1", "Damage": "30", "Effect Explanation": "",
        })
    records.append({
        "Card ID": "200", "Card Name": "Big", "Category": "Pokémon",
        "Stage (Pokémon) / Type (Energy and Trainer)": "Stage 2",
        "Previous stage": "Mid", "HP": "180", "Type": "Water", "Retreat": "3",
        "Damage": "200", "Effect Explanation": "",
    })
    for i in range(1, 10):
        eff = "Draw 3 cards" if i % 2 == 0 else "Switch your active Pokémon"
        records.append({
            "Card ID": str(300 + i), "Card Name": f"T{i}", "Category": "Trainer",
            "Stage (Pokémon) / Type (Energy and Trainer)": "Supporter",
            "Previous stage": "", "HP": "", "Type": "", "Retreat": "",
            "Damage": "", "Effect Explanation": eff,
        })
    records.append({
        "Card ID": "400", "Card Name": "Water Energy", "Category": "Energy",
        "Stage (Pokémon) / Type (Energy and Trainer)": "Basic Energy",
        "Previous stage": "", "HP": "", "Type": "Water", "Retreat": "",
        "Damage": "", "Effect Explanation": "",
    })
    return records


def test_generate_baseline_from_records():
    gen = generate_baseline_deck_from_records(_synthetic_card_records())
    assert gen["ok"] is True
    assert len(gen["card_ids"]) == 60
    assert is_placeholder_deck(gen["card_ids"]) is False
    # Stage 2 (id 200) must be excluded.
    assert 200 not in gen["card_ids"]
    # Energy filler present.
    assert 400 in gen["card_ids"]


def test_generate_fails_without_basics():
    records = [{
        "Card ID": "400", "Card Name": "Water Energy", "Category": "Energy",
        "Stage (Pokémon) / Type (Energy and Trainer)": "Basic Energy",
        "Type": "Water", "Effect Explanation": "",
    }]
    gen = generate_baseline_deck_from_records(records)
    assert gen["ok"] is False
    assert any("Basic" in e for e in gen["errors"])


def test_resolve_generates_from_csv(tmp_path):
    (tmp_path / "data" / "cards").mkdir(parents=True)
    records = _synthetic_card_records()
    cols = list({k for r in records for k in r.keys()})
    # Stable column order from first record.
    cols = list(records[0].keys())
    with open(tmp_path / "data" / "cards" / "EN_Card_Data.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow({c: r.get(c, "") for c in cols})

    deck = tmp_path / "deck.csv"
    deck.write_text("\n".join(["1"] * 60) + "\n", encoding="utf-8")
    result = resolve_deck(root=tmp_path, deck_path=deck)
    assert result.ok
    assert result.source == "generated"
    assert len(result.card_ids) == 60
