"""StrategyProfile access + validation.

A StrategyProfile is a JSON-safe dict describing how to pilot one deck. It is the
deck-specific input the typed tactics consume. Profiles are authored in
experiments/strategy_profiles.yaml; the compiler inlines the reduced literal for
ONE deck into a candidate. All accessors tolerate missing keys.

Profile shape:
    {
      "id": str,
      "executable": bool,           # may a generic compiled candidate run it?
      "lane": "stdlib_typed_lite",
      "implemented_contexts": [int,...],   # 0,1,2,7,8,38
      "unsupported_mechanics": [str,...],  # attack_damage/spread/boss/lethal/...
      "roles": {role: [card_id,...]},      # primary_attacker, setup_basic,
                                           # energy_accel, draw_engine,
                                           # key_item, search, tech
      "priority": [card_id,...],    # global want order (setup/search)
      "energy_types": [str,...],    # deck's attacker energy colors
      "deck_plan": {...},           # human-facing plan (not executed directly)
      "deckout_guard": {"min_deck": int, "max_draw": int|None},
      "discard_keep": [card_id,...],   # never discard if avoidable
      "discard_prefer": [card_id,...], # discard first when forced
      "card_ids": [card_id,...],
      "parent": str|None,
      "risks": [str,...],
    }
"""
from __future__ import annotations

from typing import Any

_ROLE_KEYS = ("primary_attacker", "setup_basic", "energy_accel", "draw_engine",
              "key_item", "search", "tech", "bench_sitter")

KNOWN_UNSUPPORTED = ("attack_damage", "lethal", "ko_targeting", "spread",
                     "boss", "gust", "opponent_hand")


def _as_int_list(v: Any) -> list:
    out = []
    if isinstance(v, list):
        for x in v:
            if isinstance(x, int) and not isinstance(x, bool):
                out.append(x)
    return out


def profile_id(profile: Any) -> Any:
    return profile.get("id") if isinstance(profile, dict) else None


def is_executable(profile: Any) -> bool:
    return bool(profile.get("executable")) if isinstance(profile, dict) else False


def implemented_contexts(profile: Any) -> tuple:
    if isinstance(profile, dict):
        return tuple(_as_int_list(profile.get("implemented_contexts")))
    return tuple()


def unsupported_mechanics(profile: Any) -> list:
    if isinstance(profile, dict):
        v = profile.get("unsupported_mechanics")
        if isinstance(v, list):
            return [str(x) for x in v]
    return []


def roles(profile: Any) -> dict:
    if isinstance(profile, dict):
        r = profile.get("roles")
        if isinstance(r, dict):
            return {str(k): _as_int_list(v) for k, v in r.items()}
    return {}


def role_ids(profile: Any, role: str) -> list:
    return roles(profile).get(role, [])


def all_role_ids(profile: Any) -> list:
    seen = []
    for ids in roles(profile).values():
        for cid in ids:
            if cid not in seen:
                seen.append(cid)
    return seen


def priority(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("priority"))
    return []


def energy_types(profile: Any) -> list:
    if isinstance(profile, dict):
        v = profile.get("energy_types")
        if isinstance(v, list):
            return [str(x) for x in v]
    return []


def deckout_guard(profile: Any) -> dict:
    if isinstance(profile, dict):
        g = profile.get("deckout_guard")
        if isinstance(g, dict):
            return g
    return {}


def discard_keep(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("discard_keep"))
    return []


def discard_prefer(profile: Any) -> list:
    if isinstance(profile, dict):
        return _as_int_list(profile.get("discard_prefer"))
    return []


def priority_rank(profile: Any, cid: Any) -> int:
    """Lower rank = more wanted. Cards not listed sort after listed ones."""
    pr = priority(profile)
    if cid in pr:
        return pr.index(cid)
    return len(pr) + 1000


def validate_profile(profile: Any) -> dict:
    """Return {ok, errors, warnings}. Never raises."""
    errors = []
    warnings = []
    if not isinstance(profile, dict):
        return {"ok": False, "errors": ["profile is not a dict"], "warnings": []}
    if not profile.get("id"):
        errors.append("missing id")
    if profile.get("lane") not in (None, "stdlib_typed_lite"):
        warnings.append("unexpected lane %r" % profile.get("lane"))
    for ctx in implemented_contexts(profile):
        if ctx not in (0, 1, 2, 7, 8, 38):
            warnings.append("context %r not a known typed context" % ctx)
    for m in unsupported_mechanics(profile):
        if m not in KNOWN_UNSUPPORTED:
            warnings.append("unsupported mechanic %r unrecognized" % m)
    if is_executable(profile) and not roles(profile):
        warnings.append("executable profile has no roles")
    # Honesty guard: an executable profile must NOT claim any unsupported
    # mechanic as an implemented context.
    return {"ok": not errors, "errors": errors, "warnings": warnings}
