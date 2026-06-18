"""Honest playbook validation.

Checks (all recorded, hard failures collected in ``errors``):
  * every required top-level field exists,
  * every card id is a plain ``int`` (never bool, never str),
  * no invented ids: each referenced id is in the confirmed set and, when
    available, present in the card metadata CSV,
  * referenced role ids exist in the deck when a deck id list is supplied,
  * the rule sections are serializable and compile to a rule dict,
  * a report summary can be produced.

Never raises for ordinary content problems; it returns a ``ValidationResult``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .schema import (
    CARD_ID_LIST_FIELDS,
    CONFIRMED_CARDS,
    REQUIRED_FIELDS,
    ROLE_SECTIONS,
    RULE_MAP,
)

DEFAULT_CARD_CSV = "data/cards/EN_Card_Data.csv"
CONFIRMED_IDS = set(CONFIRMED_CARDS.values())


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": list(self.errors),
                "warnings": list(self.warnings)}


def load_metadata_ids(card_csv: str | Path = DEFAULT_CARD_CSV) -> set[int] | None:
    """Return the set of card ids in the metadata CSV, or ``None`` if absent.

    The CSV is private (gitignored) and only used read-only for validation.
    """
    p = Path(card_csv)
    if not p.exists():
        return None
    ids: set[int] = set()
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # header
            for row in reader:
                if not row:
                    continue
                try:
                    ids.add(int(row[0]))
                except (TypeError, ValueError):
                    continue
    except OSError:
        return None
    return ids or None


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _iter_card_ids(playbook: dict):
    """Yield (where, value) for every place a card id is declared."""
    cards = playbook.get("cards")
    if isinstance(cards, dict):
        for k, v in cards.items():
            yield f"cards.{k}", v
    roles = playbook.get("roles")
    if isinstance(roles, dict):
        for sec in ROLE_SECTIONS:
            vals = roles.get(sec)
            if isinstance(vals, list):
                for v in vals:
                    yield f"roles.{sec}", v
    for section, key in CARD_ID_LIST_FIELDS:
        sec = playbook.get(section)
        if isinstance(sec, dict):
            vals = sec.get(key)
            if isinstance(vals, list):
                for v in vals:
                    yield f"{section}.{key}", v


def validate_playbook(playbook: dict,
                      deck_ids: list[int] | None = None,
                      card_csv: str | Path = DEFAULT_CARD_CSV) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(playbook, dict):
        return ValidationResult(False, ["playbook is not a mapping"], [])

    # 1. required fields
    for f in REQUIRED_FIELDS:
        if f not in playbook:
            errors.append(f"missing required field: {f}")

    # 2/3. card ids are ints; no invented ids
    meta_ids = load_metadata_ids(card_csv)
    if meta_ids is None:
        warnings.append(
            f"card metadata {card_csv} not available; id existence checked "
            "against the confirmed set only")
    known = set(CONFIRMED_IDS)
    if meta_ids:
        known |= meta_ids
    deck_set = set(deck_ids) if deck_ids else None

    seen_ids: set[int] = set()
    for where, v in _iter_card_ids(playbook):
        if not _is_int(v):
            errors.append(f"{where}: card id {v!r} is not an integer")
            continue
        seen_ids.add(v)
        if v not in known:
            errors.append(f"{where}: invented/unknown card id {v} "
                          "(not in confirmed set or metadata)")
        if deck_set is not None and v not in deck_set:
            errors.append(f"{where}: card id {v} not present in the deck")

    # 4. rules serializable + compilable
    for rule, (section, key) in RULE_MAP.items():
        sec = playbook.get(section)
        if sec is None:
            continue
        if not isinstance(sec, dict):
            errors.append(f"{section}: must be a mapping to derive {rule}")
            continue
        val = sec.get(key)
        if val is None:
            continue
        if rule == "deckout_decline_threshold":
            if not _is_int(val):
                errors.append(f"{section}.{key}: must be an integer "
                              f"(got {val!r})")
        elif not isinstance(val, bool):
            errors.append(f"{section}.{key}: must be a boolean (got {val!r})")

    # 5. report summary producible (best-effort; never raises)
    try:
        from .report import playbook_report_summary
        summary = playbook_report_summary(playbook)
        if not isinstance(summary, dict) or not summary.get("deck_id"):
            warnings.append("report summary missing deck_id")
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"report summary failed: {type(exc).__name__}: {exc}")

    if not seen_ids:
        warnings.append("no card ids declared in cards/roles")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
