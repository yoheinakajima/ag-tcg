"""Pass 39 — candidate lifecycle manager v0 (status-mark hygiene only).

Evidence-based, conservative status marks for the standing tournament. This module
NEVER creates candidates, NEVER mutates tarballs or the frozen root, and NEVER
uploads/submits. It proposes (dry-run) and — only for explicitly safe,
evidence-backed cases — applies ``CandidateStatusChanged`` marks via the
no-upload ledger. Tarballs are immutable; lifecycle is a status mark only, never a
deletion.

Policy v0 (see ``docs/TOURNAMENT_CANDIDATE_LIFECYCLE.md``):

* **PROTECTED — never demoted.** A candidate is protected when its status is one of
  :data:`PROTECTED_STATUSES` {held_probe, family_champion, portfolio_anchor,
  special_pilot_only}; OR it carries a tag in :data:`PROTECTED_TAGS`
  {live_control, water_family_current_best, manual_hold}; OR it is the immediate
  parent of an ``active`` child (lineage protection).
* **QUARANTINE** (schedulable & non-protected → ``quarantined``). Hard-failure
  evidence only: a candidate that has played at least :data:`QUARANTINE_MIN_INVALID_ONLY`
  games, all invalid/timeout/error with ZERO decisive results; OR a high invalid
  rate (>= :data:`QUARANTINE_INVALID_RATE`) over at least :data:`QUARANTINE_MIN_GAMES`
  games. This is the ONLY status change auto-applied (it removes a broken candidate
  from the schedule and protects tick budget).
* **SOFT PROBATION** (``active`` → ``probation``). An under-sampled active (games <
  the placement threshold ``min_placement_games_per_candidate``). PROPOSED in
  dry-run as ``eligible_soft_probation`` but NOT auto-applied: in early soak EVERY
  active is under-sampled, so demoting them all is churn with no benefit (probation
  is still schedulable). Requires explicit operator opt-in (``allow_soft_probation``).
* **RETAIN** — everything else (no-op; never emits an event). v0 has NO promotion
  authority; promotions are out of scope.

Idempotency: an apply emits nothing when ``old_status == new_status``. Because
``CandidateStatusChanged`` is merged by unique ``event_id`` (it is not a per-game
lifecycle event in :mod:`sync`), correctness relies on this old-vs-new check rather
than on event de-duplication.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..graph.events import EventType
from .config import TournamentConfig, load_config
from .pool import (
    ACTIVE,
    FAMILY_CHAMPION,
    HELD_PROBE,
    NEVER_SCHEDULE,
    PORTFOLIO_ANCHOR,
    PROBATION,
    QUARANTINED,
    SCHEDULABLE_STATUSES,
    SPECIAL_PILOT_ONLY,
    Candidate,
    CandidatePool,
)
from .projections import _wilson, fold_games

# Statuses that are never demoted by the lifecycle manager.
PROTECTED_STATUSES = {HELD_PROBE, FAMILY_CHAMPION, PORTFOLIO_ANCHOR, SPECIAL_PILOT_ONLY}
# Tags that pin a candidate regardless of status.
PROTECTED_TAGS = {"live_control", "water_family_current_best", "manual_hold"}

# Quarantine thresholds (conservative; documented in the lifecycle policy doc).
QUARANTINE_MIN_INVALID_ONLY = 3   # >= this many games, all invalid, 0 decisive
QUARANTINE_MIN_GAMES = 4          # min games before the invalid-rate rule applies
QUARANTINE_INVALID_RATE = 0.5     # invalid / games at or above this -> quarantine

# Action verbs.
RETAIN = "retain"
ELIGIBLE_SOFT_PROBATION = "eligible_soft_probation"
QUARANTINE = "quarantine"


@dataclass
class CandidateEvidence:
    candidate_id: str
    family_id: str
    status: str
    games: int
    decisive: int
    wins: int
    losses: int
    draws: int
    invalid: int
    adj_win_rate: float
    wilson_low: float
    wilson_high: float
    invalid_rate: float
    under_sampled: bool
    placement_threshold: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LifecycleAction:
    candidate_id: str
    family_id: str
    current_status: str
    proposed_status: str
    action: str
    reason: str
    protected: bool
    protected_reasons: list[str] = field(default_factory=list)
    auto_apply_default: bool = False   # quarantine: True; soft-probation: False
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# protection
# --------------------------------------------------------------------------- #
def protection_reasons(c: Candidate, pool: CandidatePool) -> list[str]:
    """Why (if at all) candidate ``c`` is protected from demotion."""
    reasons: list[str] = []
    if c.status in PROTECTED_STATUSES:
        reasons.append(f"protected_status:{c.status}")
    for t in sorted(set(c.tags or []) & PROTECTED_TAGS):
        reasons.append(f"protected_tag:{t}")
    for d in pool.candidates:
        if d.candidate_id != c.candidate_id \
                and d.parent_candidate_id == c.candidate_id and d.status == ACTIVE:
            reasons.append(f"parent_of_active_child:{d.candidate_id}")
    return reasons


def is_protected(c: Candidate, pool: CandidatePool) -> bool:
    return bool(protection_reasons(c, pool))


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #
def candidate_evidence(pool: CandidatePool, events, cfg: TournamentConfig) -> dict:
    """Per-candidate evidence folded from GameFinished events (Wilson 95%)."""
    agg = fold_games(list(events))
    threshold = cfg.min_placement_games_per_candidate
    out: dict[str, CandidateEvidence] = {}
    for c in pool.candidates:
        s = agg["per"].get(c.candidate_id,
                           {"wins": 0, "losses": 0, "draws": 0, "invalid": 0, "games": 0})
        decisive = s["wins"] + s["losses"]
        adj = (s["wins"] / decisive) if decisive else 0.0
        lo, hi = _wilson(s["wins"], decisive) if decisive else (0.0, 0.0)
        games = s["games"]
        inv_rate = (s["invalid"] / games) if games else 0.0
        out[c.candidate_id] = CandidateEvidence(
            candidate_id=c.candidate_id, family_id=c.family_id, status=c.status,
            games=games, decisive=decisive, wins=s["wins"], losses=s["losses"],
            draws=s["draws"], invalid=s["invalid"], adj_win_rate=round(adj, 4),
            wilson_low=round(lo, 4), wilson_high=round(hi, 4),
            invalid_rate=round(inv_rate, 4), under_sampled=(games < threshold),
            placement_threshold=threshold,
        )
    return out


def _classify(c: Candidate, e: CandidateEvidence, protected: bool) -> tuple[str, str, str, bool]:
    """Return (action, proposed_status, reason, auto_apply_default)."""
    if c.status in NEVER_SCHEDULE:
        return RETAIN, c.status, f"never_schedule_status_retained:{c.status}", False
    if c.status not in SCHEDULABLE_STATUSES:
        return RETAIN, c.status, "non_schedulable_status_retained", False
    if protected:
        return RETAIN, c.status, "protected_retained", False
    # Hard-failure quarantine (auto-applied). The "all invalid" rule requires
    # EVERY game to be invalid (invalid == games), not merely >= the floor with
    # 0 decisive — draws are non-decisive but are NOT hard failures, so a deck
    # with draws mixed in must fall through to the invalid-rate branch instead.
    if (e.games >= QUARANTINE_MIN_INVALID_ONLY and e.decisive == 0
            and e.invalid == e.games):
        return QUARANTINE, QUARANTINED, "all_invalid_no_decisive", True
    if e.games >= QUARANTINE_MIN_GAMES and e.invalid_rate >= QUARANTINE_INVALID_RATE:
        return QUARANTINE, QUARANTINED, "high_invalid_rate", True
    # Under-sampled active -> soft probation (proposal only; not auto-applied).
    if c.status == ACTIVE and e.under_sampled:
        return ELIGIBLE_SOFT_PROBATION, PROBATION, "under_sampled_active", False
    return RETAIN, c.status, "sufficient_evidence_or_no_change", False


def evaluate_lifecycle(pool: CandidatePool, events, cfg: TournamentConfig | None = None) -> dict:
    """Produce a conservative, evidence-based lifecycle PLAN (no side effects)."""
    cfg = cfg or load_config()
    ev = candidate_evidence(pool, events, cfg)
    actions: list[LifecycleAction] = []
    for c in sorted(pool.candidates, key=lambda c: c.candidate_id):
        e = ev[c.candidate_id]
        preasons = protection_reasons(c, pool)
        protected = bool(preasons)
        action, proposed, reason, auto = _classify(c, e, protected)
        actions.append(LifecycleAction(
            candidate_id=c.candidate_id, family_id=c.family_id,
            current_status=c.status, proposed_status=proposed, action=action,
            reason=reason, protected=protected, protected_reasons=preasons,
            auto_apply_default=auto, evidence=e.to_dict(),
        ))
    summary = {
        "registered": len(pool.candidates),
        "schedulable": pool.active_count(),
        "status_counts": pool.stats(),
        "action_counts": {
            a: sum(1 for x in actions if x.action == a)
            for a in (RETAIN, ELIGIBLE_SOFT_PROBATION, QUARANTINE)
        },
        "protected": sum(1 for x in actions if x.protected),
        "auto_applicable_quarantines": sum(
            1 for x in actions if x.action == QUARANTINE),
        "eligible_soft_probation": sum(
            1 for x in actions if x.action == ELIGIBLE_SOFT_PROBATION),
        "placement_threshold": cfg.min_placement_games_per_candidate,
    }
    return {
        "tournament_id": pool.tournament_id,
        "policy_version": "v0",
        "no_upload": True,
        "actions": [a.to_dict() for a in actions],
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# parent-link helpers
# --------------------------------------------------------------------------- #
def _latest_event_ids(events) -> tuple[dict, dict]:
    """(latest registration evt per cid, latest GameFinished evt per cid)."""
    reg: dict[str, str] = {}
    gf: dict[str, str] = {}
    reg_t = EventType.TournamentParticipantRegistered.value
    gf_t = EventType.GameFinished.value
    for e in events:
        et = getattr(e, "event_type", None)
        p = getattr(e, "payload", None) or {}
        eid = getattr(e, "event_id", None)
        if et == reg_t:
            snap = p.get("candidate") or p
            cid = snap.get("candidate_id")
            if cid and eid:
                reg[cid] = eid
        elif et == gf_t:
            for cid in (p.get("candidate_a"), p.get("candidate_b")):
                if cid and eid:
                    gf[cid] = eid
    return reg, gf


def _applicable(action: dict, allow_soft_probation: bool) -> bool:
    if action["action"] == QUARANTINE:
        return True
    if action["action"] == ELIGIBLE_SOFT_PROBATION:
        return allow_soft_probation
    return False


def apply_lifecycle_plan(
    plan: dict,
    pool: CandidatePool,
    ledger,
    events,
    *,
    dry_run: bool = True,
    allow_soft_probation: bool = False,
) -> dict:
    """Apply ONLY safe, applicable marks. Idempotent; emits nothing when old==new.

    Returns a result dict with ``apply_skipped=True`` when no mark is actually
    written (the early-soak default: zero quarantines and soft-probation not
    opted-in). Mutates ``pool`` in place (and emits via ``ledger``) only when
    ``dry_run`` is False and there is at least one applicable, non-idempotent mark.
    """
    reg_evt, gf_evt = _latest_event_ids(events)
    applied: list[dict] = []
    skipped_idempotent: list[dict] = []
    applicable_actions = [a for a in plan["actions"]
                          if _applicable(a, allow_soft_probation)]

    for a in applicable_actions:
        cid = a["candidate_id"]
        c = pool.by_id(cid)
        old = c.status if c is not None else a["current_status"]
        new = a["proposed_status"]
        if old == new:
            skipped_idempotent.append({**a, "skip_reason": "idempotent_old_equals_new"})
            continue
        if dry_run:
            applied.append({**a, "applied": False, "dry_run": True})
            continue
        parents = [reg_evt[cid]] if cid in reg_evt else []
        if cid in gf_evt:
            parents.append(gf_evt[cid])
        payload = {
            "candidate_id": cid,
            "old_status": old,
            "new_status": new,
            "status_note": a["reason"],
            "reason": a["reason"],
            "action": a["action"],
            "evidence_summary": a["evidence"],
            "protected_override": False,
            "pass": "39",
        }
        ev = ledger.emit(EventType.CandidateStatusChanged, payload,
                         parent_event_ids=parents, tags=["pass39", "lifecycle"])
        if c is not None:
            c.status = new
            c.status_note = a["reason"]
        applied.append({**a, "applied": True, "event_id": ev.event_id,
                        "parent_event_ids": parents})

    wrote = [x for x in applied if x.get("applied")]
    apply_skipped = (not dry_run) and len(wrote) == 0
    no_applicable = len(applicable_actions) == 0
    if no_applicable:
        explanation = (
            "No safe, evidence-backed status change applies: zero quarantines "
            "(no candidate has hard-failure invalid/timeout/error evidence) and "
            "soft-probation of under-sampled actives is not opted-in (early soak: "
            "every active is under-sampled, so demoting them is churn with no "
            "benefit — probation is still schedulable).")
    elif apply_skipped:
        explanation = ("All applicable marks were idempotent (old_status == "
                       "new_status); nothing was written.")
    else:
        explanation = f"Applied {len(wrote)} status mark(s)."

    return {
        "no_upload": True,
        "dry_run": dry_run,
        "allow_soft_probation": allow_soft_probation,
        "applicable_count": len(applicable_actions),
        "applied": applied,
        "applied_count": len(wrote),
        "skipped_idempotent": skipped_idempotent,
        "apply_skipped": apply_skipped or (dry_run and len(wrote) == 0 and no_applicable),
        "explanation": explanation,
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
_CAVEAT = ("Internal lifecycle diagnostics only. NOT a Kaggle leaderboard. "
           "NO upload, NO submit, NO auto-submit, NO candidate generation, NO "
           "tarball mutation. Status marks only; tarballs are immutable.")


def render_lifecycle_markdown(plan: dict, apply_result: dict | None, *,
                              mode: str, backend: str | None,
                              header: str = "Tournament Candidate Lifecycle") -> str:
    s = plan["summary"]
    lines = [
        f"# Pass 39 — {header}", "",
        f"_{_CAVEAT}_", "",
        f"- mode: **{mode}**  backend: {backend}",
        f"- policy_version: {plan.get('policy_version')}  "
        f"placement_threshold: {s['placement_threshold']}",
        f"- registered: {s['registered']}  schedulable: {s['schedulable']}  "
        f"protected: {s['protected']}",
        f"- action_counts: {s['action_counts']}",
        f"- status_counts: {s['status_counts']}", "",
    ]
    if apply_result is not None:
        lines += [
            "## Apply",
            f"- dry_run: **{apply_result['dry_run']}**  "
            f"allow_soft_probation: {apply_result['allow_soft_probation']}",
            f"- applicable: {apply_result['applicable_count']}  "
            f"applied: {apply_result['applied_count']}  "
            f"idempotent_skipped: {len(apply_result['skipped_idempotent'])}",
            f"- **apply_skipped: {apply_result['apply_skipped']}**",
            f"- {apply_result['explanation']}", "",
        ]
    lines += [
        "## Actions",
        "| candidate | family | status | action | proposed | reason | protected | "
        "games | dec | inv | adj_wr | wilson95 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in plan["actions"]:
        e = a["evidence"]
        prot = "yes" if a["protected"] else "no"
        lines.append(
            f"| {a['candidate_id']} | {a['family_id']} | {a['current_status']} "
            f"| {a['action']} | {a['proposed_status']} | {a['reason']} | {prot} "
            f"| {e['games']} | {e['decisive']} | {e['invalid']} "
            f"| {e['adj_win_rate']:.3f} | [{e['wilson_low']:.3f},{e['wilson_high']:.3f}] |")
    if any(a["protected"] for a in plan["actions"]):
        lines += ["", "## Protected (never demoted)"]
        for a in plan["actions"]:
            if a["protected"]:
                lines.append(f"- `{a['candidate_id']}` — {', '.join(a['protected_reasons'])}")
    return "\n".join(lines) + "\n"


def write_lifecycle_report(plan: dict, *, out_json: str | Path, out_md: str | Path,
                           apply_result: dict | None = None, mode: str = "prod",
                           backend: str | None = None, header: str = "Tournament "
                           "Candidate Lifecycle", extra: dict | None = None) -> dict:
    """Persist the lifecycle plan (and optional apply result) as json + md."""
    payload = {
        "schema": "pass39_lifecycle_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "backend": backend,
        "no_upload": True,
        "caveat": _CAVEAT,
        "plan": plan,
        "apply": apply_result,
    }
    if extra:
        payload.update(extra)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    Path(out_md).write_text(
        render_lifecycle_markdown(plan, apply_result, mode=mode, backend=backend,
                                  header=header), encoding="utf-8")
    return payload
