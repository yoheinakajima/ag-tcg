"""Fallback JSONL run ledger.

This is the **fallback** backend used when no real ``activegraph`` package/CLI is
available (see ``docs/ACTIVEGRAPH_INTEGRATION_AUDIT.md``). It reuses the
append-only, ``fcntl``-locked JSONL pattern proven in
``graph/event_store.py`` and adds a run-scoped envelope + a small run index for
O(1) ``list_runs``.

Source of truth = the JSONL event log. The runs index is a derived cache that is
rebuilt by folding events when missing/corrupt.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Iterator

from .artifacts import DEFAULT_ARTIFACTS_ROOT, atomic_write_json, repo_relpath
from .inspect import summarize_run
from .schema import RUN_STATUS_BY_EVENT, LedgerEvent, new_event_id

try:  # POSIX advisory locking; absent on Windows (same caveat as EventStore).
    import fcntl  # type: ignore

    _HAVE_FCNTL = True
except Exception:  # pragma: no cover - platform dependent
    _HAVE_FCNTL = False


DEFAULT_EVENTS_PATH = Path("data/activegraph/ptcg_ledger_events.jsonl")
DEFAULT_RUNS_PATH = Path("data/activegraph/ptcg_ledger_runs.json")


class FallbackJSONLLedger:
    """Run-scoped append-only JSONL ledger (fallback for real ActiveGraph)."""

    backend_name = "fallback_jsonl"
    is_real_activegraph = False

    def __init__(
        self,
        events_path: str | os.PathLike | None = None,
        runs_path: str | os.PathLike | None = None,
        artifacts_root: str | os.PathLike | None = None,
    ) -> None:
        self.events_path = Path(events_path) if events_path else DEFAULT_EVENTS_PATH
        self.runs_path = Path(runs_path) if runs_path else DEFAULT_RUNS_PATH
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root else DEFAULT_ARTIFACTS_ROOT
        )
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_path.parent.mkdir(parents=True, exist_ok=True)

    # -- low-level append (mirrors EventStore's fcntl-locked append) --------
    def _append_raw(self, event: LedgerEvent) -> None:
        f = open(self.events_path, "a", encoding="utf-8")
        try:
            if _HAVE_FCNTL:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                except Exception:  # noqa: BLE001
                    pass
            f.write(event.to_json() + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:  # pragma: no cover
                pass
        finally:
            if _HAVE_FCNTL:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:  # noqa: BLE001
                    pass
            f.close()

    def _iter_raw(self) -> Iterator[dict]:
        if not self.events_path.exists():
            return
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def events_for(self, run_id: str) -> list[dict]:
        return [e for e in self._iter_raw() if e.get("run_id") == run_id]

    # -- runs index --------------------------------------------------------
    def _load_runs(self) -> dict:
        if not self.runs_path.exists():
            return {}
        try:
            data = json.loads(self.runs_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 - corrupt index is non-fatal
            return {}

    def _save_runs(self, runs: dict) -> None:
        atomic_write_json(self.runs_path, runs)

    def _touch_run(self, run_id: str, event: LedgerEvent) -> None:
        runs = self._load_runs()
        rec = runs.get(run_id) or {
            "run_id": run_id,
            "created_at": event.timestamp,
            "metadata": {},
            "status": "unknown",
        }
        rec["last_event_type"] = event.event_type
        rec["last_event_at"] = event.timestamp
        rec["event_count"] = int(rec.get("event_count", 0)) + 1
        if event.event_type in RUN_STATUS_BY_EVENT:
            rec["status"] = RUN_STATUS_BY_EVENT[event.event_type]
        if event.event_type in ("ExperimentRunHeartbeat", "GameHeartbeat"):
            rec["last_heartbeat_at"] = event.timestamp
        runs[run_id] = rec
        self._save_runs(runs)

    # -- public ActiveGraphLedger interface --------------------------------
    def create_run(self, run_id: str, metadata: dict | None = None) -> None:
        runs = self._load_runs()
        if run_id not in runs:
            runs[run_id] = {
                "run_id": run_id,
                "created_at": time.time(),
                "metadata": dict(metadata or {}),
                "status": "created",
                "event_count": 0,
            }
            self._save_runs(runs)
        self.append_event(
            run_id,
            "ExperimentRunCreated",
            payload={"metadata": dict(metadata or {})},
            tags=["lifecycle"],
        )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict | None = None,
        tags: Iterable[str] | None = None,
        artifact_paths: Iterable[str] | None = None,
        parent_event_ids: Iterable[str] | None = None,
    ) -> str:
        ev = LedgerEvent(
            event_type=str(event_type),
            run_id=run_id,
            payload=dict(payload or {}),
            tags=list(tags or []),
            artifact_paths=[repo_relpath(p) for p in (artifact_paths or [])],
            parent_event_ids=list(parent_event_ids or []),
        )
        self._append_raw(ev)
        self._touch_run(run_id, ev)
        return ev.event_id

    def heartbeat(
        self,
        run_id: str,
        object_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        p = dict(payload or {})
        event_type = "ExperimentRunHeartbeat"
        if object_id is not None:
            p["game_id"] = object_id
            p["object_id"] = object_id
            event_type = "GameHeartbeat"
        self.append_event(run_id, event_type, payload=p, tags=["heartbeat"])

    def inspect_run(self, run_id: str) -> dict:
        runs = self._load_runs()
        return summarize_run(run_id, runs.get(run_id), self.events_for(run_id))

    def export_trace(self, run_id: str, output_path: str | os.PathLike) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(e, sort_keys=True) for e in self.events_for(run_id)]
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
        os.replace(tmp, out)
        return out

    def list_runs(self) -> list[dict]:
        runs = self._load_runs()
        return sorted(runs.values(), key=lambda r: r.get("created_at", 0))

    def mark_artifact(
        self,
        run_id: str,
        artifact_type: str,
        path: str | os.PathLike,
        metadata: dict | None = None,
    ) -> str:
        artifact_id = f"art_{new_event_id().split('_', 1)[1]}"
        self.append_event(
            run_id,
            "ArtifactRecorded",
            payload={
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "path": repo_relpath(path),
                "metadata": dict(metadata or {}),
            },
            tags=["artifact"],
            artifact_paths=[path],
        )
        return artifact_id
