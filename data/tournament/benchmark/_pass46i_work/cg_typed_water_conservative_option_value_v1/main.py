"""cg_typed candidate entrypoint — cg_typed_water_conservative_option_value_v1.

OWNED PASS-46H within-family per-OPTION value FAST planner. The hot path is the VERBATIM
``option_value_features.py`` INLINE_OPTION_VALUE_V0 region (an interpretable linear model
over coarse action families PLUS option-specific VISIBLE features: the resolved card's
coarse role bucket, the in-play target's area/energy-count + role, and an
end-with-productive-alternatives penalty) driven by the embedded Pass-46H profile. There
is NO online Search in this path. The deck is the selected internal source deck, unchanged.

Card identity is resolved from the option's own area/index against YOUR visible hand or
the OFFERED select list; the target is read from the option's inPlayArea/inPlayIndex over
YOUR own board. NO hidden hand / deck / prize contents are read. Role buckets are coarse
deck-composition labels; NEITHER they nor the target area are a lethal / KO / exact-damage
/ Boss-gust / spread / globally-best-action / card-value claim.

No reference-agent policy code is copied; the only bundled reference asset is the ``cg``
SDK (allowed). Runtime contract: ``agent(obs_dict) -> list[int]`` of legal option indices
(or the 60 deck card ids on the deck-submission step). Never raises.

LOCAL benchmark-lane feasibility agent — NOT a Kaggle score / leaderboard / strength
claim. NO upload / submit / promote / mutate.
"""
from __future__ import annotations

import json as _json
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

# --- Embedded Pass-46H per-option value profile (family floor + option priors + role map)
# Loaded from a JSON string so the embedded profile is byte-synced with this deck's entry
# in data/experiments/pass46h_role_maps.json. Never raises at import.
try:
    _PROFILE = _json.loads(r'''{
  "calibrated": false,
  "option_weights": {
    "end_with_alternatives": -0.8,
    "role_attacker": 0.3,
    "role_basic": 0.6,
    "role_draw": 0.7,
    "role_energy": 1.0,
    "role_evo": 0.4,
    "role_ex": 0.2,
    "role_item": 0.35,
    "role_search": 0.9,
    "role_stadium": 0.2,
    "role_supporter": 0.8,
    "role_tool": 0.25,
    "tgt_active": 0.6,
    "tgt_bench": 0.2,
    "tgt_per_energy": -0.1,
    "tgt_role_attacker": 0.5,
    "tgt_role_basic": 0.0,
    "tgt_role_evo": 0.2,
    "tgt_role_ex": 0.4
  },
  "profile_id": "conservative_option_value_v1",
  "role_map": {
    "1092": [
      "item",
      "search"
    ],
    "1121": [
      "item",
      "search"
    ],
    "1145": [
      "item",
      "search"
    ],
    "1163": [
      "tool"
    ],
    "1219": [
      "supporter",
      "search"
    ],
    "1227": [
      "supporter"
    ],
    "1262": [
      "stadium"
    ],
    "3": [
      "energy"
    ],
    "721": [
      "basic",
      "attacker"
    ],
    "722": [
      "basic",
      "attacker"
    ],
    "723": [
      "evo",
      "attacker",
      "ex"
    ]
  },
  "schema_version": "pass46h_option_value_v1",
  "scoring_mode": "lexicographic",
  "source": "interpretable_option_priors_lexicographic",
  "weights": {
    "bias": 0.0,
    "fam_attach_energy": 4.0,
    "fam_attack": 2.5,
    "fam_effect_choice": 1.0,
    "fam_end_turn": -1.0,
    "fam_move_energy": 2.0,
    "fam_other": 0.5,
    "fam_play_from_hand": 3.5,
    "fam_play_in_play": 3.0,
    "fam_select_card": 1.5,
    "fam_use_ability": 5.0
  }
}''')
except Exception:
    _PROFILE = {"profile_id": "embedded_fallback", "weights": {}}

# OptionType END marker (mirror cg.api.OptionType; used only by the legal fallback).
OT_END = 14


# ---------------------------------------------------------------------------
# Universal accessors + generic legal-selection contract (never raise).
# ---------------------------------------------------------------------------
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
# Deck-return plumbing (own deck; resilient to cwd; harness may inject _DECK_IDS).
# ---------------------------------------------------------------------------
_DECK_IDS = None
_EMBEDDED_DECK = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 721, 721, 721, 721, 722, 722, 722, 722, 723, 723, 723, 723, 1092, 1121, 1121, 1121, 1121, 1145, 1145, 1163, 1163, 1219, 1219, 1219, 1219, 1227, 1227, 1227, 1227, 1262, 1262]


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


# ================== INLINE_OPTION_VALUE_V0_BEGIN ==================
# SELF-CONTAINED: pure builtins only. No type annotations, no imports, no src
# references. Copied VERBATIM into the candidate main.py by the generator.

# Option ``type`` -> coarse action family (positively-observed cabt codes only).
# Parity-tested against ptcg_activegraph.analysis.action_resolver.OPTION_TYPE_CLASS.
OPTION_TYPE_CLASS = {
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

# Action family -> linear-model family feature key.
FAMILY_FEATURE = {
    "attack": "fam_attack",
    "attach_energy": "fam_attach_energy",
    "play_from_hand": "fam_play_from_hand",
    "use_ability": "fam_use_ability",
    "play_in_play": "fam_play_in_play",
    "move_energy": "fam_move_energy",
    "select_card": "fam_select_card",
    "effect_choice": "fam_effect_choice",
    "end_turn": "fam_end_turn",
    "unknown": "fam_other",
}

FEATURE_KEYS = (
    "bias", "fam_attack", "fam_attach_energy", "fam_play_from_hand",
    "fam_use_ability", "fam_play_in_play", "fam_move_energy", "fam_select_card",
    "fam_effect_choice", "fam_end_turn", "fam_other",
)

# cg AreaType codes (target area, observed in real frames: 4=active, 5=bench).
AREA_ACTIVE = 4
AREA_BENCH = 5
# cg zone codes for the card an option PLAYS / SELECTS (observed: 1=deck, 2=hand).
ZONE_DECK = 1
ZONE_HAND = 2

# Coarse role-bucket tokens an embedded per-deck role map may carry per card id.
ROLE_TOKENS = (
    "energy", "basic", "evo", "item", "supporter", "tool", "stadium",
    "search", "draw", "attacker", "ex",
)

# Lexicographic scale: in the conservative mode the family score is multiplied by this so
# it strictly dominates the (bounded) option-value layer. Option value is clamped below
# this in repo-side validation so the domination is exact.
LEX_SCALE = 1000000.0


def _num(x):
    try:
        if isinstance(x, bool):
            return 0.0
        return float(x)
    except Exception:
        return 0.0


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _card_id(obj):
    if isinstance(obj, bool):
        return None
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict):
        for k in ("card_id", "id", "cardId"):
            v = obj.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                return v
    return None


def family_for_option(option):
    """Coarse, honest action family for a raw cg option dict (never raises)."""
    if not isinstance(option, dict):
        return "unknown"
    return OPTION_TYPE_CLASS.get(option.get("type"), "unknown")


def _raw_options(select):
    opts = None
    try:
        if isinstance(select, dict):
            opts = select.get("option")
            if not isinstance(opts, list):
                opts = select.get("options")
            if not isinstance(opts, list):
                opts = select.get("choices")
    except Exception:
        opts = None
    return opts if isinstance(opts, list) else []


def _your_player(board):
    try:
        if not isinstance(board, dict):
            return None
        players = board.get("players")
        if not isinstance(players, list) or not players:
            return None
        yi = board.get("yourIndex")
        if not isinstance(yi, int) or isinstance(yi, bool) or yi < 0 or yi >= len(players):
            yi = 0
        p = players[yi]
        return p if isinstance(p, dict) else None
    except Exception:
        return None


def _your_hand(board):
    you = _your_player(board)
    hand = you.get("hand") if isinstance(you, dict) else None
    return hand if isinstance(hand, list) else []


def _select_deck(select):
    deck = select.get("deck") if isinstance(select, dict) else None
    return deck if isinstance(deck, list) else []


def resolve_play_card(option, select, board):
    """Resolve the card id an option PLAYS / SELECTS (never raises, None if unknown).

    Order: a direct card id on the option; then the option's ``area``/``index`` against
    the OFFERED ``select.deck`` (zone 1) or YOUR ``hand`` (zone 2); then a bare ``index``
    with no area is treated as a hand index (the play-from-hand convention). Only your own
    visible cards and the offered menu are read.
    """
    try:
        if not isinstance(option, dict):
            return None
        direct = _card_id(option)
        if direct is not None:
            return direct
        area = option.get("area")
        index = option.get("index")
        if not _is_int(index):
            return None
        if area == ZONE_DECK:
            deck = _select_deck(select)
            if 0 <= index < len(deck):
                return _card_id(deck[index])
            return None
        if area == ZONE_HAND or area is None:
            hand = _your_hand(board)
            if 0 <= index < len(hand):
                return _card_id(hand[index])
        return None
    except Exception:
        return None


def _target_poke(option, board):
    """Return the option's in-play target poke dict and area label (never raises)."""
    try:
        if not isinstance(option, dict):
            return None, "none"
        area = option.get("inPlayArea")
        index = option.get("inPlayIndex")
        if not _is_int(index):
            return None, "none"
        you = _your_player(board)
        if area == AREA_ACTIVE:
            active = you.get("active") if isinstance(you, dict) else None
            if isinstance(active, list) and 0 <= index < len(active):
                return active[index], "active"
            return None, "active"
        if area == AREA_BENCH:
            bench = you.get("bench") if isinstance(you, dict) else None
            if isinstance(bench, list) and 0 <= index < len(bench):
                return bench[index], "bench"
            return None, "bench"
        return None, "none"
    except Exception:
        return None, "none"


def _poke_energy_count(poke):
    try:
        if not isinstance(poke, dict):
            return 0
        ec = poke.get("energyCards")
        if isinstance(ec, list) and ec:
            return len(ec)
        en = poke.get("energies")
        if isinstance(en, list):
            return len(en)
        if _is_int(en):
            return en
        return 0
    except Exception:
        return 0


def _has_productive_alternative(select):
    try:
        for o in _raw_options(select):
            if family_for_option(o) != "end_turn":
                return True
        return False
    except Exception:
        return False


def extract_features(option, select=None, board=None):
    """Interpretable feature dict for one option (never raises).

    Carries: ``bias``, the family one-hot key, ``family``; the resolved played/selected
    ``resolved_card_id``; the in-play ``target_card_id`` / ``target_area`` /
    ``target_energy_count``; and ``productive_alternatives``. ``select`` / ``board`` are
    the live select menu and your own ``current`` board. Role interpretation of the ids is
    deferred to ``score_option`` (which holds the embedded role map), so features stay
    profile-independent and purely observational.
    """
    feats = {"bias": 1.0}
    try:
        fam = family_for_option(option)
    except Exception:
        fam = "unknown"
    feats["family"] = fam
    feats[FAMILY_FEATURE.get(fam, "fam_other")] = 1.0
    try:
        feats["resolved_card_id"] = resolve_play_card(option, select, board)
    except Exception:
        feats["resolved_card_id"] = None
    try:
        tpoke, tarea = _target_poke(option, board)
        feats["target_area"] = tarea
        feats["target_card_id"] = _card_id(tpoke) if tpoke is not None else None
        feats["target_energy_count"] = _poke_energy_count(tpoke)
    except Exception:
        feats["target_area"] = "none"
        feats["target_card_id"] = None
        feats["target_energy_count"] = 0
    try:
        feats["productive_alternatives"] = (
            1.0 if _has_productive_alternative(select) else 0.0)
    except Exception:
        feats["productive_alternatives"] = 0.0
    return feats


def _role_tokens(role_map, cid):
    try:
        if not isinstance(role_map, dict) or cid is None:
            return ()
        v = role_map.get(str(cid))
        if v is None:
            v = role_map.get(cid)
        if isinstance(v, list):
            return tuple(t for t in v if isinstance(t, str))
        if isinstance(v, str):
            return (v,)
        return ()
    except Exception:
        return ()


def _family_score(features, profile):
    try:
        weights = {}
        if isinstance(profile, dict):
            w = profile.get("weights")
            if isinstance(w, dict):
                weights = w
        total = _num(weights.get("bias", 0.0)) * _num(features.get("bias", 0.0))
        fam = features.get("family", "unknown")
        fam_key = FAMILY_FEATURE.get(fam, "fam_other")
        total += _num(weights.get(fam_key, 0.0))
        return total
    except Exception:
        return 0.0


def option_value(features, profile):
    """The transparent option-specific value layer (never raises, 0.0 when no map/weights).

    Sums the role-bucket weights of the card an option plays/selects, plus the target-area
    weight, a per-energy weight times the target's visible energy count, the target's own
    role-bucket weights, and an end-with-productive-alternatives penalty. With no
    ``option_weights`` it returns 0.0 so the model reduces to the family floor.
    """
    try:
        if not isinstance(profile, dict):
            return 0.0
        ow = profile.get("option_weights")
        if not isinstance(ow, dict):
            return 0.0
        role_map = profile.get("role_map")
        total = 0.0
        cid = features.get("resolved_card_id")
        for tok in _role_tokens(role_map, cid):
            total += _num(ow.get("role_" + tok, 0.0))
        tarea = features.get("target_area")
        if tarea == "active":
            total += _num(ow.get("tgt_active", 0.0))
        elif tarea == "bench":
            total += _num(ow.get("tgt_bench", 0.0))
        if tarea in ("active", "bench"):
            total += _num(ow.get("tgt_per_energy", 0.0)) * _num(
                features.get("target_energy_count", 0.0))
            tcid = features.get("target_card_id")
            for tok in _role_tokens(role_map, tcid):
                total += _num(ow.get("tgt_role_" + tok, 0.0))
        if features.get("family") == "end_turn" and _num(
                features.get("productive_alternatives", 0.0)) > 0.0:
            total += _num(ow.get("end_with_alternatives", 0.0))
        return total
    except Exception:
        return 0.0


def score_option(features, profile):
    """Transparent score for one option (never raises, always a float).

    ``additive`` mode: ``family_score + option_value``. ``lexicographic`` mode (the
    conservative profile): ``family_score * LEX_SCALE + option_value`` so the family layer
    strictly dominates and the option layer only breaks ties within a family.
    """
    try:
        if not isinstance(features, dict):
            return 0.0
        mode = "additive"
        if isinstance(profile, dict) and profile.get("scoring_mode") == "lexicographic":
            mode = "lexicographic"
        fam = _family_score(features, profile)
        opt = option_value(features, profile)
        if mode == "lexicographic":
            return fam * LEX_SCALE + opt
        return fam + opt
    except Exception:
        return 0.0


def _select_counts(select):
    """Return (options_list, n_options, min_count, max_count) (never raises)."""
    opts = _raw_options(select)
    n = len(opts)
    mn = select.get("minCount") if isinstance(select, dict) else None
    mx = select.get("maxCount") if isinstance(select, dict) else None
    try:
        mn = int(mn)
    except Exception:
        mn = 1
    try:
        mx = int(mx)
    except Exception:
        mx = mn
    if mn < 0:
        mn = 0
    if mx < mn:
        mx = mn
    return opts, n, mn, mx


def score_options(select, board, profile):
    """Return a list of (index, score, family) for every option (never raises)."""
    out = []
    try:
        opts, n, _mn, _mx = _select_counts(select)
        for i in range(n):
            o = opts[i]
            try:
                fam = family_for_option(o)
                sc = score_option(extract_features(o, select, board), profile)
            except Exception:
                fam, sc = "unknown", 0.0
            out.append((i, sc, fam))
    except Exception:
        return out
    return out


def choose_indices(select, board, profile):
    """Pick a LEGAL select-index list maximising the profile score (never raises).

    Picks the minimum required count (at least one when selection is allowed) of the
    highest-scoring distinct options, tie-broken by lowest index. Returns ``[]`` only when
    no selection is possible; the caller supplies its own legal fallback.
    """
    try:
        opts, n, mn, mx = _select_counts(select)
        if n == 0:
            return []
        scored = []
        for i in range(n):
            try:
                sc = score_option(extract_features(opts[i], select, board), profile)
            except Exception:
                sc = 0.0
            scored.append((sc, -i, i))
        scored.sort(reverse=True)
        k = mn if mn >= 1 else 1
        if k > mx:
            k = mx
        if k > n:
            k = n
        if k <= 0:
            return []
        chosen = sorted(t[2] for t in scored[:k])
        return chosen
    except Exception:
        return []
# ================== INLINE_OPTION_VALUE_V0_END ==================


# ---------------------------------------------------------------------------
# Entrypoint — fast per-option value planner over raw options (no online Search).
# ---------------------------------------------------------------------------
def agent(obs_dict):
    """Kaggle/cg entrypoint. Always returns list[int] of legal indices."""
    # 0. Deck-submission step (select present but null) -> return 60 card ids.
    try:
        if isinstance(obs_dict, dict) and "select" in obs_dict \
                and obs_dict["select"] is None:
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

    # 1. Fast per-option value scorer over the raw options (inlined, never-raise).
    try:
        board = obs_dict.get("current") if isinstance(obs_dict, dict) else None
        decision = choose_indices(select, board, _PROFILE)
    except Exception:
        decision = None
    if decision:
        out = _validate(decision, n, mn, mx)
        if out:
            return out

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
            "select": {"option": [{"type": 13}, {"type": 8}, {"type": 14}],
                       "maxCount": 1, "minCount": 0}}
    print("demo:", agent(demo))
