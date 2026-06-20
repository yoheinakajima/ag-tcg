"""Deterministic, never-raising decision primitives.

Each primitive takes a typed ``board``, a list of candidate cards/targets (each a
dict carrying at least ``card_id``), a ``profile`` (StrategyProfile dict) and the
inlined ``meta`` table. They return a plain value (card id / list / number) or an
``UNSUPPORTED`` sentinel. Ties are always broken deterministically.

Honesty: primitives that would require hidden information (attack damage, lethal,
KO/spread/Boss target identity, opponent hand) return ``UNSUPPORTED`` rather than a
guessed value. They exist so the decision layer can answer "unsupported" explicitly
instead of silently inventing a mechanic.
"""
from __future__ import annotations

from typing import Any

# These imports are STRIPPED by the compiler (the embedded layer is flat); they
# exist so the lab package and fixtures import the real cross-module names.
from ptcg_activegraph.pilot_typed.board import card_id, in_play_card_ids
from ptcg_activegraph.pilot_typed.metadata import (
    energy_type, hp, is_basic_energy, is_basic_pokemon,
)
from ptcg_activegraph.pilot_typed.profiles import (
    deckout_guard, discard_keep, discard_prefer, energy_types, priority_rank,
    roles,
)

UNSUPPORTED = "__unsupported__"

_ROLE_WEIGHT = {
    "primary_attacker": 100,
    "energy_accel": 70,
    "setup_basic": 60,
    "draw_engine": 50,
    "search": 40,
    "key_item": 30,
    "tech": 20,
    "bench_sitter": 10,
}
_DEFAULT_ROLE_WEIGHT = 5


def _cid(card: Any) -> Any:
    return card_id(card)  # noqa: F821  (board.card_id, co-embedded)


def role_of(profile: Any, cid: Any) -> Any:
    for role, ids in roles(profile).items():  # noqa: F821 (profiles.roles)
        if cid in ids:
            return role
    return None


def role_weight(profile: Any, cid: Any) -> int:
    return _ROLE_WEIGHT.get(role_of(profile, cid), _DEFAULT_ROLE_WEIGHT)


def _candidate_ids(cards: Any) -> list:
    out = []
    if isinstance(cards, list):
        for c in cards:
            out.append(_cid(c))
    return out


def choose_setup_active(board: Any, cards: Any, profile: Any, meta: Any) -> Any:
    """Pick which Basic becomes the active Pokemon at game start.

    At the setup-active context the engine only offers benchable Basics, so every
    option is a legal active. Choose the deck's intended opener: most-wanted by
    profile priority, then highest role weight, then highest known HP, then lowest
    card id (deterministic)."""
    ids = [c for c in _candidate_ids(cards) if c is not None]
    if not ids:
        return None

    def key(cid):
        return (priority_rank(profile, cid),          # noqa: F821 (profiles)
                -role_weight(profile, cid),
                -(hp(meta, cid) or 0),                 # noqa: F821 (metadata.hp)
                cid)
    return sorted(ids, key=key)[0]


def choose_setup_bench(board: Any, cards: Any, profile: Any, meta: Any,
                       need: int) -> list:
    """Pick exactly ``need`` Basics for the bench, best pieces first."""
    ids = [c for c in _candidate_ids(cards) if c is not None]
    if need <= 0 or not ids:
        return []

    def key(cid):
        return (priority_rank(profile, cid),           # noqa: F821
                -role_weight(profile, cid),
                -(hp(meta, cid) or 0),                  # noqa: F821
                cid)
    ordered = sorted(ids, key=key)
    return ordered[:need]


def choose_search_target(board: Any, cards: Any, profile: Any, meta: Any) -> Any:
    """Pick the single best card to fetch to hand.

    Prefer a piece NOT already in play (you usually want a new piece), then by
    profile priority / role weight, deterministic tie-break."""
    ids = [c for c in _candidate_ids(cards) if c is not None]
    if not ids:
        return None
    in_play = set(in_play_card_ids(board))             # noqa: F821 (board)

    def key(cid):
        return (1 if cid in in_play else 0,
                priority_rank(profile, cid),           # noqa: F821
                -role_weight(profile, cid),
                cid)
    return sorted(ids, key=key)[0]


def choose_discard(board: Any, cards: Any, profile: Any, meta: Any,
                   need: int) -> list:
    """Pick exactly ``need`` cards to discard, least valuable first.

    Keep profile ``discard_keep`` cards if at all possible; prefer
    ``discard_prefer`` and surplus basic energy; otherwise discard least-wanted
    (highest priority rank). Deterministic."""
    ids = [c for c in _candidate_ids(cards) if c is not None]
    if need <= 0 or not ids:
        return []
    keep = set(discard_keep(profile))                  # noqa: F821 (profiles)
    prefer = set(discard_prefer(profile))              # noqa: F821 (profiles)
    energy_ids = [c for c in ids if is_basic_energy(meta, c)]  # noqa: F821
    surplus_energy = set()
    # Keep at least 1 basic energy in hand if we can; mark the rest as surplus.
    if len(energy_ids) > 1:
        surplus_energy = set(energy_ids[1:])

    def discard_score(cid):
        s = 0
        if cid in keep:
            s -= 1000
        if cid in prefer:
            s += 100
        if cid in surplus_energy:
            s += 60
        s += priority_rank(profile, cid)               # noqa: F821 (less wanted)
        return s
    ordered = sorted(ids, key=lambda c: (-discard_score(c), c))
    return ordered[:need]


def safe_draw_count(board: Any, numbers: Any, profile: Any) -> Any:
    """Choose a draw quantity that avoids self-deckout.

    Pick the LARGEST offered number that still leaves at least ``min_deck`` cards
    in the deck; if none qualify, pick the smallest offered number."""
    nums = [n for n in numbers
            if isinstance(n, int) and not isinstance(n, bool)]
    if not nums:
        return None
    guard = deckout_guard(profile)                     # noqa: F821 (profiles)
    min_keep = guard.get("min_deck")
    if not (isinstance(min_keep, int) and not isinstance(min_keep, bool)):
        min_keep = 1
    deck = board.get("deck_count") if isinstance(board, dict) else None
    if not (isinstance(deck, int) and not isinstance(deck, bool)):
        # No deck info -> conservative: smallest non-zero draw, else smallest.
        positive = sorted(n for n in nums if n > 0)
        return positive[0] if positive else sorted(nums)[0]
    safe = sorted((n for n in nums if deck - n >= min_keep), reverse=True)
    if safe:
        return safe[0]
    return sorted(nums)[0]


def choose_emergency_bench(board: Any, cards: Any, profile: Any, meta: Any) -> Any:
    """At the Main action with an EMPTY bench, pick a Basic to bench as backup.

    Only returns a card the metadata (or the engine option) treats as a benchable
    Basic; deterministic best piece first."""
    ids = [c for c in _candidate_ids(cards) if c is not None]
    ids = [c for c in ids if is_basic_pokemon(meta, c)]  # noqa: F821 (metadata)
    if not ids:
        return None

    def key(cid):
        return (priority_rank(profile, cid),            # noqa: F821
                -role_weight(profile, cid),
                cid)
    return sorted(ids, key=key)[0]


def choose_attach_target(board: Any, targets: Any, profile: Any, meta: Any) -> Any:
    """Pick which of OUR in-play Pokemon should receive an energy.

    Target identity is observable (inPlayArea/inPlayIndex resolved against our own
    board), so this is honest. Prefer the intended attacker (active first), then a
    primary attacker on the bench being built up; deterministic."""
    ids = [c for c in _candidate_ids(targets) if c is not None]
    if not ids:
        return None
    active_cid = card_id(board.get("active")) if isinstance(board, dict) else None  # noqa: F821
    et = set(energy_types(profile))                     # noqa: F821 (profiles)

    def key(cid):
        w = role_weight(profile, cid)
        type_match = 1 if (et and metadata_energy_match(meta, cid, et)) else 0
        is_active = 1 if cid == active_cid else 0
        return (-w, -type_match, -is_active,
                priority_rank(profile, cid), cid)       # noqa: F821
    return sorted(ids, key=key)[0]


def metadata_energy_match(meta: Any, cid: Any, deck_energy_types: Any) -> bool:
    et = energy_type(meta, cid)                         # noqa: F821 (metadata)
    return bool(et) and et in deck_energy_types


# --- Honesty sentinels: mechanics the option schema does not expose. ---

def estimate_attack_damage(*_a, **_k) -> Any:
    """Numeric attackId only — no base damage/effect text. UNSUPPORTED."""
    return UNSUPPORTED


def choose_ko_target(*_a, **_k) -> Any:
    """Requires attack damage + attack target identity. UNSUPPORTED."""
    return UNSUPPORTED


def choose_spread_placement(*_a, **_k) -> Any:
    """Spread/Phantom-Dive targets not exposed. UNSUPPORTED (Pass-28 rule)."""
    return UNSUPPORTED


def choose_boss_target(*_a, **_k) -> Any:
    """Boss/gust target identity not observable. UNSUPPORTED."""
    return UNSUPPORTED
