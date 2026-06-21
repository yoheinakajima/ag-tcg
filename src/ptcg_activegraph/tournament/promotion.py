"""PASS 43 — Internal Promotion Gate v1.

A conservative, evidence-gated lifecycle *recommender* for the standing tournament.
It reads the candidate registry (from the ledger or a pool) plus folded GameFinished
projections, builds per-candidate evidence, and recommends ONE lifecycle action per
candidate. It NEVER mutates anything itself — emitting :class:`CandidateStatusChanged`
is the runner's job and only happens under an explicit, separately-gated ``--apply``.

Design invariants (locked; never weaken to force a promotion):

* Raw win-rate ALONE never promotes. Activation requires a Wilson lower bound that
  clears the direct-parent baseline by a margin, on top of hard sample-size minimums.
* Public references NEVER enter the promotion subject set — they are benchmark-only
  diagnostics. Any reference that somehow appears is classified
  ``blocked_public_reference`` and is never actionable.
* Protected statuses (family_champion / portfolio_anchor / held_probe) are NEVER
  demoted by this gate. Never-schedule statuses (retired / quarantined /
  special_pilot_only / invalid) are not promotion subjects.
* Tarballs are NEVER deleted or overwritten. Lifecycle is expressed purely as a
  status mark.
* Internal self-play diagnostics ONLY — NOT a Kaggle leaderboard, no upload, no
  submit, no Kaggle queue. This module emits no Kaggle/promotion-to-Kaggle events.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..graph.events import Event, EventType
from .pool import (ACTIVE, FAMILY_CHAMPION, HELD_PROBE, NEVER_SCHEDULE,
                   PORTFOLIO_ANCHOR, PROBATION, RETIRED, CandidatePool)
from .projections import _pair, _wilson, fold_games

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_MANIFEST = (REPO_ROOT / "data" / "reference_agents"
                      / "reference_agent_manifest.json")

# -- lifecycle actions -------------------------------------------------------
STAY_PROBATION = "stay_probation"
ACTIVATE = "activate"
PROMOTE_FAMILY_CHAMPION = "promote_family_champion"
RETIRE_TO_RETIRED = "retire_to_retired"
QUARANTINE = "quarantine"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"
BLOCKED_PROTECTED_STATUS = "blocked_protected_status"
BLOCKED_INVALIDITY = "blocked_invalidity"
BLOCKED_PUBLIC_REFERENCE = "blocked_public_reference"

ALL_ACTIONS = (
    STAY_PROBATION, ACTIVATE, PROMOTE_FAMILY_CHAMPION, RETIRE_TO_RETIRED,
    QUARANTINE, INSUFFICIENT_EVIDENCE, BLOCKED_PROTECTED_STATUS,
    BLOCKED_INVALIDITY, BLOCKED_PUBLIC_REFERENCE,
)
# Actions that, under --apply, would emit a CandidateStatusChanged.
ACTIONABLE = {ACTIVATE, PROMOTE_FAMILY_CHAMPION, RETIRE_TO_RETIRED, QUARANTINE}
# The new status each actionable recommendation maps to.
ACTION_TO_STATUS = {
    ACTIVATE: ACTIVE,
    PROMOTE_FAMILY_CHAMPION: FAMILY_CHAMPION,
    RETIRE_TO_RETIRED: RETIRED,
    QUARANTINE: "quarantined",
}
PROTECTED_STATUSES = {FAMILY_CHAMPION, PORTFOLIO_ANCHOR, HELD_PROBE}
_INTERNAL_CAVEAT = ("Internal self-play diagnostics only. NOT a Kaggle leaderboard "
                    "and NOT predictive of leaderboard placement. NO upload.")


# -- thresholds (locked v1; conservative) ------------------------------------
@dataclass(frozen=True)
class PromotionThresholdsV1:
    # ACTIVATE (probation -> active)
    activate_min_total_games: int = 40
    activate_min_decisive_games: int = 30
    activate_min_anchor_games: int = 10
    activate_min_anchor_decisive: int = 8
    activate_min_parent_h2h_games: int = 20
    activate_min_parent_seat_fraction: float = 0.25  # weaker seat >= 25% of H2H
    max_hardfail_rate: float = 0.05                   # (invalid+timeout+error)/games
    parent_baseline: float = 0.50                     # direct-parent null baseline
    activate_wilson_margin: float = 0.03              # wilson_low >= 0.50 + 0.03
    anchor_noninferior_margin: float = 0.03           # anchor wilson_low >= 0.50-0.03
    # PROMOTE_FAMILY_CHAMPION (active -> family_champion; stricter)
    champion_min_total_games: int = 80
    champion_min_parent_family_games: int = 40
    champion_min_anchor_games: int = 20
    champion_min_h2h_games: int = 20      # direct H2H vs the current champion
    champion_margin: float = 0.05
    # RETIRE (only with full evidence AND clearly worse than parent)
    retire_wilson_high_margin: float = 0.03           # wilson_high < 0.50 - 0.03
    # QUARANTINE (hard-failure evidence only)
    quarantine_min_n_for_rate: int = 20
    quarantine_hardfail_rate: float = 0.50
    wilson_z: float = 1.96

    def to_policy(self) -> dict:
        return asdict(self)


DEFAULT_THRESHOLDS = PromotionThresholdsV1()


# -- evidence model ----------------------------------------------------------
@dataclass
class CandidateEvidence:
    candidate_id: str
    family_id: str
    status: str
    parent_candidate_id: str | None
    is_public_reference: bool
    is_internal_generated: bool
    deck_changing: bool
    non_inert: bool
    total_games: int
    decisive_games: int
    wins: int
    losses: int
    draws: int
    invalid_count: int
    hardfail_rate: float
    win_rate: float
    wilson_low: float
    wilson_high: float
    parent_h2h_games: int
    parent_seat0: int
    parent_seat1: int
    parent_wins: int
    parent_losses: int
    parent_wilson_low: float
    anchor_games: int
    anchor_decisive: int
    anchor_wins: int
    anchor_wilson_low: float
    family_games: int
    family_champion_baseline: float | None
    champion_id: str | None
    champion_h2h_games: int
    champion_h2h_decisive: int
    champion_wins: int
    champion_wilson_low: float

    def to_dict(self) -> dict:
        return asdict(self)


def load_reference_ids(manifest: Path | None = None) -> set[str]:
    """Public-reference agent ids (benchmark-only). Defensive exclusion set."""
    p = manifest or REFERENCE_MANIFEST
    if not p.is_file():
        return set()
    raw = json.loads(p.read_text(encoding="utf-8"))
    agents = (raw.get("agents") or raw.get("reference_agents")
              or (raw if isinstance(raw, list) else []))
    ids: set[str] = set()
    for a in agents if isinstance(agents, list) else []:
        aid = a.get("agent_id") or a.get("candidate_id")
        if aid:
            ids.add(aid)
    return ids


def _is_reference(cand, reference_ids: set[str]) -> bool:
    tags = {t.lower() for t in (getattr(cand, "tags", None) or [])}
    return bool(
        cand.candidate_id in reference_ids
        or "reference" in tags or "public_reference" in tags
        or (getattr(cand, "validation_status", "") or "").startswith("external")
        or (cand.candidate_id or "").startswith("public_ref_")
    )


def _is_generated(cand) -> bool:
    tags = {t.lower() for t in (getattr(cand, "tags", None) or [])}
    return bool((cand.candidate_id or "").startswith("generated_")
                or "generated" in tags
                or "generate" in (getattr(cand, "source_pass", "") or "").lower())


def _deck_changing_from_events(events: list[Event]) -> dict[str, bool]:
    """Map candidate_id -> deck-delta proven, derived from the ledger ALONE."""
    gen_t = EventType.CandidateGenerated.value
    out: dict[str, bool] = {}
    for e in events:
        if getattr(e, "event_type", None) != gen_t:
            continue
        p = getattr(e, "payload", None) or {}
        cid = p.get("candidate_id") or p.get("generated_candidate_id")
        if not cid:
            continue
        delta = p.get("deck_delta") or {}
        changed = bool(p.get("deck_changing")
                       or (delta.get("added") or delta.get("removed")))
        out[cid] = out.get(cid, False) or changed
    return out


def _side_stats(m: dict, cid: str) -> tuple[int, int, int, int, int]:
    """(games, wins, losses, draws, invalid) for cid within matchup record m."""
    if cid == m["lo"]:
        wins, losses = m["lo_wins"], m["hi_wins"]
    else:
        wins, losses = m["hi_wins"], m["lo_wins"]
    return m["n"], wins, losses, m["draws"], m["invalid"]


def build_evidence(pool: CandidatePool, events: list[Event], *,
                   thresholds: PromotionThresholdsV1 = DEFAULT_THRESHOLDS,
                   reference_ids: set[str] | None = None,
                   non_inert_ids: set[str] | None = None) -> list[CandidateEvidence]:
    th = thresholds
    refs = reference_ids if reference_ids is not None else load_reference_ids()
    non_inert = non_inert_ids or set()
    agg = fold_games(events)
    matchup = agg["matchup"]
    directed = agg["directed"]
    deck_changing = _deck_changing_from_events(events)

    anchors = {c.candidate_id for c in pool.candidates if c.status == PORTFOLIO_ANCHOR}
    by_family: dict[str, list] = {}
    for c in pool.candidates:
        by_family.setdefault(c.family_id, []).append(c)

    out: list[CandidateEvidence] = []
    for c in pool.candidates:
        cid = c.candidate_id
        s = agg["per"].get(cid, {"wins": 0, "losses": 0, "draws": 0,
                                 "invalid": 0, "games": 0})
        total = s["games"]
        decisive = s["wins"] + s["losses"]
        invalid_count = s["invalid"]
        hardfail_rate = (invalid_count / total) if total else 0.0
        wr = (s["wins"] / decisive) if decisive else 0.0
        wlo, whi = _wilson(s["wins"], decisive, th.wilson_z) if decisive else (0.0, 0.0)

        # parent head-to-head (direct, candidate-vs-parent only)
        p_games = p_w = p_l = seat0 = seat1 = 0
        parent = c.parent_candidate_id
        if parent:
            lo, hi = _pair(cid, parent)
            mk = f"{lo}|{hi}"
            m = matchup.get(mk)
            if m:
                p_games, p_w, p_l, _pd, _pi = _side_stats(m, cid)
                seat0 = directed.get(f"{lo}>{hi}@0", 0)
                seat1 = directed.get(f"{lo}>{hi}@1", 0)
        p_dec = p_w + p_l
        p_wlo, _ = _wilson(p_w, p_dec, th.wilson_z) if p_dec else (0.0, 0.0)

        # anchor aggregate
        a_games = a_dec = a_w = 0
        for anc in anchors:
            if anc == cid:
                continue
            lo, hi = _pair(cid, anc)
            m = matchup.get(f"{lo}|{hi}")
            if not m:
                continue
            g, w, l, _d, _i = _side_stats(m, cid)
            a_games += g
            a_w += w
            a_dec += w + l
        a_wlo, _ = _wilson(a_w, a_dec, th.wilson_z) if a_dec else (0.0, 0.0)

        # family peers aggregate (same family, excluding self)
        fam_games = 0
        for peer in by_family.get(c.family_id, []):
            if peer.candidate_id == cid:
                continue
            lo, hi = _pair(cid, peer.candidate_id)
            m = matchup.get(f"{lo}|{hi}")
            if m:
                fam_games += m["n"]

        # current family champion: baseline (adj WR) + the candidate's DIRECT H2H
        # vs that champion. Promotion requires beating the champion head-to-head,
        # not merely out-farming an aggregate record against weaker opponents.
        champ_baseline = None
        champ_id = None
        for peer in by_family.get(c.family_id, []):
            if peer.status == FAMILY_CHAMPION and peer.candidate_id != cid:
                champ_id = peer.candidate_id
                ps = agg["per"].get(peer.candidate_id)
                if ps and (ps["wins"] + ps["losses"]) > 0:
                    champ_baseline = ps["wins"] / (ps["wins"] + ps["losses"])
        champ_games = champ_w = champ_l = 0
        if champ_id:
            lo, hi = _pair(cid, champ_id)
            m = matchup.get(f"{lo}|{hi}")
            if m:
                champ_games, champ_w, champ_l, _cd, _ci = _side_stats(m, cid)
        champ_dec = champ_w + champ_l
        champ_wlo, _ = _wilson(champ_w, champ_dec, th.wilson_z) if champ_dec else (0.0, 0.0)

        out.append(CandidateEvidence(
            candidate_id=cid, family_id=c.family_id, status=c.status,
            parent_candidate_id=parent,
            is_public_reference=_is_reference(c, refs),
            is_internal_generated=_is_generated(c),
            deck_changing=bool(deck_changing.get(cid, False)),
            non_inert=cid in non_inert,
            total_games=total, decisive_games=decisive,
            wins=s["wins"], losses=s["losses"], draws=s["draws"],
            invalid_count=invalid_count, hardfail_rate=round(hardfail_rate, 4),
            win_rate=round(wr, 4), wilson_low=round(wlo, 4), wilson_high=round(whi, 4),
            parent_h2h_games=p_games, parent_seat0=seat0, parent_seat1=seat1,
            parent_wins=p_w, parent_losses=p_l, parent_wilson_low=round(p_wlo, 4),
            anchor_games=a_games, anchor_decisive=a_dec, anchor_wins=a_w,
            anchor_wilson_low=round(a_wlo, 4),
            family_games=fam_games,
            family_champion_baseline=(round(champ_baseline, 4)
                                      if champ_baseline is not None else None),
            champion_id=champ_id,
            champion_h2h_games=champ_games, champion_h2h_decisive=champ_dec,
            champion_wins=champ_w, champion_wilson_low=round(champ_wlo, 4),
        ))
    return out


def _result(action: str, reasons: list[str], checks: dict,
            actionable: bool) -> dict:
    return {"action": action, "actionable": actionable and action in ACTIONABLE,
            "reasons": reasons, "checks": checks}


def classify(ev: CandidateEvidence,
             thresholds: PromotionThresholdsV1 = DEFAULT_THRESHOLDS) -> dict:
    """Recommend exactly one lifecycle action for ``ev``. Pure; no side effects."""
    th = thresholds
    checks: dict = {}

    # 1. public references are benchmark-only and never promotion subjects
    if ev.is_public_reference:
        return _result(BLOCKED_PUBLIC_REFERENCE,
                       ["public reference; benchmark-only, never enters promotion set"],
                       checks, False)
    # 2. never-schedule / invalid statuses are not subjects
    if ev.status in NEVER_SCHEDULE:
        return _result(BLOCKED_INVALIDITY,
                       [f"status '{ev.status}' is never scheduled; not a subject"],
                       checks, False)
    # 3. protected statuses are never demoted by this gate
    if ev.status in PROTECTED_STATUSES:
        return _result(BLOCKED_PROTECTED_STATUS,
                       [f"status '{ev.status}' is protected; gate never demotes it"],
                       checks, False)

    # status is now probation or active
    # 4. QUARANTINE on complete hard-failure evidence (or high rate over adequate N)
    complete_hardfail = ev.total_games > 0 and ev.invalid_count == ev.total_games
    high_rate_hardfail = (ev.total_games >= th.quarantine_min_n_for_rate
                          and ev.hardfail_rate >= th.quarantine_hardfail_rate)
    checks["complete_hardfail"] = complete_hardfail
    checks["high_rate_hardfail"] = high_rate_hardfail
    if complete_hardfail or high_rate_hardfail:
        why = ("every game invalid (complete hard-failure evidence)"
               if complete_hardfail else
               f"hard-fail rate {ev.hardfail_rate:.2f} over n={ev.total_games}")
        return _result(QUARANTINE, [why], checks, True)

    # 5. shared minimum-evidence gate
    enough_total = ev.total_games >= th.activate_min_total_games
    enough_decisive = ev.decisive_games >= th.activate_min_decisive_games
    enough_anchor = (ev.anchor_games >= th.activate_min_anchor_games
                     and ev.anchor_decisive >= th.activate_min_anchor_decisive)
    enough_parent = ev.parent_h2h_games >= th.activate_min_parent_h2h_games
    weaker_seat = min(ev.parent_seat0, ev.parent_seat1)
    seat_ok = bool(ev.parent_h2h_games
                   and ev.parent_seat0 > 0 and ev.parent_seat1 > 0
                   and weaker_seat >= th.activate_min_parent_seat_fraction
                   * ev.parent_h2h_games)
    hardfail_ok = ev.hardfail_rate <= th.max_hardfail_rate
    checks.update(enough_total=enough_total, enough_decisive=enough_decisive,
                  enough_anchor=enough_anchor, enough_parent_h2h=enough_parent,
                  seat_balanced=seat_ok, hardfail_ok=hardfail_ok)
    base_ok = (enough_total and enough_decisive and enough_anchor
               and enough_parent and seat_ok and hardfail_ok)

    # 6. RETIRE — only with full evidence AND clearly worse than the parent baseline
    if base_ok and ev.decisive_games > 0:
        clearly_worse = ev.wilson_high < (th.parent_baseline
                                          - th.retire_wilson_high_margin)
        checks["clearly_worse_than_parent"] = clearly_worse
        if clearly_worse:
            return _result(
                RETIRE_TO_RETIRED,
                [f"Wilson upper bound {ev.wilson_high:.3f} < "
                 f"{th.parent_baseline - th.retire_wilson_high_margin:.3f}; "
                 "clearly underperforms parent over adequate N"],
                checks, True)

    # 7. insufficient evidence short-circuit (sample size not met)
    if not base_ok:
        missing = [k for k in ("enough_total", "enough_decisive", "enough_anchor",
                               "enough_parent_h2h", "seat_balanced", "hardfail_ok")
                   if not checks.get(k)]
        return _result(INSUFFICIENT_EVIDENCE,
                       [f"unmet evidence gates: {', '.join(missing)}"], checks, False)

    deck_proven = ev.deck_changing or ev.non_inert
    checks["deck_delta_or_noninert_proven"] = deck_proven

    # 8a. ACTIVATE (probation only)
    if ev.status == PROBATION:
        margin = th.parent_baseline + th.activate_wilson_margin
        # aggregate strength: not a fluke over the whole record
        superiority = ev.wilson_low >= margin
        # direct parent superiority: the candidate must actually BEAT its parent
        # head-to-head, not out-farm weaker opponents in the aggregate record.
        parent_superiority = ev.parent_wilson_low >= margin
        anchor_ok = (ev.anchor_decisive > 0 and ev.anchor_wilson_low
                     >= (th.parent_baseline - th.anchor_noninferior_margin))
        checks["wilson_clears_parent_baseline"] = superiority
        checks["parent_h2h_superiority"] = parent_superiority
        checks["anchor_noninferior"] = anchor_ok
        if not deck_proven:
            return _result(STAY_PROBATION,
                           ["deck-delta / non-inertness not proven; cannot activate"],
                           checks, False)
        if superiority and parent_superiority and anchor_ok:
            return _result(
                ACTIVATE,
                ["all activate gates pass; aggregate AND direct parent-H2H Wilson "
                 "lower bounds clear the parent baseline by margin; anchor "
                 "comparison non-inferior"],
                checks, True)
        if superiority and not parent_superiority:
            why = ("aggregate Wilson lower bound clears the baseline but the direct "
                   "parent-H2H Wilson lower bound does not — a candidate must beat "
                   "its parent head-to-head, not out-farm weaker opponents")
        elif not anchor_ok and superiority and parent_superiority:
            why = "anchor comparison is not non-inferior by CI"
        else:
            why = ("Wilson lower bound does not clear the parent baseline by margin "
                   "(raw win-rate alone never promotes)")
        return _result(STAY_PROBATION, [why], checks, False)

    # 8b. PROMOTE_FAMILY_CHAMPION (active only; stricter)
    if ev.status == ACTIVE:
        champ_total = ev.total_games >= th.champion_min_total_games
        champ_pf = (ev.parent_h2h_games + ev.family_games
                    ) >= th.champion_min_parent_family_games
        champ_anchor = ev.anchor_games >= th.champion_min_anchor_games
        champ_baseline_exists = ev.family_champion_baseline is not None
        baseline = ev.family_champion_baseline or th.parent_baseline
        # aggregate strength relative to the champion's performance level
        champ_margin_ok = ev.wilson_low >= (baseline + th.champion_margin)
        # direct superiority OVER the current champion head-to-head: enough direct
        # games AND a Wilson lower bound that beats the champion (clears the even
        # baseline by the champion margin). Without this a candidate could be
        # crowned champion having never beaten — or even played — the incumbent.
        champ_h2h_enough = ev.champion_h2h_decisive >= th.champion_min_h2h_games
        champ_h2h_superior = ev.champion_wilson_low >= (th.parent_baseline
                                                        + th.champion_margin)
        champ_h2h_ok = champ_h2h_enough and champ_h2h_superior
        checks.update(champ_total=champ_total, champ_parent_family=champ_pf,
                      champ_anchor=champ_anchor,
                      champ_baseline_exists=champ_baseline_exists,
                      champ_margin_ok=champ_margin_ok,
                      champ_h2h_enough=champ_h2h_enough,
                      champ_h2h_superiority=champ_h2h_superior,
                      champ_h2h_ok=champ_h2h_ok)
        if (champ_total and champ_pf and champ_anchor and champ_baseline_exists
                and champ_margin_ok and champ_h2h_ok and deck_proven):
            return _result(
                PROMOTE_FAMILY_CHAMPION,
                ["meets stricter family-champion gate; aggregate AND direct "
                 "champion-H2H Wilson lower bounds clear the champion baseline "
                 "by margin"],
                checks, True)
        unmet = [k for k in ("champ_total", "champ_parent_family", "champ_anchor",
                             "champ_baseline_exists", "champ_margin_ok",
                             "champ_h2h_ok")
                 if not checks.get(k)]
        return _result(INSUFFICIENT_EVIDENCE,
                       [f"active candidate does not meet family-champion gate: "
                        f"{', '.join(unmet) or 'deck-delta not proven'}"],
                       checks, False)

    return _result(INSUFFICIENT_EVIDENCE, ["no applicable rule"], checks, False)


def evaluate(pool: CandidatePool, events: list[Event], *,
             thresholds: PromotionThresholdsV1 = DEFAULT_THRESHOLDS,
             reference_ids: set[str] | None = None,
             non_inert_ids: set[str] | None = None) -> dict:
    """Full dry-run evaluation. Returns per-candidate recommendations + summary."""
    evidence = build_evidence(pool, events, thresholds=thresholds,
                              reference_ids=reference_ids,
                              non_inert_ids=non_inert_ids)
    recs = []
    for ev in evidence:
        res = classify(ev, thresholds)
        recs.append({"candidate_id": ev.candidate_id, "status": ev.status,
                     "family_id": ev.family_id, **res, "evidence": ev.to_dict()})
    summary: dict[str, int] = {}
    for r in recs:
        summary[r["action"]] = summary.get(r["action"], 0) + 1
    actionable = [r for r in recs if r["actionable"]]
    return {
        "caveat": _INTERNAL_CAVEAT,
        "thresholds": thresholds.to_policy(),
        "n_candidates": len(recs),
        "summary_by_action": summary,
        "n_actionable": len(actionable),
        "recommendations": recs,
    }


def recommended_status_changes(evaluation: dict) -> list[dict]:
    """Distil actionable recommendations into status-change specs (no I/O)."""
    out = []
    for r in evaluation["recommendations"]:
        if not r.get("actionable"):
            continue
        new_status = ACTION_TO_STATUS.get(r["action"])
        if not new_status:
            continue
        out.append({
            "candidate_id": r["candidate_id"],
            "from_status": r["status"],
            "new_status": new_status,
            "action": r["action"],
            "reasons": r["reasons"],
        })
    return out
