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


# --------------------------------------------------------------------------
# Pass 11B: replay-deck archetype classification
#
# Signature card ids below were each OBSERVED in a real, extracted replay deck;
# their names were confirmed against the local official card metadata
# (data/cards/EN_Card_Data.csv). No id is invented: the classifier only keys off
# ids that actually appear in the deck handed to it. Names are a curated
# signature subset (the same pattern as CONFIRMED_CARDS), not a copy of the
# official CSV.
# --------------------------------------------------------------------------

SIGNATURE_CARDS: dict[int, str] = {
    721: "Kyogre",
    722: "Snover",
    723: "Mega Abomasnow ex",
    8: "Basic {M} Energy",
    336: "Zacian ex",
    547: "Genesect ex",
    988: "Registeel ex",
    695: "Mega Mawile ex",
    1205: "Cyrano",
    1235: "Waitress",
    121: "Dragapult ex",
    678: "Mega Lucario ex",
    756: "Mega Kangaskhan ex",
    269: "Iono's Bellibolt ex",
}

# Archetype-defining id sets (all confirmed from replays + official metadata).
_WATER_CORE = {721, 723}            # Kyogre + Mega Abomasnow ex
_WATER_SNOVER = 722                  # Snover (evolution line into Abomasnow)
_MAXBELT_SUPPORT = {1205, 1235}     # Cyrano / Waitress support package
_METAL_CORE = {336, 8}              # Zacian ex + Basic Metal Energy
_EX_TEMPO_MARKERS = {121, 678, 756, 269, 547, 988, 695}  # confirmed ex attackers


def classify_deck(
    ids: list[int],
    *,
    is_own_deck: bool = False,
    card_names: dict[int, str] | None = None,
) -> dict:
    """Classify a replay-extracted 60-card deck into a meta archetype.

    Returns ``{archetype_id, confidence, evidence_card_ids, evidence_card_names,
    notes}``. Card ids come ONLY from the deck handed in (extracted from a real
    replay); names are resolved from ``card_names`` (the local official metadata)
    falling back to the curated ``SIGNATURE_CARDS`` map. No id is ever invented.

    ``confidence`` is one of ``confirmed`` / ``provisional`` / ``unknown``.
    """
    clean = [int(i) for i in ids if not isinstance(i, bool)]
    present = set(clean)
    notes: list[str] = []

    def _name(cid: int) -> str:
        if card_names and cid in card_names:
            return card_names[cid]
        return SIGNATURE_CARDS.get(cid, f"card {cid}")

    def _result(arch_id: str, confidence: str, evidence: list[int]) -> dict:
        ev = sorted(set(evidence))
        return {
            "archetype_id": arch_id,
            "confidence": confidence,
            "evidence_card_ids": ev,
            "evidence_card_names": [_name(c) for c in ev],
            "notes": notes,
        }

    if not clean:
        notes.append("empty deck; cannot classify")
        return _result("unknown", "unknown", [])

    # Water Kyogre / Mega Abomasnow family (our own line + external water decks).
    if _WATER_CORE <= present and _WATER_SNOVER in present:
        ev = [c for c in (721, 722, 723) if c in present]
        if is_own_deck:
            return _result("water_kyogre_abomasnow_passive_mirror", "confirmed", ev)
        if _MAXBELT_SUPPORT & present:
            ev += sorted(_MAXBELT_SUPPORT & present)
            return _result("water_kyogre_abomasnow_maxbelt", "confirmed", ev)
        return _result("water_kyogre_abomasnow", "confirmed", ev)

    # Metal ex / Zacian ramp.
    if _METAL_CORE <= present:
        ev = [c for c in (336, 8, 547, 988, 695) if c in present]
        return _result("metal_ex_zacian_ramp", "confirmed", ev)

    # A confirmed ex attacker is present but the precise external list is not in
    # our named set -> honest provisional bucket (no fabricated detail).
    markers = _EX_TEMPO_MARKERS & present
    if markers:
        notes.append(
            "contains a confirmed ex attacker but does not match a named "
            "archetype signature; bucketed as generic ex tempo"
        )
        return _result("unknown_ex_tempo", "provisional", sorted(markers))

    notes.append("no confirmed archetype signature matched")
    return _result("unknown", "unknown", [])


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
