"""Artifact paths + atomic write helpers for the durable ledger.

All ledger/runner state is written atomically (write ``.tmp`` then ``os.replace``)
so a crash never leaves a half-written JSON state file as the source of truth.
Artifacts live under ``data/activegraph/artifacts/`` (never ``/tmp``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_ARTIFACTS_ROOT = Path("data/activegraph/artifacts")


def artifacts_root(root: str | os.PathLike | None = None) -> Path:
    return Path(root) if root is not None else DEFAULT_ARTIFACTS_ROOT


def run_artifacts_dir(run_id: str, root: str | os.PathLike | None = None) -> Path:
    """Directory holding durable per-run state + per-game artifacts."""
    d = artifacts_root(root) / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_relpath(path: str | os.PathLike) -> str:
    """Best-effort path relative to cwd (repo root); absolute is returned as-is."""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except Exception:  # noqa: BLE001 - outside repo / non-existent
        return str(p)


def atomic_write_text(path: str | os.PathLike, text: str) -> Path:
    """Write text atomically: tmp file + fsync + os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:  # pragma: no cover - some filesystems
            pass
    os.replace(tmp, p)
    return p


def atomic_write_json(path: str | os.PathLike, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, default=str, indent=2, sort_keys=True))
