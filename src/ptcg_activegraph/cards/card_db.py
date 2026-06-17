"""CardDB: unified card lookup over CSV / cabt / empty sources.

The DB is a thin index over a list of card records (dicts). It normalizes ids,
indexes by id and name, and computes role tags + basic features lazily.
"""

from __future__ import annotations

from typing import Any

from .csv_loader import find_card_csv, load_cards_from_csv
from .role_tags import tag_roles


class CardDB:
    """In-memory card database."""

    def __init__(self, records: list[dict] | None = None, source: str = "empty") -> None:
        self.source = source
        self._by_id: dict[str, dict] = {}
        self._by_name: dict[str, list[dict]] = {}
        self._records: list[dict] = []
        for rec in records or []:
            self._add(rec)

    def _add(self, record: dict) -> None:
        if not isinstance(record, dict):
            return
        cid = str(record.get("card_id") or record.get("id") or "").strip()
        if not cid:
            # Synthesize a stable id so the record is still queryable.
            cid = f"_auto_{len(self._records)}"
            record = {**record, "card_id": cid}
        if "roles" not in record:
            record["roles"] = tag_roles(record)
        self._records.append(record)
        self._by_id[cid] = record
        name = str(record.get("name") or "").strip().lower()
        if name:
            self._by_name.setdefault(name, []).append(record)

    # -- queries -----------------------------------------------------------
    def get(self, card_id: Any) -> dict | None:
        return self._by_id.get(str(card_id).strip())

    def all(self) -> list[dict]:
        return list(self._records)

    def search_name(self, name: str) -> list[dict]:
        if not name:
            return []
        q = str(name).strip().lower()
        exact = self._by_name.get(q, [])
        if exact:
            return list(exact)
        # Substring fallback.
        return [r for r in self._records if q in str(r.get("name", "")).lower()]

    def basic_features(self, card_id: Any) -> dict:
        """Return roles plus coarse type flags for a card."""
        rec = self.get(card_id)
        if rec is None:
            return {"card_id": str(card_id), "found": False, "roles": ["Unknown"]}
        roles = rec.get("roles") or tag_roles(rec)
        return {
            "card_id": str(rec.get("card_id")),
            "name": rec.get("name", ""),
            "found": True,
            "roles": roles,
            "is_basic": "Basic Pokémon" in roles,
            "is_evolution": "Evolution" in roles,
            "is_energy": "Energy" in roles,
            "is_trainer": "Trainer" in roles,
            "is_attacker": "Attacker" in roles,
        }

    def __len__(self) -> int:
        return len(self._records)


def load_card_db(prefer_cabt: bool = False, extra_csv_paths: list[str] | None = None) -> CardDB:
    """Load a CardDB from the best available source.

    Order: CSV (default) -> cabt (if ``prefer_cabt`` or no CSV) -> empty.
    """
    # 1. Local CSV.
    csv_path = find_card_csv(extra_csv_paths)
    if csv_path is not None and not prefer_cabt:
        records = load_cards_from_csv(csv_path)
        if records:
            return CardDB(records, source=f"csv:{csv_path}")

    # 2. cabt API.
    cabt_db = _try_load_from_cabt()
    if cabt_db is not None:
        return cabt_db

    # 3. CSV again if cabt was preferred but unavailable.
    if csv_path is not None:
        records = load_cards_from_csv(csv_path)
        if records:
            return CardDB(records, source=f"csv:{csv_path}")

    # 4. Empty placeholder.
    return CardDB([], source="empty")


def _try_load_from_cabt() -> CardDB | None:
    try:
        import cabt  # type: ignore
    except Exception:
        return None
    try:
        cards = cabt.all_card_data()  # type: ignore[attr-defined]
    except Exception:
        return None
    records: list[dict] = []
    try:
        for c in cards:
            if isinstance(c, dict):
                records.append(c)
            else:
                # Best-effort: convert objects with __dict__.
                records.append(dict(getattr(c, "__dict__", {})) or {"value": str(c)})
    except Exception:
        return None
    if not records:
        return None
    return CardDB(records, source="cabt")
