"""Robust deck resolution for first-run Kaggle scoring.

A placeholder deck will almost certainly fail Kaggle validation, so this module
resolves a *real* 60-card deck from whatever sources are available, in priority
order:

1. Existing ``deck.csv`` if valid **and not marked/detected as placeholder**.
2. Kaggle sample submission deck (``sample_submission/...``).
3. Provided deck files (``data/decks/*.csv``, ``data/cards/decks/*.csv``,
   root ``*.csv`` with exactly 60 integer rows).
4. A baseline deck generated from an official card CSV
   (``data/cards/EN_Card_Data.csv`` etc.).
5. Otherwise: fail loudly with exact instructions (never invent card IDs).

Placeholder detection is both explicit (a ``deck.meta.json`` marker) and
heuristic (tiny synthetic IDs with no card DB to confirm them).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .deck_io import load_deck, save_deck
from .validator import DECK_SIZE, validate_deck

META_FILENAME = "deck.meta.json"


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------

def load_deck_meta(deck_path: str | Path) -> dict:
    """Load the sidecar ``deck.meta.json`` next to a deck, if present."""
    meta_path = Path(deck_path).parent / META_FILENAME
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_deck_meta(deck_path: str | Path, meta: dict) -> Path:
    """Write the sidecar ``deck.meta.json`` next to a deck."""
    meta_path = Path(deck_path).parent / META_FILENAME
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta_path


def is_placeholder_deck(card_ids: list[int], meta: dict | None = None,
                        card_db: Any = None) -> bool:
    """Decide whether a deck is a non-competitive placeholder.

    Order of evidence:
    * explicit ``meta["placeholder"]`` (trusted either way),
    * trivially synthetic content (all identical, or the known 1..15 x4 seed,
      or all IDs absurdly small) when no card DB confirms the IDs are real.
    """
    if meta:
        if meta.get("placeholder") is True:
            return True
        if meta.get("placeholder") is False:
            return False

    if not card_ids:
        return True

    counts = Counter(card_ids)
    unique = len(counts)

    # All identical -> placeholder.
    if unique <= 1:
        return True

    # The exact structural seed shipped by this repo: ids 1..15, 4 copies each.
    if sorted(card_ids) == sorted([c for c in range(1, 16) for _ in range(4)]):
        return True

    # If a card DB is available and every id resolves, trust it as real.
    if card_db is not None and len(card_db) > 0:
        resolved = sum(1 for cid in counts if card_db.get(cid) is not None)
        if resolved == unique:
            return False

    # No card DB: tiny contiguous IDs (1..N) are almost certainly synthetic.
    max_id = max(counts)
    min_id = min(counts)
    if min_id >= 1 and max_id <= 20 and unique <= 20:
        return True

    return False


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def _looks_like_60_int_csv(path: Path) -> bool:
    try:
        ids = load_deck(path)
    except Exception:
        return False
    return len(ids) == DECK_SIZE


def discover_deck_sources(root: str | Path = ".") -> list[Path]:
    """Return candidate deck files in priority order (excluding the live deck.csv)."""
    root = Path(root)
    candidates: list[Path] = []

    # 2. Kaggle sample submission.
    sample_dir = root / "sample_submission"
    if sample_dir.is_dir():
        preferred = sample_dir / "deck.csv"
        if preferred.exists():
            candidates.append(preferred)
        candidates.extend(sorted(p for p in sample_dir.rglob("*.csv") if p != preferred))

    # 3. Provided deck files.
    for sub in ("data/decks", "data/cards/decks"):
        d = root / sub
        if d.is_dir():
            candidates.extend(
                sorted(p for p in d.glob("*.csv") if p.name != "resolved_deck.csv")
            )

    # Root-level *.csv with exactly 60 integer rows (skip deck.csv itself).
    for p in sorted(root.glob("*.csv")):
        if p.name in ("deck.csv", "deck.csv.example"):
            continue
        if _looks_like_60_int_csv(p):
            candidates.append(p)

    # De-dup while preserving order.
    seen: set[Path] = set()
    out: list[Path] = []
    for c in candidates:
        rp = c.resolve()
        if rp not in seen and c.exists():
            seen.add(rp)
            out.append(c)
    return out


def find_card_csv(root: str | Path = ".") -> Path | None:
    """Find an official card CSV for baseline generation."""
    root = Path(root)
    for rel in ("data/cards/EN_Card_Data.csv", "data/cards/JP_Card_Data.csv",
                "EN_Card_Data.csv", "JP_Card_Data.csv"):
        p = root / rel
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolveResult:
    ok: bool
    source: str = "none"            # existing | sample | provided | generated | none
    source_path: str | None = None
    card_ids: list[int] = field(default_factory=list)
    placeholder: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "source": self.source,
            "source_path": self.source_path,
            "deck_size": len(self.card_ids),
            "unique_cards": len(set(self.card_ids)),
            "placeholder": self.placeholder,
            "errors": self.errors,
            "warnings": self.warnings,
            "notes": self.notes,
        }


def resolve_deck(root: str | Path = ".", deck_path: str | Path = "deck.csv",
                 card_db: Any = None) -> ResolveResult:
    """Resolve the best available real deck. Does not write files."""
    root = Path(root)
    deck_path = Path(deck_path)

    # 1. Existing deck.csv if valid and not placeholder.
    if deck_path.exists():
        ids = load_deck(deck_path)
        meta = load_deck_meta(deck_path)
        result = validate_deck(ids, card_db=card_db)
        placeholder = is_placeholder_deck(ids, meta=meta, card_db=card_db)
        if result.valid and not placeholder:
            return ResolveResult(
                ok=True, source="existing", source_path=str(deck_path),
                card_ids=ids, placeholder=False,
                notes=["existing deck.csv is valid and not a placeholder"],
                warnings=result.warnings,
            )

    # 2/3. Sample or provided deck files.
    for cand in discover_deck_sources(root):
        ids = load_deck(cand)
        result = validate_deck(ids, card_db=card_db)
        if result.valid and not is_placeholder_deck(ids, card_db=card_db):
            src = "sample" if "sample_submission" in str(cand) else "provided"
            return ResolveResult(
                ok=True, source=src, source_path=str(cand), card_ids=ids,
                placeholder=False, warnings=result.warnings,
                notes=[f"adopted deck from {cand}"],
            )

    # 4. Generate from official card CSV.
    csv_path = find_card_csv(root)
    if csv_path is not None:
        from ..cards.csv_loader import load_cards_from_csv
        from .baseline_decks import generate_baseline_deck_from_records

        records = load_cards_from_csv(csv_path)
        gen = generate_baseline_deck_from_records(records)
        if gen.get("ok") and len(gen.get("card_ids", [])) == DECK_SIZE:
            return ResolveResult(
                ok=True, source="generated", source_path=str(csv_path),
                card_ids=gen["card_ids"], placeholder=False,
                notes=gen.get("notes", []), warnings=gen.get("warnings", []),
            )
        # Generation failed -> report why.
        return ResolveResult(
            ok=False, source="generated", source_path=str(csv_path),
            errors=gen.get("errors", ["could not generate a 60-card deck from CSV"]),
            notes=gen.get("notes", []),
        )

    # 5. Nothing usable.
    existing_ok = False
    if deck_path.exists():
        ids = load_deck(deck_path)
        existing_ok = validate_deck(ids, card_db=card_db).valid
    msg = [
        "No real deck source found. To resolve, do one of:",
        "  * place the Kaggle sample deck at sample_submission/deck.csv",
        "  * place a 60-line integer deck at data/decks/<name>.csv",
        "  * place the official card CSV at data/cards/EN_Card_Data.csv (or JP_)",
        "    so a baseline deck can be generated.",
    ]
    return ResolveResult(
        ok=False, source="none", errors=msg,
        placeholder=True,
        notes=["existing deck.csv is structurally valid but is a placeholder"]
        if existing_ok else [],
    )


def write_resolved(result: ResolveResult, root: str | Path = ".",
                   deck_path: str | Path = "deck.csv") -> dict:
    """Persist a successful resolution to deck.csv + data/decks/ + summary."""
    root = Path(root)
    deck_path = Path(deck_path)
    if not result.ok:
        raise ValueError("cannot write an unsuccessful resolution")

    save_deck(deck_path, result.card_ids)
    resolved_path = root / "data" / "decks" / "resolved_deck.csv"
    save_deck(resolved_path, result.card_ids)

    summary = result.to_dict()
    summary_path = root / "data" / "decks" / "resolved_deck_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    write_deck_meta(deck_path, {
        "placeholder": False,
        "source": result.source,
        "source_path": result.source_path,
        "deck_size": len(result.card_ids),
    })

    return {
        "deck_csv": str(deck_path),
        "resolved_deck": str(resolved_path),
        "summary": str(summary_path),
    }
