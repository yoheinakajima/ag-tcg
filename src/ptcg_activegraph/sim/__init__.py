"""Local simulation: cabt adapter, match runner, tournament, replay IO.

All of this degrades cleanly when cabt / kaggle-environments are not installed.
See ``docs/LOCAL_SIMULATION.md``.
"""

from .cabt_adapter import CabtAdapter, is_available
from .local_runner import LocalRunner
from .replay_io import save_replay, load_replay
from .tournament import round_robin

__all__ = [
    "CabtAdapter",
    "is_available",
    "LocalRunner",
    "save_replay",
    "load_replay",
    "round_robin",
]
