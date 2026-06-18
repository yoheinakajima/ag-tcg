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
    3, 3, 3, 3, 3, 3, 3, 3, 3, 721,
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


# === PASS16 ENTRYPOINT-SAFE ANCHOR CLONE: combo_full_safety_v3_entrypoint_safe_local ===
# Same deck + same combo_full_safety strategy as combo_full_safety_v3_fixed. The
# only change is this trailing block: it binds the proven deck-safe ``agent`` to a
# fresh name and exposes it as the LAST top-level callable so the cabt runner picks
# the correct entrypoint (the original re-bound ``agent`` left a pre-deck-safety
# callable as last, which returned [] at deck selection -> INVALID).
_ANCHOR_DECK_SAFE_AGENT = agent


def anchor_safe_agent(obs_dict):
    return _ANCHOR_DECK_SAFE_AGENT(obs_dict)
# === END PASS16 ENTRYPOINT-SAFE ANCHOR CLONE ===
