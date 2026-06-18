"""Run-ledger event schema for the PTCG ActiveGraph adapter.

The ledger envelope is *run-scoped* (top-level ``run_id``) which the homegrown
``graph.events.Event`` is not (it keys on ``match_id``). Rather than overload the
shared match-event model, the ledger layer ships its own thin ``LedgerEvent``
dataclass with the envelope required by ``docs/PTCG_ACTIVEGRAPH_RUN_LEDGER.md``.

This module is intentionally pure (no I/O) so it can be imported anywhere cheaply.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field


# Canonical ledger event types (see docs/PTCG_ACTIVEGRAPH_RUN_LEDGER.md).
LEDGER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # ExperimentRun lifecycle
        "ExperimentRunCreated",
        "ExperimentRunStarted",
        "ExperimentRunHeartbeat",
        "ExperimentRunPartial",
        "ExperimentRunFinished",
        "ExperimentRunFailed",
        # Candidate gates
        "CandidateRegistered",
        "CandidatePackageVerified",
        "CandidateSmokeVerified",
        # Fixture gate
        "FixtureGateStarted",
        "FixtureGateFinished",
        # Game lifecycle
        "GamePlanned",
        "GameStarted",
        "GameHeartbeat",
        "GameFinished",
        "GameTimeout",
        "GameCrashed",
        "GameStale",
        "GameResultRecorded",
        # Metrics / ranking / promotion
        "MetricsComputed",
        "CandidateRanked",
        "CandidatePromoted",
        "CandidateRejected",
        # Artifacts / replay / report
        "ArtifactRecorded",
        "ReplayImported",
        "ReportSiteGenerated",
        # Submission (local queue only; never auto-uploads)
        "SubmissionQueued",
        "SubmissionUploaded",
        "KaggleScoreUpdated",
    }
)

# Game status vocabulary and the event type that asserts each status.
GAME_STATUS_BY_EVENT: dict[str, str] = {
    "GamePlanned": "planned",
    "GameStarted": "running",
    "GameFinished": "completed",
    "GameTimeout": "timeout",
    "GameCrashed": "crashed",
    "GameStale": "stale",
}

# ExperimentRun status transitions keyed by event type.
RUN_STATUS_BY_EVENT: dict[str, str] = {
    "ExperimentRunCreated": "created",
    "ExperimentRunStarted": "running",
    "ExperimentRunPartial": "partial",
    "ExperimentRunFinished": "completed",
    "ExperimentRunFailed": "failed",
}


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


@dataclass
class LedgerEvent:
    """One immutable run-scoped ledger fact."""

    event_type: str
    run_id: str
    event_id: str = field(default_factory=new_event_id)
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)
    parent_event_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "LedgerEvent":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def is_known_event_type(event_type: str) -> bool:
    return event_type in LEDGER_EVENT_TYPES
