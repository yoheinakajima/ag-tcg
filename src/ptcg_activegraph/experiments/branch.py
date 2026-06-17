"""Experiment branch: an isolated candidate run directory.

Convention (see docs/STRATEGY_SEAMS.md)::

    experiments/runs/
      YYYYMMDD_HHMMSS_<branch_id>/
        branch.yaml        # this Branch serialized
        main.py            # candidate runtime (baseline + override, or copy)
        deck.csv           # candidate deck (60 integer ids)
        metrics.json       # written by the runner
        events.jsonl       # per-branch event slice (optional)
        report.md          # per-branch human summary
        submission.tar.gz  # built only when queued

The submitted root ``main.py``/``deck.csv`` are never touched; every candidate
lives entirely under its own run directory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RUNS_ROOT = Path("experiments/runs")


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


@dataclass
class Branch:
    """A single candidate experiment branch."""

    branch_id: str
    seam_id: str
    family: str
    kind: str = "policy"  # policy | deck | control
    archetype: str = ""
    hypothesis: str = ""
    parent: str = "v1_kaggle_349_8"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    run_dir: str = ""
    policy_overrides: dict = field(default_factory=dict)
    policy_diff: dict = field(default_factory=dict)
    deck_diff: dict = field(default_factory=dict)
    deck_summary: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    testable: bool = True
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "branch_id": self.branch_id,
            "seam_id": self.seam_id,
            "family": self.family,
            "kind": self.kind,
            "archetype": self.archetype,
            "hypothesis": self.hypothesis,
            "parent": self.parent,
            "created_at": self.created_at,
            "run_dir": self.run_dir,
            "policy_overrides": self.policy_overrides,
            "policy_diff": self.policy_diff,
            "deck_diff": self.deck_diff,
            "deck_summary": self.deck_summary,
            "notes": list(self.notes),
            "testable": self.testable,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Branch":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def make_run_dir(branch_id: str, root: str | Path = RUNS_ROOT, ts: str | None = None) -> Path:
    ts = ts or timestamp()
    run_dir = Path(root) / f"{ts}_{branch_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_branch_yaml(branch: Branch, run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "branch.yaml"
    path.write_text(
        yaml.safe_dump(branch.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def load_branch_yaml(run_dir: str | Path) -> Branch | None:
    path = Path(run_dir) / "branch.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return Branch.from_dict(data)


def list_runs(root: str | Path = RUNS_ROOT) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "branch.yaml").exists())
