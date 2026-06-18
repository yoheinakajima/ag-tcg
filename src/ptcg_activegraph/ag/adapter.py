"""ActiveGraph adapter — narrow, stable interface for the PTCG lab.

This is the single seam between the lab and "ActiveGraph". It prefers a *real*
``activegraph`` package if one is importable, and otherwise falls back to the
JSONL ledger (``FallbackJSONLLedger``) with a clear, one-time warning. The lab
only ever depends on the ``ActiveGraphLedger`` methods below, so swapping in a
real ActiveGraph later means implementing those methods against it — nothing
else in the codebase changes.

Interface (per Pass 7A spec):

    create_run(run_id, metadata) -> None
    append_event(run_id, event_type, payload, tags=None, artifact_paths=None) -> str
    heartbeat(run_id, object_id=None, payload=None) -> None
    inspect_run(run_id) -> dict
    export_trace(run_id, output_path) -> Path
    list_runs() -> list[dict]
    mark_artifact(run_id, artifact_type, path, metadata=None) -> str
"""

from __future__ import annotations

import importlib.util
import os
import warnings
from pathlib import Path
from typing import Iterable

from .ledger import FallbackJSONLLedger

_FALLBACK_WARNING = "Using fallback JSONL ledger, not real ActiveGraph."
_warned_once = False


def real_activegraph_available() -> bool:
    """True iff a real, importable ``activegraph`` package exists.

    Kept as a function (not a constant) so tests can monkeypatch it and so the
    check is re-evaluated if the environment changes.
    """
    try:
        return importlib.util.find_spec("activegraph") is not None
    except Exception:  # noqa: BLE001 - defensive: treat probe errors as "absent"
        return False


def _build_real_backend():  # pragma: no cover - no real package in this env
    """Construct a real-ActiveGraph-backed ledger.

    Not reachable in this environment (no ``activegraph`` installed). When a real
    package is introduced, implement the ``ActiveGraphLedger`` method surface here
    against its node/edge + run APIs and return the wrapper.
    """
    raise NotImplementedError(
        "real ActiveGraph backend not implemented; install activegraph and wire "
        "_build_real_backend() to its run/event API."
    )


class ActiveGraphLedger:
    """Adapter exposing the lab's stable ledger interface.

    Pass ``backend=`` to inject a specific backend (used by tests). Otherwise the
    adapter auto-detects: real ActiveGraph if available, else the JSONL fallback.
    """

    def __init__(
        self,
        events_path: str | os.PathLike | None = None,
        runs_path: str | os.PathLike | None = None,
        artifacts_root: str | os.PathLike | None = None,
        backend: object | None = None,
        warn: bool = True,
    ) -> None:
        global _warned_once
        if backend is not None:
            self._backend = backend
        elif real_activegraph_available():
            self._backend = _build_real_backend()
        else:
            self._backend = FallbackJSONLLedger(
                events_path=events_path,
                runs_path=runs_path,
                artifacts_root=artifacts_root,
            )
            if warn and not _warned_once:
                warnings.warn(_FALLBACK_WARNING, RuntimeWarning, stacklevel=2)
                _warned_once = True

    @property
    def backend(self) -> object:
        return self._backend

    @property
    def is_fallback(self) -> bool:
        return bool(getattr(self._backend, "is_real_activegraph", False)) is False

    @property
    def backend_name(self) -> str:
        return str(getattr(self._backend, "backend_name", type(self._backend).__name__))

    # -- delegated interface ----------------------------------------------
    def create_run(self, run_id: str, metadata: dict | None = None) -> None:
        return self._backend.create_run(run_id, metadata)

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict | None = None,
        tags: Iterable[str] | None = None,
        artifact_paths: Iterable[str] | None = None,
        parent_event_ids: Iterable[str] | None = None,
    ) -> str:
        return self._backend.append_event(
            run_id,
            event_type,
            payload=payload,
            tags=tags,
            artifact_paths=artifact_paths,
            parent_event_ids=parent_event_ids,
        )

    def heartbeat(
        self,
        run_id: str,
        object_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        return self._backend.heartbeat(run_id, object_id=object_id, payload=payload)

    def inspect_run(self, run_id: str) -> dict:
        return self._backend.inspect_run(run_id)

    def events_for(self, run_id: str) -> list[dict]:
        """Raw, append-ordered event stream for a run (used by ranking)."""
        return self._backend.events_for(run_id)

    def export_trace(self, run_id: str, output_path: str | os.PathLike) -> Path:
        return self._backend.export_trace(run_id, output_path)

    def list_runs(self) -> list[dict]:
        return self._backend.list_runs()

    def mark_artifact(
        self,
        run_id: str,
        artifact_type: str,
        path: str | os.PathLike,
        metadata: dict | None = None,
    ) -> str:
        return self._backend.mark_artifact(run_id, artifact_type, path, metadata=metadata)


def get_ledger(
    events_path: str | os.PathLike | None = None,
    runs_path: str | os.PathLike | None = None,
    artifacts_root: str | os.PathLike | None = None,
    warn: bool = True,
) -> ActiveGraphLedger:
    """Convenience factory for the default (auto-detected) ledger."""
    return ActiveGraphLedger(
        events_path=events_path,
        runs_path=runs_path,
        artifacts_root=artifacts_root,
        warn=warn,
    )
