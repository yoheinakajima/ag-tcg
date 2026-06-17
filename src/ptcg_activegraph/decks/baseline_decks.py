"""Baseline / placeholder decks.

IMPORTANT: We do **not** invent real Pokémon card IDs. A placeholder deck is
only meaningful once a real card database is present so its IDs map to actual
cards. When no card DB exists we still expose a clearly-labelled placeholder of
repeated safe integers so packaging/validation can be exercised, but it must
not be treated as a competitive decklist.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# A neutral placeholder: 60 copies of id 1. Only valid as a structural stand-in.
BASELINE_DECK_IDS: list[int] = [1] * 60

DECK_SIZE = 60


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


# ---------------------------------------------------------------------------
# Baseline deck generation directly from official card CSV records.
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _resolve_columns(headers: list[str]) -> dict:
    """Map logical fields to actual CSV headers via tolerant alias matching."""
    norm_map = {_norm(h): h for h in headers}
    cols: dict[str, str | None] = {}

    def find(pred):
        for nh, orig in norm_map.items():
            if pred(nh):
                return orig
        return None

    cols["card_id"] = find(lambda h: h in ("cardid", "id", "cardno", "number")) \
        or find(lambda h: "cardid" in h or h == "id")
    cols["name"] = find(lambda h: h in ("cardname", "name")) or find(lambda h: "name" in h)
    cols["category"] = find(lambda h: "category" in h or "supertype" in h)
    cols["stage"] = find(lambda h: "stage" in h)
    cols["prev_stage"] = find(lambda h: "previous" in h or "prevstage" in h)
    cols["hp"] = find(lambda h: h == "hp")
    cols["type"] = find(lambda h: h == "type") or find(
        lambda h: "type" in h and "stage" not in h and "retreat" not in h
    )
    cols["retreat"] = find(lambda h: "retreat" in h)
    cols["damage"] = find(lambda h: "damage" in h)
    cols["cost"] = find(lambda h: "cost" in h)
    cols["effect"] = find(lambda h: "effect" in h)
    return cols


def _get(rec: dict, cols: dict, key: str) -> str:
    col = cols.get(key)
    if not col:
        return ""
    v = rec.get(col)
    return "" if v is None else str(v)


def _num(text: str) -> int:
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else 0


def _classify(rec: dict, cols: dict) -> dict:
    category = _get(rec, cols, "category").lower()
    stage = _get(rec, cols, "stage").lower()
    type_ = _get(rec, cols, "type").lower()
    effect = _get(rec, cols, "effect").lower()
    prev = _get(rec, cols, "prev_stage").strip()

    is_energy = "energy" in category or "energy" in stage or (
        "energy" in type_ and "pok" not in category
    )
    is_trainer = any(t in category for t in ("trainer", "supporter", "item", "stadium")) \
        or any(t in stage for t in ("supporter", "item", "stadium", "trainer"))
    is_pokemon = "pok" in category or (not is_energy and not is_trainer and (
        _get(rec, cols, "hp") != "" or "basic" in stage or "stage" in stage
    ))

    is_basic = is_pokemon and ("basic" in stage or (not prev and "stage" not in stage))
    is_evolution = is_pokemon and (("stage 1" in stage) or ("stage 2" in stage) or bool(prev))
    is_stage2 = "stage 2" in stage
    is_basic_energy = is_energy and ("basic" in category or "basic" in stage or "basic" in type_
                                     or "special" not in (category + stage + type_))
    draw_search = is_trainer and any(
        k in effect for k in ("draw", "search", "deck", "hand", "look at")
    )
    switch_support = is_trainer and any(
        k in effect for k in ("switch", "retreat", "active", "bench")
    )

    return {
        "is_energy": is_energy,
        "is_basic_energy": is_basic_energy,
        "is_trainer": is_trainer,
        "is_pokemon": is_pokemon,
        "is_basic": is_basic,
        "is_evolution": is_evolution,
        "is_stage2": is_stage2,
        "draw_search": draw_search,
        "switch_support": switch_support,
        "hp": _num(_get(rec, cols, "hp")),
        "retreat": _num(_get(rec, cols, "retreat")),
        "damage": _num(_get(rec, cols, "damage")),
        "energy_type": type_,
        "card_id": _get(rec, cols, "card_id"),
    }


def generate_baseline_deck_from_records(records: list[dict]) -> dict:
    """Generate a conservative, valid 60-card baseline deck from CSV records.

    Strategy (validity over cleverness):
      * favour one energy type,
      * include high-HP, low-retreat Basic Pokémon attackers,
      * include draw/search Trainers,
      * fill remaining slots with basic Energy (no copy limit),
      * avoid Stage 2 lines.

    Returns a dict with ``ok``, ``card_ids``, ``notes``, ``warnings``, ``errors``.
    """
    notes: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    if not records:
        return {"ok": False, "card_ids": [], "errors": ["no card records"],
                "notes": notes, "warnings": warnings}

    headers: list[str] = []
    for rec in records:
        for k in rec.keys():
            if k not in headers:
                headers.append(k)
    cols = _resolve_columns(headers)
    if not cols.get("card_id"):
        return {"ok": False, "card_ids": [],
                "errors": ["could not find a Card ID column"], "notes": notes,
                "warnings": warnings}

    basics: list[dict] = []
    evolutions: list[dict] = []
    basic_energy: list[dict] = []
    trainers_draw: list[dict] = []
    trainers_other: list[dict] = []

    for rec in records:
        info = _classify(rec, cols)
        cid_raw = info["card_id"]
        try:
            info["cid"] = int(re.search(r"-?\d+", cid_raw).group())
        except (AttributeError, ValueError):
            continue
        if info["is_basic_energy"] or (info["is_energy"]):
            basic_energy.append(info)
        elif info["is_trainer"]:
            (trainers_draw if info["draw_search"] else trainers_other).append(info)
        elif info["is_basic"]:
            basics.append(info)
        elif info["is_evolution"] and not info["is_stage2"]:
            evolutions.append(info)

    if not basics:
        errors.append("no Basic Pokémon found; cannot build a startable deck")
    if not basic_energy:
        errors.append("no Energy cards found; cannot fill/attack")
    if errors:
        return {"ok": False, "card_ids": [], "errors": errors, "notes": notes,
                "warnings": warnings}

    # Pick a dominant energy type from the strongest basics.
    basics.sort(key=lambda b: (-b["hp"], b["retreat"]))
    type_counter = Counter(b["energy_type"] for b in basics[:8] if b["energy_type"])
    dominant = type_counter.most_common(1)[0][0] if type_counter else ""
    if dominant:
        notes.append(f"chose dominant energy type: {dominant!r}")

    # Best basics: dominant type first, then HP desc / retreat asc.
    def basic_key(b):
        return (0 if b["energy_type"] == dominant else 1, -b["hp"], b["retreat"])
    basics.sort(key=basic_key)

    deck: list[int] = []

    # ~16 Basic Pokémon: up to 5 distinct, 4 copies (capped to availability).
    target_basics = 16
    chosen_basics = basics[: max(4, min(5, len(basics)))]
    deck += _fill([b["cid"] for b in chosen_basics], target_basics, max_copies=4)
    notes.append(f"{len(deck)} Basic Pokémon from {len(chosen_basics)} distinct cards")

    # ~30 Trainers: draw/search first, then others; 4 copies each.
    before = len(deck)
    trainer_ids = [t["cid"] for t in trainers_draw] + [t["cid"] for t in trainers_other]
    deck += _fill(trainer_ids, 30, max_copies=4)
    notes.append(f"{len(deck) - before} Trainers (draw/search prioritised)")

    # Fill the remainder with one basic Energy of the dominant type (no cap).
    energy_pool = [e for e in basic_energy if e["energy_type"] == dominant] or basic_energy
    energy_id = energy_pool[0]["cid"]
    remaining = DECK_SIZE - len(deck)
    if remaining > 0:
        deck += [energy_id] * remaining
        notes.append(f"{remaining} basic Energy (card {energy_id}) as filler")
    elif remaining < 0:
        deck = deck[:DECK_SIZE]

    # Safety: guarantee exactly 60 by topping up with energy.
    while len(deck) < DECK_SIZE:
        deck.append(energy_id)
    deck = deck[:DECK_SIZE]

    if len(deck) != DECK_SIZE:
        return {"ok": False, "card_ids": deck,
                "errors": [f"generated {len(deck)} cards, expected {DECK_SIZE}"],
                "notes": notes, "warnings": warnings}

    return {"ok": True, "card_ids": deck, "notes": notes, "warnings": warnings,
            "errors": []}
