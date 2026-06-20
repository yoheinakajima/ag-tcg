"""Deterministic tournament scheduler v0.

Given the candidate pool, a folded :class:`SchedulerState` (derived from the
event log), and the engine config, produce a *bounded* worklist of games for one
tick. The scheduler never tries to finish a whole tournament in one call and is
fully deterministic for the same (pool, state, config).

Priority order (highest first):
  1. validation/smoke gaps for active/probation candidates
  2. new/probation candidates vs anchors (held probe, new deck vs reference/champion)
  3. parent-child confirmation (seat-swapped) until min games/seat
  4. top-bracket round-robin (least-played matchup first)
  5. exploration (active candidates with fewest total games)
  6. regression sentinels (none active in v0 — Toxic/Durant excluded)

Tie-breakers: fewer completed games for the matchup, older last_played, then
lexicographic candidate_id, then deterministic seat alternation.

Candidates whose status is retired/quarantined/special_pilot_only/invalid are
never scheduled (the pool's ``schedulable()`` already excludes them; the
scheduler asserts it too as defence in depth).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import pool as poolmod
from .config import TournamentConfig
from .pool import CandidatePool


@dataclass
class SchedulerState:
    """Folded view of completed games used to pick the next worklist."""

    games_per_candidate: dict[str, int] = field(default_factory=dict)
    matchup_counts: dict[str, int] = field(default_factory=dict)       # "lo|hi" -> n
    directed_counts: dict[str, int] = field(default_factory=dict)      # "lo>hi@seat" -> n
    last_played: dict[str, float] = field(default_factory=dict)
    ranking: list[str] = field(default_factory=list)                   # best-first cids
    smoke_done: set[str] = field(default_factory=set)

    def cand_games(self, cid: str) -> int:
        return self.games_per_candidate.get(cid, 0)

    def matchup_games(self, lo: str, hi: str) -> int:
        return self.matchup_counts.get(f"{lo}|{hi}", 0)

    def directed_games(self, lo: str, hi: str, seat: int) -> int:
        return self.directed_counts.get(f"{lo}>{hi}@{seat}", 0)


@dataclass
class ScheduledGame:
    game_id: str
    candidate_a: str   # plays at seat ``a_seat``
    candidate_b: str
    a_seat: int        # 0 or 1
    priority: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id, "candidate_a": self.candidate_a,
            "candidate_b": self.candidate_b, "a_seat": self.a_seat,
            "priority": self.priority, "reason": self.reason,
        }


def _pair(x: str, y: str) -> tuple[str, str]:
    return (x, y) if x <= y else (y, x)


def _anchor_for(cand: poolmod.Candidate, schedulable: list[poolmod.Candidate],
                state: SchedulerState) -> str | None:
    """Pick a deterministic anchor opponent: same-family champion/anchor first,
    else the global reference with the most games (most-proven), else lexicographic."""
    fam_anchors = sorted(
        (c for c in schedulable
         if c.family_id == cand.family_id and c.candidate_id != cand.candidate_id
         and c.status in (poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR)),
        key=lambda c: c.candidate_id)
    if fam_anchors:
        return fam_anchors[0].candidate_id
    global_anchors = sorted(
        (c for c in schedulable
         if c.candidate_id != cand.candidate_id
         and c.status in (poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR)),
        key=lambda c: (-state.cand_games(c.candidate_id), c.candidate_id))
    if global_anchors:
        return global_anchors[0].candidate_id
    others = sorted((c.candidate_id for c in schedulable
                     if c.candidate_id != cand.candidate_id))
    return others[0] if others else None


def _priority_matchups(pool: CandidatePool, state: SchedulerState,
                       cfg: TournamentConfig) -> list[tuple[tuple[str, str], int, str]]:
    """Return ordered, de-duplicated (pair, priority, reason) matchups."""
    sched = sorted(pool.schedulable(), key=lambda c: c.candidate_id)
    sched_ids = {c.candidate_id for c in sched}
    out: list[tuple[tuple[str, str], int, str]] = []

    def add(a: str, b: str, prio: int, reason: str) -> None:
        if a == b or a not in sched_ids or b not in sched_ids:
            return
        out.append((_pair(a, b), prio, reason))

    # Tier 1: smoke/placement gaps.
    for c in sched:
        if c.candidate_id not in state.smoke_done or state.cand_games(c.candidate_id) == 0:
            opp = _anchor_for(c, sched, state)
            if opp:
                add(c.candidate_id, opp, 1, "smoke_or_placement_gap")

    # Tier 2: new/probation/held vs anchors (under min placement games).
    for c in sorted(sched, key=lambda c: (state.cand_games(c.candidate_id), c.candidate_id)):
        if c.status in (poolmod.HELD_PROBE, poolmod.PROBATION) or \
                state.cand_games(c.candidate_id) < cfg.min_placement_games_per_candidate:
            opp = _anchor_for(c, sched, state)
            if opp:
                add(c.candidate_id, opp, 2, f"placement_vs_anchor[{c.status}]")

    # Tier 3: parent-child confirmation, seat-swapped.
    for c in sorted(sched, key=lambda c: c.candidate_id):
        p = c.parent_candidate_id
        if p and p in sched_ids:
            lo, hi = _pair(c.candidate_id, p)
            need = (state.directed_games(lo, hi, 0) < cfg.min_parent_child_games_per_seat or
                    state.directed_games(lo, hi, 1) < cfg.min_parent_child_games_per_seat)
            if need:
                add(c.candidate_id, p, 3, "parent_child_confirmation")

    # Tier 4: top-bracket round-robin (least-played matchup first).
    if state.ranking:
        top = [cid for cid in state.ranking if cid in sched_ids][:cfg.top_bracket_size]
    else:
        top = [c.candidate_id for c in sorted(
            sched, key=lambda c: (-state.cand_games(c.candidate_id), c.candidate_id))
        ][:cfg.top_bracket_size]
    bracket_pairs = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            lo, hi = _pair(top[i], top[j])
            bracket_pairs.append((lo, hi))
    for lo, hi in sorted(bracket_pairs, key=lambda p: (state.matchup_games(*p), p)):
        add(lo, hi, 4, "top_bracket_round_robin")

    # Tier 5: exploration — active candidates with fewest total games vs an anchor.
    for c in sorted(sched, key=lambda c: (state.cand_games(c.candidate_id), c.candidate_id)):
        opp = _anchor_for(c, sched, state)
        if opp:
            add(c.candidate_id, opp, 5, "exploration_fewest_games")

    # De-duplicate, keeping the highest-priority (lowest prio number) first seen.
    seen: dict[tuple[str, str], tuple[int, str]] = {}
    for pair, prio, reason in out:
        if pair not in seen or prio < seen[pair][0]:
            seen[pair] = (prio, reason)
    ordered = sorted(seen.items(), key=lambda kv: (kv[1][0], kv[0]))
    return [(pair, prio, reason) for pair, (prio, reason) in ordered]


def build_worklist(pool: CandidatePool, state: SchedulerState,
                   cfg: TournamentConfig, max_games: int | None = None) -> list[ScheduledGame]:
    """Produce a deterministic, bounded worklist of single games for one tick."""
    max_games = cfg.tick_max_games if max_games is None else max_games
    # Defence in depth: never schedule a non-schedulable candidate.
    blocked = {c.candidate_id for c in pool.candidates if not c.schedulable}
    matchups = [(p, pr, r) for (p, pr, r) in _priority_matchups(pool, state, cfg)
                if p[0] not in blocked and p[1] not in blocked]

    games: list[ScheduledGame] = []
    seq = dict(state.directed_counts)
    tid = pool.tournament_id

    def dgames(lo: str, hi: str, seat: int) -> int:
        return seq.get(f"{lo}>{hi}@{seat}", 0)

    while len(games) < max_games and matchups:
        progressed = False
        for (lo, hi), prio, reason in matchups:
            if len(games) >= max_games:
                break
            n0, n1 = dgames(lo, hi, 0), dgames(lo, hi, 1)
            seat = 0 if n0 <= n1 else 1  # deterministic seat balancing
            n = dgames(lo, hi, seat)
            gid = f"{tid}|{lo}>{hi}@{seat}|g{n}"
            # candidate_a is whoever sits at seat 0 of this game record.
            cand_a, cand_b = (lo, hi) if seat == 0 else (hi, lo)
            a_seat = 0  # candidate_a always recorded at seat 0 for clarity
            games.append(ScheduledGame(gid, cand_a, cand_b, a_seat, prio, reason))
            seq[f"{lo}>{hi}@{seat}"] = n + 1
            progressed = True
        if not progressed:
            break
    return games
