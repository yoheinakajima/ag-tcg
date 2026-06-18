"""Layer 3 helpers — card-role index built from a deck playbook.

The generic pilot reasons over *roles* (``primary_basic_attacker``, ``setup_basic``,
``evolution_payoff``, ...), never over card names. This module turns a loaded playbook
dict into a fast role index. Standard-library only (embeddable).
"""
from __future__ import annotations

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
