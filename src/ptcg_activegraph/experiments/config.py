"""Load and reason about the experiment plan and strategy seam taxonomy.

Two YAML files drive the lab:

* ``experiments/strategy_seams.yaml`` — the seam taxonomy (machine-readable).
* ``experiments/experiment_plan.yaml`` — the hand-editable control surface
  (priorities, local-eval budget, submission safety switches).

Nothing here ever rewrites the user's priorities; the lab only reads them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# repo_root/src/ptcg_activegraph/experiments/config.py -> parents[3] == repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLAN_PATH = REPO_ROOT / "experiments" / "experiment_plan.yaml"
DEFAULT_SEAMS_PATH = REPO_ROOT / "experiments" / "strategy_seams.yaml"
CARD_CSV_PATH = REPO_ROOT / "data" / "cards" / "EN_Card_Data.csv"

# Dedicated ActiveGraph lab event log (separate from per-match events).
LAB_EVENTS_PATH = REPO_ROOT / "data" / "activegraph" / "lab_events.jsonl"
RUNS_ROOT = REPO_ROOT / "experiments" / "runs"
BASELINE_DIR = REPO_ROOT / "data" / "baselines" / "v1_kaggle_349_8"

# Capability tokens that are always satisfied in this repo.
_ALWAYS = {"none", "cabt_schema"}


@dataclass
class Seam:
    """One entry from the seam taxonomy."""

    id: str
    family: str
    description: str = ""
    default_priority: int = 50
    risk: str = "low"
    requires: list[str] = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Seam":
        return cls(
            id=str(d.get("id", "")),
            family=str(d.get("family", "")),
            description=str(d.get("description", "")),
            default_priority=int(d.get("default_priority", 50)),
            risk=str(d.get("risk", "low")),
            requires=list(d.get("requires", []) or []),
            enabled=bool(d.get("enabled", True)),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "family": self.family,
            "description": self.description,
            "default_priority": self.default_priority,
            "risk": self.risk,
            "requires": list(self.requires),
            "enabled": self.enabled,
        }


@dataclass
class ExperimentConfig:
    """The merged, queryable view of plan + seams."""

    settings: dict = field(default_factory=dict)
    priorities: dict = field(default_factory=dict)
    submission_queue: dict = field(default_factory=dict)
    seams: list[Seam] = field(default_factory=list)

    # -- lookups -----------------------------------------------------------
    def seam(self, seam_id: str) -> Seam | None:
        for s in self.seams:
            if s.id == seam_id:
                return s
        return None

    def priority_for(self, seam_id: str) -> int:
        if seam_id in self.priorities:
            try:
                return int(self.priorities[seam_id])
            except (TypeError, ValueError):
                pass
        s = self.seam(seam_id)
        return int(s.default_priority) if s else 0

    def capabilities(self) -> set[str]:
        """Tokens the environment can currently satisfy."""
        caps = set(_ALWAYS)
        if CARD_CSV_PATH.exists():
            caps.add("official_card_csv")
        return caps

    def is_testable(self, seam: Seam) -> tuple[bool, str]:
        """Return ``(testable, reason)`` for a seam given current capabilities."""
        if not seam.enabled:
            return False, "disabled in strategy_seams.yaml"
        caps = self.capabilities()
        missing = [r for r in seam.requires if r not in caps]
        if missing:
            return False, "requires " + ", ".join(missing)
        return True, ""

    # -- convenience -------------------------------------------------------
    def setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


def load_yaml(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_seams(path: str | Path = DEFAULT_SEAMS_PATH) -> list[Seam]:
    raw = load_yaml(path)
    items = raw.get("seams", []) if isinstance(raw, dict) else []
    return [Seam.from_dict(d) for d in items if isinstance(d, dict)]


def load_plan(path: str | Path = DEFAULT_PLAN_PATH) -> dict:
    return load_yaml(path)


def load_config(
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    seams_path: str | Path = DEFAULT_SEAMS_PATH,
) -> ExperimentConfig:
    plan = load_plan(plan_path)
    seams = load_seams(seams_path)
    return ExperimentConfig(
        settings=dict(plan.get("settings", {}) or {}),
        priorities=dict(plan.get("priorities", {}) or {}),
        submission_queue=dict(plan.get("submission_queue", {}) or {}),
        seams=seams,
    )
