"""Heuristic role tagging for cards.

Role tags drive deck-composition analysis and (later) action priorities. Tagging
is best-effort over whatever metadata fields a card record exposes; it never
raises and falls back to ``Unknown``.
"""

from __future__ import annotations

from typing import Any

ROLE_TAGS = [
    "Basic Pokémon",
    "Evolution",
    "Attacker",
    "Draw",
    "Search",
    "Energy acceleration",
    "Switch/retreat support",
    "Recovery",
    "Disruption",
    "Stadium",
    "Energy",
    "Trainer",
    "Unknown",
]

# Keyword -> role signals applied to a card's combined text.
_KEYWORD_ROLES: list[tuple[tuple[str, ...], str]] = [
    (("draw", "draws"), "Draw"),
    (("search your deck", "search for", "look at the top"), "Search"),
    (("switch", "retreat cost", "retreat"), "Switch/retreat support"),
    (("attach", "energy from your discard", "accelerat"), "Energy acceleration"),
    (("from your discard pile to your hand", "recover", "shuffle.*into your deck"), "Recovery"),
    (("discard a card from", "your opponent", "discards"), "Disruption"),
]


def _text_of(card: dict) -> str:
    parts: list[str] = []
    for key in ("name", "Name", "text", "Text", "rules", "Rules", "ability",
                "Ability", "attacks", "Attacks", "effect", "Effect"):
        v = card.get(key)
        if v is not None:
            parts.append(str(v))
    return " ".join(parts).lower()


def _category_of(card: dict) -> str:
    for key in ("category", "Category", "supertype", "Supertype", "type", "Type",
                "card_type", "CardType"):
        v = card.get(key)
        if v:
            return str(v).lower()
    return ""


def tag_roles(card: Any) -> list[str]:
    """Return a list of role tags for a card record (dict)."""
    if not isinstance(card, dict):
        return ["Unknown"]

    roles: list[str] = []
    text = _text_of(card)
    category = _category_of(card)

    is_pokemon = "pok" in category or any(
        k in card for k in ("hp", "HP", "stage", "Stage")
    )
    is_energy = "energy" in category and "accelerat" not in text
    is_trainer = any(t in category for t in ("trainer", "supporter", "item", "stadium"))

    if is_energy:
        roles.append("Energy")
    if is_trainer or "supporter" in category or "item" in category:
        roles.append("Trainer")
    if "stadium" in category or "stadium" in text:
        roles.append("Stadium")

    if is_pokemon:
        stage = str(card.get("stage") or card.get("Stage") or "").lower()
        evolves_from = card.get("evolves_from") or card.get("Evolves From")
        if "basic" in stage or (not stage and not evolves_from):
            roles.append("Basic Pokémon")
        if evolves_from or "stage 1" in stage or "stage 2" in stage:
            roles.append("Evolution")
        # Attacker if it has any attack-like field.
        if any(k in card for k in ("attacks", "Attacks", "attack", "Attack")):
            roles.append("Attacker")
        elif "attack" in text or "damage" in text:
            roles.append("Attacker")

    for keywords, role in _KEYWORD_ROLES:
        if any(k in text for k in keywords) and role not in roles:
            roles.append(role)

    if not roles:
        roles.append("Unknown")

    # De-duplicate preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out
