"""Read/write ``deck.csv`` style decklists.

The Kaggle ``deck.csv`` is a list of 60 integer card IDs. We accept a few
tolerant formats (one id per line, comma-separated, or a CSV with an ``id``
column) and always write a clean canonical form: one integer id per line.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path


def parse_deck_text(text: str) -> list[int]:
    """Parse decklist text into a list of integer card IDs.

    Accepts newline- and/or comma-separated integers, an optional header line,
    and ignores blanks/comments (``#``). Non-integer tokens are skipped.
    """
    ids: list[int] = []
    if not text:
        return ids
    # Normalize commas to newlines, then scan tokens.
    for raw_line in text.replace(",", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Skip a header token like "id" or "card_id".
        if line.lower() in ("id", "card_id", "cardid", "deck"):
            continue
        try:
            ids.append(int(line))
        except ValueError:
            # Maybe "id" column header within a multi-col CSV row; skip.
            continue
    return ids


def load_deck(path: str | Path) -> list[int]:
    """Load a decklist of integer card IDs from a file."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    # Try structured CSV first (an ``id``/``card_id`` column).
    structured = _try_structured_csv(text)
    if structured:
        return structured
    return parse_deck_text(text)


def _try_structured_csv(text: str) -> list[int]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []
        lowered = {fn.lower(): fn for fn in reader.fieldnames if fn}
        key = None
        for cand in ("card_id", "id", "cardid", "number"):
            if cand in lowered:
                key = lowered[cand]
                break
        if key is None:
            return []
        ids: list[int] = []
        for row in reader:
            val = row.get(key)
            if val is None:
                continue
            try:
                ids.append(int(str(val).strip()))
            except ValueError:
                continue
        return ids
    except Exception:
        return []


def save_deck(path: str | Path, card_ids: list[int]) -> Path:
    """Write a decklist as one integer id per line."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(int(c)) for c in card_ids]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
