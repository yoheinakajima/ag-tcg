"""Transparent candidate ranking.

The scoring is deliberately simple and inspectable (no magic):

Hard rejects (score floored, never promotable):
  * package verify failed
  * smoke failed
  * any crash/error in the local batch
  * any timeout in the local batch

Soft scoring (higher = better) for survivors:
  * + win rate (dominant term) when known
  * + longer real games as a tie-break when outcome is unknown but stable
  * - pass-like rate
  * + attack rate
  * - fallback count
  * - decision entropy for deck variants (prefer steadier deck lines)
  * + a diversity bonus so the top of the list isn't all one seam family

Outputs ``data/experiments/latest_ranking.{json,md}``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event

RANKING_JSON = Path("data/experiments/latest_ranking.json")
RANKING_MD = Path("data/experiments/latest_ranking.md")
FOCUSED_RANKING_JSON = Path("data/experiments/focused_ranking.json")
FOCUSED_RANKING_MD = Path("data/experiments/focused_ranking.md")
PASS4_SCOUT_RANKING_JSON = Path("data/experiments/pass4_scout_ranking.json")
PASS4_SCOUT_RANKING_MD = Path("data/experiments/pass4_scout_ranking.md")
PASS5_SCOUT_RANKING_JSON = Path("data/experiments/pass5_scout_ranking.json")
PASS5_SCOUT_RANKING_MD = Path("data/experiments/pass5_scout_ranking.md")
PASS5_FOCUSED_RANKING_JSON = Path("data/experiments/pass5_focused_ranking.json")
PASS5_FOCUSED_RANKING_MD = Path("data/experiments/pass5_focused_ranking.md")
PASS6_SCOUT_RANKING_JSON = Path("data/experiments/pass6_scout_ranking.json")
PASS6_SCOUT_RANKING_MD = Path("data/experiments/pass6_scout_ranking.md")
PASS6_FOCUSED_RANKING_JSON = Path("data/experiments/pass6_focused_ranking.json")
PASS6_FOCUSED_RANKING_MD = Path("data/experiments/pass6_focused_ranking.md")

STAGE_PATHS = {
    "broad": (RANKING_JSON, RANKING_MD),
    "focused": (FOCUSED_RANKING_JSON, FOCUSED_RANKING_MD),
    "pass4_scout": (PASS4_SCOUT_RANKING_JSON, PASS4_SCOUT_RANKING_MD),
    "pass5_scout": (PASS5_SCOUT_RANKING_JSON, PASS5_SCOUT_RANKING_MD),
    "pass5_focused": (PASS5_FOCUSED_RANKING_JSON, PASS5_FOCUSED_RANKING_MD),
    "pass6_scout": (PASS6_SCOUT_RANKING_JSON, PASS6_SCOUT_RANKING_MD),
    "pass6_focused": (PASS6_FOCUSED_RANKING_JSON, PASS6_FOCUSED_RANKING_MD),
}

# z-scores for the confidence intervals we report.
Z_80 = 1.2816  # 80% two-sided -> used as the promotion gate (small samples)
Z_95 = 1.96    # 95% two-sided -> shown for transparency only

# Minimum completed games before a candidate may be labelled promotable.
DEFAULT_MIN_GAMES = 20

# Labels (most to least confident).
LABEL_PROMOTABLE = "promotable"
LABEL_CONFIRMATION = "confirmation_promising"
LABEL_SCOUT = "scout_promising"
LABEL_DIVERSITY = "diversity_candidate"
LABEL_INCONCLUSIVE = "inconclusive"
LABEL_REJECTED = "rejected"

# Control / anchor roles (never candidates; never queued; excluded from top-N).
# v2 = the ACTIVE control (the real comparison baseline candidates must beat).
# v1 = the LEGACY baseline (the original Kaggle control, kept for lineage).
# integrity anchors = exact-copy runs that prove the harness is unbiased.
ROLE_ACTIVE_CONTROL = "active_control"
ROLE_LEGACY_BASELINE = "legacy_baseline"
ROLE_INTEGRITY_ANCHOR = "integrity_anchor"
CONTROL_ROLES = (ROLE_ACTIVE_CONTROL, ROLE_LEGACY_BASELINE, ROLE_INTEGRITY_ANCHOR)
# Label shown for any control/anchor in the ranking board.
LABEL_ANCHOR = "anchor"


def control_role(branch_id, kind=None) -> str | None:
    """Classify a branch as a control/anchor, or ``None`` if it is a candidate.

    Precise by design (no bare ``"control"`` substring match, which would catch
    archetypes like ``tempo_control``):

    * ``active_control``  — a v2-deck no-override anchor (``*control_v2_anchor``).
    * ``legacy_baseline`` — the v1 exact-copy control (``kind == 'control'`` or
      ``conservative_baseline``).
    * ``integrity_anchor``— any other exact-copy anchor (``*_anchor`` /
      ``*baseline_consistency``) used only to check the harness is unbiased.
    """
    bid = str(branch_id or "")
    if "control_v2_anchor" in bid:
        return ROLE_ACTIVE_CONTROL
    if kind == "control" or "conservative_baseline" in bid:
        return ROLE_LEGACY_BASELINE
    if bid.endswith("_anchor") or "baseline_consistency" in bid:
        return ROLE_INTEGRITY_ANCHOR
    return None


def is_control_entry(entry: dict) -> bool:
    """True if a metrics/ranking dict is a control or anchor (never a candidate)."""
    role = entry.get("role")
    if role in CONTROL_ROLES:
        return True
    return control_role(entry.get("branch_id"), entry.get("kind")) is not None


def wilson_interval(wins: float, games: int, z: float = Z_80) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    ``wins`` may be fractional (e.g. draws counted as 0.5) and is clamped to
    ``[0, games]``. Returns ``(low, high)``; for ``games == 0`` returns
    ``(0.0, 1.0)`` (maximally uncertain).
    """
    n = int(games)
    if n <= 0:
        return 0.0, 1.0
    w = max(0.0, min(float(wins), float(n)))
    p = w / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return round(max(0.0, low), 4), round(min(1.0, high), 4)


def hard_reject_reasons(m: dict) -> list[str]:
    reasons = []
    if not m.get("package_ok"):
        reasons.append("package verify failed")
    if not m.get("smoke_ok"):
        reasons.append("smoke failed")
    if int(m.get("crashes", 0)) > 0:
        reasons.append(f"{m.get('crashes')} crash(es)")
    if int(m.get("timeouts", 0)) > 0:
        reasons.append(f"{m.get('timeouts')} timeout(s)")
    # A fallback means the candidate's agent raised mid-game and the runner had
    # to substitute an empty action. That is a silent gameplay failure, so the
    # candidate is not trustworthy and must never be promotable.
    if int(m.get("fallbacks", 0)) > 0:
        reasons.append(f"{m.get('fallbacks')} agent fallback(s)")
    return reasons


def soft_score(m: dict) -> float:
    score = 0.0
    win_rate = m.get("win_rate")
    if win_rate is not None:
        score += float(win_rate) * 1000.0
    else:
        # Outcome unknown: reward stable, real games (longer = less likely a
        # quick illegal exit), but far below any real win signal.
        score += min(float(m.get("avg_steps", 0)), 400.0) * 0.25
    score += float(m.get("attack_rate", 0.0)) * 120.0
    score -= float(m.get("pass_rate", 0.0)) * 120.0
    score -= float(m.get("fallbacks", 0)) * 5.0
    if m.get("kind") == "deck":
        score -= float(m.get("decision_entropy", 0.0)) * 10.0
    return round(score, 3)


def _control_adjusted_win_rate(candidates: list[dict]) -> float:
    """Adjusted win rate of the comparison control (else 0.5).

    The v2 ``active_control`` is the real baseline candidates must beat, so it is
    preferred when present. The v1 ``legacy_baseline`` is the fallback (lineage),
    and integrity anchors are ignored for the gate (they only check the harness).
    """
    by_role: dict[str, float] = {}
    for m in candidates:
        role = control_role(m.get("branch_id"), m.get("kind"))
        if role in (ROLE_ACTIVE_CONTROL, ROLE_LEGACY_BASELINE):
            awr = m.get("adjusted_win_rate")
            if awr is not None and role not in by_role:
                by_role[role] = float(awr)
    if ROLE_ACTIVE_CONTROL in by_role:
        return by_role[ROLE_ACTIVE_CONTROL]
    if ROLE_LEGACY_BASELINE in by_role:
        return by_role[ROLE_LEGACY_BASELINE]
    return 0.5


def label_for(e: dict, control_adj: float, min_games: int) -> tuple[str, str]:
    """Return ``(label, interpretation)`` for an already-scored entry.

    Conservative by design: promotion requires a real sample AND an 80% Wilson
    lower bound above 0.50 AND beating the control. Small/scout samples can only
    reach ``confirmation_promising`` or ``scout_promising`` regardless of raw rate.
    """
    if e["rejected"]:
        return LABEL_REJECTED, "Hard-rejected: " + "; ".join(e["reject_reasons"]) + "."

    games = int(e.get("games_completed") or 0)
    adj = e.get("adjusted_win_rate")
    w80_low = (e.get("wilson80") or [0.0, 1.0])[0]
    beats_control = adj is not None and adj > control_adj + 1e-9
    role = e.get("role") or control_role(e.get("branch_id"), e.get("kind"))

    # Controls and anchors are NEVER candidates: they get the "anchor" label and
    # are excluded from the candidate top-N and the submission queue. The v2
    # active control's win rate is still surfaced as the comparison baseline.
    if role in CONTROL_ROLES:
        adj_s = "n/a" if adj is None else f"{adj:.2f}"
        descr = {
            ROLE_ACTIVE_CONTROL: (
                f"v2 ACTIVE control (adjusted win rate {adj_s} over {games} games); "
                "this is the baseline candidates must beat, not a promotion target."
            ),
            ROLE_LEGACY_BASELINE: (
                f"v1 LEGACY baseline (adjusted win rate {adj_s} over {games} games); "
                "kept for lineage only; the v2 active control is the live baseline."
            ),
            ROLE_INTEGRITY_ANCHOR: (
                f"Integrity anchor — exact-copy run (adjusted win rate {adj_s} over "
                f"{games} games) that only verifies the harness is unbiased; never "
                "ranked as a candidate or queued."
            ),
        }[role]
        return LABEL_ANCHOR, descr

    if games == 0 or adj is None:
        return LABEL_INCONCLUSIVE, (
            "No completed games with a parseable outcome; cannot judge strength."
        )

    if games >= min_games and w80_low > 0.50 and beats_control:
        return LABEL_PROMOTABLE, (
            f"Adjusted win rate {adj:.2f} over {games} games with an 80% lower "
            f"bound of {w80_low:.2f} (> 0.50) and beats the control "
            f"({control_adj:.2f}). Strong enough to queue for manual review."
        )
    if games >= min_games and beats_control and adj >= 0.50:
        return LABEL_CONFIRMATION, (
            f"Adjusted win rate {adj:.2f} over {games} games beats the control "
            f"({control_adj:.2f}) but the 80% lower bound ({w80_low:.2f}) does not "
            "clear 0.50 — promising but not yet confidently above the control."
        )
    if games >= min_games:
        return LABEL_INCONCLUSIVE, (
            f"Adjusted win rate {adj:.2f} over {games} games does not beat the "
            f"control ({control_adj:.2f}); confirmed as no improvement at this "
            "sample size."
        )
    if adj >= 0.55:
        return LABEL_SCOUT, (
            f"Scout-level signal (adjusted {adj:.2f} over only {games} games); "
            "needs a focused, higher-game confirmation before promotion."
        )
    return LABEL_INCONCLUSIVE, (
        f"Adjusted win rate {adj:.2f} over {games} games is not distinguishable "
        "from the control at this sample size."
    )


def rank(
    candidates: list[dict],
    diversity_bonus: float = 50.0,
    event_store: EventStore | None = None,
    min_games: int = DEFAULT_MIN_GAMES,
) -> list[dict]:
    """Rank candidate metric dicts. Returns ranked entries (best first)."""
    store = event_store or EventStore()
    control_adj = _control_adjusted_win_rate(candidates)
    entries: list[dict] = []
    for m in candidates:
        reasons = hard_reject_reasons(m)
        rejected = bool(reasons)
        # Hard rejects never get a soft score: a broken candidate must not be
        # ranked on gameplay metrics it never legitimately produced.
        base = float("-inf") if rejected else soft_score(m)
        games = int(m.get("games_completed") or 0)
        wins = float(m.get("wins") or 0)
        draws = float(m.get("draws") or 0)
        adj_wins = wins + 0.5 * draws
        role = control_role(m.get("branch_id"), m.get("kind"))
        entries.append({
            "branch_id": m.get("branch_id"),
            "seam_id": m.get("seam_id"),
            "kind": m.get("kind"),
            "hypothesis": m.get("hypothesis", ""),
            "stage": m.get("stage"),
            "family": _family_of(m.get("seam_id", "")),
            "role": role,
            "is_control": role is not None,
            "rejected": rejected,
            "reject_reasons": reasons,
            "base_score": base,
            "score": base,
            "win_rate": m.get("win_rate"),
            "adjusted_win_rate": m.get("adjusted_win_rate"),
            "games_completed": games,
            "wins": int(wins),
            "losses": m.get("losses"),
            "draws": int(draws),
            "wilson80": list(wilson_interval(adj_wins, games, Z_80)),
            "wilson95": list(wilson_interval(adj_wins, games, Z_95)),
            "candidate_p0_win_rate": m.get("candidate_p0_win_rate"),
            "candidate_p1_win_rate": m.get("candidate_p1_win_rate"),
            "seat_balance_delta": m.get("seat_balance_delta"),
            "attack_rate": m.get("attack_rate"),
            "pass_rate": m.get("pass_rate"),
            "fallbacks": m.get("fallbacks"),
            "decision_entropy": m.get("decision_entropy"),
            "avg_steps": m.get("avg_steps"),
        })

    # Diversity bonus: first surviving candidate of each family gets a bump so
    # the top of the board isn't dominated by one seam family.
    seen_families: set[str] = set()
    for e in sorted(entries, key=lambda x: (x["rejected"], -x["base_score"])):
        if e["rejected"]:
            e["score"] = float("-inf")
            continue
        # Controls/anchors are not candidates, so they never earn a family
        # diversity bonus (that bonus exists to spread real candidates out).
        if e.get("is_control"):
            e["diversity_bonus"] = 0.0
            continue
        fam = e["family"]
        if fam not in seen_families:
            e["score"] = round(e["base_score"] + diversity_bonus, 3)
            e["diversity_bonus"] = diversity_bonus
            seen_families.add(fam)
        else:
            e["diversity_bonus"] = 0.0

    ranked = sorted(
        entries,
        key=lambda x: (x["rejected"], -(x["score"] if x["score"] != float("-inf") else -1e9)),
    )
    candidate_rank = 0
    for i, e in enumerate(ranked, 1):
        e["rank"] = i
        # candidate_rank numbers ONLY real candidates (skips controls/anchors and
        # rejects) so "top-N candidates" never includes the v2/v1 baselines.
        if e.get("is_control") or e["rejected"]:
            e["candidate_rank"] = None
        else:
            candidate_rank += 1
            e["candidate_rank"] = candidate_rank
        if e["score"] == float("-inf"):
            e["score"] = None
        if e["base_score"] == float("-inf"):
            e["base_score"] = None
        label, interp = label_for(e, control_adj, min_games)
        # A diversity candidate is a non-promotable survivor that still earned a
        # family bonus; surface that so the report can keep one per family visible.
        if label in (LABEL_SCOUT, LABEL_CONFIRMATION) and e.get("diversity_bonus"):
            e["diversity_candidate"] = True
        else:
            e["diversity_candidate"] = False
        e["label"] = label
        e["interpretation"] = interp
        e["promotable"] = label == LABEL_PROMOTABLE
        ev_type = EventType.CandidateRejected if e["rejected"] else (
            EventType.CandidatePromoted if e["promotable"] else EventType.CandidateRanked
        )
        store.append(new_event(
            ev_type,
            payload={"branch_id": e["branch_id"], "rank": i,
                     "score": e["score"], "rejected": e["rejected"],
                     "label": label, "reject_reasons": e["reject_reasons"]},
            tags=["experiment", "ranking"],
        ))
    return ranked


def _family_of(seam_id: str) -> str:
    return seam_id.split(".", 1)[0] if seam_id else "unknown"


def save_ranking(ranked: list[dict], stage: str = "broad") -> tuple[Path, Path]:
    json_path, md_path = STAGE_PATHS.get(stage, STAGE_PATHS["broad"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(ranked, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_render_md(ranked, stage), encoding="utf-8")
    return json_path, md_path


def _render_md(ranked: list[dict], stage: str = "broad") -> str:
    titles = {
        "focused": "focused (seat-swap confirmation)",
        "pass4_scout": "pass 4 scout (replay-derived, seat-swap)",
        "pass5_scout": "pass 5 scout (replay-informed board-aware, seat-swap)",
        "pass5_focused": "pass 5 focused (board-aware confirmation, seat-swap)",
        "pass6_scout": "pass 6 scout (subprocess-isolated, seat-swap)",
        "pass6_focused": "pass 6 focused (subprocess-isolated confirmation, seat-swap)",
        "broad": "broad (scout)",
    }
    title = titles.get(stage, "broad (scout)")
    lines = [f"# Candidate ranking — {title}", ""]
    lines.append("| Rank | Branch | Seam | Score | Adj WR | 80% CI | Games | "
                 "SeatΔ | Label |")
    lines.append("|----:|--------|------|------:|-------:|--------|------:|"
                 "------:|-------|")
    for e in ranked:
        sc = "-" if e.get("score") is None else f"{e['score']:.1f}"
        awr = "-" if e.get("adjusted_win_rate") is None else f"{e['adjusted_win_rate']:.2f}"
        w80 = e.get("wilson80") or [None, None]
        ci = "-" if w80[0] is None else f"{w80[0]:.2f}–{w80[1]:.2f}"
        seatd = e.get("seat_balance_delta")
        seatd_s = "-" if seatd is None else f"{seatd:+.2f}"
        lines.append(
            f"| {e['rank']} | {e['branch_id']} | {e['seam_id']} | {sc} | {awr} | "
            f"{ci} | {e.get('games_completed', 0)} | {seatd_s} | {e.get('label', '-')} |"
        )
    lines.append("")
    lines.append("## Interpretations")
    for e in ranked:
        lines.append(f"- **{e['branch_id']}** ({e.get('label', '-')}): "
                     f"{e.get('interpretation', '')}")
    lines.append("")
    return "\n".join(lines)
