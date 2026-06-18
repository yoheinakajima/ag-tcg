"""Layer 2 scoring — deck-agnostic, mechanics/role based.

Every function returns a float where higher == better. They never raise and never
produce an action; the decision layer turns scores into legal selections. Standard
library only (embeddable). Card ids are never referenced directly — only roles.
"""
from __future__ import annotations

from typing import Any

from ptcg_activegraph.pilot.roles import has_role, load_playbook_roles
from ptcg_activegraph.pilot.state import card_id, in_play_card_ids


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
