"""PTCG ActiveGraph adapter package.

Narrow, stable ledger interface for the strategy lab. Prefers a real
``activegraph`` package when present; otherwise uses a clearly-labeled JSONL
fallback. See ``docs/ACTIVEGRAPH_INTEGRATION_AUDIT.md`` and
``docs/PTCG_ACTIVEGRAPH_RUN_LEDGER.md``.
"""

from __future__ import annotations

from .adapter import ActiveGraphLedger, get_ledger, real_activegraph_available
from .artifacts import (
    DEFAULT_ARTIFACTS_ROOT,
    atomic_write_json,
    atomic_write_text,
    run_artifacts_dir,
)
from .inspect import summarize_run
from .ledger import (
    DEFAULT_EVENTS_PATH,
    DEFAULT_RUNS_PATH,
    FallbackJSONLLedger,
)
from .schema import (
    GAME_STATUS_BY_EVENT,
    LEDGER_EVENT_TYPES,
    RUN_STATUS_BY_EVENT,
    LedgerEvent,
)

__all__ = [
    "ActiveGraphLedger",
    "get_ledger",
    "real_activegraph_available",
    "FallbackJSONLLedger",
    "LedgerEvent",
    "LEDGER_EVENT_TYPES",
    "GAME_STATUS_BY_EVENT",
    "RUN_STATUS_BY_EVENT",
    "summarize_run",
    "run_artifacts_dir",
    "atomic_write_json",
    "atomic_write_text",
    "DEFAULT_ARTIFACTS_ROOT",
    "DEFAULT_EVENTS_PATH",
    "DEFAULT_RUNS_PATH",
]
