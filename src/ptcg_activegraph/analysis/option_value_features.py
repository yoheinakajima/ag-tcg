"""PASS 46H — pure, never-raise WITHIN-FAMILY per-OPTION value scorer (v0).

This is the ONE owned definition of the Pass-46H multi-profile candidate hot-path
policy. It is a SEPARATE module from the Pass-46G ``turn_planner_profiles.py`` and the
Pass-46F ``turn_scorer.py`` on purpose: each prior scorer's INLINE region is byte-frozen
inside an already-built tarball and must not change. 46H introduces a richer, still fully
interpretable contract (schema ``pass46h_option_value_v1``).

Where 46G conditioned the linear score on COARSE board-level signals (phase / target-area
role) and documented a TOP-1 *inertness* — the coarse signals rarely changed which option
won within a single legal menu — 46H asks a narrower question: do **option-specific,
strictly VISIBLE** features escape that inertness?  For every legal option it derives,
using ONLY the observable own-board and the legal select menu:

* the **card identity** an option plays / selects (resolved from the option's own
  ``area``/``index`` against your own ``hand`` or the offered ``select.deck`` list), mapped
  to a COARSE role bucket (energy / basic / evolution / item / supporter / tool / stadium /
  search / draw / attacker / ex) via an embedded per-deck ROLE MAP (JSON profile data,
  built offline from the local card CSV for ONLY this deck's ids);
* the **in-play target** an option points at (``inPlayArea`` == 4 active / 5 bench per the
  cg ``AreaType`` enum, ``inPlayIndex`` into your own active/bench), its visible energy
  COUNT, and the target's own role bucket;
* whether the option **ends the turn while productive alternatives remain** in the menu.

The score is a TRANSPARENT linear model in two layers:
``family_score = bias + family_weight`` (identical schema to the 46F/46G family floor) and
``option_value = sum(role_weight[token]) + target_area_weight + per_energy_weight*count
                 + target_role_weight + end_with_alternatives_penalty``.
Two combination modes:

* ``additive``  -> ``score = family_score + option_value``
* ``lexicographic`` -> ``score = family_score * LEX_SCALE + option_value`` (family strictly
  dominates; the option layer only ever breaks ties WITHIN a family — the conservative
  profile). ``option_value`` is bounded well below ``LEX_SCALE`` so this is exact.

With an empty ``option_weights`` / role map the model reduces EXACTLY to the family-only
floor ordering, so ``family_only_floor_v1`` is a true control directly comparable to the
46F/46G floor.

Design constraints (enforced, identical spirit to 46F/46G):

* **Pure** — no Object Storage, no EventStore, no production access, no candidate
  generation, no public-reference imports, no native ``cg`` import. Import does no I/O.
* **Never-raise** — every public function returns a safe value rather than raising.
* **Self-contained INLINE region** — the code between ``INLINE_OPTION_VALUE_V0_BEGIN`` /
  ``INLINE_OPTION_VALUE_V0_END`` is pure-builtin (no annotations, no third-party or src
  imports) so the candidate generator can embed it VERBATIM into a Kaggle ``main.py``. A
  parity test re-extracts the region from each built tarball and asserts it is
  byte-identical AND behaviourally identical to this module.

Honesty: this scorer asserts NO exact damage, lethal, missed-KO, Boss/gust, spread, or
globally-best action, and NO card-value / expected-value claim. Card identity and target
area are READ from your own visible board and the offered menu — never from hidden hand /
deck / prize contents. Role buckets are COARSE deck-composition priors, not strength
guarantees. It expresses only a *preference ordering over options, conditioned on the
option's own visible identity / target* — a within-turn planning heuristic.
"""
from __future__ import annotations

import copy
import csv
from pathlib import Path
from typing import Any, Optional

PROFILE_SCHEMA_VERSION = "pass46h_option_value_v1"

# A claim ledger this scorer refuses to make (parallel to the oracle's + 46F's + 46G's,
# extended with the option-value honesty bounds new to 46H).
UNSUPPORTED_SCORER_CLAIMS = {
    "exact_damage": "the scorer ranks options by family + coarse role; it computes no damage.",
    "lethal": "no KO / lethal is computed or asserted.",
    "missed_ko": "no missed-KO is computed or asserted.",
    "boss_gust": "no forced-switch / gust targeting is asserted.",
    "spread": "no spread distribution is asserted.",
    "best_action": "the choice is the highest-scoring option under THIS profile, "
    "not a globally optimal action.",
    "card_identity_is_visible_only": "a card's identity is resolved from the option's own "
    "area/index against YOUR visible hand or the OFFERED select.deck list; no hidden hand / "
    "deck / prize contents are read.",
    "role_is_coarse_prior": "a card's role bucket (energy/basic/evolution/item/supporter/"
    "tool/stadium/search/draw/attacker/ex) is a coarse deck-composition label from the local "
    "card CSV; it asserts no card value, tempo, or strength.",
    "target_is_area_only": "an option's target is read from its own inPlayArea (active vs "
    "bench) and inPlayIndex; it asserts only WHICH of YOUR pokemon the option points at, "
    "never that the target is correct or optimal.",
    "no_expected_value": "no win-probability / expected-value / equity for any option is "
    "computed or asserted; the score is a transparent linear preference only.",
}

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


# ----------------------- repo-side (non-INLINE) -----------------------
# Helpers used by the candidate generator, calibration, catalog and tests. These may use
# the standard library and src imports freely; they are NEVER embedded into a candidate.

# The 46F/46G family-only floor weights (``generic_progress_v0``). A 46H floor profile uses
# exactly these so it is directly comparable to the prior passes' floor ordering.
FLOOR_FAMILY_WEIGHTS = {
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
}

# Interpretable per-bucket option priors (hand-set from coarse PTCG deck-building priors,
# NOT fitted per card id — fitting per id would memorise the 46F label frames). Magnitudes
# are deliberately small (|sum| well below LEX_SCALE) and the SIGNS encode ordinary turn
# planning, in domain-priority order:
#   * ENERGY attachment is the central per-turn tempo / resource-development play, so
#     ``role_energy`` is the highest played-card weight — a "value" heuristic that ranked a
#     Tool above an Energy attach would be self-evidently miscalibrated.
#   * Card-advantage / dig (search, supporter, draw) rank next; then developing the board
#     (basics, evolutions); incremental Trainers (item, tool, stadium) rank lowest.
#   * For an in-play TARGET, value an active attacker over an idle bench sitter, with a mild
#     per-energy discount (do not over-stack one pokemon), and penalise ending the turn
#     while a productive play remains.
# These are DOMAIN priors, not weights fitted to the oracle; Part E only MEASURES them.
OPTION_VALUE_PRIORS = {
    "role_energy": 1.0,
    "role_search": 0.9,
    "role_supporter": 0.8,
    "role_draw": 0.7,
    "role_basic": 0.6,
    "role_evo": 0.4,
    "role_item": 0.35,
    "role_attacker": 0.3,
    "role_tool": 0.25,
    "role_stadium": 0.2,
    "role_ex": 0.2,
    "tgt_active": 0.6,
    "tgt_bench": 0.2,
    "tgt_per_energy": -0.1,
    "tgt_role_attacker": 0.5,
    "tgt_role_ex": 0.4,
    "tgt_role_evo": 0.2,
    "tgt_role_basic": 0.0,
    "end_with_alternatives": -0.8,
}

# CSV column holding the real card supertype/stage (Category is mostly "n/a" here; see
# .agents/memory/card-data-csv-quirks.md and pilot_typed/compiler._row_to_meta).
_STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"

_SEARCH_PHRASES = ("search your deck", "search for", "look at the top")
_DRAW_PHRASES = ("draw a card", "draw 2", "draw 3", "draw cards", "draw card",
                 "draw until", "draw the")


def _read_card_rows(card_csv, deck_ids):
    """Read raw EN_Card_Data rows for ONLY ``deck_ids`` (never raises, {} on failure)."""
    wanted = {int(c) for c in deck_ids if isinstance(c, int) and not isinstance(c, bool)}
    rows: dict = {}
    path = Path(card_csv)
    if not path.exists() or not wanted:
        return rows
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw = row.get("Card ID") or row.get("card_id") or row.get("id")
                try:
                    cid = int(str(raw).strip())
                except (TypeError, ValueError):
                    continue
                if cid in wanted:
                    rows[cid] = row
    except Exception:
        return {}
    return rows


def classify_card_roles(meta_entry, raw_row):
    """Return the coarse role-token list for one card (never raises).

    ``meta_entry`` is a ``pilot_typed.compiler.build_metadata_table`` entry (the audited
    card-type/stage/ex classifier); ``raw_row`` is the raw CSV row (for the trainer subtype,
    attacker, and search/draw text). Tokens are a coarse deck-composition label only.
    """
    tokens: list = []
    try:
        meta_entry = meta_entry if isinstance(meta_entry, dict) else {}
        raw_row = raw_row if isinstance(raw_row, dict) else {}
        ctype = meta_entry.get("card_type")
        stage_type = str(raw_row.get(_STAGE_COL) or "").lower()
        if ctype == "energy":
            tokens.append("energy")
        elif ctype == "trainer":
            if "supporter" in stage_type:
                tokens.append("supporter")
            elif "stadium" in stage_type:
                tokens.append("stadium")
            elif "tool" in stage_type:
                tokens.append("tool")
            else:
                tokens.append("item")
        elif ctype == "pokemon":
            if meta_entry.get("stage") == "basic" or meta_entry.get("is_basic_pokemon"):
                tokens.append("basic")
            else:
                tokens.append("evo")
            move = str(raw_row.get("Move Name") or "").strip().lower()
            dmg = str(raw_row.get("Damage") or "").strip().lower()
            if move not in ("", "n/a") and dmg not in ("", "n/a"):
                tokens.append("attacker")
            if meta_entry.get("ex"):
                tokens.append("ex")
        eff = str(raw_row.get("Effect Explanation") or "").lower()
        if any(p in eff for p in _SEARCH_PHRASES):
            tokens.append("search")
        if any(p in eff for p in _DRAW_PHRASES):
            tokens.append("draw")
    except Exception:
        return tokens
    # De-duplicate preserving order.
    seen: set = set()
    out: list = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_deck_role_map(card_csv, deck_ids) -> dict:
    """Build ``{str(card_id): [role tokens]}`` for a deck (never raises, {} on failure).

    Uses the audited ``pilot_typed.compiler.build_metadata_table`` classifier for the hard
    card-type/stage/ex part (which reads the correct ``Stage (Pokémon)/Type ...`` column,
    NOT the mostly-"n/a" ``Category`` column), then adds the trainer subtype + attacker +
    search/draw tokens from the raw CSV text. Built OFFLINE for ONLY this deck's ids; the
    CSV is never shipped or committed and the resulting map is embedded as JSON profile data.
    """
    role_map: dict = {}
    try:
        from ..pilot_typed.compiler import build_metadata_table
        ids = sorted({int(c) for c in deck_ids
                      if isinstance(c, int) and not isinstance(c, bool)})
        meta = build_metadata_table(card_csv, ids)
        rows = _read_card_rows(card_csv, ids)
        for cid in ids:
            role_map[str(cid)] = classify_card_roles(meta.get(cid), rows.get(cid))
    except Exception:
        return role_map
    return role_map


def _floor_profile(profile_id, role_map):
    return {
        "profile_id": profile_id,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scoring_mode": "additive",
        "calibrated": False,
        "source": "family_only_floor",
        "weights": dict(FLOOR_FAMILY_WEIGHTS),
        # No option_weights -> the option layer is inert; pure family floor (control).
        "role_map": dict(role_map) if isinstance(role_map, dict) else {},
    }


def family_only_floor_v1(role_map: Optional[dict] = None) -> dict:
    """The within-family control: family weights only, option layer fully inert."""
    return _floor_profile("family_only_floor_v1", role_map or {})


def option_value_v1(role_map: Optional[dict] = None,
                    option_weights: Optional[dict] = None) -> dict:
    """Additive option-value profile: family floor + interpretable per-option priors."""
    return {
        "profile_id": "option_value_v1",
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scoring_mode": "additive",
        "calibrated": False,
        "source": "interpretable_option_priors",
        "weights": dict(FLOOR_FAMILY_WEIGHTS),
        "option_weights": dict(option_weights or OPTION_VALUE_PRIORS),
        "role_map": dict(role_map) if isinstance(role_map, dict) else {},
    }


def conservative_option_value_v1(role_map: Optional[dict] = None,
                                 option_weights: Optional[dict] = None) -> dict:
    """Lexicographic profile: family strictly dominates; option layer breaks ties only."""
    return {
        "profile_id": "conservative_option_value_v1",
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scoring_mode": "lexicographic",
        "calibrated": False,
        "source": "interpretable_option_priors_lexicographic",
        "weights": dict(FLOOR_FAMILY_WEIGHTS),
        "option_weights": dict(option_weights or OPTION_VALUE_PRIORS),
        "role_map": dict(role_map) if isinstance(role_map, dict) else {},
    }


def default_profiles(role_map: Optional[dict] = None) -> dict:
    """The three reference 46H profiles for a deck role map (floor / value / conservative)."""
    rm = role_map or {}
    return {
        "family_only_floor_v1": family_only_floor_v1(rm),
        "option_value_v1": option_value_v1(rm),
        "conservative_option_value_v1": conservative_option_value_v1(rm),
    }


def max_abs_option_value(role_map: Optional[dict] = None,
                         option_weights: Optional[dict] = None) -> float:
    """Upper bound on |option_value| given a role map + weights (lexicographic safety).

    Conservatively sums the absolute magnitude of every weight that could ever apply to a
    single option (all role tokens of the most-tokened card, both played and target, plus
    the target-area / per-energy / end penalty). Used to assert the option layer stays
    strictly below ``LEX_SCALE`` so the lexicographic domination is exact.
    """
    ow = dict(option_weights or OPTION_VALUE_PRIORS)
    rm = role_map if isinstance(role_map, dict) else {}
    max_tokens = 0
    for v in rm.values():
        if isinstance(v, list):
            max_tokens = max(max_tokens, len(v))
    role_keys = [abs(_num(ow.get("role_" + t, 0.0))) for t in ROLE_TOKENS]
    role_keys.sort(reverse=True)
    played = sum(role_keys[:max_tokens]) if max_tokens else 0.0
    tgt_role_keys = [abs(_num(ow.get("tgt_role_" + t, 0.0))) for t in ROLE_TOKENS]
    tgt_role_keys.sort(reverse=True)
    target_role = sum(tgt_role_keys[:max_tokens]) if max_tokens else 0.0
    area = max(abs(_num(ow.get("tgt_active", 0.0))), abs(_num(ow.get("tgt_bench", 0.0))))
    # A generous energy-count cap (a single pokemon never visibly holds this many).
    per_energy = abs(_num(ow.get("tgt_per_energy", 0.0))) * 12.0
    end_pen = abs(_num(ow.get("end_with_alternatives", 0.0)))
    return played + target_role + area + per_energy + end_pen


def inline_region_source() -> str:
    """Return the exact text of the INLINE_OPTION_VALUE_V0 region (generator/parity).

    The returned string is the self-contained scorer the candidate generator embeds
    verbatim into ``main.py``. Never raises (returns ``""`` on any failure).
    """
    try:
        text = Path(__file__).read_text(encoding="utf-8")
        begin = "# ================== INLINE_OPTION_VALUE_V0_BEGIN =================="
        end = "# ================== INLINE_OPTION_VALUE_V0_END =================="
        i = text.index(begin)
        j = text.index(end) + len(end)
        return text[i:j] + "\n"
    except Exception:
        return ""


def unsupported_scorer_claims() -> dict:
    """The fixed set of claims this scorer refuses to assert (stable contract)."""
    return dict(UNSUPPORTED_SCORER_CLAIMS)
