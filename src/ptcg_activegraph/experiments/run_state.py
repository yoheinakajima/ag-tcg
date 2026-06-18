"""Durable run/game state models for the resumable evaluator (Pass 7A, Part E).

These dataclasses are the on-disk, atomic-write state that lets an evaluation run
survive a dead orchestrator. The ActiveGraph ledger event log is the ultimate
source of truth; these files are fast, regenerable projections of it used for
resume/status. All writes go through ``ag.artifacts.atomic_write_json``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..ag.artifacts import atomic_write_json, run_artifacts_dir

# Game status vocabulary (Part E).
GAME_STATUSES = (
    "planned",
    "running",
    "completed",
    "timeout",
    "crashed",
    "stale",
    "skipped",
)
TERMINAL_STATUSES = ("completed", "timeout", "crashed", "skipped")

# Runner modes (Part F/G taxonomy).
RUNNER_MODES = (
    "subprocess_per_game",
    "in_process_fast_unsafe",
    "subprocess_per_game_fast_stub",
    "worker_pool_future",
    "dummy",
)


def default_stale_threshold(cabt_timeout_seconds: int) -> float:
    """Stale threshold: 2x the game timeout + 30s (configurable upstream)."""
    return 2.0 * float(cabt_timeout_seconds) + 30.0


@dataclass
class GameState:
    game_id: str
    run_id: str
    candidate_id: str
    control_id: str
    candidate_path: str
    control_path: str
    seat: int
    status: str = "planned"
    started_at: float | None = None
    updated_at: float | None = None
    completed_at: float | None = None
    pid: int | None = None
    process_group: int | None = None
    duration_seconds: float | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    result_json_path: str | None = None
    metrics_json_path: str | None = None
    error_summary: str | None = None
    attempt: int = 0
    runner_mode: str = "subprocess_per_game"
    cabt_timeout_seconds: int = 90
    activegraph_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class CandidateState:
    candidate_id: str
    run_id: str
    branch_path: str
    package_status: str = "unknown"
    smoke_status: str = "unknown"
    fixture_status: str = "unknown"
    games_planned: int = 0
    games_completed: int = 0
    games_timeout: int = 0
    games_crashed: int = 0
    games_stale: int = 0
    metrics_status: str = "unknown"
    rank_status: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateState":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class RunState:
    run_id: str
    stage: str
    control_id: str
    control_path: str
    runs_root: str
    created_at: float = field(default_factory=time.time)
    updated_at: float | None = None
    status: str = "planned"
    runner_mode: str = "subprocess_per_game"
    cabt_timeout_seconds: int = 90
    games_per_seat: int = 1
    seats: list[int] = field(default_factory=lambda: [0, 1])
    candidate_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# -- on-disk layout helpers ----------------------------------------------------
def run_dir_for(run_id: str, artifacts_root: str | Path | None = None) -> Path:
    return run_artifacts_dir(run_id, artifacts_root)


def games_dir(run_id: str, artifacts_root: str | Path | None = None) -> Path:
    d = run_dir_for(run_id, artifacts_root) / "games"
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidates_dir(run_id: str, artifacts_root: str | Path | None = None) -> Path:
    d = run_dir_for(run_id, artifacts_root) / "candidates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_state_path(run_id: str, artifacts_root: str | Path | None = None) -> Path:
    return run_dir_for(run_id, artifacts_root) / "run_state.json"


def game_state_path(run_id: str, game_id: str, artifacts_root: str | Path | None = None) -> Path:
    return games_dir(run_id, artifacts_root) / f"{game_id}.json"


def candidate_state_path(
    run_id: str, candidate_id: str, artifacts_root: str | Path | None = None
) -> Path:
    return candidates_dir(run_id, artifacts_root) / f"{candidate_id}.json"


# -- atomic save/load ----------------------------------------------------------
def save_run_state(rs: RunState, artifacts_root: str | Path | None = None) -> Path:
    rs.updated_at = time.time()
    return atomic_write_json(run_state_path(rs.run_id, artifacts_root), rs.to_dict())


def load_run_state(run_id: str, artifacts_root: str | Path | None = None) -> RunState | None:
    p = run_state_path(run_id, artifacts_root)
    if not p.exists():
        return None
    import json

    return RunState.from_dict(json.loads(p.read_text(encoding="utf-8")))


def save_game_state(gs: GameState, artifacts_root: str | Path | None = None) -> Path:
    gs.updated_at = time.time()
    return atomic_write_json(game_state_path(gs.run_id, gs.game_id, artifacts_root), gs.to_dict())


def load_game_states(run_id: str, artifacts_root: str | Path | None = None) -> list[GameState]:
    import json

    out: list[GameState] = []
    gdir = games_dir(run_id, artifacts_root)
    for p in sorted(gdir.glob("*.json")):
        try:
            out.append(GameState.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001 - skip a corrupt state file
            continue
    return out


def save_candidate_state(cs: CandidateState, artifacts_root: str | Path | None = None) -> Path:
    return atomic_write_json(
        candidate_state_path(cs.run_id, cs.candidate_id, artifacts_root), cs.to_dict()
    )


def load_candidate_states(
    run_id: str, artifacts_root: str | Path | None = None
) -> list[CandidateState]:
    import json

    out: list[CandidateState] = []
    cdir = candidates_dir(run_id, artifacts_root)
    for p in sorted(cdir.glob("*.json")):
        try:
            out.append(CandidateState.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            continue
    return out


def is_stale(game: GameState, now: float | None = None, threshold: float | None = None) -> bool:
    """A running game whose last update is older than the stale threshold."""
    if game.status != "running":
        return False
    now = now if now is not None else time.time()
    thr = threshold if threshold is not None else default_stale_threshold(game.cabt_timeout_seconds)
    ref = game.updated_at or game.started_at or 0.0
    return (now - ref) > thr
