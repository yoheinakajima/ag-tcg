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
from __future__ import annotations

from typing import Any

from ptcg_activegraph.pilot.roles import has_role, load_playbook_roles
from ptcg_activegraph.pilot.scoring import (
    attacker_ready,
    score_attack_option,
    score_basic_active,
    score_basic_bench,
    score_discard_candidate,
    score_draw_search_action,
    score_energy_attach_target,
    score_evolution,
    score_search_target,
    score_tool_attach_target,
)
from ptcg_activegraph.pilot.state import card_id


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


def choose_to_hand(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="search_to_hand", rationale="no options")
    _, opt = _pick_best(options, lambda o: score_search_target(o, board, ri))
    return _result(card_id(opt), action_kind="search_to_hand",
                   rationale="fetch the missing plan piece")


def choose_discard(options, board, playbook):
    ri = load_playbook_roles(playbook)
    if not options:
        return _result(action_kind="discard", rationale="no options")
    need = _need_count(board, options)
    ranked = sorted(
        range(len(options)),
        key=lambda i: (-score_discard_candidate(options[i], board, ri),
                       (card_id(options[i]) if isinstance(card_id(options[i]), int)
                        else 1 << 30), i),
    )
    chosen_idx = ranked[:max(1, need)]
    chosen_ids = [card_id(options[i]) for i in sorted(chosen_idx)]
    return _result(chosen_ids[0] if chosen_ids else None, chosen_ids,
                   action_kind="discard", rationale="pay costs with excess energy")


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
