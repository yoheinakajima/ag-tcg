"""Per-call soft time budget for the runtime agent.

Kaggle imposes per-step and per-game time limits. The :class:`TimeManager`
gives the agent a cheap way to ask "do I still have budget for the expensive
path (search)?" without importing anything heavyweight. It never *enforces* a
hard stop — it only advises — so it can never be the cause of an exception.
"""

from __future__ import annotations

import time


class TimeManager:
    """Tracks a soft per-call budget in seconds."""

    def __init__(self, soft_budget_s: float = 0.5) -> None:
        self.soft_budget_s = max(0.0, float(soft_budget_s))
        self._start = time.monotonic()

    def reset(self) -> None:
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        return max(0.0, self.soft_budget_s - self.elapsed)

    def has_budget(self, fraction: float = 1.0) -> bool:
        """True while less than ``fraction`` of the budget has been spent."""
        return self.elapsed < self.soft_budget_s * fraction

    def expired(self) -> bool:
        return self.elapsed >= self.soft_budget_s
