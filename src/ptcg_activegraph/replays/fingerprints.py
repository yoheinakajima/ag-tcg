"""Deck fingerprinting for replay-derived and known decks.

All functions are pure and operate on a list of integer card ids. Two decks are
considered the *same deck* when their multiset fingerprint matches (card order in
the submitted action is not significant). The ordered fingerprint is kept too so
exact-order duplicates can be detected if ever needed.

Hard rule: these helpers only ever hash ids that are handed to them (extracted
from a real replay or read from a known deck file). No id is invented.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable


def _clean_ints(ids: Iterable) -> list[int]:
    out: list[int] = []
    for x in ids:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            out.append(x)
        else:
            try:
                out.append(int(str(x).strip()))
            except (TypeError, ValueError):
                continue
    return out


def ordered_deck_sha256(ids: Iterable) -> str:
    payload = ",".join(str(i) for i in _clean_ints(ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def multiset_deck_sha256(ids: Iterable) -> str:
    payload = ",".join(str(i) for i in sorted(_clean_ints(ids)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def card_counts(ids: Iterable) -> dict[int, int]:
    return dict(sorted(Counter(_clean_ints(ids)).items()))


def unique_card_count(ids: Iterable) -> int:
    return len(set(_clean_ints(ids)))


def deck_fingerprint(ids: Iterable) -> dict:
    clean = _clean_ints(ids)
    return {
        "card_count": len(clean),
        "unique_card_count": unique_card_count(clean),
        "ordered_deck_sha256": ordered_deck_sha256(clean),
        "multiset_deck_sha256": multiset_deck_sha256(clean),
        "card_counts": card_counts(clean),
    }


def match_multiset(ids: Iterable, known: dict[str, Iterable]) -> str | None:
    """Return the label of the known deck whose multiset matches ``ids``.

    ``known`` maps label -> id list. The first match wins; ``None`` if no known
    deck has the same multiset fingerprint.
    """
    target = multiset_deck_sha256(ids)
    for label, kids in known.items():
        if multiset_deck_sha256(kids) == target:
            return label
    return None
