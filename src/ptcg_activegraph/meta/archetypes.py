"""Opponent archetype labels derived from real Kaggle replays.

Hard rules (mirrors the meta-replay pipeline):
* Never invent card ids. Confirmed ids come from the playbook schema
  (``CONFIRMED_CARDS``), which is grounded in the official card data.
* An archetype that has no real replay (and therefore no extracted, confirmed
  deck) is ``provisional``/``blocked`` — it carries ``card_ids: unknown`` and
  contributes no fabricated detail to evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:  # schema lives in the playbooks package
    from ..playbooks.schema import CONFIRMED_CARDS
except Exception:  # pragma: no cover - defensive import
    CONFIRMED_CARDS = {}


class ArchetypeStatus(str, Enum):
    """How well-grounded an archetype label is."""

    CONFIRMED = "confirmed_from_replay"   # real replay + extracted deck
    PROVISIONAL = "provisional"           # named from summaries only
    BLOCKED = "blocked_missing_replay"    # needs a replay we do not have


@dataclass
class Archetype:
    key: str
    label: str
    status: ArchetypeStatus
    description: str
    # Confirmed numeric card ids if the deck was extracted from a real replay;
    # otherwise an empty list and ``card_ids_status="unknown"``.
    card_ids: list[int] = field(default_factory=list)
    card_ids_status: str = "unknown"
    replay_episode: Any = None
    deck_path: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "description": self.description,
            "card_ids": list(self.card_ids),
            "card_ids_status": self.card_ids_status,
            "replay_episode": self.replay_episode,
            "deck_path": self.deck_path,
            "notes": list(self.notes),
        }

    @property
    def available(self) -> bool:
        """An archetype is usable as a *real* eval surrogate only when it has a
        confirmed, replay-extracted deck."""
        return self.status == ArchetypeStatus.CONFIRMED and bool(self.card_ids)


# The provisional/blocked external labels come from match *summaries* only; the
# CONFIRMED mirror is filled in at runtime from the real self-mirror replay.
ARCHETYPES: dict[str, Archetype] = {
    "water_kyogre_abomasnow_mirror_passive": Archetype(
        key="water_kyogre_abomasnow_mirror_passive",
        label="Water Kyogre/Abomasnow mirror (passive)",
        status=ArchetypeStatus.PROVISIONAL,  # upgraded to CONFIRMED when the replay deck loads
        description=(
            "The v2 deck_energy_trim_light line itself: slow mirror, weak Snover "
            "attack loop, low evolution/bench pressure. Tends to grind and risk "
            "self-deckout."
        ),
        notes=[
            "Derived from real self-mirror replay 80374966 (both seats = v2 deck).",
        ],
    ),
    "metal_ex_zacian_ramp": Archetype(
        key="metal_ex_zacian_ramp",
        label="Metal ex Zacian ramp",
        status=ArchetypeStatus.BLOCKED,
        description=(
            "Zacian ex active + Metal Energy ramp; punishes slow setup. Possible "
            "support: Genesect ex / Mega Mawile ex / Registeel ex / Togedemaru ex "
            "/ Magearna (all UNCONFIRMED without a replay)."
        ),
        notes=[
            "No replay present (expected episode 80503804). Card ids unknown; "
            "never invented. Blocked until raw replay is added.",
        ],
    ),
    "water_kyogre_abomasnow_maxbelt": Archetype(
        key="water_kyogre_abomasnow_maxbelt",
        label="Water Kyogre/Abomasnow + Maximum Belt",
        status=ArchetypeStatus.BLOCKED,
        description=(
            "Similar water core with a stronger support package (Maximum Belt, "
            "Cyrano, Waitress UNCONFIRMED) and better long-game tempo."
        ),
        notes=[
            "No replay present (expected tymu water/maxbelt). Maximum Belt / "
            "Cyrano / Waitress ids are NOT in the confirmed set; blocked.",
        ],
    ),
}


def attach_mirror_deck(card_ids: list[int], episode: Any, deck_path: str) -> None:
    """Upgrade the mirror archetype to CONFIRMED using the real replay deck.

    Only ids that are in the confirmed card set are accepted; anything else
    keeps the archetype provisional (we never confirm an unknown id).
    """
    arch = ARCHETYPES["water_kyogre_abomasnow_mirror_passive"]
    confirmed = set(CONFIRMED_CARDS.values())
    if card_ids and all(cid in confirmed for cid in set(card_ids)):
        arch.card_ids = list(card_ids)
        arch.card_ids_status = "confirmed"
        arch.status = ArchetypeStatus.CONFIRMED
        arch.replay_episode = episode
        arch.deck_path = deck_path
    else:
        arch.notes.append("deck ids not fully in confirmed set; kept provisional")


def archetype_table() -> list[dict]:
    return [a.to_dict() for a in ARCHETYPES.values()]


def build_archetypes_yaml_obj() -> dict:
    """The serializable object written to ``archetypes.yaml``."""
    return {
        "schema": "activegraph.meta.archetypes/v1",
        "hard_rules": [
            "never invent card ids",
            "blocked archetypes contribute no fabricated data",
        ],
        "archetypes": archetype_table(),
        "available_for_eval": [a.key for a in ARCHETYPES.values() if a.available],
        "blocked_for_eval": [
            a.key for a in ARCHETYPES.values() if not a.available
        ],
    }
