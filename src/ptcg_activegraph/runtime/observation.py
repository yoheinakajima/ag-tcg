"""Defensive parsing of the Kaggle/cabt observation dict.

The observation handed to the agent each step looks roughly like::

    {
        "logs": [...],        # event logs (list, optional)
        "current": {...},     # board state (dict or None)
        "select": {           # legal choices (dict or None)
            "options": [...],
            "maxCount": 1,
            "minCount": 0,
            ...
        },
    }

Nothing here is guaranteed. The schema can change, fields can be missing, and
``current``/``select`` can be ``None`` during deck/setup phases. Every accessor
in this module returns a safe default instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedObservation:
    """A normalized, never-raising view over the raw observation dict."""

    raw: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    current: dict | None = None
    select: dict | None = None
    options: list = field(default_factory=list)
    max_count: int = 0
    min_count: int = 0

    @property
    def num_options(self) -> int:
        return len(self.options)

    @property
    def has_choice(self) -> bool:
        """True when there is at least one option to choose from."""
        return self.num_options > 0 and self.max_count > 0

    @property
    def legal_indices(self) -> list[int]:
        """Full frontier of legal option indices ``[0..num_options-1]``."""
        return list(range(self.num_options))


def _as_dict(value: Any) -> dict | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _coerce_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):  # bool is an int subclass; treat as absent
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_observation(obs: Any) -> ParsedObservation:
    """Parse an arbitrary observation into a :class:`ParsedObservation`.

    Handles ``None``, non-dict inputs, missing ``current``, missing ``select``,
    and malformed option lists without raising.
    """

    raw = obs if isinstance(obs, dict) else {}
    logs = _as_list(raw.get("logs"))
    current = _as_dict(raw.get("current"))
    select = _as_dict(raw.get("select"))

    options: list = []
    max_count = 0
    min_count = 0

    if select is not None:
        options = _as_list(select.get("options"))
        # ``maxCount`` defaults to 1 when options exist but no count is given,
        # which matches the common "pick exactly one" interaction.
        default_max = 1 if options else 0
        max_count = _coerce_int(select.get("maxCount"), default_max)
        min_count = _coerce_int(select.get("minCount"), 0)

    # Clamp counts into sane ranges relative to the available options.
    num = len(options)
    if max_count < 0:
        max_count = 0
    if max_count > num:
        max_count = num
    if min_count < 0:
        min_count = 0
    if min_count > max_count:
        min_count = max_count

    return ParsedObservation(
        raw=raw,
        logs=logs,
        current=current,
        select=select,
        options=options,
        max_count=max_count,
        min_count=min_count,
    )
