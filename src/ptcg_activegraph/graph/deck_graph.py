"""DeckGraph: a deck as a multiset of cards with derived role composition.

Layered on the CardGraph/CardDB so the lab can reason about a decklist's role
balance (attackers, draw, search, energy, ...) for deck optimization.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeckGraph:
    deck_version: str = "deck_v0"
    counts: Counter = field(default_factory=Counter)  # card_id -> copies
    role_totals: Counter = field(default_factory=Counter)

    @classmethod
    def from_card_ids(cls, card_ids: list, card_db: Any = None,
                      deck_version: str = "deck_v0") -> "DeckGraph":
        g = cls(deck_version=deck_version)
        for cid in card_ids:
            g.counts[str(cid)] += 1
        if card_db is not None:
            for cid, copies in g.counts.items():
                try:
                    feats = card_db.basic_features(cid)
                except Exception:
                    feats = {}
                for role in feats.get("roles", []) or []:
                    g.role_totals[role] += copies
        return g

    @property
    def size(self) -> int:
        return sum(self.counts.values())

    @property
    def unique_cards(self) -> int:
        return len(self.counts)

    def summary(self) -> dict:
        return {
            "deck_version": self.deck_version,
            "size": self.size,
            "unique_cards": self.unique_cards,
            "role_totals": dict(self.role_totals),
            "top_cards": self.counts.most_common(10),
        }
