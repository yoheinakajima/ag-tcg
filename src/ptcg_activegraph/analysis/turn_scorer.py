"""PASS 46F — pure, never-raise fast turn-planner scorer (single source of truth).

This module is the ONE owned definition of the candidate's fast hot-path policy.
It is *interpretable by construction*: every legal option is mapped to an honest
coarse action family (the Pass-29 ``OPTION_TYPE_CLASS`` decode) and scored by a
linear weighted sum over family features under a JSON ``profile``. There is NO
online Search in this path — the profile weights are calibrated OFFLINE against
the Pass-46E Search oracle (see ``scripts/build_pass46f_score_profile.py``).

Design constraints (enforced):

* **Pure** — no Object Storage, no EventStore, no production access, no candidate
  generation, no public-reference imports, no native ``cg`` import. Importing this
  module triggers no I/O.
* **Never-raise** — every public function returns a safe value rather than raising.
* **Self-contained INLINE region** — the code between the ``INLINE_SCORER_BEGIN`` /
  ``INLINE_SCORER_END`` markers is pure-builtin (no annotations, no third-party or
  src imports) so the candidate generator can embed it VERBATIM into a Kaggle
  ``main.py`` that cannot import ``src/``. A parity test re-extracts that region
  from the built tarball and asserts it is byte-identical AND behaviourally
  identical to this module.

Honesty: this scorer asserts NO exact damage, lethal, missed-KO, Boss/gust,
spread, or globally-best action. It only expresses a *preference ordering over
coarse action families* — a turn-planner heuristic, never a strength guarantee.
"""
from __future__ import annotations

from typing import Any, Optional

PROFILE_SCHEMA_VERSION = "pass46f_turn_scorer_v0"

# A claim ledger this scorer refuses to make (kept parallel to the oracle's).
UNSUPPORTED_SCORER_CLAIMS = {
    "exact_damage": "the scorer ranks action families; it computes no damage.",
    "lethal": "no KO / lethal is computed or asserted.",
    "missed_ko": "no missed-KO is computed or asserted.",
    "boss_gust": "no forced-switch / gust targeting is asserted.",
    "spread": "no spread distribution is asserted.",
    "best_action": "the choice is the highest-scoring family under THIS profile, "
    "not a globally optimal action.",
}

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


# Repo-side default = the uncalibrated baseline the calibrated profile is measured
# against (``generic_progress_v0``): prefer free value (abilities) and board
# development, treat attacking as progress, and end the turn LAST. Calibration may
# reorder/scale these from offline Search-oracle evidence.
DEFAULT_PROFILE = {
    "profile_id": "generic_progress_v0",
    "schema_version": PROFILE_SCHEMA_VERSION,
    "calibrated": False,
    "source": "hand_designed_baseline",
    "weights": {
        "bias": 0.0,
        "fam_use_ability": 5.0,
        "fam_attach_energy": 4.0,
        "fam_play_from_hand": 3.5,
        "fam_play_in_play": 3.0,
        "fam_attack": 2.5,
        "fam_move_energy": 2.0,
        "fam_select_card": 1.5,
        "fam_effect_choice": 1.0,
        "fam_other": 0.5,
        "fam_end_turn": -1.0,
    },
}


def baseline_profile() -> dict:
    """A fresh copy of the uncalibrated ``generic_progress_v0`` baseline profile."""
    import copy
    return copy.deepcopy(DEFAULT_PROFILE)


def inline_region_source() -> str:
    """Return the exact text of the INLINE_SCORER region (for the generator/parity).

    The returned string is the self-contained scorer the candidate generator embeds
    verbatim into ``main.py``. Never raises (returns ``""`` on any failure).
    """
    try:
        from pathlib import Path
        text = Path(__file__).read_text(encoding="utf-8")
        begin = "# ===================== INLINE_SCORER_BEGIN ====================="
        end = "# ===================== INLINE_SCORER_END ====================="
        i = text.index(begin)
        j = text.index(end) + len(end)
        return text[i:j] + "\n"
    except Exception:
        return ""


def unsupported_scorer_claims() -> dict:
    """The fixed set of claims this scorer refuses to assert (stable contract)."""
    return dict(UNSUPPORTED_SCORER_CLAIMS)
