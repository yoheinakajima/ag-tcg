"""Simple round-robin tournament among (agent, deck) entrants.

Requires cabt for actual play; without it, ``round_robin`` returns a planned
schedule (no results) and marks itself unavailable so callers can report it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

from .local_runner import LocalRunner
from .cabt_adapter import CabtUnavailableError


@dataclass
class Entrant:
    name: str
    agent: Callable[[dict], list[int]]
    deck: list[int]


@dataclass
class TournamentResult:
    available: bool
    schedule: list[tuple[str, str]] = field(default_factory=list)
    records: dict = field(default_factory=dict)  # name -> {wins,losses,draws,games}
    note: str = ""


def round_robin(
    entrants: list[Entrant],
    games_per_pair: int = 1,
    runner: LocalRunner | None = None,
) -> TournamentResult:
    """Play every pair of entrants ``games_per_pair`` times."""
    runner = runner or LocalRunner()
    schedule = [
        (a.name, b.name) for a, b in itertools.combinations(entrants, 2)
    ]
    records = {e.name: {"wins": 0, "losses": 0, "draws": 0, "games": 0} for e in entrants}

    if not runner.available():
        return TournamentResult(
            available=False,
            schedule=schedule,
            records=records,
            note="cabt unavailable: returning planned schedule only.",
        )

    by_name = {e.name: e for e in entrants}
    for a_name, b_name in schedule:
        a, b = by_name[a_name], by_name[b_name]
        for _ in range(max(1, games_per_pair)):
            try:
                result = runner.run_match(a.agent, b.agent, a.deck, b.deck)
            except CabtUnavailableError:
                return TournamentResult(
                    available=False, schedule=schedule, records=records,
                    note="cabt became unavailable mid-tournament.",
                )
            records[a_name]["games"] += 1
            records[b_name]["games"] += 1
            winner = result.get("winner")
            if winner == 0:
                records[a_name]["wins"] += 1
                records[b_name]["losses"] += 1
            elif winner == 1:
                records[b_name]["wins"] += 1
                records[a_name]["losses"] += 1
            else:
                records[a_name]["draws"] += 1
                records[b_name]["draws"] += 1

    return TournamentResult(available=True, schedule=schedule, records=records)
