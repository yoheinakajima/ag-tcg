"""Kaggle runtime entrypoint for the PTCG AI Battle Challenge.

This file is intentionally **self-contained** and **standard-library only** so
it runs unchanged inside the Kaggle/cabt sandbox. It exposes a single function::

    def agent(obs_dict: dict) -> list[int]

which the engine calls each step with an observation dict::

    {
        "logs":    [...],     # event logs (optional)
        "current": {...},     # board state (dict or None)
        "select":  {          # legal choices (dict or None)
            "options":  [...],
            "maxCount": int,
            "minCount": int,
        },
    }

It returns a list of selected legal option indices. The engine only presents
legal moves, so the agent's job is to pick among them.

Design guarantees (see docs/RUNTIME_AGENT.md):
  * Never raises outward — any internal error degrades to a legal fallback.
  * Always returns unique, in-range indices respecting maxCount/minCount.
  * Handles missing/null ``current`` and ``select`` (deck/setup phases).

A richer policy may live in ``agent.py``; if present and well-behaved it is used,
otherwise the embedded heuristic below decides. Either way the output is
validated here before returning.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Embedded, dependency-free policy (the safety net that always works).
# ---------------------------------------------------------------------------

_POSITIVE = {
    "knock": 100, "ko": 60, "prize": 80, "attack": 80, "damage": 50,
    "evolve": 45, "evolution": 40, "attach": 40, "energy": 40, "draw": 35,
    "search": 35, "supporter": 30, "ability": 30, "skill": 30, "item": 25,
    "bench": 20, "stadium": 18, "switch": 15, "active": 12,
}
_NEGATIVE = {"end": -100, "pass": -100, "discard": -20, "trash": -20, "retreat": -10}
_DISCARD_REDEEMERS = ("draw", "search", "attack", "attach", "evolve")


def _serialize(option):
    """Serialize any option to a lower-cased text blob without raising."""
    if option is None:
        return ""
    if isinstance(option, str):
        return option.lower()
    if isinstance(option, (int, float, bool)):
        return str(option).lower()
    try:
        return json.dumps(option, default=str, sort_keys=True).lower()
    except Exception:
        try:
            return str(option).lower()
        except Exception:
            return ""


def _score(option):
    text = _serialize(option)
    score = 0
    for kw, w in _POSITIVE.items():
        if kw in text:
            score += w
    for kw, w in _NEGATIVE.items():
        if kw in text:
            if kw in ("discard", "trash") and any(r in text for r in _DISCARD_REDEEMERS):
                continue
            score += w
    return score


def _parse_select(obs):
    """Return (options, max_count, min_count), tolerant of any shape."""
    if not isinstance(obs, dict):
        return [], 0, 0
    select = obs.get("select")
    if not isinstance(select, dict):
        return [], 0, 0
    options = select.get("options")
    if isinstance(options, tuple):
        options = list(options)
    if not isinstance(options, list):
        options = []
    num = len(options)

    def _int(v, default):
        try:
            if isinstance(v, bool):
                return default
            return int(v)
        except (TypeError, ValueError):
            return default

    max_count = _int(select.get("maxCount"), 1 if num else 0)
    min_count = _int(select.get("minCount"), 0)
    if max_count < 0:
        max_count = 0
    if max_count > num:
        max_count = num
    if min_count < 0:
        min_count = 0
    if min_count > max_count:
        min_count = max_count
    return options, max_count, min_count


def _fallback(num, max_count, min_count=0):
    if num <= 0 or max_count <= 0:
        return []
    max_count = min(max_count, num)
    min_count = max(0, min(min_count, max_count))
    if max_count == 1:
        return [0]
    take = min_count if min_count > 0 else max_count
    return list(range(min(take, num)))


def _heuristic(options, max_count, min_count=0):
    num = len(options)
    if num == 0 or max_count <= 0:
        return []
    scored = sorted(range(num), key=lambda i: (-_score(options[i]), i))
    if max_count == 1:
        return [scored[0]]
    chosen = []
    for idx in scored:
        if len(chosen) >= max_count:
            break
        if _score(options[idx]) > 0 or len(chosen) < min_count:
            chosen.append(idx)
    if not chosen:
        chosen = [scored[0]]
    return sorted(chosen)


def _clamp(selection, num, max_count, min_count=0):
    """Validate/repair a selection so it is always legal."""
    if num <= 0 or max_count <= 0:
        return []
    seen = set()
    cleaned = []
    for item in selection or []:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < num and idx not in seen:
            seen.add(idx)
            cleaned.append(idx)
    if len(cleaned) > max_count:
        cleaned = cleaned[:max_count]
    if len(cleaned) < min_count:
        for idx in range(num):
            if len(cleaned) >= min_count:
                break
            if idx not in seen:
                seen.add(idx)
                cleaned.append(idx)
    if not cleaned and (min_count > 0 or max_count >= 1):
        return _fallback(num, max_count, min_count)
    return cleaned


def _embedded_agent(obs):
    options, max_count, min_count = _parse_select(obs)
    if not options or max_count <= 0:
        return []
    try:
        selection = _heuristic(options, max_count, min_count)
    except Exception:
        selection = None
    if not selection:
        selection = _fallback(len(options), max_count, min_count)
    return _clamp(selection, len(options), max_count, min_count)


def validate_result(obs, result):
    """Coerce any candidate result into a guaranteed-legal selection."""
    options, max_count, min_count = _parse_select(obs)
    if not isinstance(result, (list, tuple)):
        result = []
    return _clamp(list(result), len(options), max_count, min_count)


def fallback(obs):
    """Top-level safe fallback used if everything else fails."""
    options, max_count, min_count = _parse_select(obs)
    return _fallback(len(options), max_count, min_count)


# ---------------------------------------------------------------------------
# Optional richer policy from agent.py (used only if it behaves).
# ---------------------------------------------------------------------------

try:
    from agent import agent as _external_agent  # type: ignore
except Exception:
    _external_agent = None


def agent(obs_dict):
    """Kaggle entrypoint. Always returns a list of legal option indices."""
    # 1. Try the optional external agent, validating its output.
    if _external_agent is not None:
        try:
            result = _external_agent(obs_dict)
            validated = validate_result(obs_dict, result)
            return validated
        except Exception:
            pass
    # 2. Embedded heuristic.
    try:
        return _embedded_agent(obs_dict)
    except Exception:
        pass
    # 3. Absolute last resort.
    try:
        return fallback(obs_dict)
    except Exception:
        return []


if __name__ == "__main__":
    # Tiny smoke test so `python main.py` shows it works without Kaggle.
    demo = {
        "logs": [],
        "current": None,
        "select": {
            "options": ["End turn", "Attack: Thunderbolt 90 damage", "Attach Energy"],
            "maxCount": 1,
            "minCount": 0,
        },
    }
    print("demo selection:", agent(demo))
