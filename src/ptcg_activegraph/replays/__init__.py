"""Kaggle cabt episode replay ingestion + analysis.

This package parses a Kaggle episode replay JSON (the artifact produced by a
cabt match on the competition ladder) into a structured, inspectable analysis.
It never fabricates data: when the replay file is absent the loader raises
``ReplayNotFound`` and the caller reports "needs upload" instead of guessing.
"""

from __future__ import annotations

from .analyzers import analyze, to_markdown
from .kaggle_replay import (
    KaggleReplay,
    ReplayNotFound,
    load_replay,
    parse_replay,
)

__all__ = [
    "KaggleReplay",
    "ReplayNotFound",
    "load_replay",
    "parse_replay",
    "analyze",
    "to_markdown",
]
