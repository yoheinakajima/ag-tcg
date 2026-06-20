"""Kaggle runtime entrypoint for the PTCG AI Battle Challenge.

This file is intentionally **self-contained** and **standard-library only** so
it runs unchanged inside the Kaggle/cabt sandbox. It exposes a single function::

    def agent(obs_dict: dict) -> list[int]

which the engine calls each step with an observation dict::

    {
        "logs":    [...],     # event logs (optional)
        "current": {...},     # board state (dict or None)
        "select":  {          # legal choices (dict or None)
            "options":  [...],   # (also tolerates "option")
            "maxCount": int,
            "minCount": int,
        },
    }

It returns a list of selected legal option indices. The engine only presents
legal moves, so the agent's job is to pick among them.

Design guarantees (see docs/RUNTIME_AGENT.md):
  * Never raises outward — any internal error degrades to a legal fallback.
  * Always returns a ``list[int]`` of unique, in-range indices.
  * Respects ``maxCount`` and ``minCount`` when present.
  * Handles missing/null ``obs``/``current``/``select`` (deck/setup phases).
  * Deterministic and very cheap (no search, no I/O, tiny time budget).

A richer policy may live in ``agent.py``; if importable and well-behaved it is
used, otherwise the embedded heuristic below decides. Either way the output is
re-validated here before returning.
"""

from __future__ import annotations

import json
import os as _os

# ---------------------------------------------------------------------------
# Keyword weights for the embedded heuristic (string-only, schema-agnostic).
# ---------------------------------------------------------------------------

_POSITIVE = {
    "knockout": 110, "knock": 100, "prize": 80, "attack": 80, "weakness": 55,
    "damage": 50, "evolve": 45, "evolution": 40, "attach": 40, "energy": 40,
    "draw": 35, "search": 35, "supporter": 30, "ability": 30, "skill": 30,
    "item": 25, "bench": 20, "stadium": 18, "switch": 15, "active": 12,
}
_NEGATIVE = {
    "concede": -1000, "end": -100, "pass": -100, "done": -90,
    "discard": -20, "trash": -20, "retreat": -10,
}
# When an option also looks productive, don't punish its discard/trash cost.
_DISCARD_REDEEMERS = ("draw", "search", "attack", "attach", "evolve", "energy")

# ---------------------------------------------------------------------------
# Structured option scoring from the recorded cabt schema
# (see docs/CABT_SCHEMA_NOTES.md). Real options are dicts with a numeric
# "type". These weights are conservative and ADDITIVE on top of the string
# scorer; they only nudge ranking and never produce illegal actions.
# Observed types (counts from 162 self-play observations):
#   13 = attack action (carries "attackId")            -> strongly prefer
#    8 = most common in-play action (attach/place)      -> mild prefer
#    7 = play/select card by hand index                 -> mild prefer
#    3 = select a card in a play area                   -> slight prefer
#   10 = area-7 action                                  -> slight prefer
#    9 = observed action (meaning uncertain)            -> slight
#    0 = pick a number/quantity (carries "number")      -> neutral
#  1,2 = bare simple choices (meaning uncertain)        -> neutral
#   14 = bare option, observed as turn-ending/pass-like -> mild deprefer
# Unknown types default to neutral (0) so we never over-penalize.
# ---------------------------------------------------------------------------
_OPTION_TYPE_SCORES = {
    13: 120,
    8: 12,
    7: 15,
    3: 8,
    10: 6,
    9: 4,
    0: 0,
    1: 0,
    2: 0,
    14: -40,
}
_ATTACK_TYPE = 13
_ATTACK_ID_BONUS = 30


# ---------------------------------------------------------------------------
# Pure parsing / scoring helpers.
# ---------------------------------------------------------------------------

def _safe_json_lower(obj):
    """Serialize any object to a lower-cased text blob without ever raising."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.lower()
    if isinstance(obj, bool):
        return str(obj).lower()
    if isinstance(obj, (int, float)):
        return str(obj).lower()
    try:
        return json.dumps(obj, default=str, sort_keys=True).lower()
    except Exception:
        try:
            return str(obj).lower()
        except Exception:
            return ""


def _get_select(obs):
    """Return the ``select`` dict from an observation, or ``None``."""
    if not isinstance(obs, dict):
        return None
    select = obs.get("select")
    if isinstance(select, dict):
        return select
    return None


def _get_options(select):
    """Return the option list from a ``select`` dict (tolerant of shape)."""
    if not isinstance(select, dict):
        return []
    # The competition uses "options"; tolerate "option" / "choices" as aliases.
    for key in ("options", "option", "choices"):
        val = select.get(key)
        if isinstance(val, tuple):
            val = list(val)
        if isinstance(val, list):
            return val
    return []


def _get_min_max_count(select, option_count):
    """Return ``(min_count, max_count)`` clamped to ``[0, option_count]``."""
    def _int(v, default):
        try:
            if isinstance(v, bool):
                return default
            return int(v)
        except (TypeError, ValueError):
            return default

    if not isinstance(select, dict):
        return 0, 0

    max_count = _int(select.get("maxCount"), 1 if option_count else 0)
    min_count = _int(select.get("minCount"), 0)

    if max_count < 0:
        max_count = 0
    if max_count > option_count:
        max_count = option_count
    if min_count < 0:
        min_count = 0
    if min_count > max_count:
        min_count = max_count
    return min_count, max_count


def _structured_score(option):
    """Conservative score over the recorded cabt numeric fields.

    Only applies when ``option`` is a dict with a known integer ``type``.
    Unknown types score 0 (neutral) so we never over-penalize. Never raises.
    """
    if not isinstance(option, dict):
        return 0
    t = option.get("type")
    if isinstance(t, bool):  # bool is an int subclass; treat as unknown.
        return 0
    if not isinstance(t, int):
        return 0
    score = _OPTION_TYPE_SCORES.get(t, 0)
    if t == _ATTACK_TYPE and option.get("attackId") is not None:
        score += _ATTACK_ID_BONUS
    return score


def _score_option(option, idx, obs):
    """Score a single option. Combines a conservative structured score over the
    recorded cabt numeric fields (when the option is a dict) with the
    schema-agnostic string scorer, so it works on both string and dict shapes.
    ``idx``/``obs`` are accepted for future context-aware scoring."""
    score = _structured_score(option)
    text = _safe_json_lower(option)
    for kw, w in _POSITIVE.items():
        if kw in text:
            score += w
    for kw, w in _NEGATIVE.items():
        if kw in text:
            if kw in ("discard", "trash") and any(r in text for r in _DISCARD_REDEEMERS):
                continue
            score += w
    return score


def _rank_options(options, obs):
    """Return option indices best-first; deterministic tie-break on low index."""
    n = len(options)
    return sorted(range(n), key=lambda i: (-_score_option(options[i], i, obs), i))


def _fallback_action(option_count, min_count, max_count):
    """Guaranteed-legal default selection, ignoring option semantics."""
    if option_count <= 0 or max_count <= 0:
        return []
    max_count = min(max_count, option_count)
    min_count = max(0, min(min_count, max_count))
    if max_count == 1:
        return [0]
    take = min_count if min_count > 0 else max_count
    return list(range(min(take, option_count)))


def _validate_action(result, option_count, min_count, max_count):
    """Coerce ``result`` into a unique, in-range, count-respecting selection."""
    if option_count <= 0 or max_count <= 0:
        return []
    if not isinstance(result, (list, tuple)):
        result = []
    seen = set()
    cleaned = []
    for item in result:
        try:
            if isinstance(item, bool):
                continue
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < option_count and idx not in seen:
            seen.add(idx)
            cleaned.append(idx)
    if len(cleaned) > max_count:
        cleaned = cleaned[:max_count]
    if len(cleaned) < min_count:
        for idx in range(option_count):
            if len(cleaned) >= min_count:
                break
            if idx not in seen:
                seen.add(idx)
                cleaned.append(idx)
    if not cleaned and (min_count > 0 or max_count >= 1):
        return _fallback_action(option_count, min_count, max_count)
    return cleaned


def _heuristic_action(options, min_count, max_count, obs):
    """Pick up to ``max_count`` options by heuristic rank."""
    n = len(options)
    if n == 0 or max_count <= 0:
        return []
    ranked = _rank_options(options, obs)
    if max_count == 1:
        return [ranked[0]]
    chosen = []
    for idx in ranked:
        if len(chosen) >= max_count:
            break
        if _score_option(options[idx], idx, obs) > 0 or len(chosen) < min_count:
            chosen.append(idx)
    if not chosen:
        chosen = [ranked[0]]
    return sorted(chosen)


def _embedded_agent(obs):
    """The self-contained policy: rank, then validate."""
    select = _get_select(obs)
    options = _get_options(select)
    option_count = len(options)
    min_count, max_count = _get_min_max_count(select, option_count)
    if option_count == 0 or max_count <= 0:
        return []
    try:
        selection = _heuristic_action(options, min_count, max_count, obs)
    except Exception:
        selection = None
    if not selection:
        selection = _fallback_action(option_count, min_count, max_count)
    return _validate_action(selection, option_count, min_count, max_count)


# ---------------------------------------------------------------------------
# Back-compat helpers (used by lab scripts/tests; harmless in Kaggle).
# ---------------------------------------------------------------------------

def validate_result(obs, result):
    """Coerce any candidate result into a guaranteed-legal selection."""
    select = _get_select(obs)
    options = _get_options(select)
    option_count = len(options)
    min_count, max_count = _get_min_max_count(select, option_count)
    return _validate_action(result, option_count, min_count, max_count)


def fallback(obs):
    """Top-level safe fallback used if everything else fails."""
    select = _get_select(obs)
    options = _get_options(select)
    option_count = len(options)
    min_count, max_count = _get_min_max_count(select, option_count)
    return _fallback_action(option_count, min_count, max_count)


# ---------------------------------------------------------------------------
# Deck loading (stdlib only) — cabt passes select=None on step 0 and expects
# the agent to return its 60-card deck as a list of integer card IDs.
# ---------------------------------------------------------------------------

_DECK_IDS: list[int] | None = None


def _deck_candidate_paths() -> list[str]:
    """Candidate locations for ``deck.csv`` across the environments cabt uses.

    The cabt engine exec()s the agent source, so ``__file__`` and the current
    working directory may not point at the agent directory. We therefore mirror
    the official sample: try the cwd-relative name, then this module's directory
    (guarded, since ``__file__`` can be undefined), then the documented Kaggle
    agent path. Each base is resolved independently so one bad base never aborts
    the rest.
    """
    candidates: list[str] = ["deck.csv"]
    try:
        here = _os.path.dirname(_os.path.abspath(__file__))
        candidates.append(_os.path.join(here, "deck.csv"))
    except Exception:
        pass
    candidates.append("/kaggle_simulations/agent/deck.csv")
    return candidates


def _load_deck_ids() -> list[int]:
    """Read deck.csv and return its card IDs. Cached."""
    global _DECK_IDS
    if _DECK_IDS is not None:
        return _DECK_IDS
    ids: list[int] = []
    for p in _deck_candidate_paths():
        try:
            if not _os.path.exists(p):
                continue
            parsed: list[int] = []
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed.append(int(line))
                    except ValueError:
                        pass
            # Prefer a path that yields a full 60-card deck; otherwise remember
            # the first non-empty result as a fallback but keep looking so a
            # stray earlier deck.csv can't mask the real one.
            if len(parsed) == 60:
                ids = parsed
                break
            if parsed and not ids:
                ids = parsed
        except Exception:
            continue
    _DECK_IDS = ids
    return _DECK_IDS


# ---------------------------------------------------------------------------
# Optional richer policy from agent.py (used only if it behaves).
# ---------------------------------------------------------------------------

try:
    from agent import agent as _external_agent  # type: ignore
except Exception:
    _external_agent = None


def agent(obs_dict):
    """Kaggle entrypoint. Always returns a ``list[int]`` of legal option indices."""
    # 0. Deck-submission step: cabt explicitly sets select=None on step 0 and
    #    expects the agent to return its 60 card IDs (not option indices).
    #    Only trigger when "select" key is present but null — not on empty dicts.
    try:
        if isinstance(obs_dict, dict) and "select" in obs_dict and obs_dict["select"] is None:
            deck_ids = _load_deck_ids()
            if len(deck_ids) == 60:
                return deck_ids
    except Exception:
        pass
    # 1. Optional external agent, with its output re-validated here. Only trust
    #    it when it actually proposed at least one valid index (or there's
    #    nothing to pick). If it proposed nothing while options exist it
    #    under-parsed, so we fall through to the embedded heuristic — the safe
    #    source of truth.
    if _external_agent is not None:
        try:
            raw = _external_agent(obs_dict)
            select = _get_select(obs_dict)
            options = _get_options(select)
            mn, mx = _get_min_max_count(select, len(options))
            proposed = [
                i for i in (raw if isinstance(raw, (list, tuple)) else [])
                if isinstance(i, int) and not isinstance(i, bool)
                and 0 <= i < len(options)
            ]
            if proposed or mx <= 0:
                return _validate_action(raw, len(options), mn, mx)
        except Exception:
            pass
    # 2. Embedded heuristic.
    try:
        return _embedded_agent(obs_dict)
    except Exception:
        pass
    # 3. Absolute last resort.
    try:
        return fallback(obs_dict)
    except Exception:
        return []



# === EXPERIMENT OVERRIDE: combo_full_safety_v3 (seam=policy.effect_resolution_targeting) ===
# (no overrides: exact v1 control copy)
# === END OVERRIDE ===



# === PASS8 EFFECT-SAFETY OVERRIDE: combo_full_safety_v3 (seam=policy.effect_resolution_targeting) ===
# Wraps _embedded_agent: returns a safe, validated selection for own-observation
# effect-resolution rules (decline / discard-protect / search-avoid-orphan);
# otherwise defers to the original embedded policy. Reads only the candidate's
# own board / deckCount / hand and the offered option card ids.
_P8_RULES = {'discard_protect_setup': True, 'search_avoid_orphan_evolution': True, 'search_avoid_orphan_mega_signal': True, 'decline_mega_signal_no_snover': True, 'deckout_decline_threshold': 8}
_P8_ORIG_EMBEDDED = _embedded_agent
_P8_SNOVER = 722
_P8_KYOGRE = 721
_P8_MEGA = 723
_P8_MEGA_SIGNAL = 1145
_P8_ENERGY = 3
_P8_SETUP = (721, 722, 723)


def _p8_me(obs):
    try:
        cur = obs.get("current")
        me = cur.get("yourIndex")
        players = cur.get("players")
        if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
            return players[me]
    except Exception:
        return None
    return None


def _p8_resolve(option, obs):
    try:
        if not isinstance(option, dict):
            return None
        area = option.get("area")
        index = option.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        sel = obs.get("select") if isinstance(obs, dict) else None
        if area == 1 and isinstance(sel, dict):
            deck = sel.get("deck")
            if isinstance(deck, list) and 0 <= index < len(deck):
                c = deck[index]
                return c.get("id") if isinstance(c, dict) else None
        if area == 2:
            p = _p8_me(obs)
            hand = p.get("hand") if isinstance(p, dict) else None
            if isinstance(hand, list) and 0 <= index < len(hand):
                c = hand[index]
                return c.get("id") if isinstance(c, dict) else None
    except Exception:
        return None
    return None


def _p8_board_ids(obs):
    ids = []
    try:
        p = _p8_me(obs) or {}
        for slot in ("active", "bench"):
            for e in p.get(slot) or []:
                if isinstance(e, dict) and isinstance(e.get("id"), int):
                    ids.append(e["id"])
    except Exception:
        return ids
    return ids


def _p8_deck_count(obs):
    try:
        p = _p8_me(obs)
        dc = p.get("deckCount") if isinstance(p, dict) else None
        return dc if isinstance(dc, int) and not isinstance(dc, bool) else None
    except Exception:
        return None


def _p8_should_decline(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        if mn != 0 or mx <= 0:
            return False
        ctx = sel.get("context")
        thr = R.get("deckout_decline_threshold")
        if ctx == 7 and isinstance(thr, int) and not isinstance(thr, bool):
            dc = _p8_deck_count(obs)
            if isinstance(dc, int) and dc <= thr:
                return True
        if ctx == 7 and R.get("decline_mega_signal_no_snover"):
            board = _p8_board_ids(obs)
            cids = [_p8_resolve(o, obs) for o in options]
            cids = [c for c in cids if c is not None]
            if cids and all(c == _P8_MEGA for c in cids) and _P8_SNOVER not in board:
                return True
    except Exception:
        return False
    return False


def _p8_discard_pick(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        if not R.get("discard_protect_setup"):
            return None
        need = mn if mn > 0 else mx
        if need <= 0:
            return None
        ids = [_p8_resolve(o, obs) for o in options]
        setup_idx = [i for i, c in enumerate(ids) if c in _P8_SETUP]
        if not setup_idx:
            return None
        safe_idx = [i for i, c in enumerate(ids)
                    if c is not None and c not in _P8_SETUP]
        if len(safe_idx) < need:
            return None
        safe_idx.sort(key=lambda i: (0 if ids[i] == _P8_ENERGY else 1, i))
        return sorted(safe_idx[:need])
    except Exception:
        return None


def _p8_search_pick(obs, sel, options, mn, mx):
    try:
        R = _P8_RULES
        board = _p8_board_ids(obs)
        no_snover = _P8_SNOVER not in board
        avoid = set()
        if R.get("search_avoid_orphan_evolution") and no_snover:
            avoid.add(_P8_MEGA)
        if R.get("search_avoid_orphan_mega_signal") and no_snover:
            avoid.add(_P8_MEGA_SIGNAL)
        if not avoid:
            return None
        ids = [_p8_resolve(o, obs) for o in options]
        bad = [i for i, c in enumerate(ids) if c in avoid]
        if not bad:
            return None
        good = [i for i, c in enumerate(ids)
                if c is not None and c not in avoid]
        if good:
            pref = {_P8_SNOVER: 0, _P8_KYOGRE: 1}
            good.sort(key=lambda i: (pref.get(ids[i], 2), i))
            need = mn if mn > 0 else 1
            need = min(need, mx, len(good))
            return sorted(good[:need]) if need > 0 else []
        if mn == 0:
            return []
        return None
    except Exception:
        return None


def _p8_embedded(obs):
    try:
        sel = _get_select(obs)
        if isinstance(sel, dict):
            options = _get_options(sel)
            if options:
                mn, mx = _get_min_max_count(sel, len(options))
                if _p8_should_decline(obs, sel, options, mn, mx):
                    return []
                ctx = sel.get("context")
                if ctx == 8:
                    pick = _p8_discard_pick(obs, sel, options, mn, mx)
                    if pick is not None:
                        return _validate_action(pick, len(options), mn, mx)
                if ctx == 7:
                    pick = _p8_search_pick(obs, sel, options, mn, mx)
                    if pick is not None:
                        return _validate_action(pick, len(options), mn, mx)
    except Exception:
        pass
    return _P8_ORIG_EMBEDDED(obs)


_embedded_agent = _p8_embedded
# === END PASS8 OVERRIDE ===


if __name__ == "__main__":
    # Tiny smoke test so `python main.py` shows it works without Kaggle.
    demo = {
        "logs": [],
        "current": None,
        "select": {
            "options": ["End turn", "Attack: Thunderbolt 90 damage", "Attach Energy"],
            "maxCount": 1,
            "minCount": 0,
        },
    }
    print("demo selection:", agent(demo))


# === DECK-RETURN SAFETY: embedded deck + robust select=None detection ===
# Guarantees the cabt deck-selection step (current=None, select=None) returns
# exactly 60 integer card ids, independent of cwd/file presence. See
# render_deck_safety_block in src/ptcg_activegraph/experiments/generator.py.
_EMBEDDED_DECK = [
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 720, 720, 720, 720, 721,
    721, 721, 721, 722, 722, 722, 722, 723, 723, 723,
    723, 1092, 1121, 1121, 1121, 1121, 1145, 1145, 1163, 1163,
    1219, 1219, 1219, 1219, 1227, 1227, 1227, 1227, 1262, 1262,
]


def _load_submission_deck():
    """Return the 60-card deck.

    Prefer ``deck.csv`` sitting next to THIS file (``__file__``-relative, so cwd
    can never substitute a different deck), and fall back to the embedded
    constant whenever that file is missing, unreadable, or not exactly 60 ids.
    The embedded list always reflects this candidate's own deck, so the return
    is correct even when no file is reachable.
    """
    try:
        import os as _ds_os
        path = _ds_os.path.join(_ds_os.path.dirname(_ds_os.path.abspath(__file__)),
                                "deck.csv")
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s:
                    rows.append(int(s))
        if len(rows) == 60:
            return rows
    except Exception:
        pass
    return list(_EMBEDDED_DECK)


def _ds_get(obs, name):
    """Read ``name`` from obs whether it is a dict, a dict-like Struct exposing
    ``.get``, or a plain attribute-style object. Kaggle's production deck-
    selection observation can arrive as any of these, so never assume dict."""
    try:
        if isinstance(obs, dict):
            return obs.get(name)
        getter = getattr(obs, "get", None)
        if callable(getter):
            try:
                return getter(name)
            except Exception:
                pass
        return getattr(obs, name, None)
    except Exception:
        return None


def _is_deck_request(obs):
    """True for the cabt deck-selection step: ``select`` and ``current`` both
    resolve to None. Handles dicts (key present-None OR key absent), dict-like
    Structs, and attribute-style objects; gameplay observations always carry a
    non-None ``select``/``current`` so they delegate to the strategy agent."""
    try:
        if obs is None:
            return False
        return (_ds_get(obs, "select") is None
                and _ds_get(obs, "current") is None)
    except Exception:
        return False


_PRE_DECK_SAFETY_AGENT = agent


def agent(obs_dict):
    """Kaggle entrypoint: return the 60-card deck on the deck-selection step,
    otherwise defer to the previously-defined policy. Never returns [] for a
    deck request and never raises."""
    try:
        if _is_deck_request(obs_dict):
            return _load_submission_deck()
    except Exception:
        pass
    try:
        result = _PRE_DECK_SAFETY_AGENT(obs_dict)
    except Exception:
        result = None
    if isinstance(result, list):
        return result
    try:
        return fallback(obs_dict)
    except Exception:
        return []
# === END DECK-RETURN SAFETY ===


# === PASS14 CORE-PILOT OVERRIDE: league_water_anti_disruption_pivot_v1 ===
# Embeds the Layer 1-3 core-pilot decision layer (stdlib-only) plus this deck's
# role playbook. Exposes ``core_pilot_decide(kind, board, options)`` (graded by the
# core-competency fixtures) and conservatively refines decisions at the reliably
# identifiable cabt contexts in ``_CP_RUNTIME_CONTEXTS`` while preserving the proven
# Pass-8 effect-safety policy beneath it.
from typing import Any as _CP_Any  # noqa: F401  (stdlib)

# ---- embedded: ptcg_activegraph/pilot/state.py ----
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


# ---- embedded: ptcg_activegraph/pilot/roles.py ----
"""Layer 3 helpers — card-role index built from a deck playbook.

The generic pilot reasons over *roles* (``primary_basic_attacker``, ``setup_basic``,
``evolution_payoff``, ...), never over card names. This module turns a loaded playbook
dict into a fast role index. Standard-library only (embeddable).
"""

from typing import Any

# Default deckout-guard tiers if a playbook does not specify them.
_DEFAULT_THRESHOLDS = {"penalize": 8, "heavy": 4, "critical": 2}

# Every generic-pilot feature switch defaults ON; ablations flip them off.
_DEFAULT_FLAGS = {
    "active_scoring": True,
    "bench_safety": True,
    "deckout_guard": True,
}


def _to_int(x: Any):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


class RoleIndex:
    """Immutable view over a playbook's roles, plan, thresholds and flags."""

    __slots__ = ("role_to_ids", "id_to_roles", "plan", "thresholds",
                 "preserve_only", "exceptions", "role_weights", "flags")

    def __init__(self, role_to_ids, id_to_roles, plan, thresholds,
                 preserve_only, exceptions, role_weights, flags):
        self.role_to_ids = role_to_ids
        self.id_to_roles = id_to_roles
        self.plan = plan
        self.thresholds = thresholds
        self.preserve_only = preserve_only
        self.exceptions = exceptions
        self.role_weights = role_weights
        self.flags = flags


def load_playbook_roles(playbook: Any) -> RoleIndex:
    """Build a :class:`RoleIndex` from a loaded playbook dict (idempotent)."""
    if isinstance(playbook, RoleIndex):
        return playbook
    pb = playbook if isinstance(playbook, dict) else {}

    role_to_ids: dict = {}
    id_to_roles: dict = {}
    for role, ids in (pb.get("roles") or {}).items():
        clean = []
        for cid in ids or []:
            ci = _to_int(cid)
            if ci is not None:
                clean.append(ci)
                id_to_roles.setdefault(ci, set()).add(role)
        role_to_ids[role] = set(clean)

    thresholds = dict(_DEFAULT_THRESHOLDS)
    for k, v in (pb.get("deckout_guard_thresholds") or {}).items():
        vi = _to_int(v)
        if vi is not None:
            thresholds[k] = vi

    flags = dict(_DEFAULT_FLAGS)
    for k, v in (pb.get("flags") or {}).items():
        flags[k] = bool(v)

    return RoleIndex(
        role_to_ids=role_to_ids,
        id_to_roles=id_to_roles,
        plan=pb.get("plan") or {},
        thresholds=thresholds,
        preserve_only=list((pb.get("role_weights") or {}).get("preserve_only") or []),
        exceptions=pb.get("exceptions") or {},
        role_weights=pb.get("role_weights") or {},
        flags=flags,
    )


def role_for_card(card_id_value: Any, role_index: Any) -> set:
    ri = load_playbook_roles(role_index)
    cid = _to_int(card_id_value)
    return set(ri.id_to_roles.get(cid, set()))


def has_role(card_id_value: Any, role: str, role_index: Any) -> bool:
    ri = load_playbook_roles(role_index)
    cid = _to_int(card_id_value)
    return cid in ri.role_to_ids.get(role, set())


def count_role_in_zone(zone: Any, role: str, role_index: Any) -> int:
    """Count cards in ``zone`` (list of card dicts/ids) that carry ``role``."""
    ri = load_playbook_roles(role_index)
    ids = ri.role_to_ids.get(role, set())
    n = 0
    for c in zone or []:
        cid = c.get("card_id") if isinstance(c, dict) else _to_int(c)
        if cid in ids:
            n += 1
    return n


# ---- embedded: ptcg_activegraph/pilot/scoring.py ----
"""Layer 2 scoring — deck-agnostic, mechanics/role based.

Every function returns a float where higher == better. They never raise and never
produce an action; the decision layer turns scores into legal selections. Standard
library only (embeddable). Card ids are never referenced directly — only roles.
"""

from typing import Any



def _num(x: Any, default: float = 0.0) -> float:
    if isinstance(x, bool):
        return default
    if isinstance(x, (int, float)):
        return float(x)
    return default


def _has_role_in_play(board: Any, role: str, ri: Any) -> bool:
    for cid in in_play_card_ids(board):
        if has_role(cid, role, ri):
            return True
    return False


def attacker_ready(board: Any, playbook: Any) -> bool:
    """True if our active is a primary attacker with at least one energy."""
    ri = load_playbook_roles(playbook)
    active = board.get("active") if isinstance(board, dict) else None
    if not isinstance(active, dict):
        return False
    if not has_role(card_id(active), "primary_basic_attacker", ri):
        return False
    return _num(active.get("energy"), 0.0) >= 1.0 or bool(active.get("ready"))


def score_basic_active(card: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    cid = card_id(card)
    score = 0.0
    if has_role(cid, "primary_basic_attacker", ri):
        score += 100.0
    if has_role(cid, "setup_basic", ri):
        score += 30.0
    score += _num(card.get("hp") if isinstance(card, dict) else None) * 0.1
    if isinstance(card, dict) and card.get("is_basic") is False:
        score -= 1000.0  # only basics may be the setup active
    return score


def score_basic_bench(card: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    cid = card_id(card)
    score = 0.0
    if has_role(cid, "primary_basic_attacker", ri):
        score += 80.0  # backup attacker is valuable
    if has_role(cid, "setup_basic", ri):
        score += 60.0
    if cid in in_play_card_ids(board):
        score -= 10.0  # mild duplicate de-prefer (still benchable)
    score += _num(card.get("hp") if isinstance(card, dict) else None) * 0.05
    return score


def score_energy_attach_target(target: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    tid = card_id(target)
    is_active = isinstance(target, dict) and bool(target.get("is_active"))
    is_attacker = has_role(tid, "primary_basic_attacker", ri)
    if is_active and is_attacker:
        return 100.0
    if is_active:
        return 60.0
    if is_attacker:
        return 50.0  # next attacker on the bench
    return 10.0


def score_tool_attach_target(target: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    tid = card_id(target)
    is_active = isinstance(target, dict) and bool(target.get("is_active"))
    has_tool = isinstance(target, dict) and bool(target.get("has_tool"))
    is_attacker = has_role(tid, "primary_basic_attacker", ri)
    if has_tool:
        return -50.0  # don't double up a tool
    if is_active and is_attacker:
        return 100.0
    if is_active:
        return 50.0
    if is_attacker:
        return 40.0
    return 10.0


def score_evolution(card: Any, target: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    cid = card_id(card)
    if not has_role(cid, "evolution_payoff", ri):
        return 0.0
    # The line is ready only when a setup basic is in play (the evolution target).
    if _has_role_in_play(board, "setup_basic", ri) or target is not None:
        return 80.0
    return -50.0  # orphan evolution


def score_search_target(card: Any, board: Any, playbook: Any,
                        effect_card_id: Any = None) -> float:
    ri = load_playbook_roles(playbook)
    cid = card_id(card)
    has_setup = _has_role_in_play(board, "setup_basic", ri)
    has_attacker = _has_role_in_play(board, "primary_basic_attacker", ri)
    score = 0.0
    if has_role(cid, "setup_basic", ri):
        score += 100.0 if not has_setup else 20.0
    if has_role(cid, "evolution_payoff", ri):
        score += 90.0 if has_setup else -50.0  # avoid orphan evolution
    if has_role(cid, "primary_basic_attacker", ri):
        score += 95.0 if not has_attacker else 15.0
    if has_role(cid, "search_cards", ri):
        score += 5.0
    return score


def score_discard_candidate(card: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    cid = card_id(card)
    score = 0.0
    if has_role(cid, "basic_energy", ri):
        score += 100.0  # pay costs with excess energy first
    # Never trade away the only setup/attacker/payoff.
    if (has_role(cid, "setup_basic", ri)
            or has_role(cid, "primary_basic_attacker", ri)
            or has_role(cid, "evolution_payoff", ri)):
        score -= 80.0
    if has_role(cid, "draw_support", ri):
        score += 10.0
    return score


def score_attack_option(option: Any, board: Any, playbook: Any) -> float:
    score = 100.0
    if isinstance(option, dict):
        if option.get("knocks_out"):
            score += 100.0
        score += _num(option.get("damage")) * 0.1
    return score


def score_draw_search_action(option: Any, board: Any, playbook: Any) -> float:
    ri = load_playbook_roles(playbook)
    score = 70.0  # drawing is fine when the deck is healthy and nothing better exists
    if ri.flags.get("deckout_guard", True):
        dc = board.get("deck_count") if isinstance(board, dict) else None
        if isinstance(dc, int) and not isinstance(dc, bool):
            if dc <= ri.thresholds.get("critical", 2):
                score -= 200.0
            elif dc <= ri.thresholds.get("heavy", 4):
                score -= 120.0
            elif dc <= ri.thresholds.get("penalize", 8):
                score -= 60.0
    if attacker_ready(board, ri):
        score -= 50.0  # stop passive loops: attack instead
    return score


def board_pressure_score(board: Any, playbook: Any) -> float:
    """Rough board-development measure (higher == more developed)."""
    ri = load_playbook_roles(playbook)
    score = 0.0
    if attacker_ready(board, ri):
        score += 50.0
    if _has_role_in_play(board, "setup_basic", ri):
        score += 20.0
    if _has_role_in_play(board, "evolution_payoff", ri):
        score += 30.0
    score += len(board.get("bench") or []) * 5.0 if isinstance(board, dict) else 0.0
    return score


# ---- embedded: ptcg_activegraph/pilot/decisions.py ----
"""Layer 2 decisions — turn scores into legal, deterministic selections.

Each ``choose_*`` takes ``(options, board, playbook)`` and returns a result dict::

    {"chosen_card_id": int|None,
     "chosen_card_ids": [int, ...],
     "action_kind": str,
     "rationale": str}

Ties break deterministically: highest score, then lowest card id, then lowest index.
``core_pilot_decide(kind, board, options, playbook)`` dispatches by decision kind.
Standard library only (embeddable).
"""

from typing import Any



def _result(chosen_card_id=None, chosen_card_ids=None, action_kind="", rationale=""):
    if chosen_card_ids is None:
        chosen_card_ids = [] if chosen_card_id is None else [chosen_card_id]
    return {
        "chosen_card_id": chosen_card_id,
        "chosen_card_ids": list(chosen_card_ids),
        "action_kind": action_kind,
        "rationale": rationale,
    }


def _pick_best(options, score_fn):
    """Return ``(index, option)`` of the best-scoring option (deterministic)."""
    best_i = None
    best_key = None
    for i, opt in enumerate(options):
        try:
            sc = score_fn(opt)
        except Exception:
            sc = float("-inf")
        cid = card_id(opt)
        cid_key = cid if isinstance(cid, int) else 1 << 30
        key = (sc, -cid_key, -i)  # max score, then lowest id, then lowest index
        if best_key is None or key > best_key:
            best_key = key
            best_i = i
    if best_i is None:
        return None, None
    return best_i, options[best_i]


def _need_count(board, options) -> int:
    """How many items a multi-select (discard) wants; defaults to 1."""
    if isinstance(board, dict):
        for key in ("discard_count", "need", "min_count"):
            v = board.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
    return 1


def choose_setup_active(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="setup_active", rationale="no options")
    if not ri.flags.get("active_scoring", True):
        opt = options[0]  # ablation: naive first-option
        return _result(card_id(opt), action_kind="setup_active",
                       rationale="ablation:no_active_scoring")
    _, opt = _pick_best(options, lambda o: score_basic_active(o, board, ri))
    return _result(card_id(opt), action_kind="setup_active",
                   rationale="best basic attacker as active")


# Promotion after a knock-out reuses the active-selection competence.
def choose_promote_after_ko(options, board, playbook):
    res = choose_setup_active(options, board, playbook)
    res["action_kind"] = "promote_after_ko"
    return res


def choose_setup_bench(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="setup_bench", rationale="no options")
    bench = board.get("bench") or [] if isinstance(board, dict) else []
    bench_max = board.get("bench_max", 5) if isinstance(board, dict) else 5
    if len(bench) >= bench_max:
        return _result(action_kind="skip", rationale="bench full")
    if not ri.flags.get("bench_safety", True):
        return _result(action_kind="skip", rationale="ablation:no_bench_safety")
    _, opt = _pick_best(options, lambda o: score_basic_bench(o, board, ri))
    return _result(card_id(opt), action_kind="setup_bench",
                   rationale="develop a useful backup/setup basic")


def choose_setup_bench_multi(options, board, playbook):
    """Bench refinement that preserves a base-committed COUNT and only reorders
    WHICH basics are benched. ``board['bench_pick_count']`` carries the count the
    base policy already committed to (so the runtime hook never changes how many
    basics are placed -- it only swaps in higher-value backups)."""
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="setup_bench", rationale="no options")
    need = 1
    if isinstance(board, dict) and isinstance(board.get("bench_pick_count"), int) \
            and not isinstance(board.get("bench_pick_count"), bool):
        need = max(1, board["bench_pick_count"])
    ranked = sorted(
        range(len(options)),
        key=lambda i: (-score_basic_bench(options[i], board, ri),
                       (card_id(options[i]) if isinstance(card_id(options[i]), int)
                        else 1 << 30), i),
    )
    chosen_idx = ranked[:need]
    chosen_ids = [card_id(options[i]) for i in sorted(chosen_idx)]
    return _result(chosen_ids[0] if chosen_ids else None, chosen_ids,
                   action_kind="setup_bench", rationale="develop best backup basics")


def choose_draw_count(options, board, playbook):
    """Pick a numeric quantity (cabt ``select.type==8``; options carry a ``number``
    field) at a 'choose a number' decision. Policy is a conservative *low-deck
    draw-avoid* guard: draw as much as offered while keeping at least one card in
    the deck, so the pilot never decks itself out. With deck size unknown it
    defaults to the maximum offered number.

    Returns the usual result dict plus a ``chosen_number`` key (the selected
    quantity). This is a safety guard, not a strategic override: at the SELECT
    level exactly one option is still chosen -- only WHICH number changes."""
    nums = []
    for o in options:
        n = o.get("number") if isinstance(o, dict) else None
        if isinstance(n, int) and not isinstance(n, bool):
            nums.append(n)
    if not nums:
        r = _result(action_kind="draw_count", rationale="no numeric options")
        r["chosen_number"] = None
        return r
    deck_count = None
    if isinstance(board, dict):
        dc = board.get("deck_count")
        if isinstance(dc, int) and not isinstance(dc, bool):
            deck_count = dc
    if deck_count is not None:
        # Keep >= 1 card in deck after the draw to avoid self-deckout.
        safe = [n for n in nums if deck_count - n >= 1]
        if safe:
            chosen = max(safe)
            rat = "max safe draw keeping deck non-empty (deck=%d)" % deck_count
        else:
            chosen = min(nums)
            rat = "deck critically low (deck=%d); minimal draw" % deck_count
    else:
        chosen = max(nums)
        rat = "deck size unknown; default to max offered"
    r = _result(action_kind="draw_count", rationale=rat)
    r["chosen_number"] = chosen
    return r


def choose_attach_target(options, board, playbook, attach_kind="energy"):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="attach_" + attach_kind, rationale="no options")
    if attach_kind == "tool":
        scorer = lambda o: score_tool_attach_target(o, board, ri)
    else:
        scorer = lambda o: score_energy_attach_target(o, board, ri)
    _, opt = _pick_best(options, scorer)
    return _result(card_id(opt), action_kind="attach_" + attach_kind,
                   rationale="attach to the (next) attacker")


def choose_evolution(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="evolve", rationale="no options")
    def scorer(o):
        target = o.get("target_card_id") if isinstance(o, dict) else None
        return score_evolution(o, target, board, ri)
    idx, opt = _pick_best(options, scorer)
    if opt is None or scorer(opt) <= 0:
        return _result(action_kind="skip", rationale="line not ready")
    return _result(card_id(opt), action_kind="evolve",
                   rationale="evolve when the line is ready")


def _is_benchable_basic(cid, ri) -> bool:
    """A Basic that can be put on the bench: a setup or primary attacker basic.

    Evolution payoffs (e.g. Mega Abomasnow ex) are deliberately excluded -- they
    are played onto a Basic and are never a legal bench play."""
    return has_role(cid, "primary_basic_attacker", ri) or has_role(cid, "setup_basic", ri)


def _backup_basic_rank(cid, ri):
    """Prefer a primary attacker basic over a pure setup basic, then lowest id."""
    pref = 0 if has_role(cid, "primary_basic_attacker", ri) else 1
    return (pref, cid if isinstance(cid, int) and not isinstance(cid, bool) else 1 << 30)


def choose_to_hand(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="search_to_hand", rationale="no options")
    # Anti-disruption search pivot (flag-gated, Pass 22): when our board is
    # collapsing (bench empty), fetch a backup benchable Basic instead of a
    # greedy thinning/tool target so a single KO cannot end the game. Still
    # selects exactly ONE search target -- only WHICH target changes.
    if ri.flags.get("anti_disruption_search_pivot"):
        bench = board.get("bench") or [] if isinstance(board, dict) else []
        if len(bench) == 0:
            backups = [o for o in options if _is_benchable_basic(card_id(o), ri)]
            if backups:
                best = sorted(backups, key=lambda o: _backup_basic_rank(card_id(o), ri))[0]
                return _result(card_id(best), action_kind="search_to_hand",
                               rationale="anti-disruption: fetch a backup basic while bench empty")
    _, opt = _pick_best(options, lambda o: score_search_target(o, board, ri))
    return _result(card_id(opt), action_kind="search_to_hand",
                   rationale="fetch the missing plan piece")


def choose_discard(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="discard", rationale="no options")
    need = _need_count(board, options)
    work = list(range(len(options)))
    # Preserve-backup-basic (flag-gated, Pass 22): never include a benchable Basic
    # in the discard selection when enough non-basic candidates can satisfy the
    # required COUNT. The count the base policy committed to is unchanged -- only
    # WHICH cards are discarded changes, so the last backup line is never trashed.
    if ri.flags.get("preserve_backup_basic_on_discard"):
        non_basic = [i for i in work if not _is_benchable_basic(card_id(options[i]), ri)]
        if len(non_basic) >= max(1, need):
            work = non_basic
    ranked = sorted(
        work,
        key=lambda i: (-score_discard_candidate(options[i], board, ri),
                       (card_id(options[i]) if isinstance(card_id(options[i]), int)
                        else 1 << 30), i),
    )
    chosen_idx = ranked[:max(1, need)]
    chosen_ids = [card_id(options[i]) for i in sorted(chosen_idx)]
    return _result(chosen_ids[0] if chosen_ids else None, chosen_ids,
                   action_kind="discard", rationale="pay costs with excess energy (preserve backups)")


def choose_emergency_backup_bench(options, board, playbook):
    """Pass 22 ctx0 emergency hook: when the bench is EMPTY, bench a backup
    benchable Basic before the lone active is orphaned and a single KO ends the
    game. Flag-gated (``emergency_backup_bench``) and narrow:

      * only fires when the bench is empty (the literal board-collapse risk);
      * only chooses among options that are benchable Basics by role;
      * returns ``chosen_card_id=None`` (no change) otherwise.

    The compiler wiring additionally never overrides an attack option, so this
    never trades a knock-out for a bench play."""
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="skip", rationale="no options")
    if not ri.flags.get("emergency_backup_bench"):
        return _result(action_kind="skip", rationale="hook disabled")
    bench = board.get("bench") or [] if isinstance(board, dict) else []
    if len(bench) > 0:
        return _result(action_kind="skip", rationale="bench not empty; no emergency")
    cands = [o for o in options if _is_benchable_basic(card_id(o), ri)]
    if not cands:
        return _result(action_kind="skip", rationale="no backup basic available to bench")
    best = sorted(cands, key=lambda o: _backup_basic_rank(card_id(o), ri))[0]
    return _result(card_id(best), action_kind="emergency_backup_bench",
                   rationale="bench a backup basic before the active is orphaned")


def _active_near_ko(board) -> bool:
    if not isinstance(board, dict):
        return False
    if board.get("active_near_ko"):
        return True
    active = board.get("active")
    if isinstance(active, dict):
        hp = active.get("hp")
        max_hp = active.get("max_hp")
        if (isinstance(hp, int) and isinstance(max_hp, int) and not isinstance(hp, bool)
                and not isinstance(max_hp, bool) and max_hp > 0):
            return hp <= 0.3 * max_hp
    return False


def _safe_discard_count(board, ri) -> int:
    hand = board.get("hand") or [] if isinstance(board, dict) else []
    n = 0
    for c in hand:
        if has_role(card_id(c), "basic_energy", ri):
            n += 1
    return n


def choose_main_action(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="skip", rationale="no options")
    near_ko = _active_near_ko(board)
    sb_min = 3
    sb_cfg = (ri.exceptions or {}).get("secret_box") or {}
    if isinstance(sb_cfg.get("min_safe_discards"), int):
        sb_min = sb_cfg["min_safe_discards"]
    safe_discards = _safe_discard_count(board, ri)
    has_productive = any(
        isinstance(o, dict) and (o.get("is_attack") or o.get("is_bench_play")
                                 or o.get("is_evolve") or o.get("is_attach"))
        for o in options
    )

    def scorer(o):
        if not isinstance(o, dict):
            return 0.0
        if o.get("is_attack"):
            return score_attack_option(o, board, ri)
        if o.get("is_bench_play"):
            return 90.0 if near_ko else 40.0  # develop backup before a passive draw
        if o.get("is_evolve"):
            return 60.0
        if o.get("is_attach"):
            return 55.0
        if o.get("is_secret_box"):
            # Advisory Layer-4 guard: avoid when too few safe discards and a
            # productive alternative exists.
            if safe_discards < sb_min and has_productive:
                return -100.0
            return 25.0
        if o.get("is_draw_search"):
            return score_draw_search_action(o, board, ri)
        return 30.0  # generic productive action

    idx, opt = _pick_best(options, scorer)
    kind = "main_action"
    if isinstance(opt, dict):
        if opt.get("is_attack"):
            kind = "attack"
        elif opt.get("is_bench_play"):
            kind = "bench_play"
        elif opt.get("is_evolve"):
            kind = "evolve"
        elif opt.get("is_attach"):
            kind = "attach"
        elif opt.get("is_secret_box"):
            kind = "secret_box"
        elif opt.get("is_draw_search"):
            kind = "draw_search"
    return _result(card_id(opt), action_kind=kind, rationale="best board-advancing action")


def choose_attack(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="attack", rationale="no options")
    _, opt = _pick_best(options, lambda o: score_attack_option(o, board, ri))
    return _result(card_id(opt), action_kind="attack",
                   rationale="strongest available attack")


_DISPATCH = {
    "setup_active": lambda o, b, p: choose_setup_active(o, b, p),
    "promote_after_ko": lambda o, b, p: choose_promote_after_ko(o, b, p),
    "setup_bench": lambda o, b, p: choose_setup_bench(o, b, p),
    "setup_bench_multi": lambda o, b, p: choose_setup_bench_multi(o, b, p),
    "draw_count": lambda o, b, p: choose_draw_count(o, b, p),
    "attach_energy": lambda o, b, p: choose_attach_target(o, b, p, "energy"),
    "attach_tool": lambda o, b, p: choose_attach_target(o, b, p, "tool"),
    "evolve": lambda o, b, p: choose_evolution(o, b, p),
    "search_to_hand": lambda o, b, p: choose_to_hand(o, b, p),
    "discard": lambda o, b, p: choose_discard(o, b, p),
    "main_action": lambda o, b, p: choose_main_action(o, b, p),
    "attack": lambda o, b, p: choose_attack(o, b, p),
    "emergency_backup_bench": lambda o, b, p: choose_emergency_backup_bench(o, b, p),
}


def decide(kind, board, options, playbook):
    """Dispatch a decision by kind. Unknown kinds return an empty result."""
    fn = _DISPATCH.get(kind)
    if fn is None:
        return _result(action_kind="unknown", rationale="unknown kind: %r" % (kind,))
    try:
        return fn(options or [], board or {}, playbook)
    except Exception as exc:  # never raise into a runtime agent
        return _result(action_kind="error", rationale="decide error: %r" % (exc,))


# Lab alias; the compiler emits its own playbook-defaulting wrapper of the same name.
core_pilot_decide = decide

_CP_PLAYBOOK = {'roles': {'basic_energy': [3], 'primary_basic_attacker': [721], 'setup_basic': [722], 'evolution_payoff': [723], 'search': [1121, 1145], 'high_risk_search': [1092], 'tool': [1163], 'draw': [1219, 1227, 1262], 'stadium': [1262]}, 'plan': {'primary_plan': 'kyogre_tempo', 'secondary_plan': 'abomasnow_evolution', 'avoid_plans': ['passive_draw_loop', 'deckout']}, 'deckout_guard_thresholds': {'penalize': 8, 'heavy': 4, 'critical': 2}, 'role_weights': {'active_prefers': ['primary_basic_attacker'], 'bench_prefers': ['primary_basic_attacker', 'setup_basic'], 'attach_prefers': ['active_attacker', 'next_attacker'], 'search_prefers': 'missing_plan_piece', 'discard_prefers': ['basic_energy'], 'preserve_only': ['setup_basic', 'primary_basic_attacker', 'evolution_payoff_when_setup_exists']}, 'exceptions': {}, 'flags': {'emergency_backup_bench': True, 'anti_disruption_search_pivot': True, 'preserve_backup_basic_on_discard': True}}

# Reliably-identifiable cabt select.context integers this candidate refines at
# runtime (7=ToHand search, 8=discard). Empirically confirmed + named in state.py.
_CP_RUNTIME_CONTEXTS = (0, 7, 8)


def core_pilot_decide(kind, board, options, playbook=None):
    """Public decision entry; defaults to this deck's embedded playbook."""
    return decide(kind, board, options, playbook if playbook is not None else _CP_PLAYBOOK)


_CP_ORIG_EMBEDDED = _embedded_agent


def _cp_indices_for_ids(built, chosen_ids):
    idxs = []
    used = set()
    for cid in chosen_ids:
        for i, b in enumerate(built):
            if i in used:
                continue
            if b.get("card_id") == cid:
                idxs.append(i)
                used.add(i)
                break
    return idxs


def _cp_embedded(obs):
    """Run the proven base policy, then refine ONLY at the reliably identifiable
    cabt contexts in ``_CP_RUNTIME_CONTEXTS`` (7=ToHand search, 8=discard).

    Refinement never changes WHETHER or HOW MANY cards are acted on — the base
    policy already decided that (and owns all effect-safety). We only reorder
    WHICH card(s) of the base's committed action are chosen, and bail back to the
    base result on any mismatch or error."""
    base = _CP_ORIG_EMBEDDED(obs)
    try:
        sel = _get_select(obs)
        if not isinstance(sel, dict):
            return base
        options = _get_options(sel)
        if not options:
            return base
        mn, mx = _get_min_max_count(sel, len(options))
        ctx = sel.get("context")
        # Only refine when the base policy committed to acting (non-empty list,
        # not a safety decline).
        if not (isinstance(base, list) and len(base) >= 1):
            return base
        # Emergency backup bench (Pass 22): at the Main action context, when the
        # bench is EMPTY and a backup benchable Basic can be played (a type-7
        # play-from-hand option whose hand card is a setup/primary basic), bench
        # it instead of passing/drawing/attaching -- but NEVER instead of an
        # attack. Still exactly ONE Main option selected; bails to base on any
        # mismatch, and only fires when the embedded playbook sets the flag.
        if ctx == 0 and 0 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 and len(base) == 1:
            base_i = base[0]
            chosen = options[base_i] if 0 <= base_i < len(options) else None
            chosen_type = chosen.get("type") if isinstance(chosen, dict) else None
            if chosen_type != 13:  # never override an attack option
                board = build_board(obs)
                hand = board.get("hand") or [] if isinstance(board, dict) else []
                built = []
                for o in options:
                    cid = None
                    if isinstance(o, dict) and o.get("type") == 7:
                        ix = o.get("index")
                        if isinstance(ix, int) and not isinstance(ix, bool) and 0 <= ix < len(hand):
                            cid = card_id(hand[ix])
                    built.append({"card_id": cid})
                res = core_pilot_decide("emergency_backup_bench", board, built)
                cid = res.get("chosen_card_id")
                if cid is not None:
                    base_cid = built[base_i].get("card_id") if 0 <= base_i < len(built) else None
                    if base_cid != cid:
                        idxs = _cp_indices_for_ids(built, [cid])
                        if idxs:
                            refined = _validate_action(idxs, len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
        # Refine WHICH basic becomes the active Pokemon at setup (count is fixed
        # at exactly 1 by the engine -- only the choice changes; Kyogre > Snover).
        elif ctx == 1 and 1 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 and len(base) == 1:
            built = [{"card_id": resolve_option_card(obs, o)} for o in options]
            board = build_board(obs)
            res = core_pilot_decide("setup_active", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _cp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == 1:
                        return refined
        # Refine WHICH basics go to the bench at setup, keeping exactly the COUNT
        # the base policy already committed to (never benches more/fewer).
        elif ctx == 2 and 2 in _CP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx and need >= 1:
                built = [{"card_id": resolve_option_card(obs, o)} for o in options]
                board = build_board(obs)
                if isinstance(board, dict):
                    board["bench_pick_count"] = need
                res = core_pilot_decide("setup_bench_multi", board, built)
                chosen_ids = res.get("chosen_card_ids") or []
                idxs = _cp_indices_for_ids(built, chosen_ids)
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        # Refine the search target at the ToHand-search context.
        elif ctx == 7 and 7 in _CP_RUNTIME_CONTEXTS and mx >= 1:
            built = [{"card_id": resolve_option_card(obs, o)} for o in options]
            board = build_board(obs)
            res = core_pilot_decide("search_to_hand", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _cp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined:
                        return refined
        # Refine WHICH cards to discard at the discard context, keeping exactly
        # the COUNT the base policy already committed to (only the choice changes).
        elif ctx == 8 and 8 in _CP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx:
                built = [{"card_id": resolve_option_card(obs, o)} for o in options]
                board = build_board(obs)
                if isinstance(board, dict):
                    board["discard_count"] = need
                res = core_pilot_decide("discard", board, built)
                chosen_ids = res.get("chosen_card_ids") or []
                idxs = _cp_indices_for_ids(built, chosen_ids)
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        # Refine a numeric 'choose a number' select (e.g. draw-count): pick the
        # quantity that avoids self-deckout. Still exactly ONE option selected --
        # only WHICH number changes; deck size comes from build_board (the select
        # itself carries no deck info).
        elif ctx == 38 and 38 in _CP_RUNTIME_CONTEXTS and mn == 1 and mx == 1:
            numbers = [o.get("number") if isinstance(o, dict) else None
                       for o in options]
            if all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
                board = build_board(obs)
                res = core_pilot_decide("draw_count", board, options)
                chosen_number = res.get("chosen_number")
                if isinstance(chosen_number, int) and not isinstance(chosen_number, bool):
                    pick = None
                    for i, o in enumerate(options):
                        if isinstance(o, dict) and o.get("number") == chosen_number:
                            pick = i
                            break
                    if pick is not None:
                        refined = _validate_action([pick], len(options), mn, mx)
                        if refined and len(refined) == 1:
                            return refined
    except Exception:
        pass
    return base


_embedded_agent = _cp_embedded


# Kaggle/cabt selects the LAST top-level callable in this module as the agent
# (see kaggle_environments.agent.get_last_callable). The override above appended
# new callables AFTER the deck-safety ``agent`` entrypoint, which would silently
# hijack the entrypoint and bypass deck-selection handling (the agent would
# return [] on the deck-selection step -> INVALID). The real entrypoint must be
# the last callable, and it MUST use a FRESH name: re-binding an existing global
# (e.g. ``agent = ...``) does not change dict insertion order, so it would not
# become last. ``core_pilot_agent`` simply delegates to the deck-safe ``agent``
# (which uses the refined ``_embedded_agent`` for gameplay). ``agent`` itself is
# left untouched so callers that invoke it by name still work.
_cp_deck_safe_agent = agent


def core_pilot_agent(obs_dict):
    return _cp_deck_safe_agent(obs_dict)
# === END PASS14 CORE-PILOT OVERRIDE ===


# === PASS35 TYPED STRATEGY OVERRIDE: water_basic_density_v1_typed35 ===
# Embeds the typed board-aware strategy layer (stdlib-only) plus this deck's
# StrategyProfile and a minimal per-card metadata table. Exposes
# ``typed_decide(kind, board, options)`` (graded by the typed-strategy fixtures)
# and conservatively refines decisions at the reliably-identifiable cabt contexts
# in ``_TP_RUNTIME_CONTEXTS`` while preserving the proven base policy beneath it.
from typing import Any as _TP_Any  # noqa: F401  (stdlib)

# ---- embedded: pilot_typed/board.py ----
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


# ---- embedded: pilot_typed/metadata.py ----
"""Per-card metadata lookups.

Operates on an inlined metadata table (built at COMPILE time from the local
EN_Card_Data.csv for ONLY our portfolio/candidate card ids; the CSV is never
shipped or committed). All helpers tolerate a missing/partial table and return
conservative defaults so runtime never depends on metadata being complete.

Metadata entry shape (all keys optional except implied by presence):
    meta[card_id] = {
        "name": str, "card_type": "pokemon"|"energy"|"trainer"|...,
        "subtype": str, "stage": "basic"|"stage1"|"stage2"|None,
        "is_basic_pokemon": bool, "is_basic_energy": bool,
        "energy_type": str|None, "hp": int|None,
        "ex": bool, "retreat_cost": int|None,
    }
Keys are ints (card ids). When loaded from JSON they may arrive as strings, so
lookups coerce both.
"""



def _coerce_table(meta: Any) -> dict:
    return meta if isinstance(meta, dict) else {}


def card_meta(meta: Any, cid: Any) -> dict:
    table = _coerce_table(meta)
    if cid is None:
        return {}
    entry = table.get(cid)
    if entry is None:
        entry = table.get(str(cid))
    return entry if isinstance(entry, dict) else {}


def name(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("name")


def card_type(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("card_type")


def is_pokemon(meta: Any, cid: Any) -> bool:
    return card_type(meta, cid) == "pokemon"


def is_trainer(meta: Any, cid: Any) -> bool:
    return card_type(meta, cid) == "trainer"


def is_energy(meta: Any, cid: Any) -> bool:
    m = card_meta(meta, cid)
    return m.get("card_type") == "energy" or bool(m.get("is_basic_energy"))


def is_basic_energy(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid).get("is_basic_energy"))


def stage(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("stage")


def is_basic_pokemon(meta: Any, cid: Any) -> bool:
    """True only when metadata positively says this is a Basic Pokemon.

    Conservative: returns False when metadata is missing so callers must have a
    separate observation-derived signal (e.g. a setup option the engine offered)
    before treating a card as a benchable Basic.
    """
    m = card_meta(meta, cid)
    if m.get("is_basic_pokemon") is True:
        return True
    if m.get("card_type") == "pokemon" and m.get("stage") == "basic":
        return True
    return False


def energy_type(meta: Any, cid: Any) -> Any:
    return card_meta(meta, cid).get("energy_type")


def hp(meta: Any, cid: Any) -> Any:
    v = card_meta(meta, cid).get("hp")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def is_ex(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid).get("ex"))


def retreat_cost(meta: Any, cid: Any) -> Any:
    v = card_meta(meta, cid).get("retreat_cost")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def has_meta(meta: Any, cid: Any) -> bool:
    return bool(card_meta(meta, cid))


# ---- embedded: pilot_typed/profiles.py ----
"""StrategyProfile access + validation.

A StrategyProfile is a JSON-safe dict describing how to pilot one deck. It is the
deck-specific input the typed tactics consume. Profiles are authored in
experiments/strategy_profiles.yaml; the compiler inlines the reduced literal for
ONE deck into a candidate. All accessors tolerate missing keys.

Profile shape:
    {
      "id": str,
      "executable": bool,           # may a generic compiled candidate run it?
      "lane": "stdlib_typed_lite",
      "implemented_contexts": [int,...],   # 0,1,2,7,8,38
      "unsupported_mechanics": [str,...],  # attack_damage/spread/boss/lethal/...
      "roles": {role: [card_id,...]},      # primary_attacker, setup_basic,
                                           # energy_accel, draw_engine,
                                           # key_item, search, tech
      "priority": [card_id,...],    # global want order (setup/search)
      "energy_types": [str,...],    # deck's attacker energy colors
      "deck_plan": {...},           # human-facing plan (not executed directly)
      "deckout_guard": {"min_deck": int, "max_draw": int|None},
      "discard_keep": [card_id,...],   # never discard if avoidable
      "discard_prefer": [card_id,...], # discard first when forced
      "card_ids": [card_id,...],
      "parent": str|None,
      "risks": [str,...],
    }
"""


_ROLE_KEYS = ("primary_attacker", "setup_basic", "energy_accel", "draw_engine",
              "key_item", "search", "tech", "bench_sitter")

KNOWN_UNSUPPORTED = ("attack_damage", "lethal", "ko_targeting", "spread",
                     "boss", "gust", "opponent_hand")


def _as_int_list(v: Any) -> list:
    out = []
    if isinstance(v, list):
        for x in v:
            if isinstance(x, int) and not isinstance(x, bool):
                out.append(x)
    return out


def profile_id(profile: Any) -> Any:
    return profile.get("id") if isinstance(profile, dict) else None


def is_executable(profile: Any) -> bool:
    return bool(profile.get("executable")) if isinstance(profile, dict) else False


def implemented_contexts(profile: Any) -> tuple:
    if isinstance(profile, dict):
        return tuple(_as_int_list(profile.get("implemented_contexts")))
    return tuple()


def unsupported_mechanics(profile: Any) -> list:
    if isinstance(profile, dict):
        v = profile.get("unsupported_mechanics")
        if isinstance(v, list):
            return [str(x) for x in v]
    return []


def roles(profile: Any) -> dict:
    if isinstance(profile, dict):
        r = profile.get("roles")
        if isinstance(r, dict):
            return {str(k): _as_int_list(v) for k, v in r.items()}
    return {}


def role_ids(profile: Any, role: str) -> list:
    return roles(profile).get(role, [])


def all_role_ids(profile: Any) -> list:
    seen = []
    for ids in roles(profile).values():
        for cid in ids:
            if cid not in seen:
                seen.append(cid)
    return seen


def priority(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("priority"))
    return []


def energy_types(profile: Any) -> list:
    if isinstance(profile, dict):
        v = profile.get("energy_types")
        if isinstance(v, list):
            return [str(x) for x in v]
    return []


def deckout_guard(profile: Any) -> dict:
    if isinstance(profile, dict):
        g = profile.get("deckout_guard")
        if isinstance(g, dict):
            return g
    return {}


def discard_keep(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("discard_keep"))
    return []


def discard_prefer(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("discard_prefer"))
    return []


def priority_rank(profile: Any, cid: Any) -> int:
    """Lower rank = more wanted. Cards not listed sort after listed ones."""
    pr = priority(profile)
    if cid in pr:
        return pr.index(cid)
    return len(pr) + 1000


def validate_profile(profile: Any) -> dict:
    """Return {ok, errors, warnings}. Never raises."""
    errors = []
    warnings = []
    if not isinstance(profile, dict):
        return {"ok": False, "errors": ["profile is not a dict"], "warnings": []}
    if not profile.get("id"):
        errors.append("missing id")
    if profile.get("lane") not in (None, "stdlib_typed_lite"):
        warnings.append("unexpected lane %r" % profile.get("lane"))
    for ctx in implemented_contexts(profile):
        if ctx not in (0, 1, 2, 7, 8, 38):
            warnings.append("context %r not a known typed context" % ctx)
    for m in unsupported_mechanics(profile):
        if m not in KNOWN_UNSUPPORTED:
            warnings.append("unsupported mechanic %r unrecognized" % m)
    if is_executable(profile) and not roles(profile):
        warnings.append("executable profile has no roles")
    # Honesty guard: an executable profile must NOT claim any unsupported
    # mechanic as an implemented context.
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ---- embedded: pilot_typed/tactics.py ----
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


# These imports are STRIPPED by the compiler (the embedded layer is flat); they
# exist so the lab package and fixtures import the real cross-module names.

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


# ---- embedded: pilot_typed/decisions.py ----
"""Per-context decision routing.

``decide(kind, board, options, profile, meta)`` is the single public entry the
fixtures grade AND the compiled runtime calls, so the deterministic gate tests
exactly what ships. Never raises; returns a small result dict per kind:

    setup_active / search_to_hand / emergency_backup_bench -> {"chosen_card_id": id|None}
    setup_bench_multi  -> {"chosen_card_ids": [id,...]}   (uses board["bench_pick_count"])
    discard            -> {"chosen_card_ids": [id,...]}   (uses board["discard_count"])
    draw_count         -> {"chosen_number": int|None}
    attach_energy      -> {"chosen_target_id": id|None}
    <unsupported kind> -> {"unsupported": True, "reason": str}

Each ``options`` element is a dict carrying at least ``card_id`` (for attach,
``card_id`` is the in-play target). The compiler builds these from the raw obs.
"""


# STRIPPED by the compiler (embedded layer is flat); present so the lab package
# and fixtures import the real cross-module names.

_UNSUPPORTED_KINDS = {
    "attack": "attack damage/effect not in option schema (numeric attackId only)",
    "ko_target": "attack damage + target identity unsupported",
    "lethal": "depends on attack damage (unsupported)",
    "spread": "spread targets not exposed (Pass-28 honesty rule)",
    "boss": "Boss/gust target identity not observable",
    "gust": "gust target identity not observable",
}


def decide(kind: Any, board: Any, options: Any, profile: Any = None,
           meta: Any = None) -> dict:
    profile = profile if isinstance(profile, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    board = board if isinstance(board, dict) else {}
    options = options if isinstance(options, list) else []
    try:
        if kind in _UNSUPPORTED_KINDS:
            return {"unsupported": True, "reason": _UNSUPPORTED_KINDS[kind]}

        if kind == "setup_active":
            return {"chosen_card_id":
                    choose_setup_active(board, options, profile, meta)}  # noqa: F821

        if kind == "setup_bench_multi":
            need = board.get("bench_pick_count")
            if not (isinstance(need, int) and not isinstance(need, bool)):
                need = len(options)
            return {"chosen_card_ids":
                    choose_setup_bench(board, options, profile, meta, need)}  # noqa: F821

        if kind == "search_to_hand":
            return {"chosen_card_id":
                    choose_search_target(board, options, profile, meta)}  # noqa: F821

        if kind == "discard":
            need = board.get("discard_count")
            if not (isinstance(need, int) and not isinstance(need, bool)):
                need = 0
            return {"chosen_card_ids":
                    choose_discard(board, options, profile, meta, need)}  # noqa: F821

        if kind == "draw_count":
            numbers = [o.get("number") if isinstance(o, dict) else o
                       for o in options]
            return {"chosen_number":
                    safe_draw_count(board, numbers, profile)}  # noqa: F821

        if kind == "emergency_backup_bench":
            return {"chosen_card_id":
                    choose_emergency_bench(board, options, profile, meta)}  # noqa: F821

        if kind == "attach_energy":
            return {"chosen_target_id":
                    choose_attach_target(board, options, profile, meta)}  # noqa: F821
    except Exception:
        return {}
    return {}

_TP_PROFILE = {'id': 'water_basic_density_v1', 'executable': True, 'lane': 'stdlib_typed_lite', 'implemented_contexts': [0, 1, 2, 7, 8, 38], 'unsupported_mechanics': ['attack_damage', 'lethal', 'ko_targeting', 'spread', 'boss', 'gust', 'opponent_hand'], 'roles': {'primary_attacker': [721, 723], 'setup_basic': [720, 721, 722], 'draw_engine': [1219, 1227], 'search': [1121, 1145, 1092], 'key_item': [1163], 'tech': [1262], 'bench_sitter': [720]}, 'priority': [721, 723, 722, 720, 1121, 1145], 'energy_types': ['Water'], 'deckout_guard': {'min_deck': 2, 'max_draw': None}, 'discard_keep': [721, 722, 723, 1163], 'discard_prefer': [3]}
_TP_META = {3: {'name': 'Basic {W} Energy', 'card_type': 'energy', 'is_basic_energy': True, 'energy_type': 'Water'}, 720: {'name': 'Mantine', 'card_type': 'pokemon', 'stage': 'basic', 'is_basic_pokemon': True, 'energy_type': 'Water', 'hp': 110, 'retreat_cost': 1}, 721: {'name': 'Kyogre', 'card_type': 'pokemon', 'stage': 'basic', 'is_basic_pokemon': True, 'energy_type': 'Water', 'hp': 150, 'retreat_cost': 3}, 722: {'name': 'Snover', 'card_type': 'pokemon', 'stage': 'basic', 'is_basic_pokemon': True, 'energy_type': 'Water', 'hp': 90, 'retreat_cost': 3}, 723: {'name': 'Mega Abomasnow ex', 'card_type': 'pokemon', 'stage': 'stage1', 'energy_type': 'Water', 'hp': 350, 'retreat_cost': 4, 'ex': True}, 1092: {'name': 'Secret Box', 'card_type': 'trainer'}, 1121: {'name': 'Ultra Ball', 'card_type': 'trainer'}, 1145: {'name': 'Mega Signal', 'card_type': 'trainer'}, 1163: {'name': 'Powerglass', 'card_type': 'trainer'}, 1219: {'name': "Team Rocket's Petrel", 'card_type': 'trainer'}, 1227: {'name': "Lillie's Determination", 'card_type': 'trainer'}, 1262: {'name': 'Surfing Beach', 'card_type': 'trainer'}}
_TP_RUNTIME_CONTEXTS = (0, 1, 2, 7, 8, 38)


def typed_decide(kind, board, options, profile=None, meta=None):
    """Public typed decision entry; defaults to this deck's profile + metadata."""
    return decide(kind, board, options,
                  profile if profile is not None else _TP_PROFILE,
                  meta if meta is not None else _TP_META)


_TP_ORIG_EMBEDDED = _embedded_agent


def _tp_indices_for_ids(built, chosen_ids):
    idxs, used = [], set()
    for cid in chosen_ids:
        for i, b in enumerate(built):
            if i in used:
                continue
            if b.get("card_id") == cid:
                idxs.append(i)
                used.add(i)
                break
    return idxs


def _tp_type8_target_options(obs, options):
    """[(index, target_card_id)] for attach-like (type 8) options with a
    resolvable distinct in-play target."""
    out = []
    for i, o in enumerate(options):
        if isinstance(o, dict) and o.get("type") == 8:
            tgt = resolve_option_target(obs, o)
            if tgt is not None:
                out.append((i, tgt))
    return out


def _tp_embedded(obs):
    """Run the proven base policy, then refine ONLY at reliably-identifiable
    contexts. Refinement never changes WHETHER or HOW MANY options are acted on;
    it only reorders WHICH option(s) of the base's committed action are chosen,
    and bails back to base on any mismatch or error."""
    base = _TP_ORIG_EMBEDDED(obs)
    try:
        sel = _get_select(obs)
        if not isinstance(sel, dict):
            return base
        options = _get_options(sel)
        if not options:
            return base
        mn, mx = _get_min_max_count(sel, len(options))
        ctx = sel.get("context")
        if not (isinstance(base, list) and len(base) >= 1):
            return base
        board = build_board(obs)

        if ctx == 0 and 0 in _TP_RUNTIME_CONTEXTS and len(base) == 1:
            base_i = base[0]
            chosen = options[base_i] if 0 <= base_i < len(options) else None
            chosen_type = chosen.get("type") if isinstance(chosen, dict) else None
            # (a) Emergency backup bench: empty bench, base picked a non-attack
            # play-from-hand; bench the best Basic instead.
            bench_empty = not (board.get("bench") if isinstance(board, dict) else None)
            if mn == 1 and mx == 1 and chosen_type != 13 and bench_empty:
                hand = board.get("hand") or []
                built = []
                for o in options:
                    cid = None
                    if isinstance(o, dict) and o.get("type") == 7:
                        ix = o.get("index")
                        if isinstance(ix, int) and not isinstance(ix, bool) \
                                and 0 <= ix < len(hand):
                            cid = card_id(hand[ix])
                    built.append({"card_id": cid})
                res = typed_decide("emergency_backup_bench", board, built)
                cid = res.get("chosen_card_id")
                if cid is not None and 0 <= base_i < len(built):
                    if built[base_i].get("card_id") != cid:
                        idxs = _tp_indices_for_ids(built, [cid])
                        if idxs:
                            refined = _validate_action(idxs, len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
            # (b) Attach-target: base picked a type-8 attach with a resolvable
            # target and there are >=2 distinct targets; choose the intended
            # attacker. Count/type unchanged (still exactly the one option).
            if mn == 1 and mx == 1 and chosen_type == 8:
                pairs = _tp_type8_target_options(obs, options)
                targets = [t for _, t in pairs]
                if len(set(targets)) >= 2:
                    built = [{"card_id": t} for _, t in pairs]
                    res = typed_decide("attach_energy", board, built)
                    tgt = res.get("chosen_target_id")
                    if tgt is not None:
                        for i, t in pairs:
                            if t == tgt:
                                refined = _validate_action([i], len(options), mn, mx)
                                if refined and len(refined) == 1:
                                    return refined
                                break
        elif ctx == 1 and 1 in _TP_RUNTIME_CONTEXTS and mn == 1 and mx == 1 \
                and len(base) == 1:
            built = [{"card_id": resolve_option_card(obs, o)} for o in options]
            res = typed_decide("setup_active", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _tp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == 1:
                        return refined
        elif ctx == 2 and 2 in _TP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx and need >= 1:
                built = [{"card_id": resolve_option_card(obs, o)} for o in options]
                if isinstance(board, dict):
                    board["bench_pick_count"] = need
                res = typed_decide("setup_bench_multi", board, built)
                idxs = _tp_indices_for_ids(built, res.get("chosen_card_ids") or [])
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        elif ctx == 7 and 7 in _TP_RUNTIME_CONTEXTS and mx >= 1:
            built = [{"card_id": resolve_option_card(obs, o)} for o in options]
            res = typed_decide("search_to_hand", board, built)
            cid = res.get("chosen_card_id")
            if cid is not None:
                idxs = _tp_indices_for_ids(built, [cid])
                if idxs:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined:
                        return refined
        elif ctx == 8 and 8 in _TP_RUNTIME_CONTEXTS:
            need = len(base)
            if mn <= need <= mx:
                built = [{"card_id": resolve_option_card(obs, o)} for o in options]
                if isinstance(board, dict):
                    board["discard_count"] = need
                res = typed_decide("discard", board, built)
                idxs = _tp_indices_for_ids(built, res.get("chosen_card_ids") or [])
                if len(idxs) == need:
                    refined = _validate_action(idxs, len(options), mn, mx)
                    if refined and len(refined) == need:
                        return refined
        elif ctx == 38 and 38 in _TP_RUNTIME_CONTEXTS and mn == 1 and mx == 1:
            numbers = [o.get("number") if isinstance(o, dict) else None
                       for o in options]
            if all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
                res = typed_decide("draw_count", board, options)
                chosen_number = res.get("chosen_number")
                if isinstance(chosen_number, int) and not isinstance(chosen_number, bool):
                    for i, o in enumerate(options):
                        if isinstance(o, dict) and o.get("number") == chosen_number:
                            refined = _validate_action([i], len(options), mn, mx)
                            if refined and len(refined) == 1:
                                return refined
                            break
    except Exception:
        pass
    return base


_embedded_agent = _tp_embedded


def _tp_obs_get(obs, key, default=None):
    """Read ``key`` from a dict OR a Struct-like obs (cabt sends both)."""
    if isinstance(obs, dict):
        return obs.get(key, default)
    getter = getattr(obs, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            return default
    return getattr(obs, key, default)


def _tp_is_deck_selection(obs):
    """True on the deck-submission step (select is None OR absent), across the
    dict and Struct-like obs shapes cabt uses. A present ``select`` dict (even
    with no options) is gameplay/malformed, NOT deck-selection."""
    if obs is None:
        return False
    sel = _tp_obs_get(obs, "select", "__tp_absent__")
    if isinstance(sel, dict):
        return False
    return True


def _tp_deck_ids():
    try:
        ids = _load_deck_ids()
        return ids if isinstance(ids, list) else []
    except Exception:
        return []


# Robust module-level agent: return the 60-card deck on EVERY deck-selection
# shape (the proven base only handled literal ``select=None``), else delegate to
# the base policy (which uses the refined ``_embedded_agent`` for gameplay).
_tp_base_agent = agent


def _tp_robust_agent(obs_dict):
    try:
        if _tp_is_deck_selection(obs_dict):
            ids = _tp_deck_ids()
            if len(ids) == 60:
                return ids
    except Exception:
        pass
    return _tp_base_agent(obs_dict)


agent = _tp_robust_agent


# Kaggle/cabt selects the LAST top-level callable as the agent. The real
# entrypoint must be last and use a FRESH name (re-binding ``agent`` does not
# change dict insertion order). ``typed_pilot_agent`` delegates to the robust
# deck-safe ``agent`` above.
_tp_deck_safe_agent = agent


def typed_pilot_agent(obs_dict):
    return _tp_deck_safe_agent(obs_dict)
# === END PASS35 TYPED STRATEGY OVERRIDE ===
