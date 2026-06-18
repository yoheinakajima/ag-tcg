"""Load a playbook YAML file into a plain dict (no validation here)."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_playbook(path: str | Path) -> dict:
    """Read and parse a playbook YAML file.

    Returns the parsed mapping. Raises ``FileNotFoundError`` if missing and
    ``ValueError`` if the file does not parse to a mapping.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no playbook at {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"playbook {p} did not parse to a mapping")
    return data
