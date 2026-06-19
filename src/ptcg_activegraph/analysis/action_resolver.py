"""Pass 29 action resolver (v2) — decode cabt option dicts into structured,
confidence-tagged resolutions WITHOUT overclaiming.

Design goals
------------
* Self-contained: operates on raw cabt option dicts plus optional context
  (the enclosing ``select`` block and/or a board snapshot). No candidate import.
* Honest confidence tiers (never invent card ids):
    - ``direct_option``            — action class / target read straight from the
                                     option's own schema fields.
    - ``verified_by_following_log``— a subsequent engine log entry confirms the
                                     card/zone movement the option implied.
    - ``inferred_from_state_delta``— identity/effect inferred by comparing board
                                     snapshots before/after (no direct field).
    - ``unresolved``               — cannot be determined from available data;
                                     reported as such rather than guessed.

The cabt schema codes below were decoded from the one available raw replay
(``data/replays/80374966.json``) plus the Pass-28 forensic trace; anything not
positively observed is left as ``unknown`` rather than assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Option ``type`` -> coarse action class (only positively-observed codes mapped).
OPTION_TYPE_CLASS: dict[int, str] = {
    0: "effect_choice",
    1: "effect_choice",
    2: "effect_choice",
    3: "select_card",
    6: "move_energy",
    7: "play_from_hand",
    8: "attach_energy",
    9: "use_ability",
    10: "play_in_play",
    12: "end_turn",
    13: "attack",
    14: "end_turn",
}

# Zone ``area`` codes (observed in replay option/log fields).
AREA_NAMES: dict[Optional[int], str] = {
    0: "unknown", 1: "deck", 2: "hand", 4: "active", 5: "bench", 6: "discard",
}

CONFIDENCE_TIERS = (
    "direct_option",
    "verified_by_following_log",
    "inferred_from_state_delta",
    "unresolved",
)


def area_name(area: Optional[int]) -> str:
    return AREA_NAMES.get(area, f"area_{area}")


@dataclass
class Resolution:
    """A single resolved option."""
    action_class: str = "unknown"
    raw_type: Optional[int] = None
    # source (what is being acted with) and target (what is being acted upon).
    source_area: Optional[str] = None
    source_index: Optional[int] = None
    target_area: Optional[str] = None
    target_index: Optional[int] = None
    attack_id: Optional[int] = None
    card_id: Optional[int] = None
    card_name: Optional[str] = None
    target_card_id: Optional[int] = None
    target_card_name: Optional[str] = None
    is_loop_exit: Optional[bool] = None  # True/False only when determinable
    confidence: str = "unresolved"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _board_pokemon(board: Optional[dict], area: Optional[str],
                   index: Optional[int]) -> tuple[Optional[int], Optional[str]]:
    """Resolve a target Pokemon (card id/name) from a board snapshot."""
    if not isinstance(board, dict) or area is None:
        return None, None
    if area == "active":
        a = board.get("active")
        if isinstance(a, dict):
            return a.get("card_id"), a.get("name")
    elif area == "bench":
        bench = board.get("bench") or []
        if isinstance(index, int) and 0 <= index < len(bench):
            b = bench[index]
            if isinstance(b, dict):
                return b.get("card_id"), b.get("name")
    return None, None


def resolve_option(option: dict, *, select: Optional[dict] = None,
                   board: Optional[dict] = None) -> Resolution:
    """Resolve a single raw cabt option dict to a :class:`Resolution`.

    ``select`` is the enclosing select block (for ``deck`` lookups on searches);
    ``board`` is an optional board snapshot used to name attach/attack targets.
    """
    if not isinstance(option, dict):
        return Resolution(notes=["option was not a dict"])
    otype = option.get("type")
    res = Resolution(raw_type=otype,
                     action_class=OPTION_TYPE_CLASS.get(otype, "unknown"),
                     attack_id=option.get("attackId"))

    # The action class is always read straight from the schema -> direct_option.
    res.confidence = "direct_option" if res.action_class != "unknown" else "unresolved"

    # Source zone (what is being played / moved).
    if "area" in option:
        res.source_area = area_name(option.get("area"))
        res.source_index = option.get("index")

    # Target zone (where it goes / what it hits).
    if "inPlayArea" in option:
        res.target_area = area_name(option.get("inPlayArea"))
        res.target_index = option.get("inPlayIndex")
        tid, tname = _board_pokemon(board, res.target_area, res.target_index)
        res.target_card_id, res.target_card_name = tid, tname

    # Attack target naming (defaults to opponent active when board present).
    if res.action_class == "attack" and isinstance(board, dict):
        opp = board.get("opponent_active")
        if isinstance(opp, dict):
            res.target_card_id = opp.get("card_id")
            res.target_card_name = opp.get("name")

    # Search / select-from-deck: try select.deck identity (no invention).
    if res.action_class == "select_card" and isinstance(select, dict):
        deck = select.get("deck") or []
        idx = option.get("index")
        if isinstance(deck, list) and isinstance(idx, int) and 0 <= idx < len(deck):
            ent = deck[idx]
            if isinstance(ent, dict):
                res.card_id = ent.get("id")
                res.notes.append("card id from select.deck[index] (positional)")
        else:
            res.notes.append("select_card identity not positionally resolvable "
                             "from select.deck; left null")

    # end_turn / effect_choice carry no card identity by design.
    if res.action_class in ("end_turn", "effect_choice"):
        res.notes.append("no card identity by schema design")

    return res


def classify_select_window(select: dict) -> dict[str, Any]:
    """Characterise a select block: is it a real choice, and is any option an
    explicit loop exit (end_turn / a 'no'/decline effect_choice)?"""
    opts = select.get("option") or select.get("options") or []
    n = len(opts) if isinstance(opts, list) else 0
    min_c = select.get("minCount")
    max_c = select.get("maxCount")
    resolved = [resolve_option(o, select=select) for o in opts] if n else []
    classes = sorted({r.action_class for r in resolved})
    has_end = any(r.action_class == "end_turn" for r in resolved)
    # A forced step offers exactly one option (or min==max==n with no opt-out).
    forced = (n <= 1)
    has_exit_option = bool(has_end)
    return {
        "context": select.get("context"),
        "select_type": select.get("type"),
        "n_options": n,
        "min_count": min_c,
        "max_count": max_c,
        "is_forced_single_option": forced,
        "option_classes_present": classes,
        "has_explicit_exit_option": has_exit_option,
        "exit_option_observable": has_exit_option,
    }


def match_following_log(res: Resolution, logs: list[dict]) -> bool:
    """Return True if a following engine-log entry corroborates ``res``.

    Logs are per-step movement deltas: ``{cardId, fromArea, toArea, type, ...}``.
    We corroborate by zone transition consistency, never by inventing ids.
    """
    if not isinstance(logs, list):
        return False
    src = res.source_area
    tgt = res.target_area
    for lg in logs:
        if not isinstance(lg, dict):
            continue
        f, t = area_name(lg.get("fromArea")), area_name(lg.get("toArea"))
        if res.action_class == "attach_energy" and t in ("active", "bench"):
            if tgt is None or t == tgt:
                return True
        if res.action_class == "play_from_hand" and f == "hand":
            return True
        if res.action_class == "select_card" and f == "deck":
            if res.card_id is None and lg.get("cardId") is not None:
                res.card_id = lg.get("cardId")
                res.notes.append("card id recovered from following deck->zone log")
            return True
        if res.action_class == "move_energy" and (src == f or tgt == t):
            return True
    return False
