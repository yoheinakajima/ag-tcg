"""Derived deck features for analysis and a rough bot-playability score."""

from __future__ import annotations

from collections import Counter
from typing import Any


def compute_deck_features(card_ids: list[int], card_db: Any = None) -> dict:
    """Compute coarse composition features for a decklist.

    Without a card DB, only size/uniqueness are known. With one, we estimate
    Pokémon/Trainer/Energy/Basic counts and a 0..1 bot-playability score.
    """
    counts = Counter(card_ids)
    features: dict = {
        "size": len(card_ids),
        "unique_cards": len(counts),
        "max_copies": max(counts.values()) if counts else 0,
    }

    if card_db is None:
        features["playability_score"] = None
        return features

    pokemon = basic = evolution = trainer = energy = attacker = 0
    for cid, n in counts.items():
        try:
            feats = card_db.basic_features(cid)
        except Exception:
            continue
        roles = feats.get("roles", [])
        if feats.get("is_basic"):
            basic += n
        if feats.get("is_evolution"):
            evolution += n
        if feats.get("is_energy"):
            energy += n
        if feats.get("is_trainer"):
            trainer += n
        if feats.get("is_attacker"):
            attacker += n
        if "Basic Pokémon" in roles or "Evolution" in roles or feats.get("is_attacker"):
            if not feats.get("is_energy") and not feats.get("is_trainer"):
                pokemon += n

    features.update(
        {
            "pokemon_count": pokemon,
            "basic_count": basic,
            "evolution_count": evolution,
            "trainer_count": trainer,
            "energy_count": energy,
            "attacker_count": attacker,
        }
    )
    features["playability_score"] = _playability_score(features)
    return features


def _playability_score(f: dict) -> float:
    """A rough 0..1 heuristic: can a simple bot actually function with this deck?

    Rewards having basics, some energy, some draw/attackers, and penalizes
    extreme imbalance. Purely advisory.
    """
    score = 0.0
    basic = f.get("basic_count", 0)
    energy = f.get("energy_count", 0)
    attacker = f.get("attacker_count", 0)
    size = f.get("size", 60) or 60

    # Need basics to start: peak reward around 8-14 basics.
    if basic > 0:
        score += min(basic, 12) / 12 * 0.35
    # Energy presence: peak around 8-15.
    if energy > 0:
        score += min(energy, 12) / 12 * 0.25
    # Attackers present.
    if attacker > 0:
        score += min(attacker, 12) / 12 * 0.25
    # Size sanity.
    if size == 60:
        score += 0.15

    return round(min(1.0, score), 3)
