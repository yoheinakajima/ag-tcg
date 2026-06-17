"""CSV ingestion for card metadata.

Reads whatever columns are present and returns a list of dict records with a
normalized ``card_id`` and ``name`` when those can be inferred. Tolerant of
unknown schemas; uses only the standard-library ``csv`` module.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

# Candidate locations for the official card CSVs, in priority order.
CANDIDATE_CSV_PATHS = [
    "data/cards/EN_Card_Data.csv",
    "data/cards/JP_Card_Data.csv",
    "EN_Card_Data.csv",
    "JP_Card_Data.csv",
]

_ID_KEYS = ("card_id", "Card ID", "CardID", "id", "ID", "card_no", "Card No", "number", "Number")
_NAME_KEYS = ("name", "Name", "card_name", "Card Name", "CardName")


def find_card_csv(extra_paths: list[str] | None = None) -> Path | None:
    """Return the first existing candidate card CSV, or ``None``."""
    for p in (extra_paths or []) + CANDIDATE_CSV_PATHS:
        path = Path(p)
        if path.exists() and path.is_file():
            return path
    return None


def _first(record: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


def load_cards_from_csv(path: str | Path) -> list[dict]:
    """Load card records from a CSV file.

    Returns a list of dicts. Each gets a ``card_id`` and ``name`` key derived
    from common column names when possible, plus all original columns.
    """
    path = Path(path)
    if not path.exists():
        return []

    out: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = dict(row)
            cid = _first(record, _ID_KEYS)
            name = _first(record, _NAME_KEYS)
            if cid is not None and "card_id" not in record:
                record["card_id"] = str(cid).strip()
            if name is not None and "name" not in record:
                record["name"] = str(name).strip()
            out.append(record)
    return out
