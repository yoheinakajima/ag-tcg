"""The runtime decision cascade.

This is the heart of the submitted agent. It is dependency-free and never
raises outward: any internal error degrades to the fallback policy. The cascade
mirrors ``docs/RUNTIME_AGENT.md``::

    1. Parse observation.
    2. If no legal choice -> [].
    3. Determine maxCount/minCount.
    4. Optional search policy (off by default).
    5. Heuristic policy.
    6. Fallback policy.
    7. Validate (range, uniqueness, count) and return.

``make_agent`` builds a configured ``agent(obs) -> list[int]`` callable. The
module also exposes a ready-to-use default :func:`choose`.
"""

from __future__ import annotations

from typing import Any, Callable

from .action import option_count
from .fallback_policy import clamp_selection, fallback_select
from .heuristic_policy import heuristic_select
from .observation import parse_observation
from .search_policy import SearchPolicy
from .time_manager import TimeManager


def choose(
    obs: Any,
    *,
    use_heuristic: bool = True,
    search_policy: SearchPolicy | None = None,
    soft_budget_s: float = 0.5,
    trace: dict | None = None,
) -> list[int]:
    """Decide a legal selection for ``obs``.

    Guaranteed to return a list of unique, in-range ``int`` indices that
    respects ``maxCount``/``minCount``. ``trace`` (if provided) is populated
    with which policy produced the result — used by the lab, ignored by Kaggle.
    """
    tm = TimeManager(soft_budget_s)
    parsed = parse_observation(obs)
    num = parsed.num_options
    max_count = parsed.max_count
    min_count = parsed.min_count

    def record(policy: str) -> None:
        if trace is not None:
            trace["policy"] = policy
            trace["num_options"] = num
            trace["max_count"] = max_count
            trace["min_count"] = min_count

    # 2/3. Nothing to choose.
    if not parsed.has_choice:
        record("none")
        return []

    selection: list[int] | None = None
    policy_used = "fallback"

    # 4. Optional search policy (off unless explicitly enabled + cabt present).
    if search_policy is not None:
        try:
            result = search_policy.suggest(
                parsed.raw, parsed.legal_indices, max_count, tm
            )
            if result is not None:
                selection = result
                policy_used = "search"
        except Exception:
            selection = None

    # 5. Heuristic policy.
    if selection is None and use_heuristic:
        try:
            result = heuristic_select(parsed.options, max_count, min_count)
            if result:
                selection = result
                policy_used = "heuristic"
        except Exception:
            selection = None

    # 6. Fallback policy.
    if not selection:
        selection = fallback_select(num, max_count, min_count)
        policy_used = "fallback"

    # 7. Validate / repair.
    final = clamp_selection(selection, num, max_count, min_count)
    if not final and (min_count > 0 or max_count >= 1):
        final = fallback_select(num, max_count, min_count)
        policy_used = "fallback"

    record(policy_used)
    return final


def make_agent(
    *,
    use_heuristic: bool = True,
    enable_search: bool = False,
    soft_budget_s: float = 0.5,
) -> Callable[[Any], list[int]]:
    """Build a configured ``agent(obs) -> list[int]`` callable.

    The returned callable is hardened: any exception anywhere collapses to the
    fallback policy so it can never crash the Kaggle runtime.
    """
    search_policy = SearchPolicy(enabled=enable_search) if enable_search else None

    def agent(obs: Any) -> list[int]:
        try:
            return choose(
                obs,
                use_heuristic=use_heuristic,
                search_policy=search_policy,
                soft_budget_s=soft_budget_s,
            )
        except Exception:
            # Absolute last resort: parse minimally and take the safe default.
            try:
                parsed = parse_observation(obs)
                return fallback_select(
                    parsed.num_options, parsed.max_count, parsed.min_count
                )
            except Exception:
                return []

    return agent
