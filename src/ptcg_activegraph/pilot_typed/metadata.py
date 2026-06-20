"""Per-card metadata lookups.

Operates on an inlined metadata table (built at COMPILE time from the local
EN_Card_Data.csv for ONLY our portfolio/candidate card ids; the CSV is never
shipped or committed). All helpers tolerate a missing/partial table and return
conservative defaults so runtime never depends on metadata being complete.

Metadata entry shape (all keys optional except implied by presence):
    meta[card_id] = {
        "name": str, "card_type": "pokemon"|"energy"|"trainer"|...,
        "subtype": str, "stage": "basic"|"stage1"|"stage2"|None,
        "is_basic_pokemon": bool, "is_basic_energy": bool,
        "energy_type": str|None, "hp": int|None,
        "ex": bool, "retreat_cost": int|None,
    }
Keys are ints (card ids). When loaded from JSON they may arrive as strings, so
lookups coerce both.
"""
from __future__ import annotations

from typing import Any


def _coerce_table(meta: Any) -> dict:
    return meta if isinstance(meta, dict) else {}


def card_meta(meta: Any, cid: Any) -> dict:
    table = _coerce_table(meta)
    if cid is None:
        return {}
    entry = table.get(cid)
    if entry is None:
        entry = table.get(str(cid))
    return entry if isinstance(entry, dict) else {}


def name(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("name")


def card_type(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("card_type")


def is_pokemon(meta: Any, cid: Any) -> bool:
    return card_type(meta, cid) == "pokemon"


def is_trainer(meta: Any, cid: Any) -> bool:
    return card_type(meta, cid) == "trainer"


def is_energy(meta: Any, cid: Any) -> bool:
    m = card_meta(meta, cid)
    return m.get("card_type") == "energy" or bool(m.get("is_basic_energy"))


def is_basic_energy(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid).get("is_basic_energy"))


def stage(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("stage")


def is_basic_pokemon(meta: Any, cid: Any) -> bool:
    """True only when metadata positively says this is a Basic Pokemon.

    Conservative: returns False when metadata is missing so callers must have a
    separate observation-derived signal (e.g. a setup option the engine offered)
    before treating a card as a benchable Basic.
    """
    m = card_meta(meta, cid)
    if m.get("is_basic_pokemon") is True:
        return True
    if m.get("card_type") == "pokemon" and m.get("stage") == "basic":
        return True
    return False


def energy_type(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("energy_type")


def hp(meta: Any, cid: Any) -> Any:
    v = card_meta(meta, cid).get("hp")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def is_ex(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid).get("ex"))


def retreat_cost(meta: Any, cid: Any) -> Any:
    v = card_meta(meta, cid).get("retreat_cost")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def has_meta(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid))
