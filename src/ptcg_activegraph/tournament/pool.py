"""Canonical candidate pool: model, persistence, and lifecycle policy.

The pool is the durable list of every candidate the standing engine knows about.
Tarballs are immutable and never deleted — lifecycle is expressed purely as a
``status`` mark. Pass 36 does NOT create new candidates.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT_DIR = REPO_ROOT / "data" / "tournament"
POOL_PATH = TOURNAMENT_DIR / "candidate_pool.json"

# Candidate lifecycle statuses.
ACTIVE = "active"
HELD_PROBE = "held_probe"
FAMILY_CHAMPION = "family_champion"
PORTFOLIO_ANCHOR = "portfolio_anchor"
PROBATION = "probation"
RETIRED = "retired"
QUARANTINED = "quarantined"
SPECIAL_PILOT_ONLY = "special_pilot_only"
INVALID = "invalid"

VALID_STATUSES = {
    ACTIVE, HELD_PROBE, FAMILY_CHAMPION, PORTFOLIO_ANCHOR, PROBATION,
    RETIRED, QUARANTINED, SPECIAL_PILOT_ONLY, INVALID,
}

# Statuses that participate in the active schedule / count toward the active cap.
SCHEDULABLE_STATUSES = {ACTIVE, HELD_PROBE, FAMILY_CHAMPION, PORTFOLIO_ANCHOR, PROBATION}
# Statuses that must NEVER be scheduled.
NEVER_SCHEDULE = {RETIRED, QUARANTINED, SPECIAL_PILOT_ONLY, INVALID}


@dataclass
class Candidate:
    candidate_id: str
    family_id: str
    generation: int = 0
    parent_candidate_id: str | None = None
    tarball_path: str = ""
    deck_fingerprint: str | None = None
    main_fingerprint: str | None = None
    status: str = ACTIVE
    source_pass: str = ""
    validation_status: str | None = None
    entrypoint_status: str | None = None
    smoke_status: str | None = None
    tags: list[str] = field(default_factory=list)
    no_upload: bool = True
    status_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def schedulable(self) -> bool:
        return self.status in SCHEDULABLE_STATUSES


class CandidatePool:
    """A loadable/savable collection of :class:`Candidate`."""

    def __init__(self, candidates: list[Candidate] | None = None,
                 tournament_id: str = "ptcg_standing_tournament_v0") -> None:
        self.tournament_id = tournament_id
        self.candidates: list[Candidate] = candidates or []

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "CandidatePool":
        p = Path(path) if path is not None else POOL_PATH
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        cands = [Candidate.from_dict(c) for c in raw.get("candidates", [])]
        return cls(cands, tournament_id=raw.get("tournament_id",
                                                "ptcg_standing_tournament_v0"))

    @classmethod
    def from_events(cls, events, tournament_id: str | None = None) -> "CandidatePool":
        """Reconstruct the candidate registry from the event ledger ALONE.

        Uses the latest ``TournamentParticipantRegistered`` snapshot per
        candidate (the engine emits a full candidate dict per registration), so
        projections can be rebuilt without reading ``candidate_pool.json``.
        """
        from ..graph.events import EventType  # local import to avoid cycle

        latest: dict[str, dict] = {}
        tid = tournament_id
        for e in events:
            et = getattr(e, "event_type", None)
            if et == EventType.TournamentEngineInitialized.value and tid is None:
                tid = e.payload.get("tournament_id")
            if et != EventType.TournamentParticipantRegistered.value:
                continue
            snap = e.payload.get("candidate") or e.payload
            cid = snap.get("candidate_id")
            if cid:
                latest[cid] = snap  # later registration wins
        cands = [Candidate.from_dict(s) for s in latest.values()]
        cands.sort(key=lambda c: c.candidate_id)
        return cls(cands, tournament_id=tid or "ptcg_standing_tournament_v0")

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path is not None else POOL_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "tournament_id": self.tournament_id,
            "no_upload": True,
            "note": "Internal diagnostics only. Tarballs are immutable; status "
                    "marks only, never deleted. NOT a Kaggle leaderboard.",
            "candidates": [c.to_dict() for c in self.candidates],
        }
        p.write_text(json.dumps(body, indent=2, sort_keys=False))
        return p

    # -- queries -----------------------------------------------------------
    def by_id(self, cid: str) -> Candidate | None:
        return next((c for c in self.candidates if c.candidate_id == cid), None)

    def schedulable(self) -> list[Candidate]:
        return [c for c in self.candidates if c.schedulable]

    def active_count(self) -> int:
        return len(self.schedulable())

    def by_family(self) -> dict[str, list[Candidate]]:
        out: dict[str, list[Candidate]] = {}
        for c in self.candidates:
            out.setdefault(c.family_id, []).append(c)
        return out

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.candidates:
            out[c.status] = out.get(c.status, 0) + 1
        return out
