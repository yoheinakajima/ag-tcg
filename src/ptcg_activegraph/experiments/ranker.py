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
from pathlib import Path

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event

RANKING_JSON = Path("data/experiments/latest_ranking.json")
RANKING_MD = Path("data/experiments/latest_ranking.md")


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


def rank(
    candidates: list[dict],
    diversity_bonus: float = 50.0,
    event_store: EventStore | None = None,
) -> list[dict]:
    """Rank candidate metric dicts. Returns ranked entries (best first)."""
    store = event_store or EventStore()
    entries: list[dict] = []
    for m in candidates:
        reasons = hard_reject_reasons(m)
        rejected = bool(reasons)
        # Hard rejects never get a soft score: a broken candidate must not be
        # ranked on gameplay metrics it never legitimately produced.
        base = float("-inf") if rejected else soft_score(m)
        entries.append({
            "branch_id": m.get("branch_id"),
            "seam_id": m.get("seam_id"),
            "kind": m.get("kind"),
            "family": _family_of(m.get("seam_id", "")),
            "rejected": rejected,
            "reject_reasons": reasons,
            "base_score": base,
            "score": base,
            "win_rate": m.get("win_rate"),
            "games_completed": m.get("games_completed"),
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
    for i, e in enumerate(ranked, 1):
        e["rank"] = i
        if e["score"] == float("-inf"):
            e["score"] = None
        if e["base_score"] == float("-inf"):
            e["base_score"] = None
        store.append(new_event(
            EventType.CandidateRanked,
            payload={"branch_id": e["branch_id"], "rank": i,
                     "score": e["score"], "rejected": e["rejected"],
                     "reject_reasons": e["reject_reasons"]},
            tags=["experiment", "ranking"],
        ))
    return ranked


def _family_of(seam_id: str) -> str:
    return seam_id.split(".", 1)[0] if seam_id else "unknown"


def save_ranking(ranked: list[dict]) -> tuple[Path, Path]:
    RANKING_JSON.parent.mkdir(parents=True, exist_ok=True)
    RANKING_JSON.write_text(json.dumps(ranked, indent=2, default=str), encoding="utf-8")
    RANKING_MD.write_text(_render_md(ranked), encoding="utf-8")
    return RANKING_JSON, RANKING_MD


def _render_md(ranked: list[dict]) -> str:
    lines = ["# Candidate ranking (latest)", ""]
    lines.append("| Rank | Branch | Seam | Score | Win rate | Games | Attack | Pass | Status |")
    lines.append("|----:|--------|------|------:|---------:|------:|-------:|-----:|--------|")
    for e in ranked:
        status = "REJECTED: " + "; ".join(e["reject_reasons"]) if e["rejected"] else "ok"
        wr = "-" if e.get("win_rate") is None else f"{e['win_rate']:.2f}"
        sc = "-" if e.get("score") is None else f"{e['score']:.1f}"
        lines.append(
            f"| {e['rank']} | {e['branch_id']} | {e['seam_id']} | {sc} | {wr} | "
            f"{e.get('games_completed', 0)} | {e.get('attack_rate', 0)} | "
            f"{e.get('pass_rate', 0)} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)
