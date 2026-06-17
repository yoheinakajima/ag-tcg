"""Save/load match replays as JSON (and optional HTML render passthrough)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_replay(path: str | Path, replay: dict) -> Path:
    """Persist a replay dict as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, indent=2, default=str), encoding="utf-8")
    return path


def load_replay(path: str | Path) -> dict | None:
    """Load a replay dict, or ``None`` if missing/corrupt."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_html(path: str | Path, html: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(html), encoding="utf-8")
    return path
