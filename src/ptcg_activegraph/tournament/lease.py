"""Best-effort deployment lease for the scheduled tournament worker (Pass 37).

A Scheduled Deployment could in principle overlap with a manual run, or a
previous invocation that ran long. To avoid two workers ticking at once we take
a coarse lease object in persistent storage:
``locks/tournament_tick.lock.json``.

**Honesty note:** Replit Object Storage has no atomic compare-and-swap, so this
lease is *best-effort*, not a correctness proof. Two workers that both observe
"no lease" within the same instant can both acquire. We minimise the blast
radius with three layers:

1. This storage lease (catches the common, non-simultaneous overlap).
2. The schedule discipline: lease TTL > job timeout, and schedule interval > TTL,
   so a normally-finishing job has released before the next one starts.
3. The push-time re-pull + merge-by-event_id in :mod:`sync` (the real safety
   net), which makes overlapping disjoint work merge cleanly and turns genuine
   divergence into a logged conflict rather than silent data loss.

The local engine ``flock`` (``data/tournament/.tick.lock``) still guards against
two processes inside a single container.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass

from .storage import StorageBackend, StorageError

LOCK_KEY = "locks/tournament_tick.lock.json"
DEFAULT_TTL_SECONDS = 1800  # 30 min — must exceed the worker job timeout.


class LeaseHeldError(StorageError):
    """Another worker holds a non-expired lease."""


@dataclass
class Lease:
    key: str
    owner: str
    tick_id: str
    started_at: float
    expires_at: float
    heartbeat_at: float
    ttl_seconds: int

    def to_doc(self) -> dict:
        d = asdict(self)
        d["no_upload"] = True
        return d


def default_owner() -> str:
    """A stable-ish identifier for the running worker instance."""
    host = socket.gethostname()
    pid = os.getpid()
    return f"{host}:{pid}:{uuid.uuid4().hex[:6]}"


def read_lease(backend: StorageBackend, key: str = LOCK_KEY) -> dict | None:
    if not backend.exists(key):
        return None
    try:
        return backend.get_json(key)
    except Exception:
        return None


def acquire_lease(
    backend: StorageBackend,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    owner: str | None = None,
    tick_id: str | None = None,
    now: float | None = None,
    key: str = LOCK_KEY,
) -> Lease:
    """Acquire the lease or raise :class:`LeaseHeldError` if one is active."""
    now = time.time() if now is None else now
    owner = owner or default_owner()
    tick_id = tick_id or f"tick_{uuid.uuid4().hex[:10]}"

    existing = read_lease(backend, key)
    if existing:
        expires = float(existing.get("expires_at", 0) or 0)
        same = existing.get("tick_id") == tick_id and existing.get("owner") == owner
        if expires > now and not same:
            raise LeaseHeldError(
                "tournament tick lease is held by "
                f"{existing.get('owner')} (tick {existing.get('tick_id')}), "
                f"expires in {expires - now:.0f}s; refusing to start a second worker."
            )

    lease = Lease(
        key=key,
        owner=owner,
        tick_id=tick_id,
        started_at=now,
        expires_at=now + ttl_seconds,
        heartbeat_at=now,
        ttl_seconds=ttl_seconds,
    )
    backend.put_json(key, lease.to_doc())
    return lease


def heartbeat(
    backend: StorageBackend, lease: Lease, *, now: float | None = None
) -> Lease:
    """Extend the lease while a long tick is still running."""
    now = time.time() if now is None else now
    lease.heartbeat_at = now
    lease.expires_at = now + lease.ttl_seconds
    backend.put_json(lease.key, lease.to_doc())
    return lease


def release_lease(backend: StorageBackend, lease: Lease) -> bool:
    """Release the lease iff we still own it. Returns True if released."""
    current = read_lease(backend, lease.key)
    if current and (
        current.get("owner") == lease.owner
        and current.get("tick_id") == lease.tick_id
    ):
        backend.delete(lease.key)
        return True
    return False
