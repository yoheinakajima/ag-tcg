"""State sync + manifest for the deployment-ready tournament worker (Pass 37).

The Pass 36 engine keeps its primary state on the local filesystem under
``data/tournament/``. A scheduled deployment worker treats that directory as a
**disposable working copy**: it pulls persistent state in, runs one bounded tick,
rebuilds projections, then pushes a verified snapshot back to persistent storage.

The honesty-critical part is the push. Object Storage has no atomic
compare-and-swap, so two overlapping workers could both pull the same
``events.jsonl`` and race. We minimise damage by re-reading the remote ledger
immediately before upload and **merging by ``event_id``**:

* Disjoint games (the normal concurrent case) merge cleanly — no event is lost.
* Two ``GameFinished`` for the **same** ``game_id`` with the **same**
  ``artifact_sha256`` are an idempotent duplicate; we keep one.
* Two ``GameFinished`` for the same ``game_id`` with **different**
  ``artifact_sha256`` is a hard :class:`ConflictError`: we write a conflict
  report and refuse to overwrite the remote ledger. We never silently discard
  remote events.

Nothing here uploads to Kaggle or submits anything. Every synced event already
carries ``no_upload=true`` (enforced by the ledger).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..graph.events import Event
from .storage import StorageBackend, StorageError, _sha256_bytes

TOURNAMENT_DIR = Path(__file__).resolve().parents[3] / "data" / "tournament"

EVENTS_KEY = "events.jsonl"
POOL_KEY = "candidate_pool.json"
CONFIG_KEY = "config.yaml"
MANIFEST_KEY = "storage_manifest.json"
CONFLICT_KEY = "conflict_report.json"
LOCK_PREFIX = "locks/"
SYNC_DIRS = ("projections", "runs", "games")
# Files/dirs that are NOT part of the synced primary state.
_EXCLUDE_TOP = {MANIFEST_KEY, CONFLICT_KEY, ".tick.lock"}

# Per-game lifecycle events that must be unique per game_id in a merged ledger.
_LIFECYCLE = {"GameScheduled", "GameStarted", "GameFinished"}


class ConflictError(StorageError):
    """A genuine divergence between local and remote ledgers (not auto-mergeable)."""


# --------------------------------------------------------------------------- #
# key collection
# --------------------------------------------------------------------------- #
def collect_local_keys(local_root: str | Path = TOURNAMENT_DIR) -> list[str]:
    """Relative keys of the local primary state we sync (excludes manifest/locks)."""
    local_root = Path(local_root)
    keys: list[str] = []
    for top in (EVENTS_KEY, POOL_KEY, CONFIG_KEY):
        if (local_root / top).is_file():
            keys.append(top)
    for sub in SYNC_DIRS:
        base = local_root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                keys.append(p.relative_to(local_root).as_posix())
    return sorted(set(keys))


# --------------------------------------------------------------------------- #
# pull
# --------------------------------------------------------------------------- #
def pull_state(backend: StorageBackend, local_root: str | Path = TOURNAMENT_DIR) -> dict:
    """Download every remote key (except locks) into the local working dir."""
    local_root = Path(local_root)
    local_root.mkdir(parents=True, exist_ok=True)
    pulled: list[str] = []
    total_bytes = 0
    for key in backend.list():
        if key.startswith(LOCK_PREFIX):
            continue
        data = backend.read_bytes(key)
        dest = local_root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        pulled.append(key)
        total_bytes += len(data)
    return {"keys": pulled, "count": len(pulled), "bytes": total_bytes}


def remote_events_hash(backend: StorageBackend) -> str | None:
    """sha256 of the remote events.jsonl bytes (None if it does not exist)."""
    return backend.sha256(EVENTS_KEY)


# --------------------------------------------------------------------------- #
# event reconciliation (pure)
# --------------------------------------------------------------------------- #
def parse_events_text(text: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def dump_events(events: Iterable[dict]) -> str:
    """Canonical JSONL identical to what the EventStore would write."""
    lines = [Event.from_dict(e).to_json() for e in events]
    return ("\n".join(lines) + "\n") if lines else ""


def _sort_key(e: dict) -> tuple:
    return (e.get("timestamp", 0.0), str(e.get("event_id", "")))


def reconcile_events(local_events: list[dict], remote_events: list[dict]) -> tuple[list[dict], dict]:
    """Merge two ledgers honestly. Returns (merged_events, report).

    Raises :class:`ConflictError` when the same ``game_id`` has two finishes with
    different ``artifact_sha256`` (a genuine divergence we must not paper over).
    """
    by_id: dict[str, dict] = {}
    for e in list(remote_events) + list(local_events):
        eid = e.get("event_id")
        if eid is None:
            # No id (should not happen): fall back to content hash so we dedupe
            # identical rows but keep genuinely different ones.
            eid = "noid_" + hashlib.sha256(
                json.dumps(e, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
        by_id.setdefault(eid, e)

    merged = sorted(by_id.values(), key=_sort_key)

    # Enforce one lifecycle event per (type, game_id); detect finish conflicts.
    conflicts: list[dict] = []
    deduped_lifecycle = 0
    finish_sha: dict[str, str] = {}
    for e in merged:
        if e.get("event_type") != "GameFinished":
            continue
        gid = (e.get("payload") or {}).get("game_id")
        sha = (e.get("payload") or {}).get("artifact_sha256")
        if gid is None:
            continue
        if gid in finish_sha and finish_sha[gid] != sha:
            conflicts.append({
                "game_id": gid,
                "sha_a": finish_sha[gid],
                "sha_b": sha,
            })
        else:
            finish_sha.setdefault(gid, sha)
    if conflicts:
        raise ConflictError(
            "ledger divergence: same game_id finished with different artifact "
            f"sha256 in local vs remote: {conflicts}"
        )

    # Collapse duplicate lifecycle events (same type+game_id) keeping earliest.
    seen_life: set[tuple[str, str]] = set()
    final: list[dict] = []
    for e in merged:
        et = e.get("event_type")
        if et in _LIFECYCLE:
            gid = (e.get("payload") or {}).get("game_id")
            if gid is not None:
                k = (et, str(gid))
                if k in seen_life:
                    deduped_lifecycle += 1
                    continue
                seen_life.add(k)
        final.append(e)

    report = {
        "local_count": len(local_events),
        "remote_count": len(remote_events),
        "merged_count": len(final),
        "deduped_lifecycle": deduped_lifecycle,
        "added_from_remote": max(0, len(final) - len(local_events)),
    }
    return final, report


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def build_manifest(
    local_root: str | Path,
    keys: Iterable[str],
    *,
    base_remote_hash: str | None,
    tick_id: str | None,
    status: str = "clean",
) -> dict:
    local_root = Path(local_root)
    files = []
    event_count = 0
    last_event_id = None
    for key in sorted(keys):
        p = local_root / key
        if not p.is_file():
            continue
        data = p.read_bytes()
        files.append({"key": key, "size": len(data), "sha256": _sha256_bytes(data)})
    ev_path = local_root / EVENTS_KEY
    if ev_path.is_file():
        evs = parse_events_text(ev_path.read_text(encoding="utf-8"))
        event_count = len(evs)
        if evs:
            last_event_id = evs[-1].get("event_id")
    manifest = {
        "schema": "pass37_storage_manifest_v1",
        "generated_at": time.time(),
        "tick_id": tick_id,
        "status": status,
        "no_upload": True,
        "auto_submit": False,
        "base_remote_hash": base_remote_hash,
        "event_count": event_count,
        "last_event_id": last_event_id,
        "files": files,
    }
    (local_root / MANIFEST_KEY).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


# --------------------------------------------------------------------------- #
# push (re-pull + merge + verify)
# --------------------------------------------------------------------------- #
def push_state(
    backend: StorageBackend,
    local_root: str | Path = TOURNAMENT_DIR,
    *,
    base_remote_hash: str | None = None,
    tick_id: str | None = None,
    on_remote_drift: Callable[[], None] | None = None,
    dry_run: bool = False,
) -> dict:
    """Reconcile against the current remote ledger, then upload a verified snapshot.

    ``on_remote_drift`` (if given) is invoked after a clean merge is written to
    the local working dir, so the caller can rebuild projections from the merged
    ledger before upload.
    """
    local_root = Path(local_root)
    status = "clean"
    drift = False

    # Re-read the remote ledger right before upload to catch a concurrent writer.
    current_remote_hash = remote_events_hash(backend)
    if (
        current_remote_hash is not None
        and base_remote_hash is not None
        and current_remote_hash != base_remote_hash
    ):
        drift = True
        local_events = parse_events_text(
            (local_root / EVENTS_KEY).read_text(encoding="utf-8")
        ) if (local_root / EVENTS_KEY).is_file() else []
        remote_events = parse_events_text(backend.read_text(EVENTS_KEY))
        try:
            merged, _report = reconcile_events(local_events, remote_events)
        except ConflictError as exc:
            report = {
                "schema": "pass37_conflict_report_v1",
                "generated_at": time.time(),
                "tick_id": tick_id,
                "base_remote_hash": base_remote_hash,
                "current_remote_hash": current_remote_hash,
                "error": str(exc),
                "no_upload": True,
            }
            (local_root / CONFLICT_KEY).write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
            # Best-effort: stash the conflict report remotely WITHOUT touching
            # the remote ledger, so the divergence is visible after the fact.
            try:
                backend.put_json(f"conflict_reports/{tick_id or 'unknown'}.json", report)
            except Exception:
                pass
            raise
        # Write merged ledger back locally, then let caller rebuild projections.
        (local_root / EVENTS_KEY).write_text(dump_events(merged), encoding="utf-8")
        status = "merged"
        if on_remote_drift is not None:
            on_remote_drift()

    keys = collect_local_keys(local_root)
    manifest = build_manifest(
        local_root, keys,
        base_remote_hash=base_remote_hash, tick_id=tick_id, status=status,
    )

    if dry_run:
        return {
            "status": "dry_run", "drift": drift, "uploaded": [],
            "verify": {"ok": True, "checked": 0, "mismatches": []},
            "manifest": manifest, "keys": keys,
        }

    uploaded = backend.upload_dir(local_root, keys)
    backend.write_text(
        MANIFEST_KEY, (local_root / MANIFEST_KEY).read_text(encoding="utf-8")
    )
    verify = backend.verify(local_root, keys)
    return {
        "status": status, "drift": drift, "uploaded": uploaded,
        "verify": verify, "manifest": manifest, "keys": keys,
    }
