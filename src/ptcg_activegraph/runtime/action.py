"""Defensive parsing and serialization of ``select`` options.

The cabt option schema is not fixed. An option may be a plain string, an int, a
dict with assorted fields, or a nested structure. These helpers turn *any*
option into a stable, lower-cased text blob plus a best-effort field map so the
heuristic policy can score it without ever assuming a particular shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OptionView:
    """A normalized view of a single legal option."""

    index: int
    raw: Any
    text: str = ""
    fields: dict = field(default_factory=dict)

    def field_text(self, *names: str) -> str:
        """Return concatenated lower-cased text of the named fields, if any."""
        parts: list[str] = []
        for name in names:
            value = self.fields.get(name)
            if value is not None:
                parts.append(_to_text(value))
        return " ".join(parts).lower()


def _to_text(value: Any) -> str:
    """Serialize any value to text without raising."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except (TypeError, ValueError):
        try:
            return str(value)
        except Exception:  # pragma: no cover - extremely defensive
            return ""


def _flatten_fields(value: Any) -> dict:
    """Extract a shallow field map from dict-like options."""
    if isinstance(value, dict):
        return dict(value)
    return {}


def serialize_option(option: Any) -> str:
    """Return a lower-cased text blob for an option for keyword scoring."""
    return _to_text(option).lower()


def parse_option(index: int, option: Any) -> OptionView:
    """Build an :class:`OptionView` from a raw option."""
    return OptionView(
        index=index,
        raw=option,
        text=serialize_option(option),
        fields=_flatten_fields(option),
    )


def parse_select(options: Any) -> list[OptionView]:
    """Parse a list of raw options into :class:`OptionView` objects.

    Accepts anything; non-list inputs yield an empty list.
    """
    if isinstance(options, tuple):
        options = list(options)
    if not isinstance(options, list):
        return []
    return [parse_option(i, opt) for i, opt in enumerate(options)]


def option_count(options: Any) -> int:
    """Safely count options."""
    if isinstance(options, (list, tuple)):
        return len(options)
    return 0
