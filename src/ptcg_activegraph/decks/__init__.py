"""Deck IO, validation, features, and baseline decks.

See ``docs/CARD_AND_DECK_GRAPH.md`` and ``docs/KAGGLE_SUBMISSION.md``.
"""

from .deck_io import load_deck, save_deck, parse_deck_text
from .validator import validate_deck, DeckValidationResult
from .deck_features import compute_deck_features
from .baseline_decks import make_placeholder_deck, BASELINE_DECK_IDS

__all__ = [
    "load_deck",
    "save_deck",
    "parse_deck_text",
    "validate_deck",
    "DeckValidationResult",
    "compute_deck_features",
    "make_placeholder_deck",
    "BASELINE_DECK_IDS",
]
