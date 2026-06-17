"""CardGraph: nodes are cards, edges are evolution / synergy relations.

This is a thin relational view layered on top of the :class:`CardDB`. It is used
by the lab for deck construction and analysis, never by the Kaggle runtime.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CardNode:
    card_id: str
    name: str = ""
    attributes: dict = field(default_factory=dict)
    roles: list[str] = field(default_factory=list)


class CardGraph:
    """Cards plus best-effort evolution edges."""

    def __init__(self) -> None:
        self.nodes: dict[str, CardNode] = {}
        # evolves_from[child] = parent_name; evolves_to[parent] = [children]
        self.evolves_to: dict[str, list[str]] = defaultdict(list)

    def add_card(self, card_id: str, name: str = "", attributes: dict | None = None,
                 roles: list[str] | None = None) -> CardNode:
        node = CardNode(
            card_id=str(card_id),
            name=name or "",
            attributes=attributes or {},
            roles=roles or [],
        )
        self.nodes[node.card_id] = node
        return node

    def add_evolution(self, parent_name: str, child_id: str) -> None:
        if parent_name:
            self.evolves_to[parent_name.lower()].append(str(child_id))

    @classmethod
    def from_card_db(cls, card_db: Any) -> "CardGraph":
        """Build a graph from a :class:`CardDB`-like object."""
        g = cls()
        try:
            cards = card_db.all()
        except Exception:
            cards = []
        for card in cards:
            cid = str(card.get("card_id") or card.get("id") or card.get("Card ID") or "")
            if not cid:
                continue
            name = str(card.get("name") or card.get("Name") or "")
            roles = card.get("roles") or []
            g.add_card(cid, name, attributes=card, roles=roles)
            # Heuristic evolution edge from an "evolves from" style field.
            evo_from = (
                card.get("evolves_from")
                or card.get("Evolves From")
                or card.get("EvolvesFrom")
            )
            if evo_from:
                g.add_evolution(str(evo_from), cid)
        return g

    def neighbors(self, card_id: str) -> list[str]:
        node = self.nodes.get(str(card_id))
        if not node:
            return []
        return list(self.evolves_to.get(node.name.lower(), []))

    def __len__(self) -> int:
        return len(self.nodes)
