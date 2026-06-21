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

        Folds two event types in canonical ``(timestamp, original index)`` order so
        projections can be rebuilt without reading ``candidate_pool.json``:

        * ``TournamentParticipantRegistered`` — the engine emits a full candidate
          dict per registration; it REPLACES the entire snapshot for that
          candidate (a later registration supersedes an earlier one, including any
          earlier status mark).
        * ``CandidateStatusChanged`` — a Pass 39 lifecycle mark that mutates ONLY
          the ``status`` (and ``status_note``) of an already-registered candidate;
          last-write-wins. A change for an unknown candidate, or to a status not in
          :data:`VALID_STATUSES`, is ignored.

        Backward-compatible: with no ``CandidateStatusChanged`` events (every pass
        before Pass 39) the result is identical to folding registrations alone.
        """
        from ..graph.events import EventType  # local import to avoid cycle

        reg_t = EventType.TournamentParticipantRegistered.value
        chg_t = EventType.CandidateStatusChanged.value
        init_t = EventType.TournamentEngineInitialized.value

        tid = tournament_id
        # (timestamp, original_index, kind, candidate_id, data)
        items: list[tuple] = []
        for idx, e in enumerate(events):
            et = getattr(e, "event_type", None)
            payload = getattr(e, "payload", None) or {}
            if et == init_t and tid is None:
                tid = payload.get("tournament_id")
            ts = getattr(e, "timestamp", 0.0) or 0.0
            if et == reg_t:
                snap = payload.get("candidate") or payload
                cid = snap.get("candidate_id")
                if cid:
                    items.append((ts, idx, "reg", cid, dict(snap)))
            elif et == chg_t:
                cid = payload.get("candidate_id")
                if cid:
                    items.append((ts, idx, "status", cid, payload))

        items.sort(key=lambda x: (x[0], x[1]))
        cands: dict[str, Candidate] = {}
        for _ts, _idx, kind, cid, data in items:
            if kind == "reg":
                cands[cid] = Candidate.from_dict(data)  # full snapshot replace
            else:  # status mark: mutate only status/status_note
                c = cands.get(cid)
                if c is None:
                    continue
                ns = data.get("new_status")
                if not ns or ns not in VALID_STATUSES:
                    continue  # invalid/unknown status -> ignore the whole mark
                c.status = ns
                if data.get("status_note") is not None:
                    c.status_note = data.get("status_note")
        out = sorted(cands.values(), key=lambda c: c.candidate_id)
        return cls(out, tournament_id=tid or "ptcg_standing_tournament_v0")

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
