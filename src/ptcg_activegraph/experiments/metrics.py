"""Aggregate per-game results into transparent candidate metrics.

The runner emits one result dict per game; :func:`compute_metrics` folds a list
of them into the numbers the ranker and report consume. Everything degrades
gracefully: if win/loss can't be parsed we still report games completed, steps
and decision instrumentation, and mark the outcome ``unknown``.
"""

from __future__ import annotations

import math
from collections import Counter


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_metrics(results: list[dict]) -> dict:
    """Fold per-game result dicts into aggregate metrics."""
    games_attempted = len(results)
    completed = [r for r in results if r.get("completed")]
    games_completed = len(completed)

    wins = sum(1 for r in completed if r.get("candidate_won") is True)
    losses = sum(1 for r in completed if r.get("candidate_won") is False)
    draws = sum(1 for r in completed if r.get("candidate_won") is None and r.get("draw"))
    unknown = games_completed - wins - losses - draws

    crashes = sum(1 for r in results if r.get("error"))
    timeouts = sum(1 for r in results if r.get("timeout"))

    steps = [int(r.get("steps", 0)) for r in completed if r.get("steps")]
    avg_steps = _safe_div(sum(steps), len(steps))
    max_steps = max(steps) if steps else 0

    decisions = sum(int(r.get("decisions", 0)) for r in results)
    attacks = sum(int(r.get("attacks", 0)) for r in results)
    passes = sum(int(r.get("passes", 0)) for r in results)
    attack_available = sum(int(r.get("attack_available", 0)) for r in results)
    fallbacks = sum(int(r.get("fallbacks", 0)) for r in results)
    option_count_sum = sum(int(r.get("option_count_sum", 0)) for r in results)

    # Decision entropy over chosen option types (lower = more deterministic).
    type_counter: Counter = Counter()
    for r in results:
        for k, v in (r.get("type_counts") or {}).items():
            type_counter[str(k)] += int(v)
    entropy = _decision_entropy(type_counter)

    # Seat split.
    seat0 = [r for r in completed if r.get("candidate_seat") == 0]
    seat1 = [r for r in completed if r.get("candidate_seat") == 1]
    seat0_wins = sum(1 for r in seat0 if r.get("candidate_won") is True)
    seat1_wins = sum(1 for r in seat1 if r.get("candidate_won") is True)
    seat0_rate = _safe_div(seat0_wins, len(seat0)) if seat0 else None
    seat1_rate = _safe_div(seat1_wins, len(seat1)) if seat1 else None
    if seat0_rate is not None and seat1_rate is not None:
        seat_balance_delta = round(seat0_rate - seat1_rate, 4)
    else:
        seat_balance_delta = None

    win_rate = _safe_div(wins, games_completed) if games_completed else None
    # Draw-adjusted win rate: a draw counts as half a win (standard convention),
    # so a candidate is not unfairly punished/rewarded for stalemates.
    adjusted_win_rate = (
        round(_safe_div(wins + 0.5 * draws, games_completed), 4)
        if games_completed else None
    )

    return {
        "games_attempted": games_attempted,
        "games_completed": games_completed,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "unknown_outcomes": unknown,
        "win_rate": win_rate,
        "adjusted_win_rate": adjusted_win_rate,
        "combined_win_rate": win_rate,
        "crashes": crashes,
        "timeouts": timeouts,
        "avg_steps": round(avg_steps, 2),
        "max_steps": max_steps,
        "decisions": decisions,
        "attacks": attacks,
        "passes": passes,
        "attack_available": attack_available,
        "fallbacks": fallbacks,
        "attack_rate": round(_safe_div(attacks, decisions), 4),
        "attack_take_rate": round(_safe_div(attacks, attack_available), 4),
        "pass_rate": round(_safe_div(passes, decisions), 4),
        "avg_options": round(_safe_div(option_count_sum, decisions), 3),
        "decision_entropy": round(entropy, 4),
        "seat0_games": len(seat0),
        "seat1_games": len(seat1),
        "seat0_wins": seat0_wins,
        "seat1_wins": seat1_wins,
        "candidate_as_p0_games": len(seat0),
        "candidate_as_p0_wins": seat0_wins,
        "candidate_as_p1_games": len(seat1),
        "candidate_as_p1_wins": seat1_wins,
        "candidate_p0_win_rate": None if seat0_rate is None else round(seat0_rate, 4),
        "candidate_p1_win_rate": None if seat1_rate is None else round(seat1_rate, 4),
        "seat_balance_delta": seat_balance_delta,
    }


def _decision_entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    ent = 0.0
    for n in counter.values():
        p = n / total
        if p > 0:
            ent -= p * math.log2(p)
    return ent
