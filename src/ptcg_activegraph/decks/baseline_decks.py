"""Baseline / placeholder decks.

IMPORTANT: We do **not** invent real Pokémon card IDs. A placeholder deck is
only meaningful once a real card database is present so its IDs map to actual
cards. When no card DB exists we still expose a clearly-labelled placeholder of
repeated safe integers so packaging/validation can be exercised, but it must
not be treated as a competitive decklist.
"""

from __future__ import annotations

from typing import Any

# A neutral placeholder: 60 copies of id 1. Only valid as a structural stand-in.
BASELINE_DECK_IDS: list[int] = [1] * 60


def make_placeholder_deck(card_db: Any = None, size: int = 60) -> list[int]:
    """Build a structurally-valid 60-id placeholder deck.

    If a non-empty ``card_db`` is available, prefer real basic-Pokémon and
    energy IDs so the deck is at least plausibly playable. Otherwise return the
    neutral repeated-id placeholder.
    """
    if card_db is None or len(card_db) == 0:
        return [1] * size

    basics: list[int] = []
    energies: list[int] = []
    others: list[int] = []
    for rec in card_db.all():
        cid = rec.get("card_id")
        try:
            cid_int = int(cid)
        except (TypeError, ValueError):
            continue
        feats = card_db.basic_features(cid)
        if feats.get("is_basic"):
            basics.append(cid_int)
        elif feats.get("is_energy"):
            energies.append(cid_int)
        else:
            others.append(cid_int)

    deck: list[int] = []
    # Roughly: 12 basics, 15 energy, fill remainder with others, capped at 4 each.
    deck += _fill(basics, 12)
    deck += _fill(energies, 15)
    deck += _fill(others or basics or energies, size - len(deck))

    # Final safety: pad/truncate to exactly ``size``.
    if not deck:
        return [1] * size
    while len(deck) < size:
        deck.append(deck[len(deck) % len(deck)] if deck else 1)
    return deck[:size]


def _fill(pool: list[int], target: int, max_copies: int = 4) -> list[int]:
    out: list[int] = []
    if not pool or target <= 0:
        return out
    i = 0
    copies: dict[int, int] = {}
    while len(out) < target:
        cid = pool[i % len(pool)]
        i += 1
        if copies.get(cid, 0) < max_copies:
            out.append(cid)
            copies[cid] = copies.get(cid, 0) + 1
        elif i > len(pool) * (max_copies + 1):
            break
    return out
