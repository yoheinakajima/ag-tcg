"""Typed event records for the ActiveGraph event log.

Events are immutable facts. Each carries enough provenance (``match_id``,
``turn``, ``player``, ``policy_version``, ``deck_version``, ``parent_event_ids``)
to reconstruct any projection and to fork/replay experiments.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """All recognized event types in the development loop."""

    MatchStarted = "MatchStarted"
    DeckLoaded = "DeckLoaded"
    ObservationReceived = "ObservationReceived"
    LegalOptionsProjected = "LegalOptionsProjected"
    BeliefStateProjected = "BeliefStateProjected"
    CandidateActionGenerated = "CandidateActionGenerated"
    SearchStarted = "SearchStarted"
    SearchWorldSampled = "SearchWorldSampled"
    SearchActionEvaluated = "SearchActionEvaluated"
    ActionChosen = "ActionChosen"
    ActionFallbackUsed = "ActionFallbackUsed"
    ActionApplied = "ActionApplied"
    TurnEnded = "TurnEnded"
    GameEnded = "GameEnded"
    FailureTagged = "FailureTagged"
    RegimeSelected = "RegimeSelected"
    PatchPlanCreated = "PatchPlanCreated"
    ValidationRunStarted = "ValidationRunStarted"
    ValidationRunFinished = "ValidationRunFinished"
    PolicyPromoted = "PolicyPromoted"
    DeckPromoted = "DeckPromoted"
    SubmissionPackaged = "SubmissionPackaged"
    ReportGenerated = "ReportGenerated"

    # --- ActiveGraph strategy-lab event types -----------------------------
    BaselineRegistered = "BaselineRegistered"
    IdeaGenerated = "IdeaGenerated"
    HypothesisRegistered = "HypothesisRegistered"
    StrategySeamSelected = "StrategySeamSelected"
    ExperimentBranchCreated = "ExperimentBranchCreated"
    DeckVariantCreated = "DeckVariantCreated"
    PolicyVariantCreated = "PolicyVariantCreated"
    LocalEvaluationStarted = "LocalEvaluationStarted"
    LocalEvaluationFinished = "LocalEvaluationFinished"
    MatchBatchStarted = "MatchBatchStarted"
    MatchBatchFinished = "MatchBatchFinished"
    MetricsComputed = "MetricsComputed"
    FailureRegimeTagged = "FailureRegimeTagged"
    CandidateRanked = "CandidateRanked"
    CandidatePromoted = "CandidatePromoted"
    CandidateRejected = "CandidateRejected"
    SubmissionQueued = "SubmissionQueued"
    SubmissionUploaded = "SubmissionUploaded"
    KaggleScoreUpdated = "KaggleScoreUpdated"
    ReportSiteGenerated = "ReportSiteGenerated"

    # --- Pass 4: Kaggle replay ingestion ----------------------------------
    ReplayImported = "ReplayImported"
    ReplayAnalyzed = "ReplayAnalyzed"
    # --- Pass 26: replay action-opportunity mining ------------------------
    ReplayWindowTagged = "ReplayWindowTagged"

    # --- Pass 9: playbook architecture + confirmation ---------------------
    ArchitectureDecisionRecorded = "ArchitectureDecisionRecorded"
    PlaybookArchitectureStarted = "PlaybookArchitectureStarted"
    ConfirmationPassStarted = "ConfirmationPassStarted"

    # --- Pass 18: strategy family registry + iteration tracking -----------
    StrategyFamilyRegistered = "StrategyFamilyRegistered"
    StrategyIterationCreated = "StrategyIterationCreated"
    StrategyIterationEvaluated = "StrategyIterationEvaluated"
    StrategyHypothesisLogged = "StrategyHypothesisLogged"
    StrategyFixtureAdded = "StrategyFixtureAdded"
    StrategyBlocked = "StrategyBlocked"
    StrategyDecisionRecorded = "StrategyDecisionRecorded"
    StrategyPromotionDecision = "StrategyPromotionDecision"
    InternalLeagueStarted = "InternalLeagueStarted"
    InternalLeagueFinished = "InternalLeagueFinished"
    StrategyReportGenerated = "StrategyReportGenerated"

    # --- Pass 19: parent/child head-to-head forensics ---------------------
    ParentChildComparisonStarted = "ParentChildComparisonStarted"
    ParentChildComparisonFinished = "ParentChildComparisonFinished"

    # --- Pass 36: standing tournament engine v0 ---------------------------
    TournamentEngineInitialized = "TournamentEngineInitialized"
    TournamentTickStarted = "TournamentTickStarted"
    TournamentTickFinished = "TournamentTickFinished"
    TournamentParticipantRegistered = "TournamentParticipantRegistered"
    GameScheduled = "GameScheduled"
    GameStarted = "GameStarted"
    GameFinished = "GameFinished"
    MatchupFinished = "MatchupFinished"
    TournamentRankingUpdated = "TournamentRankingUpdated"
    CandidatePoolUpdated = "CandidatePoolUpdated"
    CandidateStatusChanged = "CandidateStatusChanged"
    CandidateNonInertnessMeasured = "CandidateNonInertnessMeasured"
    TournamentProjectionUpdated = "TournamentProjectionUpdated"
    TournamentReportGenerated = "TournamentReportGenerated"

    # --- Pass 40: public-reference benchmark lane (separate from our pool) -
    # Benchmark opponents only. These event types are NEVER folded by
    # ``fold_games`` / ``CandidatePool.from_events`` / the scheduler / lifecycle,
    # so reference agents never enter our candidate pool, rankings, active-cap,
    # queue, promotion, or mutation lineage. Every one carries no_upload=true and
    # is written to a SEPARATE benchmark ledger file.
    PublicReferenceAgentRegistered = "PublicReferenceAgentRegistered"
    CgTypedLaneValidated = "CgTypedLaneValidated"
    PublicBenchmarkTickStarted = "PublicBenchmarkTickStarted"
    PublicBenchmarkGameScheduled = "PublicBenchmarkGameScheduled"
    PublicBenchmarkGameStarted = "PublicBenchmarkGameStarted"
    PublicBenchmarkGameFinished = "PublicBenchmarkGameFinished"
    PublicBenchmarkProjectionUpdated = "PublicBenchmarkProjectionUpdated"
    PublicBenchmarkTickFinished = "PublicBenchmarkTickFinished"

    # --- Pass 41: reference-calibrated owned cg_typed candidate spike ------
    # The owned cg_typed candidate is a LOCAL-ONLY benchmark subject; these two
    # types are NEVER folded by the scheduler/lifecycle/pool and carry
    # no_upload=true. ReferenceCalibrationFinished is written to the SEPARATE
    # benchmark ledger (reference opponents only); OwnedCgCandidateRegistered is
    # written to the main lab ledger and is NOT a promotion/queue/active-cap
    # signal (distinct from the forbidden CandidatePromoted/SubmissionQueued).
    OwnedCgCandidateRegistered = "OwnedCgCandidateRegistered"
    ReferenceCalibrationFinished = "ReferenceCalibrationFinished"

    # --- Pass 42: candidate generation v0 (deterministic probation factory) ---
    # A NEW internal candidate is generated locally from an eligible family via a
    # deterministic stdlib-safe mutation operator and admitted ONLY as
    # ``probation`` (never active/champion/anchor). These two types are purely
    # informational provenance facts: they are NEVER folded by
    # ``CandidatePool.from_events`` / the scheduler / lifecycle (only
    # TournamentParticipantRegistered + CandidateStatusChanged are folded), so they
    # can never act as a promotion/queue/active-cap signal. Both carry
    # no_upload=true and are written to the main lab ledger. They are DISTINCT from
    # the forbidden CandidatePromoted / SubmissionQueued / SubmissionUploaded /
    # KaggleScoreUpdated, none of which this pass ever emits.
    CandidateGenerated = "CandidateGenerated"
    CandidateValidationFinished = "CandidateValidationFinished"


@dataclass
class Event:
    """A single immutable event record."""

    event_type: str
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: float = field(default_factory=time.time)
    match_id: str | None = None
    turn: int | None = None
    player: int | None = None
    policy_version: str | None = None
    deck_version: str | None = None
    payload: dict = field(default_factory=dict)
    parent_event_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Normalize enum -> str if an EventType slipped in.
        if isinstance(d.get("event_type"), Enum):
            d["event_type"] = d["event_type"].value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in d.items() if k in known}
        et = kwargs.get("event_type")
        if isinstance(et, EventType):
            kwargs["event_type"] = et.value
        return cls(**kwargs)


def new_event(event_type: EventType | str, **kwargs: Any) -> Event:
    """Convenience constructor.

    ``new_event(EventType.MatchStarted, match_id="m1", payload={...})``
    """
    et = event_type.value if isinstance(event_type, EventType) else str(event_type)
    return Event(event_type=et, **kwargs)
