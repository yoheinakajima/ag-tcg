"""Deck validation for Kaggle submission.

Rules enforced (hard):

* exactly 60 cards
* every entry is an integer card id

Soft checks (warnings, require card metadata): max copies, presence of at least
one Basic Pokémon, energy/Pokémon/Trainer balance.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DECK_SIZE = 60
DEFAULT_MAX_COPIES = 4  # standard TCG rule; basic Energy is typically exempt


@dataclass
class DeckValidationResult:
    valid: bool
    size: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "size": self.size,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "features": self.features,
        }


def validate_deck(
    card_ids: Any,
    card_db: Any = None,
    deck_size: int = DECK_SIZE,
    max_copies: int = DEFAULT_MAX_COPIES,
) -> DeckValidationResult:
    """Validate a decklist. ``card_db`` enables richer (soft) checks."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(card_ids, (list, tuple)):
        return DeckValidationResult(
            valid=False, size=0, errors=["deck is not a list of card ids"]
        )

    # Hard: every entry must be an integer.
    int_ids: list[int] = []
    for i, c in enumerate(card_ids):
        if isinstance(c, bool):
            errors.append(f"entry {i} is a bool, not an int")
            continue
        try:
            int_ids.append(int(c))
        except (TypeError, ValueError):
            errors.append(f"entry {i} ({c!r}) is not an integer card id")

    size = len(card_ids)

    # Hard: exactly 60 cards.
    if size != deck_size:
        errors.append(f"deck has {size} cards; must be exactly {deck_size}")

    counts = dict(Counter(int_ids))

    # Soft: max copies (Energy may be exempt if we can detect it).
    for cid, n in counts.items():
        if n > max_copies:
            is_energy = False
            if card_db is not None:
                try:
                    is_energy = card_db.basic_features(cid).get("is_energy", False)
                except Exception:
                    is_energy = False
            if not is_energy:
                warnings.append(f"card {cid} appears {n} times (> {max_copies})")

    features: dict = {}
    if card_db is not None:
        from .deck_features import compute_deck_features

        features = compute_deck_features(int_ids, card_db)
        if features.get("basic_count", 0) == 0:
            warnings.append("no Basic Pokémon detected; deck may be unable to start")

    valid = len(errors) == 0
    return DeckValidationResult(
        valid=valid,
        size=size,
        errors=errors,
        warnings=warnings,
        counts=counts,
        features=features,
    )
