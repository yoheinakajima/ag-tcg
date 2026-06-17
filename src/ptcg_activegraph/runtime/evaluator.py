"""State evaluation helpers used by search and (later) tuned heuristics.

Provides a single scalar ``evaluate_state`` over a parsed/extracted belief, plus
a notion of "terminal-ish" advantage (prizes remaining). This is intentionally
simple and is a documented *patch seam* (``state_evaluator_formula``) the lab
can tune. It is pure and never raises.
"""

from __future__ import annotations

from typing import Any

from .belief import BeliefState, extract_belief

# Weights for the linear evaluation. Tunable via the lab (patch seam).
W_PRIZE = 100.0       # fewer of our prizes remaining is better (closer to win)
W_OPP_PRIZE = 100.0   # more of opponent's prizes remaining is worse for them
W_HAND = 3.0
W_BOARD = 6.0
W_OPP_BOARD = 6.0


def evaluate_belief(belief: BeliefState) -> float:
    """Linear score from our perspective; higher is better.

    Lower own prize_count is good (we are closer to taking all prizes). We model
    "prizes remaining" so fewer-remaining is advantageous.
    """
    score = 0.0
    score += W_OPP_PRIZE * belief.opp_prize_count   # opp far from winning -> good
    score -= W_PRIZE * belief.own_prize_count       # we far from winning -> bad
    score += W_HAND * len(belief.own_hand)
    score += W_BOARD * len(belief.own_board)
    score -= W_OPP_BOARD * len(belief.opp_bench)
    score -= W_HAND * belief.opp_hand_count
    return score


def evaluate_state(current: Any) -> float:
    """Evaluate a raw board state by extracting a belief first."""
    return evaluate_belief(extract_belief(current))
