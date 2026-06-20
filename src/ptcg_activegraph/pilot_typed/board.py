"""Typed board view over a raw cabt observation.

Pure, total, never-raising. Standard-library only so it can be embedded verbatim
into a candidate ``main.py``. Reconstructs the same typed signal the Kaggle
``cg.api`` wrapper exposes, directly from the raw ``obs_dict`` (see
docs/TYPED_AGENT_ARCHITECTURE.md for the audited schema).

Typed board contract:

    board = {
      "active": poke | None, "bench": [poke, ...], "bench_max": int,
      "hand": [card, ...], "hand_count": int, "deck_count": int|None,
      "discard": [card, ...], "prize_count": int,
      "opponent": {"active": poke|None, "bench": [...], "bench_max": int,
                   "hand_count": int, "deck_count": int|None,
                   "discard": [card,...], "prize_count": int, "status": {...}},
      "status": {asleep/burned/confused/paralyzed/poisoned: bool},
      "stadium": int|None, "stadium_played": bool, "supporter_played": bool,
      "energy_attached": bool, "retreated": bool,
      "turn": int|None, "turn_action_count": int|None, "your_index": int|None,
    }
    poke = {"card_id": int, "hp": int?, "max_hp": int?, "energy": int,
            "energy_ids": [int,...], "has_tool": bool, "tool_ids": [int,...],
            "pre_evolution": int?}
    card = {"card_id": int}
"""
from __future__ import annotations

from typing import Any

DEFAULT_BENCH_MAX = 5

_STATUS_KEYS = ("asleep", "burned", "confused", "paralyzed", "poisoned")


def safe_get(obj: Any, key: Any, default: Any = None) -> Any:
    if isinstance(obj, dict):
        val = obj.get(key, default)
        return default if val is None else val
    return default


def card_id(obj: Any, default: Any = None) -> Any:
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


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def get_current(obs: Any) -> Any:
    return safe_get(obs, "current")


def get_select(obs: Any) -> Any:
    sel = safe_get(obs, "select")
    return sel if isinstance(sel, dict) else None


def get_players(obs: Any) -> list:
    players = safe_get(get_current(obs), "players")
    return players if isinstance(players, list) else []


def your_index(obs: Any) -> Any:
    me = safe_get(get_current(obs), "yourIndex")
    return me if _is_int(me) else None


def get_own_player(obs: Any) -> Any:
    players = get_players(obs)
    me = your_index(obs)
    if me is not None and 0 <= me < len(players):
        return players[me]
    return players[0] if players else None


def get_opp_player(obs: Any) -> Any:
    players = get_players(obs)
    me = your_index(obs)
    if me is not None:
        for i, p in enumerate(players):
            if i != me:
                return p
    return players[1] if len(players) > 1 else None


def _cards(zone: Any) -> list:
    return zone if isinstance(zone, list) else []


def get_hand_cards(obs: Any) -> list:
    return _cards(safe_get(get_own_player(obs), "hand"))


def context_int(obs: Any) -> Any:
    ctx = safe_get(get_select(obs), "context")
    return ctx if _is_int(ctx) else None


def option_type(option: Any) -> Any:
    t = safe_get(option, "type")
    return t if _is_int(t) else None


def resolve_option_card(obs: Any, option: Any) -> Any:
    """Resolve an option to the card id it refers to (hand/deck zone)."""
    if not isinstance(option, dict):
        return None
    direct = card_id(option)
    if direct is not None:
        return direct
    area = option.get("area")
    index = option.get("index")
    if not _is_int(index):
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
    """Resolve an option's in-play target (own active/bench) to a card id."""
    if not isinstance(option, dict):
        return None
    area = option.get("inPlayArea")
    index = option.get("inPlayIndex")
    if not _is_int(index):
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


def _norm_poke(raw: Any) -> dict:
    poke: dict = {"card_id": card_id(raw)}
    if isinstance(raw, dict):
        for src, dst in (("hp", "hp"), ("maxHp", "max_hp"),
                         ("preEvolution", "pre_evolution")):
            v = raw.get(src)
            if v is not None:
                poke[dst] = v
        e_ids = []
        for e in _cards(raw.get("energyCards")):
            cid = card_id(e)
            if cid is not None:
                e_ids.append(cid)
        energies = raw.get("energies")
        if not e_ids and _is_int(energies):
            poke["energy"] = energies
        else:
            poke["energy"] = len(e_ids)
        poke["energy_ids"] = e_ids
        t_ids = []
        for t in _cards(raw.get("tools")):
            cid = card_id(t)
            if cid is not None:
                t_ids.append(cid)
        poke["tool_ids"] = t_ids
        poke["has_tool"] = len(t_ids) > 0
    else:
        poke["energy"] = 0
        poke["energy_ids"] = []
        poke["tool_ids"] = []
        poke["has_tool"] = False
    return poke


def _norm_card(raw: Any) -> dict:
    return {"card_id": card_id(raw)}


def _status(player: Any) -> dict:
    return {k: bool(safe_get(player, k, False)) for k in _STATUS_KEYS}


def _deck_count(player: Any) -> Any:
    dc = safe_get(player, "deckCount")
    return dc if _is_int(dc) else None


def _hand_count(player: Any) -> int:
    hc = safe_get(player, "handCount")
    if _is_int(hc):
        return hc
    return len(_cards(safe_get(player, "hand")))


def _bench_max(player: Any) -> int:
    bm = safe_get(player, "benchMax")
    return bm if _is_int(bm) else DEFAULT_BENCH_MAX


def build_board(obs: Any) -> dict:
    """Best-effort typed board from a cabt observation. Never raises."""
    try:
        me = get_own_player(obs)
        opp = get_opp_player(obs)
        active_raw = _cards(safe_get(me, "active"))
        opp_active_raw = _cards(safe_get(opp, "active"))
        cur = get_current(obs)
        board = {
            "active": _norm_poke(active_raw[0]) if active_raw else None,
            "bench": [_norm_poke(c) for c in _cards(safe_get(me, "bench"))],
            "bench_max": _bench_max(me),
            "hand": [_norm_card(c) for c in _cards(safe_get(me, "hand"))],
            "hand_count": _hand_count(me),
            "deck_count": _deck_count(me),
            "discard": [_norm_card(c) for c in _cards(safe_get(me, "discard"))],
            "prize_count": len(_cards(safe_get(me, "prize"))),
            "status": _status(me),
            "opponent": {
                "active": _norm_poke(opp_active_raw[0]) if opp_active_raw else None,
                "bench": [_norm_poke(c) for c in _cards(safe_get(opp, "bench"))],
                "bench_max": _bench_max(opp),
                "hand_count": _hand_count(opp),
                "deck_count": _deck_count(opp),
                "discard": [_norm_card(c) for c in _cards(safe_get(opp, "discard"))],
                "prize_count": len(_cards(safe_get(opp, "prize"))),
                "status": _status(opp),
            },
            "stadium": safe_get(cur, "stadium") if _is_int(safe_get(cur, "stadium")) else None,
            "stadium_played": bool(safe_get(cur, "stadiumPlayed", False)),
            "supporter_played": bool(safe_get(cur, "supporterPlayed", False)),
            "energy_attached": bool(safe_get(cur, "energyAttached", False)),
            "retreated": bool(safe_get(cur, "retreated", False)),
            "turn": safe_get(cur, "turn") if _is_int(safe_get(cur, "turn")) else None,
            "turn_action_count": safe_get(cur, "turnActionCount")
            if _is_int(safe_get(cur, "turnActionCount")) else None,
            "your_index": your_index(obs),
        }
        return board
    except Exception:
        return {"active": None, "bench": [], "bench_max": DEFAULT_BENCH_MAX,
                "hand": [], "hand_count": 0, "deck_count": None, "discard": [],
                "prize_count": 0, "status": {}, "opponent": {}, "stadium": None,
                "stadium_played": False, "supporter_played": False,
                "energy_attached": False, "retreated": False, "turn": None,
                "turn_action_count": None, "your_index": None}


def in_play_card_ids(board: Any) -> list:
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
