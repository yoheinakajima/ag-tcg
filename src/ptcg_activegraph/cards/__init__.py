"""Card ingestion, role tagging, and lookup.

Sources, in priority order:

1. Local CSV (``data/cards/EN_Card_Data.csv`` etc.).
2. cabt API (``all_card_data()`` / ``all_attack()``) when importable.
3. Empty placeholder DB.

See ``docs/CARD_AND_DECK_GRAPH.md``.
"""

from .card_db import CardDB, load_card_db
from .csv_loader import load_cards_from_csv, find_card_csv
from .role_tags import tag_roles, ROLE_TAGS

__all__ = [
    "CardDB",
    "load_card_db",
    "load_cards_from_csv",
    "find_card_csv",
    "tag_roles",
    "ROLE_TAGS",
]
