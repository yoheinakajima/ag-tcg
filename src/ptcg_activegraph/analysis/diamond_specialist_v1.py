"""PASS 46L — Diamond cg_typed SPECIALIST TURN PLANNER v1 (pure / never-raise).

v1 is a NARROW, namespace-independent STRUCTURAL upgrade of the Pass-46J v0 planner. The
Pass-46L Part-B trace audit + resolution probe showed the role-keyed search/bench/discard/
attach refinements fire on only ~10% of live reference decisions (a card-id grounding gap,
not a policy gap) and that attack/end-turn gating is already correct live; so v1 changes ONLY
the levers that read the live board directly (target board zone + visible attached-energy
count): a stronger attach-to-active preference, a harsher already-energized penalty, and a
small most-energized-promote tilt. Everything else (attack/end-turn policy, attackId tie-break,
the role-keyed tables, the deckout draw guard, the role-id map) is kept BYTE-FOR-BYTE from v0;
extending the role-id map from observed play would be inventing card ids and is forbidden.

This is the ONE owned definition of the Pass-46J deck-specific turn planner for the
internal parent deck ``diamond_toolbox_diancie``. Unlike the Pass-46H *flat* per-option
scorers (a static family floor + a linear option-value layer), this module is a real
**planner**: it computes a single :func:`make_turn_plan` ``DiamondTurnPlan`` ONCE per
decision from a visible-only :func:`make_board_view` ``DiamondBoardView`` and then ranks
the legal option indices *in line with that shared plan* via :func:`choose_indices`, so the
agent's attach / search / discard / attack choices on a turn COHERE around one intent.

Design constraints (enforced, same spirit as 46F/46G/46H):

* **Pure** — no Object Storage, no EventStore, no production access, no candidate
  generation, no public-reference imports, no native ``cg`` import, no file I/O, and NO
  online Search in the hot path. Import does no I/O.
* **Never-raise** — every public function returns a safe value rather than raising; any
  parse failure degrades to an honest-unknown plan and the caller's legal fallback.
* **Self-contained INLINE region** — the code between ``INLINE_DIAMOND_SPECIALIST_V1_BEGIN``
  / ``INLINE_DIAMOND_SPECIALIST_V1_END`` is pure-builtin (no annotations, no third-party or
  src imports) so the candidate generator can embed it VERBATIM into a Kaggle ``main.py``. A
  parity test re-extracts the region from the built tarball and asserts it is byte-identical
  AND behaviourally identical to this module.
* **Dispatch by raw option ``type`` code / action_class** — NEVER by the ``turn_primitives``
  family-name strings (whose vocabulary differs: attach / ability / main_play / evolve /
  unknown). See the blueprint ``dispatch_grounding`` bridge.

Honesty boundary (hard): this planner asserts NO exact damage, lethal, KO, missed-KO,
Boss/gust target, spread, best-action / best-attack, card value, tempo value, opponent
hidden-hand contents, opponent / own deck order, prize contents, or any Kaggle
score / strength. Card identities and targets are READ only from your own visible board and
the OFFERED select menu. Role buckets are COARSE deck-composition labels, not strength
claims. Energy adequacy is judged by the VISIBLE attached-energy COUNT only — never a
computed attack cost / damage threshold (attack costs are not reliably observable). The
attack policy is a heuristic *gate only* (prefer attacking over passing when the plan wants
a clock); it never ranks attacks by damage (numeric ``attackId`` only).
"""
from __future__ import annotations

# ================== INLINE_DIAMOND_SPECIALIST_V1_BEGIN ==================
# SELF-CONTAINED: pure builtins only. No type annotations, no imports, no src
# references. Copied VERBATIM into the candidate main.py by the generator.

# Owned per-deck role map for diamond_toolbox_diancie. Coarse deck-composition labels
# derived offline from the verified Part-B audit (every id checked vs EN_Card_Data.csv);
# NOT a value/strength claim. Card id -> role tokens.
DIAMOND_ROLE_MAP = {
    5: ("energy",),
    183: ("basic", "energy_accel", "bench_fill", "search"),
    186: ("basic", "backup_attacker", "search"),
    331: ("basic", "ex", "backup_attacker", "anti_ex"),
    434: ("basic", "copy_tech"),
    525: ("basic", "ex", "backup_attacker", "turn1_enabler"),
    751: ("basic", "backup_attacker", "bench_fill", "search"),
    765: ("basic", "backup_attacker", "healer"),
    766: ("basic", "ex", "main_attacker", "damage_reduction", "scaling_discard"),
    767: ("basic", "backup_attacker", "bench_fill", "search"),
    1086: ("bench_fill", "search"),
    1121: ("search",),
    1182: ("disruption",),
    1224: ("draw",),
    1231: ("search",),
}

MAIN_ATTACKER_ID = 766
ENERGY_ID = 5
# Inferred attacker preference order (copy count / HP / ex / attack presence priors);
# NOT a strength claim. Used only to break ties when choosing/promoting an active.
ATTACKER_PRIORITY = (766, 331, 525, 751, 765, 186, 767)

# Option ``type`` -> coarse action_class (positively-observed cabt codes only).
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

# cg AreaType codes (target area observed in real frames: 4=active, 5=bench).
AREA_ACTIVE = 4
AREA_BENCH = 5
# cg zone codes for the card an option PLAYS / SELECTS (observed: 1=deck, 2=hand).
ZONE_DECK = 1
ZONE_HAND = 2

# Lexicographic scale: the plan-conditioned family base dominates; the bounded
# within-family refinement only ever orders options that share a context.
DS_SCALE = 1000.0
# Strong negative so a protected discard (last main attacker / needed energy) sinks below
# every other discard option, while still remaining a LEGAL index if it is forced.
DS_PROTECT = -DS_SCALE * 50.0

DS_UNSUPPORTED_CLAIMS = (
    "exact_damage", "lethal", "ko", "missed_ko", "boss_gust_target", "spread",
    "best_action", "best_attack", "card_value", "tempo_value",
    "opponent_hand_contents", "opponent_deck_order", "own_deck_order",
    "prize_contents", "kaggle_score_or_strength",
)


def unsupported_claims():
    """Hard honesty boundary: claims this planner refuses to make (never raises)."""
    return DS_UNSUPPORTED_CLAIMS


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num(x):
    try:
        if isinstance(x, bool):
            return 0.0
        return float(x)
    except Exception:
        return 0.0


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


def _roles(cid, role_map):
    """Role tokens for a card id (never raises). ``role_map`` None -> embedded map;
    pass an explicit dict (e.g. {}) to override (the no-roles ablation)."""
    try:
        if cid is None:
            return ()
        m = DIAMOND_ROLE_MAP if role_map is None else role_map
        if not isinstance(m, dict):
            return ()
        v = m.get(cid)
        if v is None:
            v = m.get(str(cid))
        if isinstance(v, (list, tuple)):
            return tuple(t for t in v if isinstance(t, str))
        if isinstance(v, str):
            return (v,)
        return ()
    except Exception:
        return ()


def _has_role(cid, token, role_map):
    return token in _roles(cid, role_map)


def family_for_option(option):
    """Coarse, honest action_class for a raw cg option dict (never raises)."""
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


def _select_deck(select):
    deck = select.get("deck") if isinstance(select, dict) else None
    return deck if isinstance(deck, list) else []


def _your_player(board):
    try:
        if not isinstance(board, dict):
            return None
        players = board.get("players")
        if not isinstance(players, list) or not players:
            return None
        yi = board.get("yourIndex")
        if not _is_int(yi) or yi < 0 or yi >= len(players):
            yi = 0
        p = players[yi]
        return p if isinstance(p, dict) else None
    except Exception:
        return None


def _opp_player(board):
    try:
        if not isinstance(board, dict):
            return None
        players = board.get("players")
        if not isinstance(players, list) or len(players) != 2:
            return None
        yi = board.get("yourIndex")
        if not _is_int(yi) or yi < 0 or yi >= len(players):
            yi = 0
        p = players[1 - yi]
        return p if isinstance(p, dict) else None
    except Exception:
        return None


def _your_hand(board):
    you = _your_player(board)
    hand = you.get("hand") if isinstance(you, dict) else None
    return hand if isinstance(hand, list) else []


def _active_poke(player):
    """Visible active Pokemon dict for a player (never raises, None if absent)."""
    try:
        if not isinstance(player, dict):
            return None
        a = player.get("active")
        if a is None:
            a = player.get("activePokemon")
        if isinstance(a, list):
            for x in a:
                if isinstance(x, dict):
                    return x
            return None
        if isinstance(a, dict):
            return a
        return None
    except Exception:
        return None


def _bench_pokes(player):
    try:
        if not isinstance(player, dict):
            return []
        b = player.get("bench")
        if not isinstance(b, list):
            b = player.get("benchPokemon")
        if not isinstance(b, list):
            return []
        return [x for x in b if isinstance(x, dict)]
    except Exception:
        return []


def _poke_energy_count(poke):
    try:
        if not isinstance(poke, dict):
            return 0
        ec = poke.get("energyCards")
        if isinstance(ec, list):
            return len(ec)
        en = poke.get("energies")
        if isinstance(en, list):
            return len(en)
        if _is_int(en):
            return en
        ea = poke.get("attachedEnergy")
        if isinstance(ea, list):
            return len(ea)
        if _is_int(ea):
            return ea
        return 0
    except Exception:
        return 0


def _list_len_key(player, keys):
    for k in keys:
        v = player.get(k)
        if isinstance(v, list):
            return len(v)
    return None


def _int_key(player, keys):
    for k in keys:
        v = player.get(k)
        if _is_int(v):
            return v
    return None


def _player_counts(player):
    """Honest per-zone VISIBLE counts for ONE player (never raises). Hidden hand
    contents are never read — only the count. Unknown zones stay None."""
    out = {"hand_count": None, "deck_count": None, "prize_remaining": None,
           "discard_count": None, "bench_count": None, "active_present": None}
    try:
        if not isinstance(player, dict):
            return out
        hc = _list_len_key(player, ("hand",))
        if hc is None:
            hc = _int_key(player, ("handCount", "handSize"))
        out["hand_count"] = hc
        dc = _int_key(player, ("deckCount", "deckSize"))
        if dc is None:
            dc = _list_len_key(player, ("deck",))
        out["deck_count"] = dc
        pr = _list_len_key(player, ("prizes", "prizeCards", "prize"))
        if pr is None:
            pr = _int_key(player, ("prizeCount", "prizesRemaining"))
        out["prize_remaining"] = pr
        disc = _int_key(player, ("discardCount",))
        if disc is None:
            disc = _list_len_key(player, ("discard", "discardPile"))
        out["discard_count"] = disc
        out["bench_count"] = len(_bench_pokes(player))
        out["active_present"] = _active_poke(player) is not None
        return out
    except Exception:
        return out


def resolve_play_card(option, select, board):
    """Card id an option PLAYS / SELECTS (never raises, None if unknown).

    Order: a direct id on the option; then the option's ``area``/``index`` against the
    OFFERED ``select.deck`` (zone 1) or YOUR ``hand`` (zone 2); then a bare ``index`` with
    no area is treated as a hand index. Only your own visible cards and the offered menu
    are read."""
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
    """The option's in-play target poke dict + area label over YOUR board (never raises)."""
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


def _select_ctx(select):
    """Honest select-window summary (never raises)."""
    out = {"n_options": 0, "min_count": None, "max_count": None,
           "families_present": [], "is_forced_single": None}
    try:
        opts = _raw_options(select)
        n = len(opts)
        out["n_options"] = n
        if isinstance(select, dict):
            out["min_count"] = select.get("minCount")
            out["max_count"] = select.get("maxCount")
        fams = []
        for o in opts:
            f = family_for_option(o)
            if f not in fams:
                fams.append(f)
        out["families_present"] = sorted(fams)
        out["is_forced_single"] = (n <= 1)
        return out
    except Exception:
        return out


def _infer_phase(turn, self_counts, active, active_energy):
    try:
        active_present = None
        if isinstance(self_counts, dict):
            active_present = self_counts.get("active_present")
        if active is None and active_present is not True:
            if turn in (0, 1) or active_present is False:
                return "setup"
        if _is_int(turn) and turn in (0, 1):
            return "setup"
        if active is not None and _is_num(active_energy) and active_energy >= 1:
            if turn is None or (_is_int(turn) and turn >= 2):
                return "attack"
        if active is not None:
            return "develop"
        return "develop"
    except Exception:
        return "develop"


def make_board_view(select, board, role_map=None):
    """Visible-only DiamondBoardView for the acting seat (never raises). Opponent block
    carries COUNTS + the (face-up, visible) active id only — never hidden hand contents."""
    view = {"turn": None, "acting_seat": None, "went_first": None, "phase": "develop",
            "self_counts": None, "opp_counts": None, "my_active_id": None,
            "my_active_role": [], "my_bench_ids": [], "my_active_energy_count": 0,
            "opp_active_id": None, "opp_active_is_ex": None, "select_ctx": None,
            "checkable": False, "fallback_reason": None}
    try:
        view["select_ctx"] = _select_ctx(select)
        if not isinstance(board, dict):
            view["fallback_reason"] = "no_board"
            return view
        you = _your_player(board)
        turn = board.get("turn") if _is_int(board.get("turn")) else None
        view["turn"] = turn
        yi = board.get("yourIndex")
        view["acting_seat"] = yi if _is_int(yi) else None
        self_counts = _player_counts(you)
        view["self_counts"] = self_counts
        view["opp_counts"] = _player_counts(_opp_player(board))
        active = _active_poke(you)
        aid = _card_id(active)
        view["my_active_id"] = aid
        view["my_active_role"] = list(_roles(aid, role_map))
        view["my_active_energy_count"] = _poke_energy_count(active)
        view["my_bench_ids"] = [_card_id(b) for b in _bench_pokes(you)]
        opp_active = _active_poke(_opp_player(board))
        oaid = _card_id(opp_active)
        view["opp_active_id"] = oaid
        view["opp_active_is_ex"] = (_has_role(oaid, "ex", role_map)
                                    if oaid is not None else None)
        view["phase"] = _infer_phase(turn, self_counts, active,
                                     view["my_active_energy_count"])
        view["checkable"] = True
        return view
    except Exception:
        view["fallback_reason"] = "board_view_exception"
        return view


def _in_play_ids(view):
    ids = []
    aid = view.get("my_active_id")
    if aid is not None:
        ids.append(aid)
    for b in (view.get("my_bench_ids") or []):
        if b is not None:
            ids.append(b)
    return ids


def neutral_plan():
    """A plan with NO shared intent (the no-shared-plan ablation control): fixed develop
    phase, no targets, attack gate off. Scoring then falls back to generic role ordering."""
    return {"phase": "develop", "desired_active_role": "main_attacker",
            "attacker_target": None, "backup_target": None, "energy_target": None,
            "setup_bench": [], "search_targets": [], "safe_discard": [],
            "retreat_switch_goal": "none", "attack_now": False,
            "draw_deckout_safety": None, "fallback_reason": "neutral_plan", "neutral": True}


def make_turn_plan(view, role_map=None):
    """One coherent DiamondTurnPlan from a DiamondBoardView (never raises). Heuristic and
    visible-only: no damage/lethal/KO is computed anywhere."""
    plan = neutral_plan()
    plan["neutral"] = False
    plan["fallback_reason"] = None
    try:
        if not isinstance(view, dict):
            return neutral_plan()
        phase = view.get("phase") or "develop"
        plan["phase"] = phase
        self_counts = view.get("self_counts") or {}
        aid = view.get("my_active_id")
        bench_ids = view.get("my_bench_ids") or []
        in_play = _in_play_ids(view)
        active_energy = view.get("my_active_energy_count")
        active_energy = active_energy if _is_num(active_energy) else 0

        plan["desired_active_role"] = (
            "turn1_enabler" if phase == "setup" else "main_attacker")

        plan["attacker_target"] = (MAIN_ATTACKER_ID
                                   if MAIN_ATTACKER_ID in in_play else None)
        backup = None
        for cid in in_play:
            if cid != MAIN_ATTACKER_ID and _has_role(cid, "backup_attacker", role_map):
                backup = cid
                break
        plan["backup_target"] = backup

        energy_target = None
        if MAIN_ATTACKER_ID in in_play:
            energy_target = MAIN_ATTACKER_ID
        elif aid is not None and (_has_role(aid, "main_attacker", role_map)
                                  or _has_role(aid, "backup_attacker", role_map)):
            energy_target = aid
        else:
            for cid in in_play:
                if _has_role(cid, "backup_attacker", role_map):
                    energy_target = cid
                    break
        plan["energy_target"] = energy_target

        plan["setup_bench"] = ["energy_accel", "bench_fill",
                               "main_attacker", "backup_attacker"]

        bench_count = self_counts.get("bench_count")
        bench_thin = _is_int(bench_count) and bench_count < 3
        energy_short = active_energy < 2
        search_targets = []
        if MAIN_ATTACKER_ID not in in_play:
            search_targets.append(MAIN_ATTACKER_ID)
        if energy_short:
            search_targets.append(ENERGY_ID)
        if bench_thin:
            search_targets.append("bench_fill")
        search_targets.append("draw")
        search_targets.append("search")
        plan["search_targets"] = search_targets

        safe_discard = ["copy_tech", "anti_ex", "duplicate_trainer"]
        if active_energy >= 2:
            safe_discard.append("energy")
        plan["safe_discard"] = safe_discard

        plan["retreat_switch_goal"] = (
            "promote_main_attacker"
            if (MAIN_ATTACKER_ID in bench_ids and aid != MAIN_ATTACKER_ID
                and phase != "setup") else "none")

        plan["attack_now"] = bool(
            phase == "attack" and aid is not None
            and (_has_role(aid, "main_attacker", role_map)
                 or _has_role(aid, "backup_attacker", role_map))
            and active_energy >= 1)

        deck_count = self_counts.get("deck_count")
        plan["draw_deckout_safety"] = (max(0, deck_count - 1)
                                       if _is_int(deck_count) else None)

        if not view.get("checkable"):
            plan["fallback_reason"] = "view_not_checkable"
        return plan
    except Exception:
        p = neutral_plan()
        p["fallback_reason"] = "turn_plan_exception"
        return p


def _context_of(option, select, board, plan, role_map):
    """Map a raw option to ONE specialist context by raw type code / action_class +
    visible identity (never raises). Never keyed on family-name strings."""
    try:
        ac = family_for_option(option)
        if ac == "attach_energy":
            return "attach_energy"
        if ac == "use_ability":
            return "use_ability"
        if ac == "move_energy":
            return "move_energy"
        if ac == "attack":
            return "attack"
        if ac == "end_turn":
            return "end_turn"
        if ac == "effect_choice":
            if isinstance(option, dict) and _is_num(option.get("number")):
                return "draw_count"
            return "effect_choice"
        if ac == "select_card":
            deck = _select_deck(select)
            if deck:
                return "search_to_hand"
            if isinstance(option, dict) and option.get("inPlayArea") in (AREA_ACTIVE,
                                                                         AREA_BENCH):
                return "choose_active"
            if isinstance(option, dict) and option.get("area") == ZONE_DECK:
                return "search_to_hand"
            return "discard"
        if ac == "play_from_hand":
            cid = resolve_play_card(option, select, board)
            roles = _roles(cid, role_map)
            is_poke = "basic" in roles
            phase = plan.get("phase") if isinstance(plan, dict) else None
            ap = None
            sc = plan.get("_self_counts") if isinstance(plan, dict) else None
            if isinstance(sc, dict):
                ap = sc.get("active_present")
            if is_poke and phase == "setup" and ap is not True:
                return "choose_active"
            if is_poke:
                return "setup_bench"
            return "play_from_hand_engine"
        if ac == "play_in_play":
            return "play_in_play"
        return "default"
    except Exception:
        return "default"


_BASE_DEVELOP = {
    "search_to_hand": 92.0, "play_from_hand_engine": 88.0, "setup_bench": 84.0,
    "play_in_play": 82.0, "attach_energy": 80.0, "choose_active": 78.0,
    "draw_count": 72.0, "use_ability": 70.0, "move_energy": 60.0, "discard": 55.0,
    "attack": 30.0, "effect_choice": 45.0, "default": 45.0, "end_turn": 0.0,
}
_BASE_SETUP = {
    "choose_active": 95.0, "search_to_hand": 92.0, "setup_bench": 90.0,
    "play_in_play": 88.0, "play_from_hand_engine": 80.0, "draw_count": 70.0,
    "attach_energy": 60.0, "use_ability": 55.0, "discard": 50.0, "move_energy": 40.0,
    "effect_choice": 45.0, "default": 45.0, "attack": 10.0, "end_turn": 0.0,
}


def _base(context, plan):
    try:
        phase = plan.get("phase") if isinstance(plan, dict) else "develop"
        attack_now = bool(plan.get("attack_now")) if isinstance(plan, dict) else False
        table = _BASE_SETUP if phase == "setup" else _BASE_DEVELOP
        if context == "attack":
            if phase == "attack" and attack_now:
                return 95.0
            return 50.0 if attack_now else 30.0
        return table.get(context, 45.0)
    except Exception:
        return 45.0


def _within(context, option, select, board, plan, role_map):
    """Bounded, plan-driven refinement WITHIN a context (never raises). Magnitudes stay
    well below DS_SCALE so the plan-conditioned family base dominates ordering."""
    try:
        plan = plan if isinstance(plan, dict) else {}
        if context == "attack":
            # Multiple attack options are ordered by their NUMERIC ``attackId`` ONLY,
            # lowest id first. This is an ARBITRARY, deterministic, reproducible tie-break
            # — NOT a damage / best-attack / lethal / KO / missed-KO / spread claim and NOT
            # a strength ranking; the id is just a stable label. A bounded monotone
            # transform keeps the magnitude far below DS_SCALE so the plan-conditioned
            # family base still dominates ordering. A missing/invalid id stays neutral.
            aid = option.get("attackId") if isinstance(option, dict) else None
            if not _is_int(aid) or aid < 0:
                return 0.0
            return 9.0 / (1.0 + float(aid))
        if context == "attach_energy":
            tpoke, tarea = _target_poke(option, board)
            tcid = _card_id(tpoke) if tpoke is not None else None
            # v1 structural reweight (namespace-free): prefer the VISIBLE active attacker.
            s = 14.0 if tarea == "active" else 0.0
            et = plan.get("energy_target")
            if tcid is not None and et is not None and tcid == et:
                s += 40.0
            elif _has_role(tcid, "main_attacker", role_map):
                s += 30.0
            elif (_has_role(tcid, "backup_attacker", role_map)
                  or _has_role(tcid, plan.get("desired_active_role"), role_map)):
                s += 15.0
            # v1: harsher anti-overload on an already-energized target (visible count only).
            s -= 5.0 * _num(_poke_energy_count(tpoke))
            return s
        if context == "search_to_hand":
            cid = resolve_play_card(option, select, board)
            targets = plan.get("search_targets") or []
            for pos, t in enumerate(targets):
                if _is_int(t) and cid == t:
                    return 40.0 - 4.0 * pos
            roles = _roles(cid, role_map)
            for pos, t in enumerate(targets):
                if isinstance(t, str) and t in roles:
                    return 28.0 - 4.0 * pos
            if "main_attacker" in roles and plan.get("attacker_target") is None:
                return 24.0
            if "search" in roles or "draw" in roles:
                return 10.0
            return 4.0
        if context == "discard":
            cid = resolve_play_card(option, select, board)
            roles = _roles(cid, role_map)
            if cid is not None and cid == plan.get("energy_target"):
                return DS_PROTECT
            if "main_attacker" in roles:
                return DS_PROTECT
            safe = plan.get("safe_discard") or []
            for tok in roles:
                if tok in safe:
                    return 28.0
            if "duplicate_trainer" in safe and ("search" in roles or "draw" in roles
                                                or "disruption" in roles):
                return 14.0
            return 2.0
        if context == "choose_active":
            cid = resolve_play_card(option, select, board)
            roles = _roles(cid, role_map)
            phase = plan.get("phase")
            s = 0.0
            if phase == "setup":
                if "turn1_enabler" in roles:
                    s += 30.0
                if cid == MAIN_ATTACKER_ID:
                    s -= 15.0
            else:
                tpoke, _a = _target_poke(option, board)
                # v1: lead with the most-energized visible Pokemon when promoting an active.
                s += 8.0 * _num(_poke_energy_count(tpoke))
                if "main_attacker" in roles:
                    s += 20.0
            if cid in ATTACKER_PRIORITY:
                s += 4.0 * (len(ATTACKER_PRIORITY) - ATTACKER_PRIORITY.index(cid))
            return s
        if context in ("setup_bench", "play_in_play"):
            cid = resolve_play_card(option, select, board)
            roles = _roles(cid, role_map)
            if "energy_accel" in roles:
                return 25.0
            if "bench_fill" in roles:
                return 20.0
            if "main_attacker" in roles:
                return 18.0
            if "backup_attacker" in roles:
                return 15.0
            if "search" in roles:
                return 12.0
            return 5.0
        if context == "play_from_hand_engine":
            cid = resolve_play_card(option, select, board)
            roles = _roles(cid, role_map)
            if "search" in roles:
                return 25.0 if (plan.get("search_targets")) else 15.0
            if "draw" in roles:
                return 22.0
            if "disruption" in roles:
                opp = plan.get("_opp_active_present")
                return 18.0 if opp else 6.0
            return 5.0
        if context == "move_energy":
            tpoke, _a = _target_poke(option, board)
            tcid = _card_id(tpoke) if tpoke is not None else None
            if tcid is not None and tcid == plan.get("energy_target"):
                return 20.0
            return 0.0
        if context == "draw_count":
            number = option.get("number") if isinstance(option, dict) else None
            safety = plan.get("draw_deckout_safety")
            n = _num(number)
            if _is_int(safety):
                if n <= safety:
                    return 3.0 * n
                return 3.0 * safety - 20.0 * (n - safety)
            return 1.0 * n
        if context == "use_ability":
            return 5.0
        if context == "effect_choice":
            return 0.0
        return 0.0
    except Exception:
        return 0.0


def _annotate_plan(plan, view):
    """Attach a couple of visible context flags the scorer needs (never raises)."""
    try:
        if isinstance(plan, dict) and isinstance(view, dict):
            plan["_self_counts"] = view.get("self_counts")
            opp = view.get("opp_counts")
            plan["_opp_active_present"] = (opp.get("active_present")
                                          if isinstance(opp, dict) else None)
    except Exception:
        pass
    return plan


def score_options_from_plan(select, board, plan, role_map=None):
    """Rank legal options against the SHARED plan: list of (index, score, context).

    Never raises. The plan-conditioned family base dominates (DS_SCALE) and the bounded
    within-family refinement orders options that share a context."""
    out = []
    try:
        opts = _raw_options(select)
        for i in range(len(opts)):
            o = opts[i]
            try:
                ctx = _context_of(o, select, board, plan, role_map)
                sc = _base(ctx, plan) * DS_SCALE + _within(
                    ctx, o, select, board, plan, role_map)
            except Exception:
                ctx, sc = "default", 45.0 * DS_SCALE
            out.append((i, sc, ctx))
        return out
    except Exception:
        return out


def _select_counts(select):
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


def choose_indices(select, board, plan=None, role_map=None):
    """Pick a LEGAL select-index list that best matches the shared plan (never raises).

    Builds the DiamondBoardView + DiamondTurnPlan ONCE (when ``plan`` is not supplied),
    then takes the minimum required count of the highest-scoring distinct options, tie-
    broken by lowest index. Returns [] only when no selection is possible; the caller
    supplies its own legal fallback."""
    try:
        if plan is None:
            view = make_board_view(select, board, role_map)
            plan = make_turn_plan(view, role_map)
            _annotate_plan(plan, view)
        opts, n, mn, mx = _select_counts(select)
        if n == 0:
            return []
        scored = []
        for i in range(n):
            try:
                ctx = _context_of(opts[i], select, board, plan, role_map)
                sc = _base(ctx, plan) * DS_SCALE + _within(
                    ctx, opts[i], select, board, plan, role_map)
            except Exception:
                sc = 45.0 * DS_SCALE
            scored.append((sc, -i, i))
        scored.sort(reverse=True)
        k = mn if mn >= 1 else 1
        if k > mx:
            k = mx
        if k > n:
            k = n
        if k <= 0:
            return []
        return sorted(t[2] for t in scored[:k])
    except Exception:
        return []
# ================== INLINE_DIAMOND_SPECIALIST_V1_END ==================


# ----------------------- repo-side (non-INLINE) -----------------------
# Helpers used by the candidate generator, validation and tests. These may use the
# standard library and src imports freely; they are NEVER embedded into a candidate.

from pathlib import Path  # noqa: E402

INLINE_BEGIN_MARKER = "# ================== INLINE_DIAMOND_SPECIALIST_V1_BEGIN =================="
INLINE_END_MARKER = "# ================== INLINE_DIAMOND_SPECIALIST_V1_END =================="


def inline_region_text(module_path: "str | Path | None" = None) -> str:
    """Return the exact text of the INLINE region (markers inclusive) of this module.

    The candidate generator embeds this verbatim; a parity test re-extracts the region
    from the built tarball and asserts byte-identity against this return value."""
    path = Path(module_path) if module_path is not None else Path(__file__)
    text = path.read_text(encoding="utf-8")
    begin = text.index(INLINE_BEGIN_MARKER)
    end = text.index(INLINE_END_MARKER) + len(INLINE_END_MARKER)
    return text[begin:end]


def role_map_matches(reference: dict) -> dict:
    """Compare the embedded DIAMOND_ROLE_MAP against a reference role map (e.g. the
    blueprint's ``diamond_role_map``). Returns a structured diff; never raises."""
    out = {"matches": True, "missing_ids": [], "extra_ids": [], "role_diffs": {}}
    try:
        ref = {int(k): tuple(v) for k, v in (reference or {}).items()}
        mine = {int(k): tuple(v) for k, v in DIAMOND_ROLE_MAP.items()}
        for cid in sorted(set(ref) - set(mine)):
            out["missing_ids"].append(cid)
        for cid in sorted(set(mine) - set(ref)):
            out["extra_ids"].append(cid)
        for cid in sorted(set(mine) & set(ref)):
            if list(mine[cid]) != list(ref[cid]):
                out["role_diffs"][cid] = {"mine": list(mine[cid]),
                                          "reference": list(ref[cid])}
        out["matches"] = not (out["missing_ids"] or out["extra_ids"]
                              or out["role_diffs"])
        return out
    except Exception as exc:  # noqa: BLE001
        out["matches"] = False
        out["error"] = repr(exc)
        return out
