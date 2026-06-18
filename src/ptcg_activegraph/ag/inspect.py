"""Pure projections over ledger events (no I/O).

Used by ``ActiveGraphLedger.inspect_run`` and the report site to fold a run's
event stream into a status summary. The event log is the source of truth; this
just recomputes the current view.
"""

from __future__ import annotations

from collections import Counter

from .schema import GAME_STATUS_BY_EVENT, RUN_STATUS_BY_EVENT


def _payload_id(event: dict, key: str) -> str | None:
    p = event.get("payload") or {}
    return p.get(key)


def summarize_run(run_id: str, run_meta: dict | None, events: list[dict]) -> dict:
    """Fold a run's events into an inspect summary dict.

    ``events`` must already be filtered to this ``run_id`` and in append order.
    """
    events_by_type: Counter = Counter()
    game_status: dict[str, str] = {}
    candidate_ids: set[str] = set()
    artifact_paths: list[str] = []
    timestamps: list[float] = []
    run_status = (run_meta or {}).get("status", "unknown")
    last_heartbeat_at: float | None = None

    for ev in events:
        et = ev.get("event_type", "")
        events_by_type[et] += 1
        ts = ev.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamps.append(float(ts))
        if et in RUN_STATUS_BY_EVENT:
            run_status = RUN_STATUS_BY_EVENT[et]
        if et in ("ExperimentRunHeartbeat", "GameHeartbeat"):
            if isinstance(ts, (int, float)):
                last_heartbeat_at = float(ts)
        gid = _payload_id(ev, "game_id")
        if gid and et in GAME_STATUS_BY_EVENT:
            game_status[gid] = GAME_STATUS_BY_EVENT[et]
        cid = _payload_id(ev, "candidate_id")
        if cid:
            candidate_ids.add(cid)
        for ap in ev.get("artifact_paths") or []:
            artifact_paths.append(ap)

    return {
        "run_id": run_id,
        "status": run_status,
        "metadata": (run_meta or {}).get("metadata", {}),
        "created_at": (run_meta or {}).get("created_at"),
        "event_count": len(events),
        "events_by_type": dict(events_by_type),
        "candidate_count": len(candidate_ids),
        "candidate_ids": sorted(candidate_ids),
        "game_count": len(game_status),
        "game_status_counts": dict(Counter(game_status.values())),
        "game_status": game_status,
        "artifact_paths": artifact_paths,
        "last_heartbeat_at": last_heartbeat_at,
        "first_event_at": min(timestamps) if timestamps else None,
        "last_event_at": max(timestamps) if timestamps else None,
    }
