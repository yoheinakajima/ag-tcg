"""cg_typed candidate entrypoint — cg_typed_mono_lightning_miraidon_policy_v1.

OWNED candidate for the PASS-41 reference-calibrated cg_typed spike. This is an
ORIGINAL typed policy for the Miraidon ex mono-Lightning deck: it imports the
bundled ``cg`` SDK and reasons over the typed ``cg.api`` enums / card database
(SelectContext, OptionType, EnergyType, all_card_data, all_attack) plus the
concrete board state (prizes, HP, attached energies, deck count). No
reference-agent policy code is copied; the only shared conventions are the
deck-return plumbing and the never-raise / always-legal fallback contract (this
project's own conventions).

Runtime contract: ``agent(obs_dict) -> list[int]`` returning legal option
indices (or the 60 deck card ids on the deck-submission step). Never raises.

This is a LOCAL benchmark-lane feasibility agent — NOT a Kaggle score, NOT a
leaderboard, NOT a strength claim. NO upload / submit / promote / mutate.
"""
from __future__ import annotations

import os as _os
import sys as _sys

# --- Bundled cg SDK import (robust to cwd; AST-visible for the cg_typed lane) ---
try:
    from cg import api as _cg
except Exception:  # pragma: no cover - resolve cg/ next to this file, then retry
    try:
        _here = _os.path.dirname(_os.path.abspath(__file__))
        if _here and _here not in _sys.path:
            _sys.path.insert(0, _here)
    except Exception:
        pass
    try:
        from cg import api as _cg
    except Exception:
        _cg = None

# Static card / attack databases (built once at import; empty if SDK absent).
try:
    _CARDS = {c.cardId: c for c in _cg.all_card_data()} if _cg else {}
    _ATTACKS = {a.attackId: a for a in _cg.all_attack()} if _cg else {}
except Exception:
    _CARDS, _ATTACKS = {}, {}

# --- Semantic constants -----------------------------------------------------
LIGHTNING, COLORLESS, FIGHTING = 4, 0, 6
ID_MIRAIDON, ID_THUNDURUS = 957, 514
ID_PAWMI, ID_PAWMO, ID_PAWMOT = 809, 810, 811
ID_BASIC_L = 4
ID_ULTRA_BALL, ID_POFFIN, ID_CHEREN = 1121, 1086, 1224
ID_RARE_CANDY, ID_BOSS, ID_DAWN, ID_LEVINCIA = 1079, 1182, 1231, 1254
ATK_HADRON_SPARK = 1377
_DECK_GUARD = 3  # below this deckCount, throttle optional draw/search

# OptionType ints (mirror cg.api.OptionType; literals keep the fallback path alive)
OT_NUMBER, OT_YES, OT_NO, OT_CARD = 0, 1, 2, 3
OT_TOOL_CARD, OT_ENERGY_CARD, OT_ENERGY = 4, 5, 6
OT_PLAY, OT_ATTACH, OT_EVOLVE, OT_ABILITY = 7, 8, 9, 10
OT_DISCARD, OT_RETREAT, OT_ATTACK, OT_END = 11, 12, 13, 14
# AreaType ints
AR_DECK, AR_HAND, AR_DISCARD, AR_ACTIVE, AR_BENCH, AR_PRIZE = 1, 2, 3, 4, 5, 6
# SelectContext ints
SC_MAIN = 0
SC_SETUP_ACTIVE, SC_SETUP_BENCH, SC_SWITCH, SC_TO_ACTIVE, SC_TO_BENCH, SC_TO_FIELD = 1, 2, 3, 4, 5, 6
SC_TO_HAND, SC_DISCARD = 7, 8
SC_DAMAGE_COUNTER, SC_DAMAGE_COUNTER_ANY, SC_DAMAGE = 13, 14, 15
SC_REMOVE_DAMAGE_COUNTER, SC_HEAL = 16, 17
SC_DRAW_COUNT, SC_DAMAGE_COUNTER_COUNT, SC_REMOVE_DAMAGE_COUNTER_COUNT = 38, 39, 40
SC_IS_FIRST, SC_MULLIGAN, SC_ACTIVATE, SC_FIRST_EFFECT, SC_COIN_HEAD = 41, 42, 43, 44, 46


# --- Universal accessor: works on a cg dataclass OR a raw dict ---------------
def _g(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_int(v, default=None):
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Deck-return plumbing (own deck; resilient to cwd; harness may inject _DECK_IDS)
# ---------------------------------------------------------------------------
_DECK_IDS = None
_EMBEDDED_DECK = [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    514, 514, 809, 809, 809, 810, 811, 811, 811, 957, 957, 957, 957,
    1079, 1079, 1079, 1086, 1086, 1086, 1086, 1121, 1121, 1121, 1121,
    1182, 1182, 1224, 1224, 1224, 1224, 1231, 1231, 1254, 1254,
]


def _deck_paths():
    paths = []
    try:
        here = _os.path.dirname(_os.path.abspath(__file__))
        paths.append(_os.path.join(here, "deck.csv"))
    except Exception:
        pass
    paths.append("deck.csv")
    paths.append("/kaggle_simulations/agent/deck.csv")
    return paths


def _load_deck_ids():
    global _DECK_IDS
    if _DECK_IDS:
        return _DECK_IDS
    ids = []
    for p in _deck_paths():
        try:
            if not _os.path.exists(p):
                continue
            parsed = []
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        v = _as_int(line)
                        if v is not None:
                            parsed.append(v)
            if len(parsed) == 60:
                ids = parsed
                break
            if parsed and not ids:
                ids = parsed
        except Exception:
            continue
    if len(ids) != 60:
        ids = list(_EMBEDDED_DECK)
    _DECK_IDS = ids
    return _DECK_IDS


# ---------------------------------------------------------------------------
# Generic legal-selection contract (never raise, always legal).
# ---------------------------------------------------------------------------
def _get_select(obs):
    s = _g(obs, "select")
    return s if (isinstance(s, dict) or s is not None) else None


def _get_options(select):
    for key in ("option", "options", "choices"):
        v = _g(select, key)
        if isinstance(v, tuple):
            v = list(v)
        if isinstance(v, list):
            return v
    return []


def _min_max(select, n):
    mx = _as_int(_g(select, "maxCount"), 1 if n else 0)
    mn = _as_int(_g(select, "minCount"), 0)
    mx = 0 if mx is None or mx < 0 else min(mx, n)
    mn = 0 if mn is None or mn < 0 else mn
    if mn > mx:
        mn = mx
    return mn, mx


def _fallback_action(n, mn, mx):
    if n <= 0 or mx <= 0:
        return []
    mx = min(mx, n)
    mn = max(0, min(mn, mx))
    if mx == 1:
        return [0]
    take = mn if mn > 0 else mx
    return list(range(min(take, n)))


def _validate(result, n, mn, mx):
    if n <= 0 or mx <= 0:
        return []
    if not isinstance(result, (list, tuple)):
        result = []
    seen, out = set(), []
    for it in result:
        idx = _as_int(it)
        if idx is not None and 0 <= idx < n and idx not in seen:
            seen.add(idx)
            out.append(idx)
    if len(out) > mx:
        out = out[:mx]
    if len(out) < mn:
        for idx in range(n):
            if len(out) >= mn:
                break
            if idx not in seen:
                seen.add(idx)
                out.append(idx)
    if not out and (mn > 0 or mx >= 1):
        return _fallback_action(n, mn, mx)
    return out


# ---------------------------------------------------------------------------
# Typed board reads (via _g; root is a decoded Observation or the raw dict).
# ---------------------------------------------------------------------------
def _players(root):
    cur = _g(root, "current")
    me = _as_int(_g(cur, "yourIndex"), 0)
    players = _g(cur, "players")
    if not isinstance(players, list) or me is None or not (0 <= me < len(players)):
        return None, None, None
    opp = players[1 - me] if len(players) == 2 else None
    return players[me], opp, me


def _active(pstate):
    a = _g(pstate, "active")
    if isinstance(a, list) and a:
        return a[0]
    return None


def _bench(pstate):
    b = _g(pstate, "bench")
    return b if isinstance(b, list) else []


def _prize_left(pstate):
    pr = _g(pstate, "prize")
    return len(pr) if isinstance(pr, list) else 6


def _energies(pkmn):
    e = _g(pkmn, "energies")
    out = []
    if isinstance(e, list):
        for x in e:
            v = _as_int(x)
            if v is not None:
                out.append(v)
    return out


def _card(cid):
    return _CARDS.get(cid) if cid is not None else None


def _is_ex(pkmn):
    c = _card(_as_int(_g(pkmn, "id")))
    return bool(_g(c, "ex") or _g(c, "megaEx")) if c else False


def _effective_damage(attack, attacker_id, defender_pkmn):
    """Weakness- and ex-aware damage estimate (ranking only, not a claim)."""
    if attack is None or defender_pkmn is None:
        return 0
    dmg = _as_int(_g(attack, "damage"), 0) or 0
    dc = _card(_as_int(_g(defender_pkmn, "id")))
    if dc is not None and _as_int(_g(dc, "weakness")) == LIGHTNING:
        dmg *= 2
    if _as_int(_g(attack, "attackId")) == ATK_HADRON_SPARK and _is_ex(defender_pkmn):
        dmg += 120  # Hadron Spark hits harder into ex; bias toward it
    return dmg


def _attacker_priority(cid):
    return {ID_MIRAIDON: 100, ID_PAWMOT: 80, ID_THUNDURUS: 70,
            ID_PAWMO: 40, ID_PAWMI: 35}.get(cid, 10)


def _resolve_card_id(opt, root, select):
    """Resolve a CARD-ish option to its underlying card id (best effort)."""
    area = _as_int(_g(opt, "area"))
    index = _as_int(_g(opt, "index"))
    pidx = _as_int(_g(opt, "playerIndex"))
    if index is None:
        return None
    try:
        if area == AR_DECK:
            deck = _g(select, "deck")
            if isinstance(deck, list) and 0 <= index < len(deck):
                return _as_int(_g(deck[index], "id"))
        if area == AR_HAND:
            mine, _opp, me = _players(root)
            hand = _g(mine, "hand")
            if isinstance(hand, list) and 0 <= index < len(hand):
                return _as_int(_g(hand[index], "id"))
        if area in (AR_ACTIVE, AR_BENCH):
            cur = _g(root, "current")
            players = _g(cur, "players")
            if isinstance(players, list) and pidx is not None and 0 <= pidx < len(players):
                seq = _active_or_bench(players[pidx], area)
                if isinstance(seq, list) and 0 <= index < len(seq):
                    return _as_int(_g(seq[index], "id"))
    except Exception:
        return None
    return None


def _active_or_bench(pstate, area):
    if area == AR_ACTIVE:
        a = _g(pstate, "active")
        return a if isinstance(a, list) else []
    return _bench(pstate)


def _resolve_target_pkmn(opt, root):
    """Resolve the in-play Pokemon an option points at (inPlay* or area/index)."""
    cur = _g(root, "current")
    players = _g(cur, "players")
    if not isinstance(players, list):
        return None
    area = _as_int(_g(opt, "inPlayArea"))
    index = _as_int(_g(opt, "inPlayIndex"))
    pidx = _as_int(_g(opt, "playerIndex"))
    if area is None:
        area = _as_int(_g(opt, "area"))
        index = _as_int(_g(opt, "index"))
    if pidx is None or not (0 <= pidx < len(players)) or index is None:
        return None
    seq = _active_or_bench(players[pidx], area) if area in (AR_ACTIVE, AR_BENCH) else None
    if isinstance(seq, list) and 0 <= index < len(seq):
        return seq[index]
    return None


# ---------------------------------------------------------------------------
# Context handlers — each returns a list[int] of indices, or None to defer.
# ---------------------------------------------------------------------------
def _yes_no_index(options, want_yes):
    yidx = nidx = None
    for i, o in enumerate(options):
        t = _as_int(_g(o, "type"))
        if t == OT_YES and yidx is None:
            yidx = i
        elif t == OT_NO and nidx is None:
            nidx = i
    if want_yes:
        return [yidx] if yidx is not None else ([nidx] if nidx is not None else [0])
    return [nidx] if nidx is not None else ([yidx] if yidx is not None else [0])


def _score_main(i, opt, root, select, mine, opp):
    t = _as_int(_g(opt, "type"))
    if t == OT_END:
        return -1000.0
    if t == OT_ATTACK:
        my_active = _active(mine)
        opp_active = _active(opp)
        atk = _ATTACKS.get(_as_int(_g(opt, "attackId")))
        my_id = _as_int(_g(my_active, "id"))
        if opp_active is None:
            return 500.0 + (_as_int(_g(atk, "damage"), 0) or 0)
        dmg = _effective_damage(atk, my_id, opp_active)
        cur_hp = _as_int(_g(opp_active, "hp"), 9999) or 9999
        if dmg >= cur_hp:  # lethal -> take the prize
            bonus = (6 - _prize_left(mine)) * 60
            if _is_ex(opp_active):
                bonus += 200
            return 10000.0 + bonus + dmg
        return 500.0 + dmg
    if t == OT_ABILITY:
        dc = _as_int(_g(mine, "deckCount"), 60) or 60
        return 900.0 if dc > _DECK_GUARD else 250.0
    if t == OT_ATTACH:
        tgt = _resolve_target_pkmn(opt, root)
        s = 800.0
        tid = _as_int(_g(tgt, "id"))
        if tid is not None and _as_int(_g(_card(tid), "energyType")) == LIGHTNING:
            s += 40.0
        my_active = _active(mine)
        if tgt is not None and my_active is not None and \
                _as_int(_g(tgt, "serial")) == _as_int(_g(my_active, "serial")):
            s += 60.0
        return s
    if t == OT_EVOLVE:
        return 760.0
    if t == OT_PLAY:
        cid = _resolve_card_id(opt, root, select)
        dc = _as_int(_g(mine, "deckCount"), 60) or 60
        hand_n = _as_int(_g(mine, "handCount"), 0) or 0
        if cid in (ID_MIRAIDON, ID_THUNDURUS, ID_PAWMI):
            return 720.0  # develop attackers to the board
        if cid == ID_BOSS:
            return 700.0 if _bench(opp) else 480.0
        if cid == ID_ULTRA_BALL:
            return 320.0 if (dc <= _DECK_GUARD or hand_n <= 2) else 660.0
        if cid in (ID_CHEREN, ID_POFFIN, ID_DAWN, ID_RARE_CANDY):
            return 300.0 if dc <= _DECK_GUARD else 650.0
        if cid == ID_LEVINCIA:
            return 540.0
        return 600.0
    if t == OT_RETREAT:
        my_active = _active(mine)
        my_id = _as_int(_g(my_active, "id"))
        ready_bench = any(_attacker_priority(_as_int(_g(p, "id"))) >= 70 and _energies(p)
                          for p in _bench(mine))
        weak_active = _attacker_priority(my_id) < 70 or not _energies(my_active)
        return 200.0 if (ready_bench and weak_active) else -1100.0
    return 100.0


def _decide(root, raw_obs):
    if _cg is None:
        return None
    select = _g(root, "select")
    if select is None:
        return None
    options = _get_options(select)
    n = len(options)
    if n == 0:
        return None
    mn, mx = _min_max(select, n)
    if mx <= 0:
        return None
    ctx = _as_int(_g(select, "context"))
    mine, opp, _me = _players(root)

    # YES / NO decisions
    if ctx == SC_IS_FIRST:
        return _yes_no_index(options, want_yes=True)
    if ctx == SC_COIN_HEAD:
        return _yes_no_index(options, want_yes=True)
    if ctx == SC_FIRST_EFFECT:
        return _yes_no_index(options, want_yes=True)
    if ctx == SC_ACTIVATE:
        dc = _as_int(_g(mine, "deckCount"), 60) or 60
        return _yes_no_index(options, want_yes=dc > _DECK_GUARD)
    if ctx == SC_MULLIGAN:
        hand = _g(mine, "hand")
        has_basic = False
        if isinstance(hand, list):
            for c in hand:
                cd = _card(_as_int(_g(c, "id")))
                if cd and _g(cd, "basic"):
                    has_basic = True
                    break
        return _yes_no_index(options, want_yes=not has_basic)

    # Promote / place attackers
    if ctx in (SC_SETUP_ACTIVE, SC_TO_ACTIVE, SC_SWITCH):
        scored = sorted(range(n), key=lambda i: -_attacker_priority(
            _resolve_card_id(options[i], root, select)))
        return [scored[0]]
    if ctx in (SC_SETUP_BENCH, SC_TO_BENCH, SC_TO_FIELD):
        scored = sorted(range(n), key=lambda i: -_attacker_priority(
            _resolve_card_id(options[i], root, select)))
        take = mx if mx > 0 else 1
        return sorted(scored[:take]) if take else []

    # Search-to-hand priority
    if ctx == SC_TO_HAND:
        in_play_ids = set()
        for p in [_active(mine)] + _bench(mine):
            pid = _as_int(_g(p, "id"))
            if pid is not None:
                in_play_ids.add(pid)
        miraidon_out = ID_MIRAIDON in in_play_ids
        evo_base_ok = bool({ID_PAWMI, ID_PAWMO} & in_play_ids) or True

        def sval(i):
            cid = _resolve_card_id(options[i], root, select)
            if cid == ID_MIRAIDON:
                return 40 if miraidon_out else 100
            if cid == ID_BASIC_L:
                return 70
            if cid == ID_THUNDURUS:
                return 60
            if cid == ID_PAWMI:
                return 55
            if cid == ID_PAWMOT:
                return 45 if evo_base_ok else 5
            return 30
        scored = sorted(range(n), key=lambda i: -sval(i))
        take = mn if mn > 0 else 1
        take = min(take, mx) if mx else take
        return sorted(scored[:take]) if take else []

    # Forced discard: shed least useful, protect attackers + energy
    if ctx == SC_DISCARD:
        def keep(i):
            cid = _resolve_card_id(options[i], root, select)
            if cid in (ID_MIRAIDON, ID_PAWMOT, ID_THUNDURUS):
                return 100
            if cid in (ID_PAWMI, ID_PAWMO, ID_RARE_CANDY):
                return 70
            if cid in (ID_BOSS, ID_LEVINCIA):
                return 60
            if cid in (ID_CHEREN, ID_POFFIN, ID_DAWN, ID_ULTRA_BALL):
                return 45
            if cid == ID_BASIC_L:
                return 30
            return 40
        need = mn if mn > 0 else (1 if mx else 0)
        if need <= 0:
            return [] if mn == 0 else None
        order = sorted(range(n), key=lambda i: (keep(i), i))
        return sorted(order[:min(need, mx)])

    # Damage placement: convert a target into a KO when possible
    if ctx in (SC_DAMAGE, SC_DAMAGE_COUNTER, SC_DAMAGE_COUNTER_ANY):
        def hp_of(i):
            tp = _resolve_target_pkmn(options[i], root)
            return _as_int(_g(tp, "hp"), 9999) or 9999
        scored = sorted(range(n), key=lambda i: hp_of(i))
        take = mn if mn > 0 else 1
        return sorted(scored[:min(take, mx)]) if mx else []

    # Heal / remove damage from our most-hurt valuable attacker
    if ctx in (SC_HEAL, SC_REMOVE_DAMAGE_COUNTER):
        def hurt(i):
            tp = _resolve_target_pkmn(options[i], root)
            mh = _as_int(_g(tp, "maxHp"), 0) or 0
            hp = _as_int(_g(tp, "hp"), 0) or 0
            return -(mh - hp)
        scored = sorted(range(n), key=lambda i: hurt(i))
        take = mn if mn > 0 else 1
        return sorted(scored[:min(take, mx)]) if mx else []

    # Count selections: draw the max safe number; max beneficial otherwise
    if ctx in (SC_DRAW_COUNT, SC_DAMAGE_COUNTER_COUNT, SC_REMOVE_DAMAGE_COUNTER_COUNT):
        def num(i):
            return _as_int(_g(options[i], "number"), 0) or 0
        if ctx == SC_DRAW_COUNT:
            dc = _as_int(_g(mine, "deckCount"), 60) or 60
            safe = [i for i in range(n) if num(i) <= max(0, dc - 1)]
            pool = safe or list(range(n))
            return [max(pool, key=num)]
        return [max(range(n), key=num)]

    # Main phase: tiered typed scoring
    if ctx == SC_MAIN or ctx is None:
        scores = [(_score_main(i, options[i], root, select, mine, opp), i)
                  for i in range(n)]
        scores.sort(key=lambda x: (-x[0], x[1]))
        if mx == 1:
            return [scores[0][1]]
        chosen = [idx for sc, idx in scores if sc > 0][:mx]
        if len(chosen) < mn:
            for sc, idx in scores:
                if len(chosen) >= mn:
                    break
                if idx not in chosen:
                    chosen.append(idx)
        return sorted(chosen) if chosen else [scores[0][1]]

    return None  # unhandled context -> generic fallback


# ---------------------------------------------------------------------------
# Entrypoint.
# ---------------------------------------------------------------------------
def agent(obs_dict):
    """Kaggle/cg entrypoint. Always returns list[int] of legal indices."""
    # 0. Deck-submission step (select present but null) -> return 60 card ids.
    try:
        if isinstance(obs_dict, dict) and "select" in obs_dict and obs_dict["select"] is None:
            deck = _load_deck_ids()
            if len(deck) == 60:
                return deck
    except Exception:
        pass

    select = _get_select(obs_dict)
    options = _get_options(select)
    n = len(options)
    mn, mx = _min_max(select, n)
    if n == 0 or mx <= 0:
        return []

    # 1. Typed decision (decode to cg dataclasses; fall back to raw dict view).
    try:
        root = None
        if _cg is not None:
            try:
                root = _cg.to_observation_class(obs_dict)
            except Exception:
                root = None
        decision = _decide(root if root is not None else obs_dict, obs_dict)
    except Exception:
        decision = None
    if decision:
        return _validate(decision, n, mn, mx)

    # 2. Generic legal fallback: prefer an action over ending the turn.
    try:
        if mx == 1:
            for i, o in enumerate(options):
                if _as_int(_g(o, "type")) != OT_END:
                    return [i]
            return [0]
    except Exception:
        pass
    return _validate(_fallback_action(n, mn, mx), n, mn, mx)


if __name__ == "__main__":
    demo = {"logs": [], "current": None,
            "select": {"option": [{"type": 13, "attackId": 1377},
                                  {"type": 14}], "maxCount": 1, "minCount": 0}}
    print("demo:", agent(demo))
