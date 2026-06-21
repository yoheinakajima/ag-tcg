"""cg_typed candidate entrypoint — cg_typed_water_anti_disruption_searchcal_v1.

OWNED PASS-46F search-calibrated FAST TURN-PLANNER candidate. The hot path is the
VERBATIM ``turn_scorer.py`` INLINE_SCORER region (an interpretable linear model
over coarse action families) driven by an embedded profile whose weights were
calibrated OFFLINE against the Pass-46E Search oracle. There is NO online Search
in this path. The deck is the selected internal source deck, copied unchanged.

No reference-agent policy code is copied; the only bundled reference asset is the
``cg`` SDK (allowed). Runtime contract: ``agent(obs_dict) -> list[int]`` of legal
option indices (or the 60 deck card ids on the deck-submission step). Never raises.

LOCAL benchmark-lane feasibility agent — NOT a Kaggle score / leaderboard /
strength claim. NO upload / submit / promote / mutate. Asserts NO exact-damage,
lethal, missed-KO, Boss-gust, spread, or globally-best action.
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

# --- Embedded Pass-46F calibrated profile (offline Search-oracle calibrated) ----
# Loaded from a JSON string so the embedded weights are byte-synced with
# data/experiments/pass46f_score_profile.json. Never raises at import.
try:
    _PROFILE = _json.loads(r'''{
  "calibrated": true,
  "calibration": {
    "gain": 1.0,
    "label_dataset": "pass46f_turn_label_dataset.json",
    "median_ref": 8.0,
    "method": "structural_prior + GAIN*clamp(median/MEDIAN_REF,-1,1)",
    "min_n": 5,
    "n_candidate_items": 271,
    "n_supported_items": 271,
    "robust_statistic": "median (mean rejected: fabricated-hidden-state outliers, e.g. select_card mean>>median)"
  },
  "no_online_search": true,
  "profile_id": "search_calibrated_v0",
  "schema_version": "pass46f_turn_scorer_v0",
  "source": "offline_search_oracle_calibration",
  "structural_prior": {
    "attach_energy": 0.5,
    "attack": 0.35,
    "effect_choice": 0.2,
    "end_turn": -0.5,
    "move_energy": 0.3,
    "play_from_hand": 0.4,
    "play_in_play": 0.4,
    "select_card": 0.3,
    "unknown": 0.1,
    "use_ability": 0.6
  },
  "unsupported_claims": {
    "best_action": "the choice is the highest-scoring family under THIS profile, not a globally optimal action.",
    "boss_gust": "no forced-switch / gust targeting is asserted.",
    "exact_damage": "the scorer ranks action families; it computes no damage.",
    "lethal": "no KO / lethal is computed or asserted.",
    "missed_ko": "no missed-KO is computed or asserted.",
    "spread": "no spread distribution is asserted."
  },
  "weights": {
    "bias": 0.0,
    "fam_attach_energy": 1.5,
    "fam_attack": 0.975,
    "fam_effect_choice": 0.2,
    "fam_end_turn": -0.5,
    "fam_move_energy": 0.3,
    "fam_other": 0.1,
    "fam_play_from_hand": 0.4,
    "fam_play_in_play": 0.4,
    "fam_select_card": 0.3,
    "fam_use_ability": 0.6
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


# ===================== INLINE_SCORER_BEGIN =====================
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

# Action family -> linear-model feature key.
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


def family_for_option(option):
    """Coarse, honest action family for a raw cg option dict (never raises)."""
    if not isinstance(option, dict):
        return "unknown"
    return OPTION_TYPE_CLASS.get(option.get("type"), "unknown")


def extract_features(option, select=None, board=None):
    """Interpretable feature dict for one option. v0 = bias + one family one-hot.

    ``select`` / ``board`` are accepted for forward-compatibility (richer context
    features) but are intentionally unused in v0 to keep the model interpretable
    and the offline calibration tractable. Never raises.
    """
    feats = {"bias": 1.0}
    try:
        fam = family_for_option(option)
        key = FAMILY_FEATURE.get(fam, "fam_other")
    except Exception:
        key = "fam_other"
    feats[key] = 1.0
    return feats


def score_option(features, profile):
    """Linear weighted sum of features under ``profile['weights']`` (never raises)."""
    try:
        weights = {}
        if isinstance(profile, dict):
            w = profile.get("weights")
            if isinstance(w, dict):
                weights = w
        total = 0.0
        if isinstance(features, dict):
            for fk, fv in features.items():
                try:
                    total += float(weights.get(fk, 0.0)) * float(fv)
                except Exception:
                    continue
        return total
    except Exception:
        return 0.0


def _select_counts(select):
    """Return (options_list, n_options, min_count, max_count) (never raises)."""
    opts = []
    if isinstance(select, dict):
        opts = select.get("option")
        if not isinstance(opts, list):
            opts = select.get("options")
        if not isinstance(opts, list):
            opts = []
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

    Picks the minimum required count (at least one when selection is allowed) of
    the highest-scoring distinct options, tie-broken by lowest index. Returns ``[]``
    only when no selection is possible; the caller supplies its own legal fallback.
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
# ===================== INLINE_SCORER_END =====================


# ---------------------------------------------------------------------------
# Entrypoint — fast calibrated turn-planner over raw options (no online Search).
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

    # 1. Fast calibrated scorer over the raw options (inlined, never-raise).
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
