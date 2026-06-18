"""Durable, resumable per-game evaluator (Pass 7A, Part E).

This layer does NOT run large batches. It defines durable per-run/per-game state
and a resumable execute loop so a dead orchestrator can be recovered:

* ``plan`` writes ``GamePlanned`` events + planned state for every game.
* ``execute`` runs planned (or, on resume, stale) games one at a time, emitting
  ``GameStarted`` (with pid/process-group) before launch and
  ``GameFinished``/``GameTimeout``/``GameCrashed`` after, with atomic state writes
  at every transition. Buffered stdout is never the state of record.
* ``resume`` skips completed games and (optionally) retries stale ones.
* ``mark_stale`` reconciles ``running`` games whose last update exceeds the stale
  threshold (default ``2 x timeout + 30s``) — the signature of a killed parent.

The default real executor reuses the proven killable subprocess child
(``_game_subprocess.py``) but redirects its stdout/stderr to durable per-game log
files and records the child pid/process-group. A pluggable ``executor`` lets tests
drive completed/timeout/crashed/stale paths without invoking cabt.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from ..ag import ActiveGraphLedger
from ..ag.artifacts import run_artifacts_dir
from . import run_state as rs
from .run_state import (
    CandidateState,
    GameState,
    RunState,
    default_stale_threshold,
    is_stale,
)

_CHILD_SCRIPT = str(Path(__file__).with_name("_game_subprocess.py"))
_KILL_GRACE_SECONDS = 5

# result-dict -> game status classification (shared by real + dummy executors).
def classify_result(result: dict) -> str:
    if result.get("timeout"):
        return "timeout"
    if result.get("error"):
        return "crashed"
    if result.get("completed"):
        return "completed"
    return "crashed"


GameExecutor = Callable[[GameState], dict]


class DurableRunner:
    def __init__(
        self,
        ledger: ActiveGraphLedger | None = None,
        artifacts_root: str | Path | None = None,
    ) -> None:
        self.ledger = ledger or ActiveGraphLedger(warn=False)
        self.artifacts_root = artifacts_root

    # -- planning ---------------------------------------------------------
    def plan(
        self,
        runs_root: str | Path,
        control_dir: str | Path,
        stage: str,
        games_per_seat: int = 1,
        seats: tuple[int, ...] = (0, 1),
        limit_candidates: int | None = None,
        runner_mode: str = "subprocess_per_game",
        cabt_timeout_seconds: int = 90,
        run_id: str | None = None,
    ) -> str:
        from .branch import list_runs, load_branch_yaml

        control_dir = Path(control_dir)
        run_id = run_id or f"run_{stage}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.ledger.create_run(
            run_id,
            {
                "stage": stage,
                "runs_root": str(runs_root),
                "control_dir": str(control_dir),
                "games_per_seat": games_per_seat,
                "runner_mode": runner_mode,
            },
        )

        candidate_dirs = list_runs(runs_root)
        if limit_candidates is not None:
            candidate_dirs = candidate_dirs[: max(0, int(limit_candidates))]

        candidate_ids: list[str] = []
        for cdir in candidate_dirs:
            branch = load_branch_yaml(cdir)
            candidate_id = branch.branch_id if branch is not None else cdir.name
            candidate_ids.append(candidate_id)
            n_planned = len(seats) * int(games_per_seat)
            cs = CandidateState(
                candidate_id=candidate_id,
                run_id=run_id,
                branch_path=str(cdir),
                games_planned=n_planned,
            )
            rs.save_candidate_state(cs, self.artifacts_root)
            self.ledger.append_event(
                run_id,
                "CandidateRegistered",
                {"candidate_id": candidate_id, "branch_path": str(cdir)},
            )
            for seat in seats:
                for _ in range(int(games_per_seat)):
                    gid = f"g_{uuid.uuid4().hex[:10]}"
                    gs = GameState(
                        game_id=gid,
                        run_id=run_id,
                        candidate_id=candidate_id,
                        control_id="v2_active_control",
                        candidate_path=str(cdir),
                        control_path=str(control_dir),
                        seat=int(seat),
                        status="planned",
                        runner_mode=runner_mode,
                        cabt_timeout_seconds=int(cabt_timeout_seconds),
                    )
                    eid = self.ledger.append_event(
                        run_id,
                        "GamePlanned",
                        {
                            "game_id": gid,
                            "candidate_id": candidate_id,
                            "seat": int(seat),
                        },
                    )
                    gs.activegraph_event_ids.append(eid)
                    rs.save_game_state(gs, self.artifacts_root)

        run = RunState(
            run_id=run_id,
            stage=stage,
            control_id="v2_active_control",
            control_path=str(control_dir),
            runs_root=str(runs_root),
            status="planned",
            runner_mode=runner_mode,
            cabt_timeout_seconds=int(cabt_timeout_seconds),
            games_per_seat=int(games_per_seat),
            seats=list(seats),
            candidate_ids=candidate_ids,
        )
        rs.save_run_state(run, self.artifacts_root)
        return run_id

    # -- execution --------------------------------------------------------
    def _pick_games(self, run_id: str, include_stale: bool) -> list[GameState]:
        wanted = {"planned"}
        if include_stale:
            wanted.add("stale")
        return [g for g in rs.load_game_states(run_id, self.artifacts_root) if g.status in wanted]

    def execute(
        self,
        run_id: str,
        max_games: int | None = None,
        executor: GameExecutor | None = None,
        include_stale: bool = False,
    ) -> dict:
        run = rs.load_run_state(run_id, self.artifacts_root)
        if run is None:
            raise FileNotFoundError(f"no run state for {run_id!r}; plan it first")
        run.status = "running"
        rs.save_run_state(run, self.artifacts_root)
        self.ledger.append_event(run_id, "ExperimentRunStarted", {"stage": run.stage})

        exec_fn = executor or self._real_executor
        games = self._pick_games(run_id, include_stale)
        if max_games is not None:
            games = games[: max(0, int(max_games))]

        ran = {"completed": 0, "timeout": 0, "crashed": 0}
        for g in games:
            status = self._run_one(run_id, g, exec_fn)
            ran[status] = ran.get(status, 0) + 1
            self._recompute_candidate(run_id, g.candidate_id)
            # Durable progress heartbeat: a resumed/inspected run can see the
            # orchestrator was alive at this point even mid-batch.
            self.ledger.heartbeat(run_id, payload={"ran": dict(ran)})

        # Only a run with no games left to do (planned/running/stale) is truly
        # complete. A capped/partial pass stays resumable and is recorded as
        # "partial" so the ledger and report never claim false completion.
        remaining = rs.load_game_states(run_id, self.artifacts_root)
        pending = [g for g in remaining if g.status in ("planned", "running", "stale")]
        if pending:
            run.status = "partial"
            rs.save_run_state(run, self.artifacts_root)
            self.ledger.append_event(
                run_id,
                "ExperimentRunPartial",
                {"ran": ran, "pending_games": len(pending)},
            )
            return {"run_id": run_id, "ran": ran, "status": "partial",
                    "pending_games": len(pending)}

        run.status = "completed"
        rs.save_run_state(run, self.artifacts_root)
        self.ledger.append_event(run_id, "ExperimentRunFinished", {"ran": ran})
        return {"run_id": run_id, "ran": ran, "status": "completed",
                "pending_games": 0}

    def resume(
        self,
        run_id: str,
        max_games: int | None = None,
        retry_stale: bool = False,
        executor: GameExecutor | None = None,
    ) -> dict:
        """Resume: completed games are skipped; stale games retried iff retry_stale."""
        self.mark_stale(run_id)
        return self.execute(
            run_id, max_games=max_games, executor=executor, include_stale=retry_stale
        )

    def _run_one(self, run_id: str, game: GameState, exec_fn: GameExecutor) -> str:
        game.status = "running"
        game.attempt += 1
        game.started_at = time.time()
        game.error_summary = None
        eid = self.ledger.append_event(
            run_id,
            "GameStarted",
            {"game_id": game.game_id, "candidate_id": game.candidate_id, "seat": game.seat,
             "attempt": game.attempt},
        )
        game.activegraph_event_ids.append(eid)
        rs.save_game_state(game, self.artifacts_root)

        try:
            result = exec_fn(game)
        except Exception as exc:  # noqa: BLE001 - executor crash => crashed game
            result = {"completed": False, "error": f"executor raised: {exc!r}"}

        status = classify_result(result)
        now = time.time()
        game.status = status
        game.completed_at = now
        if game.started_at:
            game.duration_seconds = now - game.started_at
        game.error_summary = result.get("error")
        rdir = run_artifacts_dir(run_id, self.artifacts_root) / "games"
        result_path = rdir / f"{game.game_id}.result.json"
        try:
            result_path.write_text(json.dumps(result, default=str), encoding="utf-8")
            game.result_json_path = str(result_path)
        except Exception:  # noqa: BLE001
            pass

        event_type = {
            "completed": "GameFinished",
            "timeout": "GameTimeout",
            "crashed": "GameCrashed",
        }.get(status, "GameCrashed")
        eid2 = self.ledger.append_event(
            run_id,
            event_type,
            {
                "game_id": game.game_id,
                "candidate_id": game.candidate_id,
                "seat": game.seat,
                "candidate_won": result.get("candidate_won"),
                "steps": result.get("steps"),
                "duration_seconds": game.duration_seconds,
                "error": result.get("error"),
            },
            tags=[status],
            artifact_paths=[game.result_json_path] if game.result_json_path else None,
            parent_event_ids=[eid],
        )
        game.activegraph_event_ids.append(eid2)
        # GameResultRecorded carries the structured outcome separately.
        self.ledger.append_event(
            run_id,
            "GameResultRecorded",
            {"game_id": game.game_id, "result": result},
            parent_event_ids=[eid2],
        )
        rs.save_game_state(game, self.artifacts_root)
        return status

    # -- real cabt executor (durable: pid + stdout/stderr capture) --------
    def _real_executor(self, game: GameState) -> dict:
        from ..decks.deck_io import load_deck

        cand_dir = Path(game.candidate_path)
        ctrl_dir = Path(game.control_path)
        cand_deck = load_deck(cand_dir / "deck.csv")
        ctrl_deck = load_deck(ctrl_dir / "deck.csv")
        gdir = run_artifacts_dir(game.run_id, self.artifacts_root) / "games"
        gdir.mkdir(parents=True, exist_ok=True)
        spec_path = gdir / f"{game.game_id}.spec.json"
        out_path = gdir / f"{game.game_id}.out.json"
        stdout_path = gdir / f"{game.game_id}.stdout.log"
        stderr_path = gdir / f"{game.game_id}.stderr.log"
        spec = {
            "control_main": str(ctrl_dir / "main.py"),
            "control_deck": list(ctrl_deck),
            "cand_main": str(cand_dir / "main.py"),
            "cand_deck": list(cand_deck),
            "candidate_seat": game.seat,
        }
        spec_path.write_text(json.dumps(spec, default=str), encoding="utf-8")
        game.stdout_path = str(stdout_path)
        game.stderr_path = str(stderr_path)

        cmd = [sys.executable, _CHILD_SCRIPT, str(spec_path), str(out_path)]
        result = {"completed": False, "candidate_won": None, "timeout": False, "error": None}
        with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
            try:
                proc = subprocess.Popen(cmd, stdout=so, stderr=se, start_new_session=True)
            except Exception as exc:  # noqa: BLE001
                result["error"] = f"subprocess spawn failed: {exc!r}"
                return result
            game.pid = proc.pid
            try:
                game.process_group = os.getpgid(proc.pid)
            except Exception:  # noqa: BLE001
                game.process_group = None
            rs.save_game_state(game, self.artifacts_root)
            try:
                proc.wait(timeout=game.cabt_timeout_seconds)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                result["timeout"] = True
                result["error"] = f"timeout >{game.cabt_timeout_seconds}s (child killed)"
                return result
        if proc.returncode != 0:
            result["error"] = f"child exited with code {proc.returncode}"
            return result
        try:
            parsed = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
            result["error"] = "child result not a JSON object"
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"no parseable child result: {exc!r}"
        return result

    # -- stale reconciliation --------------------------------------------
    def mark_stale(self, run_id: str, stale_threshold: float | None = None) -> list[str]:
        marked: list[str] = []
        for g in rs.load_game_states(run_id, self.artifacts_root):
            thr = stale_threshold
            if thr is None:
                thr = default_stale_threshold(g.cabt_timeout_seconds)
            if is_stale(g, threshold=thr):
                g.status = "stale"
                rs.save_game_state(g, self.artifacts_root)
                eid = self.ledger.append_event(
                    run_id,
                    "GameStale",
                    {"game_id": g.game_id, "candidate_id": g.candidate_id,
                     "last_update": g.updated_at},
                    tags=["stale"],
                )
                g.activegraph_event_ids.append(eid)
                rs.save_game_state(g, self.artifacts_root)
                marked.append(g.game_id)
        return marked

    # -- candidate rollup -------------------------------------------------
    def _recompute_candidate(self, run_id: str, candidate_id: str) -> None:
        games = [
            g
            for g in rs.load_game_states(run_id, self.artifacts_root)
            if g.candidate_id == candidate_id
        ]
        states = [cs for cs in rs.load_candidate_states(run_id, self.artifacts_root)
                  if cs.candidate_id == candidate_id]
        cs = states[0] if states else CandidateState(
            candidate_id=candidate_id, run_id=run_id, branch_path="",
            games_planned=len(games),
        )
        cs.games_completed = sum(1 for g in games if g.status == "completed")
        cs.games_timeout = sum(1 for g in games if g.status == "timeout")
        cs.games_crashed = sum(1 for g in games if g.status == "crashed")
        cs.games_stale = sum(1 for g in games if g.status == "stale")
        rs.save_candidate_state(cs, self.artifacts_root)

    # -- status -----------------------------------------------------------
    def status(self, run_id: str) -> dict:
        run = rs.load_run_state(run_id, self.artifacts_root)
        games = rs.load_game_states(run_id, self.artifacts_root)
        from collections import Counter

        status_counts = Counter(g.status for g in games)
        return {
            "run_id": run_id,
            "run_status": run.status if run else "unknown",
            "stage": run.stage if run else None,
            "games_total": len(games),
            "game_status_counts": dict(status_counts),
            "candidates": [cs.to_dict() for cs in rs.load_candidate_states(run_id, self.artifacts_root)],
            "ledger": self.ledger.inspect_run(run_id),
        }


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the child's process group (mirrors runner.py)."""
    def _sig(s):
        try:
            os.killpg(os.getpgid(proc.pid), s)
        except Exception:  # noqa: BLE001
            try:
                proc.send_signal(s)
            except Exception:  # noqa: BLE001
                pass

    _sig(signal.SIGTERM)
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
        return
    except Exception:  # noqa: BLE001
        pass
    _sig(signal.SIGKILL)
    try:
        proc.wait(timeout=_KILL_GRACE_SECONDS)
    except Exception:  # noqa: BLE001
        pass
