"""PASS 46G — pure, never-raise PHASE/ROLE-aware turn-planner scorer (v2).

This is the ONE owned definition of the Pass-46G multi-profile candidate hot-path
policy. It is a SEPARATE module from the Pass-46F ``turn_scorer.py`` on purpose: the
46F scorer's INLINE region is byte-frozen inside the already-built 46F tarball, so it
must not change. 46G introduces a richer, still fully interpretable contract
(schema ``pass46g_turn_scorer_v1``).

Like 46F it maps every legal option to an honest coarse action family, but it ALSO
conditions the linear score on two extra interpretable signals derived ONLY from the
OBSERVABLE own-board and the legal option menu:

* **phase** — a COARSE heuristic LABEL (``setup`` / ``develop`` / ``attack_ready`` /
  ``recovery`` / ``late_game``) read from your own ``current`` board: turn counter,
  whether your active exists and its visible hp fraction, your visible deck count, and
  your remaining prize COUNT (count only — prize contents stay hidden), plus whether an
  ``attack`` option is currently in the legal menu. It is a label, NOT a claim that an
  attack is good / lethal / a KO.
* **role** — a target-AREA label for an option, read straight from the option's
  ``inPlayArea`` per the cg ``AreaType`` enum (``4`` = active spot -> ``targets_active``,
  ``5`` = bench -> ``targets_bench``; otherwise ``role_none``). It only says which of
  YOUR pokemon the option targets, never that the target is correct.

The score is a TRANSPARENT additive linear model:
``score = bias + family_weight + phase_adj[phase][family] + role_adj[role]
          + end_pass_penalty(if ending with productive options left)
          + deckout_draw_penalty(if deck is low and the family is draw-ish)``.
With an empty ``phase_weights`` / ``role_weights`` and zero penalties the model
reduces EXACTLY to the 46F family-only baseline (``generic_progress_v0``), so the two
schemas are directly comparable in offline calibration.

Design constraints (enforced, identical spirit to 46F):

* **Pure** — no Object Storage, no EventStore, no production access, no candidate
  generation, no public-reference imports, no native ``cg`` import. Import does no I/O.
* **Never-raise** — every public function returns a safe value rather than raising.
* **Self-contained INLINE region** — the code between ``INLINE_SCORER_V2_BEGIN`` /
  ``INLINE_SCORER_V2_END`` is pure-builtin (no annotations, no third-party or src
  imports) so the candidate generator can embed it VERBATIM into a Kaggle ``main.py``.
  A parity test re-extracts the region from each built tarball and asserts it is
  byte-identical AND behaviourally identical to this module.

Honesty: this scorer asserts NO exact damage, lethal, missed-KO, Boss/gust, spread, or
globally-best action. ``phase`` and ``role`` are coarse observable labels, not strength
guarantees. It only expresses a *preference ordering over coarse action families,
conditioned on observable phase/role* — a turn-planner heuristic.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

PROFILE_SCHEMA_VERSION = "pass46g_turn_scorer_v1"

# A claim ledger this scorer refuses to make (kept parallel to the oracle's + 46F's,
# extended with the phase/role honesty bounds new to 46G).
UNSUPPORTED_SCORER_CLAIMS = {
    "exact_damage": "the scorer ranks action families; it computes no damage.",
    "lethal": "no KO / lethal is computed or asserted.",
    "missed_ko": "no missed-KO is computed or asserted.",
    "boss_gust": "no forced-switch / gust targeting is asserted.",
    "spread": "no spread distribution is asserted.",
    "best_action": "the choice is the highest-scoring family under THIS profile, "
    "not a globally optimal action.",
    "phase_is_label_not_claim": "phase is a coarse observable heuristic label "
    "(turn / own board / legal menu); it asserts no attack-readiness, advantage, "
    "or tempo claim.",
    "role_is_target_area_only": "role is read from the option's own inPlayArea "
    "(active vs bench); it asserts only which of YOUR pokemon an option targets, "
    "never that the target is correct or optimal.",
    "no_hidden_state": "no opponent hidden hand / deck contents / prize contents are "
    "read; only your own visible board and count-only signals are used.",
}

# ===================== INLINE_SCORER_V2_BEGIN =====================
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

# cg AreaType codes used for the honest role (target-area) label.
AREA_ACTIVE = 4
AREA_BENCH = 5

# Coarse phase-detection thresholds (fixed module constants so the phase LABEL is
# consistent across every profile; profiles differ only in how they WEIGHT a phase).
PHASE_LOW_DECK = 8        # your visible deckCount at/below this => late_game / low_deck
PHASE_LOW_PRIZE = 2       # your remaining prize COUNT at/below this => late_game
PHASE_RECOVERY_HP_FRAC = 0.5  # active visible hp <= 50% of its maxHp => recovery

# Families treated as draw-ish for the optional low-deck safety penalty (coarse prior:
# these families are the ones most associated with drawing / searching the deck).
DRAWISH_FAMILIES = ("use_ability", "select_card")


def _num(x):
    try:
        if isinstance(x, bool):
            return 0.0
        return float(x)
    except Exception:
        return 0.0


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def family_for_option(option):
    """Coarse, honest action family for a raw cg option dict (never raises)."""
    if not isinstance(option, dict):
        return "unknown"
    return OPTION_TYPE_CLASS.get(option.get("type"), "unknown")


def option_role(option):
    """Honest target-AREA label from the option's own inPlayArea (never raises).

    ``targets_active`` (inPlayArea == active spot) / ``targets_bench`` (bench) /
    ``role_none`` (no destination area in the option schema). Asserts only WHICH of
    your pokemon the option targets, never that the target is correct.
    """
    try:
        if not isinstance(option, dict):
            return "role_none"
        a = option.get("inPlayArea")
        if a == AREA_ACTIVE:
            return "targets_active"
        if a == AREA_BENCH:
            return "targets_bench"
        return "role_none"
    except Exception:
        return "role_none"


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


def _attack_available(select):
    try:
        for o in _raw_options(select):
            if family_for_option(o) == "attack":
                return True
        return False
    except Exception:
        return False


def _has_productive_alternative(select):
    try:
        for o in _raw_options(select):
            if family_for_option(o) != "end_turn":
                return True
        return False
    except Exception:
        return False


def detect_phase(select, board):
    """Coarse, honest phase LABEL from your OWN observable board + legal menu.

    Precedence: late_game (low deck / few prizes left) > attack_ready (an attack option
    is legal now) > recovery (your active visibly at <=50% hp) > setup (no active, or
    very first turn) > develop. Never raises (returns ``develop`` on any failure). Uses
    only your own visible board and COUNT-only prize/deck signals; no hidden state.
    """
    try:
        you = _your_player(board)
        deck = you.get("deckCount") if isinstance(you, dict) else None
        prize_remaining = None
        has_active = False
        active_hp = None
        active_max = None
        if isinstance(you, dict):
            pr = you.get("prize")
            if isinstance(pr, list):
                prize_remaining = len(pr)
            act = you.get("active")
            if isinstance(act, list) and act and isinstance(act[0], dict):
                has_active = True
                active_hp = act[0].get("hp")
                active_max = act[0].get("maxHp")
        turn = board.get("turn") if isinstance(board, dict) else None
        if _is_num(deck) and deck <= PHASE_LOW_DECK:
            return "late_game"
        if _is_num(prize_remaining) and prize_remaining <= PHASE_LOW_PRIZE:
            return "late_game"
        if _attack_available(select):
            return "attack_ready"
        if has_active and _is_num(active_hp) and _is_num(active_max) \
                and active_max > 0 and active_hp <= PHASE_RECOVERY_HP_FRAC * active_max:
            return "recovery"
        if not has_active:
            return "setup"
        if _is_num(turn) and turn <= 1:
            return "setup"
        return "develop"
    except Exception:
        return "develop"


def extract_features(option, select=None, board=None):
    """Interpretable feature dict for one option (never raises).

    Carries: ``bias``, the family one-hot feature key, plus the observable context
    signals ``family`` / ``phase`` / ``role`` / ``low_deck`` / ``productive_alternatives``
    used by the additive scorer. ``select`` / ``board`` are the live select menu and
    your own ``current`` board.
    """
    feats = {"bias": 1.0}
    try:
        fam = family_for_option(option)
    except Exception:
        fam = "unknown"
    feats["family"] = fam
    feats[FAMILY_FEATURE.get(fam, "fam_other")] = 1.0
    try:
        feats["role"] = option_role(option)
    except Exception:
        feats["role"] = "role_none"
    try:
        feats["phase"] = detect_phase(select, board)
    except Exception:
        feats["phase"] = "develop"
    low = 0.0
    try:
        you = _your_player(board)
        deck = you.get("deckCount") if isinstance(you, dict) else None
        if _is_num(deck) and deck <= PHASE_LOW_DECK:
            low = 1.0
    except Exception:
        low = 0.0
    feats["low_deck"] = low
    try:
        feats["productive_alternatives"] = (
            1.0 if _has_productive_alternative(select) else 0.0)
    except Exception:
        feats["productive_alternatives"] = 0.0
    return feats


def score_option(features, profile):
    """Transparent additive linear score for one option (never raises).

    score = bias + family_weight + phase_adj[phase][family] + role_adj[role]
            + end_pass_penalty (when ending with productive options remaining)
            + deckout_draw_penalty (when deck is low and the family is draw-ish).
    With empty phase/role tables and zero penalties this reduces to the family-only
    baseline ordering.
    """
    try:
        if not isinstance(features, dict):
            return 0.0
        weights = {}
        phase_weights = {}
        role_weights = {}
        epp = 0.0
        ddp = 0.0
        if isinstance(profile, dict):
            w = profile.get("weights")
            if isinstance(w, dict):
                weights = w
            pw = profile.get("phase_weights")
            if isinstance(pw, dict):
                phase_weights = pw
            rw = profile.get("role_weights")
            if isinstance(rw, dict):
                role_weights = rw
            epp = _num(profile.get("end_pass_penalty_when_productive", 0.0))
            ddp = _num(profile.get("deckout_draw_penalty", 0.0))
        fam = features.get("family", "unknown")
        fam_key = FAMILY_FEATURE.get(fam, "fam_other")
        total = 0.0
        total += _num(weights.get("bias", 0.0)) * _num(features.get("bias", 0.0))
        total += _num(weights.get(fam_key, 0.0))
        phase = features.get("phase")
        pdict = phase_weights.get(phase) if isinstance(phase_weights, dict) else None
        if isinstance(pdict, dict):
            total += _num(pdict.get(fam, 0.0))
        role = features.get("role")
        if role in role_weights:
            total += _num(role_weights.get(role, 0.0))
        if fam == "end_turn" and _num(features.get("productive_alternatives", 0.0)) > 0.0:
            total += epp
        if _num(features.get("low_deck", 0.0)) > 0.0 and fam in DRAWISH_FAMILIES:
            total += ddp
        return total
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
    highest-scoring distinct options, tie-broken by lowest index. Returns ``[]`` only
    when no selection is possible; the caller supplies its own legal fallback.
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
# ===================== INLINE_SCORER_V2_END =====================


# Reference tuples (repo-side; for the catalog / calibration / tests).
PHASES = ("setup", "develop", "attack_ready", "recovery", "late_game")
ROLES = ("targets_active", "targets_bench", "role_none")

# Repo-side default = the uncalibrated baseline every 46G profile is MEASURED against
# (``generic_progress_v0``). Identical family weights to the 46F baseline, expressed in
# the v2 schema with empty phase/role tables and zero penalties so it reduces exactly to
# the family-only ordering. Part D reports each profile's offline fit RELATIVE to this.
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
    "phase_weights": {},
    "role_weights": {},
    "end_pass_penalty_when_productive": 0.0,
    "deckout_draw_penalty": 0.0,
}


def baseline_profile() -> dict:
    """A fresh copy of the uncalibrated ``generic_progress_v0`` baseline profile."""
    return copy.deepcopy(DEFAULT_PROFILE)


def inline_region_source() -> str:
    """Return the exact text of the INLINE_SCORER_V2 region (generator/parity).

    The returned string is the self-contained scorer the candidate generator embeds
    verbatim into ``main.py``. Never raises (returns ``""`` on any failure).
    """
    try:
        from pathlib import Path
        text = Path(__file__).read_text(encoding="utf-8")
        begin = "# ===================== INLINE_SCORER_V2_BEGIN ====================="
        end = "# ===================== INLINE_SCORER_V2_END ====================="
        i = text.index(begin)
        j = text.index(end) + len(end)
        return text[i:j] + "\n"
    except Exception:
        return ""


def unsupported_scorer_claims() -> dict:
    """The fixed set of claims this scorer refuses to assert (stable contract)."""
    return dict(UNSUPPORTED_SCORER_CLAIMS)
