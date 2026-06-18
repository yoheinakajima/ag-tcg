"""Rank scout candidates from durable ledger state (Pass 7B, Part G).

This reads the ActiveGraph durable ledger ONLY — never old ``metrics.json``
files or detached stdout. For one run it folds the per-game outcome stream
(``GameResultRecorded`` + the ``GameFinished``/``GameTimeout``/``GameCrashed``/
``GameStale`` status projection) into a per-candidate ranking with Wilson
confidence intervals, seat splits, failure counts, and a conservative promotion
label.

Hard ranking rules (mirrored from the Pass 7B spec):

* Controls/anchors never appear in the top candidate list and never queue.
* Any timeout/crash/stale on a candidate means it is *not* promotable.
* Small samples are at most ``scout_promising`` / ``inconclusive``.
* No ``promotable`` label below 20 completed games.
* Metrics come from completed games only; crash/timeout/stale counts are
  preserved alongside.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..ag import ActiveGraphLedger

# z-scores for two-sided Wilson intervals.
_Z = {80: 1.2815515594600303, 95: 1.959963984540054}

_CONTROL_HINTS = ("control", "anchor", "baseline")


def _is_control_like(candidate_id: str) -> bool:
    cid = candidate_id.lower()
    return any(h in cid for h in _CONTROL_HINTS)


def wilson_interval(successes: float, n: int, confidence: int = 95) -> tuple[float, float]:
    """Two-sided Wilson score interval for a binomial proportion.

    ``successes`` may be fractional (draws counted as half a win). Returns
    ``(low, high)`` clamped to [0, 1]; ``(0.0, 1.0)`` when ``n == 0``.
    """
    if n <= 0:
        return (0.0, 1.0)
    z = _Z.get(confidence, _Z[95])
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class CandidateRanking:
    candidate_id: str
    role: str = "candidate"
    games_planned: int = 0
    games_completed: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    adjusted_win_rate: float | None = None
    wilson_80: tuple[float, float] | None = None
    wilson_95: tuple[float, float] | None = None
    seat_p0_win_rate: float | None = None
    seat_p1_win_rate: float | None = None
    crashes: int = 0
    timeouts: int = 0
    stale: int = 0
    fixture_gate_status: str = "not_tested"
    package_status: str | None = None
    smoke_status: str | None = None
    runner_mode: str | None = None
    fast_import_stub_used: bool = False
    promotion_label: str = "inconclusive"

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["wilson_80"] = list(self.wilson_80) if self.wilson_80 else None
        d["wilson_95"] = list(self.wilson_95) if self.wilson_95 else None
        return d


@dataclass
class _GameAgg:
    seat: int | None = None
    final_status: str | None = None
    completed: bool = False
    candidate_won: bool | None = None
    draw: bool = False
    fast_stub: bool = False


def _collect_games(events: list[dict]) -> dict[str, dict[str, _GameAgg]]:
    """candidate_id -> {game_id -> _GameAgg} folded from the event stream."""
    status_by_event = {
        "GameFinished": "completed",
        "GameTimeout": "timeout",
        "GameCrashed": "crashed",
        "GameStale": "stale",
    }
    out: dict[str, dict[str, _GameAgg]] = {}
    cand_by_game: dict[str, str] = {}

    for ev in events:
        et = ev.get("event_type", "")
        p = ev.get("payload") or {}
        gid = p.get("game_id")
        cid = p.get("candidate_id")
        if gid and cid:
            cand_by_game[gid] = cid
        if et == "GamePlanned" and gid and cid:
            out.setdefault(cid, {}).setdefault(gid, _GameAgg(seat=p.get("seat")))

    for ev in events:
        et = ev.get("event_type", "")
        p = ev.get("payload") or {}
        gid = p.get("game_id")
        if not gid:
            continue
        cid = cand_by_game.get(gid)
        if not cid:
            continue
        agg = out.setdefault(cid, {}).setdefault(gid, _GameAgg())
        if et in status_by_event:
            agg.final_status = status_by_event[et]
            if p.get("seat") is not None:
                agg.seat = p.get("seat")
        if et == "GameResultRecorded":
            res = p.get("result") or {}
            agg.completed = bool(res.get("completed"))
            agg.candidate_won = res.get("candidate_won")
            agg.draw = bool(res.get("draw"))
            if res.get("candidate_seat") is not None:
                agg.seat = res.get("candidate_seat")
            agg.fast_stub = bool(res.get("fast_import_stub_enabled"))
    return out


def _label(r: CandidateRanking) -> str:
    if r.role in ("anchor", "active_control"):
        return "anchor_control"
    if r.fixture_gate_status == "fail":
        return "blocked"
    if r.games_completed == 0:
        return "blocked"
    # Any instability disqualifies promotion outright.
    if r.crashes or r.timeouts or r.stale:
        return "inconclusive"
    adj = r.adjusted_win_rate or 0.0
    lo95 = r.wilson_95[0] if r.wilson_95 else 0.0
    if r.games_completed >= 20 and lo95 > 0.5:
        return "promotable"
    if adj > 0.5:
        return "scout_promising"
    if adj < 0.4:
        return "rejected"
    return "inconclusive"


def rank_run(
    run_id: str,
    ledger: ActiveGraphLedger | None = None,
    fixture_status: dict[str, str] | None = None,
    package_status: dict[str, str] | None = None,
    smoke_status: dict[str, str] | None = None,
) -> dict:
    """Build the full ranking dict for ``run_id`` from durable ledger state."""
    ledger = ledger or ActiveGraphLedger(warn=False)
    events = ledger.events_for(run_id)
    run_meta = next((r for r in ledger.list_runs() if r.get("run_id") == run_id), {})
    meta = (run_meta or {}).get("metadata", {}) or {}
    run_fast_stub = bool(meta.get("fast_import_stub"))
    runner_mode = meta.get("runner_mode")
    fixture_status = fixture_status or {}

    games_by_cand = _collect_games(events)
    rankings: list[CandidateRanking] = []
    for cid, games in sorted(games_by_cand.items()):
        r = CandidateRanking(candidate_id=cid)
        r.role = "anchor" if _is_control_like(cid) else "candidate"
        r.runner_mode = runner_mode
        r.games_planned = len(games)
        r.fixture_gate_status = fixture_status.get(cid, "not_tested")
        if package_status:
            r.package_status = package_status.get(cid)
        if smoke_status:
            r.smoke_status = smoke_status.get(cid)

        p0_wins = p0_n = p1_wins = p1_n = 0
        adj_success = 0.0
        for agg in games.values():
            if agg.fast_stub:
                r.fast_import_stub_used = True
            fs = agg.final_status
            if fs == "timeout":
                r.timeouts += 1
            elif fs == "crashed":
                r.crashes += 1
            elif fs == "stale":
                r.stale += 1
            if not agg.completed:
                continue
            r.games_completed += 1
            won = bool(agg.candidate_won)
            if agg.draw:
                r.draws += 1
                adj_success += 0.5
            elif won:
                r.wins += 1
                adj_success += 1.0
            else:
                r.losses += 1
            if agg.seat == 0:
                p0_n += 1
                p0_wins += 1 if (won and not agg.draw) else 0
            elif agg.seat == 1:
                p1_n += 1
                p1_wins += 1 if (won and not agg.draw) else 0

        if not r.fast_import_stub_used and run_fast_stub:
            r.fast_import_stub_used = run_fast_stub
        n = r.games_completed
        if n:
            r.adjusted_win_rate = round(adj_success / n, 4)
            r.wilson_80 = tuple(round(x, 4) for x in wilson_interval(adj_success, n, 80))
            r.wilson_95 = tuple(round(x, 4) for x in wilson_interval(adj_success, n, 95))
        if p0_n:
            r.seat_p0_win_rate = round(p0_wins / p0_n, 4)
        if p1_n:
            r.seat_p1_win_rate = round(p1_wins / p1_n, 4)
        r.promotion_label = _label(r)
        rankings.append(r)

    candidates = [r for r in rankings if r.role == "candidate"]
    anchors = [r for r in rankings if r.role != "candidate"]
    candidates.sort(
        key=lambda r: (
            r.adjusted_win_rate if r.adjusted_win_rate is not None else -1.0,
            r.games_completed,
        ),
        reverse=True,
    )

    any_fast_stub = run_fast_stub or any(
        r.fast_import_stub_used for r in (candidates + anchors)
    )
    return {
        "run_id": run_id,
        "stage": meta.get("stage"),
        "runner_mode": runner_mode,
        "fast_import_stub_used": any_fast_stub,
        "control": "v2_deck_energy_trim_light_479_1",
        "ranking_source": "durable_activegraph_ledger",
        "candidates": [r.to_dict() for r in candidates],
        "anchors": [r.to_dict() for r in anchors],
    }


def _fmt_ci(ci) -> str:
    if not ci:
        return "—"
    return f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def ranking_to_markdown(rank: dict) -> str:
    lines: list[str] = []
    lines.append("# Pass 7B Scout Ranking (durable ledger)")
    lines.append("")
    lines.append(f"- run_id: `{rank['run_id']}`")
    lines.append(f"- stage: `{rank.get('stage')}`")
    lines.append(f"- ranking source: `{rank.get('ranking_source')}`")
    lines.append(f"- runner mode: `{rank.get('runner_mode')}`")
    lines.append(f"- fast import stub used: {rank.get('fast_import_stub_used')}")
    lines.append(f"- active control: {rank.get('control')} (excluded from candidate list)")
    lines.append("")
    lines.append("## Candidates (controls/anchors excluded)")
    lines.append("")
    header = (
        "| # | candidate | label | completed | W-L-D | adj win | "
        "Wilson 80% | Wilson 95% | p0 | p1 | crash | timeout | stale | fixture |"
    )
    lines.append(header)
    lines.append("|" + "---|" * 14)
    for i, c in enumerate(rank["candidates"], 1):
        p0 = "—" if c["seat_p0_win_rate"] is None else f"{c['seat_p0_win_rate']:.2f}"
        p1 = "—" if c["seat_p1_win_rate"] is None else f"{c['seat_p1_win_rate']:.2f}"
        adj = "—" if c["adjusted_win_rate"] is None else f"{c['adjusted_win_rate']:.2f}"
        lines.append(
            f"| {i} | {c['candidate_id']} | {c['promotion_label']} | "
            f"{c['games_completed']}/{c['games_planned']} | "
            f"{c['wins']}-{c['losses']}-{c['draws']} | {adj} | "
            f"{_fmt_ci(c['wilson_80'])} | {_fmt_ci(c['wilson_95'])} | {p0} | {p1} | "
            f"{c['crashes']} | {c['timeouts']} | {c['stale']} | {c['fixture_gate_status']} |"
        )
    lines.append("")
    lines.append("## Anchors / controls (never queued)")
    lines.append("")
    for a in rank["anchors"]:
        adj = "—" if a["adjusted_win_rate"] is None else f"{a['adjusted_win_rate']:.2f}"
        lines.append(
            f"- `{a['candidate_id']}` — role {a['role']}, label {a['promotion_label']}, "
            f"completed {a['games_completed']}/{a['games_planned']}, adj {adj}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_ranking(
    run_id: str,
    out_json: str | Path,
    out_md: str | Path,
    ledger: ActiveGraphLedger | None = None,
    fixture_status: dict[str, str] | None = None,
) -> dict:
    rank = rank_run(run_id, ledger=ledger, fixture_status=fixture_status)
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(rank, indent=2, default=str), encoding="utf-8")
    Path(out_md).write_text(ranking_to_markdown(rank), encoding="utf-8")
    return rank
