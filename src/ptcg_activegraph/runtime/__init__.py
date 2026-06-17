"""Runtime agent: compact, safe, deterministic Pokémon TCG policy.

This subpackage holds the logic that the submitted Kaggle agent uses. It is
deliberately dependency-free (standard library only) so it can run inside the
Kaggle/cabt sandbox unchanged. The same modules are imported by the lab and by
the unit tests.

Public surface:

* :func:`agent_core.choose` — the main decision entrypoint.
* :func:`fallback_policy.fallback_select` — last-resort legal policy.
* :func:`heuristic_policy.rank_options` — keyword/field heuristic ranking.
* :func:`observation.parse_observation` — defensive observation parsing.
* :func:`action.parse_select` — defensive select/option parsing.
"""

from .agent_core import choose, make_agent
from .fallback_policy import fallback_select
from .heuristic_policy import rank_options, score_option

__all__ = [
    "choose",
    "make_agent",
    "fallback_select",
    "rank_options",
    "score_option",
]
