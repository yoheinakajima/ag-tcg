"""Local simulation: cabt adapter, match runner, tournament, replay IO.

All of this degrades cleanly when cabt / kaggle-environments are not installed.
See ``docs/LOCAL_SIMULATION.md``.
"""

from .cabt_adapter import CabtAdapter, is_available
from .kaggle_import_optimization import (
    disable_fast_cabt_import_stub,
    enable_fast_cabt_import_stub,
    validate_fast_import,
)
from .local_runner import LocalRunner
from .replay_io import save_replay, load_replay
from .tournament import round_robin

__all__ = [
    "CabtAdapter",
    "is_available",
    "enable_fast_cabt_import_stub",
    "disable_fast_cabt_import_stub",
    "validate_fast_import",
    "LocalRunner",
    "save_replay",
    "load_replay",
    "round_robin",
]
