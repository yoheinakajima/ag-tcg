"""Runtime agent wrapper.

This module exposes ``agent(obs_dict) -> list[int]``. When the richer
``ptcg_activegraph`` package is importable (e.g. during lab runs or if the
package is vendored into the submission), it delegates to the package's
configured agent. Otherwise it falls back to a self-contained embedded policy
that mirrors ``main.py`` so this file is safe to ship on its own.

``main.py`` imports ``agent`` from here and *re-validates* its output, so even a
misbehaving policy here cannot produce an illegal move.
"""

from __future__ import annotations

# Try the full package first (best behavior).
_package_agent = None
try:  # pragma: no cover - depends on packaging/sys.path
    from ptcg_activegraph.runtime import make_agent

    _package_agent = make_agent(use_heuristic=True, enable_search=False)
except Exception:
    _package_agent = None


# Self-contained fallback (kept in sync with main.py's embedded policy).
import json


def _serialize(option):
    if option is None:
        return ""
    if isinstance(option, str):
        return option.lower()
    if isinstance(option, (int, float, bool)):
        return str(option).lower()
    try:
        return json.dumps(option, default=str, sort_keys=True).lower()
    except Exception:
        return str(option).lower()


_POSITIVE = {
    "knock": 100, "ko": 60, "prize": 80, "attack": 80, "damage": 50,
    "evolve": 45, "evolution": 40, "attach": 40, "energy": 40, "draw": 35,
    "search": 35, "supporter": 30, "ability": 30, "skill": 30, "item": 25,
    "bench": 20, "stadium": 18, "switch": 15, "active": 12,
}
_NEGATIVE = {"end": -100, "pass": -100, "discard": -20, "trash": -20, "retreat": -10}


def _score(option):
    text = _serialize(option)
    s = 0
    for kw, w in _POSITIVE.items():
        if kw in text:
            s += w
    for kw, w in _NEGATIVE.items():
        if kw in text:
            if kw in ("discard", "trash") and any(
                r in text for r in ("draw", "search", "attack", "attach", "evolve")
            ):
                continue
            s += w
    return s


def _embedded(obs):
    if not isinstance(obs, dict):
        return []
    select = obs.get("select")
    if not isinstance(select, dict):
        return []
    options = select.get("options")
    if not isinstance(options, list) or not options:
        return []
    num = len(options)
    try:
        max_count = int(select.get("maxCount", 1))
    except (TypeError, ValueError):
        max_count = 1
    if max_count <= 0:
        return []
    max_count = min(max_count, num)
    ranked = sorted(range(num), key=lambda i: (-_score(options[i]), i))
    if max_count == 1:
        return [ranked[0]]
    return sorted(ranked[:max_count])


def agent(obs_dict):
    """Return a list of legal option indices for the observation."""
    if _package_agent is not None:
        try:
            return _package_agent(obs_dict)
        except Exception:
            pass
    return _embedded(obs_dict)
