"""Layer 1 — state model.

Pure, total, never-raising readers over a cabt observation, plus a normalized
``board`` builder the upper pilot layers reason about. Standard-library only so the
whole module can be embedded verbatim into a stdlib-only candidate ``main.py``.

The normalized board contract (see docs/CORE_PILOT_ARCHITECTURE.md):

    board = {
      "active":     card | None,
      "bench":      [card, ...],
      "bench_max":  int,
      "hand":       [card, ...],
      "deck_count": int,
      "discard":    [card, ...],
      "prize_count":int,
      "opponent_active": card | None,
    }
    card = {"card_id": int, "hp": int?, "is_basic": bool?, "energy": int?, ...}
"""
from __future__ import annotations

from typing import Any

DEFAULT_BENCH_MAX = 5

# cabt select.context integers we can name reliably (see docs/CABT_SCHEMA_NOTES.md
# and the Pass-8 effect-safety guards).
_CONTEXT_NAMES = {7: "search_draw", 8: "discard"}


def safe_get(obj: Any, key: Any, default: Any = None) -> Any:
    """``obj.get(key)`` that never raises and tolerates non-mappings."""
    if isinstance(obj, dict):
        val = obj.get(key, default)
        return default if val is None else val
    return default


def card_id(obj: Any, default: Any = None) -> Any:
    """Best-effort card id from a card/option dict or a bare int."""
    if isinstance(obj, bool):
        return default
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        for key in ("card_id", "id", "cardId"):
            val = obj.get(key)
            if isinstance(val, int) and not isinstance(val, bool):
                return val
    return default


def get_current(obs: Any) -> Any:
    return safe_get(obs, "current")


def get_select(obs: Any) -> Any:
    sel = safe_get(obs, "select")
    return sel if isinstance(sel, dict) else None


def get_players(obs: Any) -> list:
    cur = get_current(obs)
    players = safe_get(cur, "players")
    return players if isinstance(players, list) else []


def get_own_player(obs: Any) -> Any:
    cur = get_current(obs)
    players = get_players(obs)
    me = safe_get(cur, "yourIndex")
    if isinstance(me, int) and not isinstance(me, bool) and 0 <= me < len(players):
        return players[me]
    return players[0] if players else None


def get_opp_player(obs: Any) -> Any:
    cur = get_current(obs)
    players = get_players(obs)
    me = safe_get(cur, "yourIndex")
    if isinstance(me, int) and not isinstance(me, bool):
        for i, p in enumerate(players):
            if i != me:
                return p
    return players[1] if len(players) > 1 else None


def _cards(zone: Any) -> list:
    return zone if isinstance(zone, list) else []


def get_hand_cards(obs: Any) -> list:
    return _cards(safe_get(get_own_player(obs), "hand"))


def get_active(obs: Any) -> Any:
    active = _cards(safe_get(get_own_player(obs), "active"))
    return active[0] if active else None


def get_bench(obs: Any) -> list:
    return _cards(safe_get(get_own_player(obs), "bench"))


def get_discard(obs: Any) -> list:
    return _cards(safe_get(get_own_player(obs), "discard"))


def get_deck_count(obs: Any) -> Any:
    dc = safe_get(get_own_player(obs), "deckCount")
    return dc if isinstance(dc, int) and not isinstance(dc, bool) else None


def context_name(select: Any) -> str:
    ctx = safe_get(select, "context")
    return _CONTEXT_NAMES.get(ctx, "unknown")


def option_type(option: Any) -> Any:
    t = safe_get(option, "type")
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def resolve_option_card(obs: Any, option: Any) -> Any:
    """Resolve an option to the card id it refers to, when possible."""
    if not isinstance(option, dict):
        return None
    direct = card_id(option)
    if direct is not None:
        return direct
    area = option.get("area")
    index = option.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    sel = get_select(obs)
    if area == 1 and isinstance(sel, dict):
        deck = sel.get("deck")
        if isinstance(deck, list) and 0 <= index < len(deck):
            return card_id(deck[index])
    if area == 2:
        hand = get_hand_cards(obs)
        if 0 <= index < len(hand):
            return card_id(hand[index])
    return None


def resolve_option_target(obs: Any, option: Any) -> Any:
    """Resolve an option's in-play target (active/bench) to a card id."""
    if not isinstance(option, dict):
        return None
    area = option.get("inPlayArea")
    index = option.get("inPlayIndex")
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    player = get_own_player(obs)
    if area in (0, "active"):
        active = _cards(safe_get(player, "active"))
        if 0 <= index < len(active):
            return card_id(active[index])
    bench = _cards(safe_get(player, "bench"))
    if 0 <= index < len(bench):
        return card_id(bench[index])
    return None


def _norm_card(raw: Any) -> dict:
    cid = card_id(raw)
    card: dict = {"card_id": cid}
    if isinstance(raw, dict):
        for src, dst in (("hp", "hp"), ("maxHp", "max_hp"), ("isBasic", "is_basic")):
            if src in raw:
                card[dst] = raw[src]
        attached = raw.get("attached") or raw.get("energy")
        if isinstance(attached, list):
            card["energy"] = len(attached)
        elif isinstance(attached, int) and not isinstance(attached, bool):
            card["energy"] = attached
        tools = raw.get("tools")
        if isinstance(tools, list):
            card["has_tool"] = len(tools) > 0
    return card


def build_board(obs: Any) -> dict:
    """Best-effort normalized board from a cabt observation. Never raises."""
    try:
        active_raw = get_active(obs)
        bench = [_norm_card(c) for c in get_bench(obs)]
        opp_active_raw = _cards(safe_get(get_opp_player(obs), "active"))
        return {
            "active": _norm_card(active_raw) if active_raw is not None else None,
            "bench": bench,
            "bench_max": DEFAULT_BENCH_MAX,
            "hand": [_norm_card(c) for c in get_hand_cards(obs)],
            "deck_count": get_deck_count(obs),
            "discard": [_norm_card(c) for c in get_discard(obs)],
            "prize_count": len(_cards(safe_get(get_own_player(obs), "prize"))),
            "opponent_active": _norm_card(opp_active_raw[0]) if opp_active_raw else None,
        }
    except Exception:
        return {"active": None, "bench": [], "bench_max": DEFAULT_BENCH_MAX,
                "hand": [], "deck_count": None, "discard": [], "prize_count": 0,
                "opponent_active": None}


def in_play_card_ids(board: Any) -> list:
    """Card ids currently in play (active + bench)."""
    ids = []
    if isinstance(board, dict):
        active = board.get("active")
        if active is not None:
            cid = card_id(active)
            if cid is not None:
                ids.append(cid)
        for c in board.get("bench") or []:
            cid = card_id(c)
            if cid is not None:
                ids.append(cid)
    return ids
