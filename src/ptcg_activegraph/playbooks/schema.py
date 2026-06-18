"""Playbook schema: required fields, confirmed card ids, and the field->rule map.

The schema is intentionally small and declarative. Card ids are the *confirmed*
ids from ``data/cards/EN_Card_Data.csv`` (the only ids we are allowed to use);
inventing an id is a hard validation failure.
"""

from __future__ import annotations

# Confirmed card ids (name -> id). NEVER invent ids; these are grounded in
# data/cards/EN_Card_Data.csv and reused across Pass 4-9.
CONFIRMED_CARDS: dict[str, int] = {
    "basic_water_energy": 3,
    "kyogre": 721,
    "snover": 722,
    "mega_abomasnow_ex": 723,
    "secret_box": 1092,
    "ultra_ball": 1121,
    "mega_signal": 1145,
    "powerglass": 1163,
    "petrel": 1219,
    "lillie": 1227,
    "surfing_beach": 1262,
}

CARD_NAMES: dict[int, str] = {
    3: "Basic {W} Energy",
    721: "Kyogre",
    722: "Snover",
    723: "Mega Abomasnow ex",
    1092: "Secret Box",
    1121: "Ultra Ball",
    1145: "Mega Signal",
    1163: "Powerglass",
    1219: "Team Rocket's Petrel",
    1227: "Lillie's Determination",
    1262: "Surfing Beach",
}

# Top-level fields every playbook must declare.
REQUIRED_FIELDS: tuple[str, ...] = (
    "deck_id",
    "baseline_id",
    "cards",
    "roles",
    "gameplan",
    "opening",
    "main_phase_priorities",
    "effect_resolution",
    "discard_safety",
    "search",
    "deckout_guard",
    "attachment",
    "fixture_requirements",
    "report_notes",
)

# Sections whose card-id values are validated against the confirmed set / deck.
ROLE_SECTIONS: tuple[str, ...] = (
    "primary_attackers",
    "setup_basics",
    "evolution_payoffs",
    "search_cards",
    "risky_search_cards",
    "draw_cards",
    "tools",
    "energy",
)

# Additional (section, key) fields whose list values are card ids and must be
# validated against the confirmed set / deck (beyond ``cards`` and ``roles``).
CARD_ID_LIST_FIELDS: tuple[tuple[str, str], ...] = (
    ("discard_safety", "prefer_discard"),
    ("discard_safety", "never_discard_only"),
)

# The Pass-8 effect-safety rule keys this schema can compile into, with the
# playbook (section, key) each is derived from. Used by compiler.compile_rules
# and by report summaries so the mapping is single-sourced.
RULE_MAP: dict[str, tuple[str, str]] = {
    "discard_protect_setup": ("discard_safety", "protect_setup"),
    "search_avoid_orphan_evolution": ("search", "avoid_orphan_evolution"),
    "search_avoid_orphan_mega_signal": ("search", "avoid_orphan_mega_signal"),
    "decline_mega_signal_no_snover": ("effect_resolution", "decline_mega_signal_no_snover"),
    "deckout_decline_threshold": ("deckout_guard", "decline_threshold"),
}


def card_name(cid: int) -> str:
    """Human name for a confirmed card id (falls back to ``card <id>``)."""
    return CARD_NAMES.get(int(cid), f"card {cid}")
