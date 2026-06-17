"""Belief-state scaffolding for hidden-information reasoning.

This module does *not* drive the Kaggle runtime decision yet. It provides the
data structures and a best-effort extractor so the lab can begin modelling what
each player knows vs. what is hidden, and so the search policy can eventually
sample plausible hidden states to feed ``cabt.search_begin``.

Everything degrades to "unknown" when the board schema is unrecognized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BeliefState:
    """What we believe about the full game state from one player's view."""

    own_hand: list = field(default_factory=list)
    own_discard: list = field(default_factory=list)
    own_board: list = field(default_factory=list)
    own_deck_count: int = 0
    own_prize_count: int = 0

    opp_active: Any = None
    opp_bench: list = field(default_factory=list)
    opp_discard: list = field(default_factory=list)
    opp_hand_count: int = 0
    opp_deck_count: int = 0
    opp_prize_count: int = 0

    unknown_cards: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "own_hand": self.own_hand,
            "own_discard": self.own_discard,
            "own_board": self.own_board,
            "own_deck_count": self.own_deck_count,
            "own_prize_count": self.own_prize_count,
            "opp_active": self.opp_active,
            "opp_bench": self.opp_bench,
            "opp_discard": self.opp_discard,
            "opp_hand_count": self.opp_hand_count,
            "opp_deck_count": self.opp_deck_count,
            "opp_prize_count": self.opp_prize_count,
            "unknown_cards": self.unknown_cards,
            "notes": self.notes,
        }


def _first_present(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def extract_belief(current: Any) -> BeliefState:
    """Best-effort extraction of a :class:`BeliefState` from board state.

    The cabt board schema is not finalized here, so this looks for a handful of
    commonly-named keys and records what it could not find under ``notes``. It
    never raises.
    """
    belief = BeliefState()
    if not isinstance(current, dict):
        belief.notes.append("current is not a dict; belief is empty")
        return belief

    own = _first_present(current, "self", "me", "player", "own", "p0")
    opp = _first_present(current, "opponent", "opp", "enemy", "p1")

    if isinstance(own, dict):
        belief.own_hand = _as_list(_first_present(own, "hand"))
        belief.own_discard = _as_list(_first_present(own, "discard", "discardPile"))
        belief.own_board = _as_list(_first_present(own, "bench", "board", "field"))
        belief.own_deck_count = _as_count(_first_present(own, "deck", "deckCount"))
        belief.own_prize_count = _as_count(_first_present(own, "prize", "prizes", "prizeCount"))
    else:
        belief.notes.append("own board not found")

    if isinstance(opp, dict):
        belief.opp_active = _first_present(opp, "active")
        belief.opp_bench = _as_list(_first_present(opp, "bench", "board", "field"))
        belief.opp_discard = _as_list(_first_present(opp, "discard", "discardPile"))
        belief.opp_hand_count = _as_count(_first_present(opp, "hand", "handCount"))
        belief.opp_deck_count = _as_count(_first_present(opp, "deck", "deckCount"))
        belief.opp_prize_count = _as_count(_first_present(opp, "prize", "prizes", "prizeCount"))
    else:
        belief.notes.append("opponent board not found")

    return belief


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_count(value: Any) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class WorldSampler:
    """Placeholder sampler for plausible hidden states.

    The real implementation will draw the opponent's hand/deck/prizes (and our
    own hidden prizes/deck) consistent with the public log and known decklists,
    producing concrete worlds for ``cabt.search_begin`` to evaluate. For now it
    returns a single "all unknown" world so downstream code has a stable shape
    to consume.
    """

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def sample(self, belief: BeliefState, n: int = 1) -> list[dict]:
        n = max(1, int(n))
        return [
            {
                "world_id": i,
                "predicted_opp_hand": [],  # unknown
                "predicted_opp_deck": [],  # unknown
                "predicted_own_prizes": [],  # unknown
                "confidence": 0.0,
                "belief": belief.to_dict(),
            }
            for i in range(n)
        ]
