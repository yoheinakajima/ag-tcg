"""Bounded, resumable, event-first tournament tick runner.

A *tick* schedules and plays a bounded set of games, emitting events LIVE
(GameScheduled -> GameStarted -> GameFinished) as it goes. Each game runs in an
isolated subprocess (the cabt worker), so a hung native engine or a killed
background shell never corrupts state: finished games are already durable on the
ledger, and re-running resumes without replaying finished game ids.

This runner does NOT generate candidates and NEVER uploads or submits.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from ..graph.events import EventType
from . import artifacts, projections
from .config import TournamentConfig, load_config
from .ledger import TournamentLedger
from .pool import CandidatePool
from .scheduler import build_worklist

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = REPO_ROOT / "scripts" / "_tournament_game_worker.py"
RUNS_DIR = REPO_ROOT / "data" / "tournament" / "runs"
TICK_LOCK_PATH = REPO_ROOT / "data" / "tournament" / ".tick.lock"


class TickInProgressError(RuntimeError):
    """Raised when another tick already holds the single-run lock."""


@contextlib.contextmanager
def _tick_lock(lock_path: Path = TICK_LOCK_PATH):
    """Single-run guard: only one tick may schedule/play at a time.

    Without this, two concurrent daemon invocations could compute the same
    pre-filter worklist and schedule overlapping game ids before either appended
    its finishes — breaking the no-duplicate-game-id guarantee. The lock is a
    non-blocking flock; a second concurrent tick fails fast rather than racing.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise TickInProgressError(
                    "another tournament tick is already running "
                    f"(lock held: {lock_path})") from exc
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()} ts={time.time()}\n".encode())
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class TournamentEngine:
    def __init__(self, cfg: TournamentConfig | None = None,
                 pool: CandidatePool | None = None,
                 ledger: TournamentLedger | None = None) -> None:
        self.cfg = cfg or load_config()
        self.pool = pool or CandidatePool.load()
        self.ledger = ledger or TournamentLedger()
        self._main_cache: dict[str, str] = {}
        self._agents_dir: Path | None = None

    # -- engine init (idempotent) -----------------------------------------
    def ensure_initialized(self) -> None:
        events = self.ledger.load()
        if not any(e.event_type == EventType.TournamentEngineInitialized.value
                   for e in events):
            self.ledger.emit(EventType.TournamentEngineInitialized, {
                "tournament_id": self.pool.tournament_id,
                "config": self.cfg.to_dict(),
                "sidecar_codec": artifacts.sidecar_codec(),
            }, tags=["lifecycle"])
        registered = {e.payload.get("candidate_id") for e in events
                      if e.event_type == EventType.TournamentParticipantRegistered.value}
        # Register EVERY candidate (not just schedulable) with a FULL snapshot, so
        # the registry — and therefore every projection — is rebuildable from the
        # ledger alone (see CandidatePool.from_events).
        for c in sorted(self.pool.candidates, key=lambda c: c.candidate_id):
            if c.candidate_id not in registered:
                self.ledger.emit(EventType.TournamentParticipantRegistered, {
                    "candidate_id": c.candidate_id, "family_id": c.family_id,
                    "status": c.status, "tarball_path": c.tarball_path,
                    "candidate": c.to_dict(),
                }, tags=["lifecycle"])

    # -- agent extraction --------------------------------------------------
    def _main_for(self, candidate_id: str) -> str:
        if candidate_id in self._main_cache:
            return self._main_cache[candidate_id]
        if self._agents_dir is None:
            self._agents_dir = Path(tempfile.mkdtemp(prefix="ptcg_tourney_agents_"))
        c = self.pool.by_id(candidate_id)
        if c is None:
            raise KeyError(candidate_id)
        tar = REPO_ROOT / "data" / "submissions" / c.tarball_path
        main = artifacts.extract_agent_main(tar, self._agents_dir / candidate_id)
        self._main_cache[candidate_id] = main
        return main

    # -- one game (isolated subprocess) -----------------------------------
    def _play_one(self, game: dict, tick_id: str, run_id: str,
                  parent_ids: list[str]) -> dict:
        a, b = game["candidate_a"], game["candidate_b"]
        first_main = self._main_for(a)   # candidate_a sits at seat 0
        second_main = self._main_for(b)
        spec = [{"game_id": game["game_id"], "candidate_a": a, "candidate_b": b,
                 "a_seat": 0, "first_main": first_main, "second_main": second_main}]
        with tempfile.TemporaryDirectory(prefix="ptcg_game_") as td:
            spec_path = Path(td) / "spec.json"
            out_path = Path(td) / "out.jsonl"
            spec_path.write_text(json.dumps(spec))
            gt = self.cfg.per_game_timeout_seconds
            sched_ev = self.ledger.emit(EventType.GameScheduled, {
                "game_id": game["game_id"], "tick_id": tick_id, "run_id": run_id,
                "tournament_id": self.pool.tournament_id, "candidate_a": a,
                "candidate_b": b, "seat_assignment": {a: 0, b: 1},
                "priority": game["priority"], "reason": game["reason"],
            }, parent_event_ids=parent_ids, tags=["game"])
            start_ev = self.ledger.emit(EventType.GameStarted, {
                "game_id": game["game_id"], "tick_id": tick_id, "run_id": run_id,
                "candidate_a": a, "candidate_b": b,
            }, parent_event_ids=[sched_ev.event_id], tags=["game"])
            t0 = time.time()
            res_line = None
            try:
                subprocess.run(
                    [sys.executable, str(WORKER), str(spec_path), str(out_path),
                     str(gt + 5), str(gt)],
                    timeout=gt + 30, capture_output=True, text=True,
                    cwd=str(REPO_ROOT))
            except subprocess.TimeoutExpired:
                pass  # hard backstop kill; durable lines (if any) remain on disk
            elapsed = round(time.time() - t0, 3)
            if out_path.exists():
                for ln in out_path.read_text(encoding="utf-8").splitlines():
                    try:
                        rec = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("ev") == "result" and rec.get("game_id") == game["game_id"]:
                        res_line = rec

        if res_line is None:
            result = "timeout"
            payload = {"ok": False, "timeout": True, "a_outcome": None,
                       "steps": None, "elapsed_s": elapsed, "error": "wedged_or_killed"}
        elif res_line.get("ok"):
            result = res_line.get("a_outcome") or "draw"
            payload = {"ok": True, "timeout": False,
                       "a_outcome": res_line.get("a_outcome"),
                       "steps": res_line.get("steps"),
                       "elapsed_s": res_line.get("elapsed_s", elapsed),
                       "rewards": res_line.get("rewards"),
                       "statuses": res_line.get("statuses"), "error": None}
        else:
            result = "timeout" if res_line.get("timeout") else "error"
            payload = {"ok": False, "timeout": bool(res_line.get("timeout")),
                       "a_outcome": None, "steps": res_line.get("steps"),
                       "elapsed_s": res_line.get("elapsed_s", elapsed),
                       "error": res_line.get("error")}

        sidecar = artifacts.write_game_sidecar(game["game_id"], {
            "game_id": game["game_id"], "tournament_id": self.pool.tournament_id,
            "tick_id": tick_id, "run_id": run_id, "candidate_a": a, "candidate_b": b,
            "seat_assignment": {a: 0, b: 1}, "result": result, **payload,
        })
        fin = self.ledger.emit(EventType.GameFinished, {
            "game_id": game["game_id"], "tick_id": tick_id, "run_id": run_id,
            "tournament_id": self.pool.tournament_id, "candidate_a": a,
            "candidate_b": b, "seat_assignment": {a: 0, b: 1}, "result": result,
            "artifact_path": sidecar["path"], "artifact_sha256": sidecar["sha256"],
            "artifact_codec": sidecar["codec"], **payload,
        }, parent_event_ids=[start_ev.event_id], tags=["game"])
        return {"game_id": game["game_id"], "result": result,
                "event_id": fin.event_id, "elapsed_s": payload["elapsed_s"]}

    # -- one bounded tick --------------------------------------------------
    def run_tick(self, max_games: int | None = None,
                 max_seconds: int | None = None) -> dict:
        """Run one bounded tick under a single-run lock (concurrency-safe)."""
        with _tick_lock():
            return self._do_tick(max_games=max_games, max_seconds=max_seconds)

    def _do_tick(self, max_games: int | None = None,
                 max_seconds: int | None = None) -> dict:
        self.ensure_initialized()
        max_games = self.cfg.tick_max_games if max_games is None else max_games
        max_seconds = self.cfg.tick_max_seconds if max_seconds is None else max_seconds
        tick_id = f"tick_{uuid.uuid4().hex[:10]}"
        run_id = tick_id

        events = self.ledger.load()
        prior = projections.write_projections(self.pool, events, self.cfg)
        state = projections.build_scheduler_state(events, ranking=prior["ranked_ids"])
        worklist = build_worklist(self.pool, state, self.cfg, max_games=max_games)

        finished = self.ledger.finished_game_ids()
        worklist = [g for g in worklist if g.game_id not in finished]
        projections.write_scheduler_queue(worklist, self.cfg)

        tick_started = self.ledger.emit(EventType.TournamentTickStarted, {
            "tick_id": tick_id, "run_id": run_id,
            "tournament_id": self.pool.tournament_id,
            "planned_games": len(worklist), "max_games": max_games,
            "max_seconds": max_seconds,
        }, tags=["lifecycle", "tick"])

        deadline = time.time() + max_seconds
        played: list[dict] = []
        stop_reason = "worklist_exhausted"
        for g in worklist:
            if len(played) >= max_games:
                stop_reason = "max_games"
                break
            if time.time() >= deadline:
                stop_reason = "max_seconds"
                break
            played.append(self._play_one(
                g.to_dict(), tick_id, run_id,
                parent_ids=[tick_started.event_id]))

        events = self.ledger.load()
        summary = projections.write_projections(
            self.pool, events, self.cfg,
            tick_status={"tick_id": tick_id, "stop_reason": stop_reason,
                         "games_played": len(played), "ts": time.time()})
        # refresh scheduler queue for the NEXT tick
        next_state = projections.build_scheduler_state(events, ranking=summary["ranked_ids"])
        next_worklist = build_worklist(self.pool, next_state, self.cfg, max_games=max_games)
        next_finished = self.ledger.finished_game_ids()
        next_worklist = [x for x in next_worklist if x.game_id not in next_finished]
        projections.write_scheduler_queue(next_worklist, self.cfg)

        self.ledger.emit(EventType.TournamentRankingUpdated, {
            "tick_id": tick_id, "top": summary["ranked_ids"][:self.cfg.top_bracket_size],
            "totals": summary["totals"],
        }, parent_event_ids=[tick_started.event_id], tags=["tick"])
        self.ledger.emit(EventType.TournamentProjectionUpdated, {
            "tick_id": tick_id, "last_event_id": summary["last_event_id"],
        }, parent_event_ids=[tick_started.event_id], tags=["tick"])
        tick_fin = self.ledger.emit(EventType.TournamentTickFinished, {
            "tick_id": tick_id, "run_id": run_id, "stop_reason": stop_reason,
            "games_played": len(played), "results": played,
            "next_queue_size": len(next_worklist),
        }, parent_event_ids=[tick_started.event_id], tags=["lifecycle", "tick"])

        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        run_rec = {"tick_id": tick_id, "run_id": run_id,
                   "tournament_id": self.pool.tournament_id,
                   "stop_reason": stop_reason, "planned": len(worklist),
                   "games_played": len(played), "results": played,
                   "totals": summary["totals"],
                   "tick_finished_event": tick_fin.event_id,
                   "next_queue_size": len(next_worklist), "no_upload": True}
        (RUNS_DIR / f"{tick_id}.json").write_text(json.dumps(run_rec, indent=2))
        return run_rec
