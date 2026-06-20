"""Persistent storage backends for the standing tournament engine (Pass 37).

The Pass 36 engine keeps its primary state on the local filesystem under
``data/tournament/``. That is fine in the dev workspace, but a **published Replit
deployment runs from a snapshot and must not trust its own filesystem for durable
state**. Pass 37 adds a small storage abstraction so a scheduled worker can keep
the ledger / projections / game sidecars in a persistent backend.

Design contract (deployment readiness only — NO upload, NO auto-submit):

* ``LocalFileStorageBackend`` — durable for the dev workspace only.
* ``InMemoryStorageBackend`` — a fake backend for tests.
* ``ObjectStorageBackend`` — Replit App / Object Storage (durable in deployment).
  The ``replit`` import is **lazy and local** to this backend so it never enters
  the Kaggle runtime tarball path.

Hard rules enforced here:

* In **production** the default backend is persistent storage. If persistent
  storage is requested but unavailable, we **fail closed** with a clear error —
  we never silently fall back to the (non-durable) deployment filesystem.
* ``assert_no_auto_submit`` refuses to run if auto-submit is requested via env or
  config. Pass 37 performs no upload and no auto-submit, full stop.
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT_DIR = REPO_ROOT / "data" / "tournament"
DEFAULT_PREFIX = "tournament/v0"
# Local "persistent storage" lives OUTSIDE the working dir so dev pull/push is a
# real round-trip and ``data/tournament/`` stays usable for inspection.
DEFAULT_LOCAL_STORE_ROOT = REPO_ROOT / "data" / "tournament_storage"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class StorageError(RuntimeError):
    """Base class for storage problems."""


class StorageUnavailableError(StorageError):
    """Requested persistent backend (e.g. Object Storage) is not usable."""


class ProductionStorageError(StorageError):
    """Production requested a non-durable backend; refused (fail closed)."""


class AutoSubmitRefusedError(StorageError):
    """Auto-submit was requested; refused. Pass 37 performs NO auto-submit."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Backend interface
# --------------------------------------------------------------------------- #
class StorageBackend(ABC):
    """Key/value blob store. Keys are POSIX-style logical paths.

    Concrete backends implement the byte primitives + ``list``/``delete``/
    ``exists``; the text/json/sha/dir helpers are shared here.
    """

    name = "abstract"

    def __init__(self, prefix: str = DEFAULT_PREFIX) -> None:
        self.prefix = (prefix or "").strip("/")

    # -- key mapping -------------------------------------------------------- #
    def _full(self, key: str) -> str:
        k = str(key).strip("/")
        return f"{self.prefix}/{k}" if self.prefix else k

    # -- byte primitives (abstract) ---------------------------------------- #
    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def list(self, prefix: str = "") -> list[str]: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    # -- text / json helpers ----------------------------------------------- #
    def read_text(self, key: str) -> str:
        return self.read_bytes(key).decode("utf-8")

    def write_text(self, key: str, text: str) -> None:
        self.write_bytes(key, text.encode("utf-8"))

    def get_json(self, key: str, default=None):
        if not self.exists(key):
            return default
        return json.loads(self.read_text(key))

    def put_json(self, key: str, obj) -> None:
        self.write_text(key, json.dumps(obj, indent=2, sort_keys=True))

    def sha256(self, key: str) -> str | None:
        if not self.exists(key):
            return None
        return _sha256_bytes(self.read_bytes(key))

    # -- directory helpers (local working dir <-> backend) ----------------- #
    def download_dir(self, local_root: str | Path, prefix: str = "") -> list[str]:
        """Download every key under ``prefix`` into ``local_root/<key>``."""
        local_root = Path(local_root)
        keys = self.list(prefix)
        for key in keys:
            dest = local_root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.read_bytes(key))
        return keys

    def upload_dir(self, local_root: str | Path, rel_keys: Iterable[str]) -> list[str]:
        """Upload ``local_root/<key>`` to the backend for each rel key."""
        local_root = Path(local_root)
        done: list[str] = []
        for key in rel_keys:
            p = local_root / key
            if p.exists():
                self.write_bytes(key, p.read_bytes())
                done.append(key)
        return done

    def verify(self, local_root: str | Path, rel_keys: Iterable[str]) -> dict:
        """Confirm stored sha256 matches the local file for each key."""
        local_root = Path(local_root)
        mismatches: list[str] = []
        checked = 0
        for key in rel_keys:
            p = local_root / key
            if not p.exists():
                continue
            checked += 1
            if self.sha256(key) != _sha256_bytes(p.read_bytes()):
                mismatches.append(key)
        return {"checked": checked, "mismatches": mismatches, "ok": not mismatches}


# --------------------------------------------------------------------------- #
# Local filesystem backend (dev-durable only)
# --------------------------------------------------------------------------- #
class LocalFileStorageBackend(StorageBackend):
    name = "local"

    def __init__(self, root: str | Path | None = None, prefix: str = DEFAULT_PREFIX) -> None:
        super().__init__(prefix)
        self.root = Path(root) if root is not None else DEFAULT_LOCAL_STORE_ROOT

    def _path(self, key: str) -> Path:
        return self.root / self._full(key)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def list(self, prefix: str = "") -> list[str]:
        base = self.root / self.prefix if self.prefix else self.root
        if not base.exists():
            return []
        want = str(prefix).strip("/")
        out: list[str] = []
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            if not want or rel == want or rel.startswith(want + "/"):
                out.append(rel)
        return out

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


# --------------------------------------------------------------------------- #
# In-memory backend (tests / fake App Storage)
# --------------------------------------------------------------------------- #
class InMemoryStorageBackend(StorageBackend):
    name = "memory"

    def __init__(self, prefix: str = DEFAULT_PREFIX, store: dict | None = None) -> None:
        super().__init__(prefix)
        # shared dict lets a test simulate two workers on one "remote".
        self._store: dict[str, bytes] = store if store is not None else {}

    def exists(self, key: str) -> bool:
        return self._full(key) in self._store

    def read_bytes(self, key: str) -> bytes:
        try:
            return self._store[self._full(key)]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    def write_bytes(self, key: str, data: bytes) -> None:
        self._store[self._full(key)] = bytes(data)

    def list(self, prefix: str = "") -> list[str]:
        head = self.prefix + "/" if self.prefix else ""
        want = str(prefix).strip("/")
        out: list[str] = []
        for full in sorted(self._store):
            if head and not full.startswith(head):
                continue
            rel = full[len(head):]
            if not want or rel == want or rel.startswith(want + "/"):
                out.append(rel)
        return out

    def delete(self, key: str) -> None:
        self._store.pop(self._full(key), None)


# --------------------------------------------------------------------------- #
# Replit App / Object Storage backend (deployment-durable)
# --------------------------------------------------------------------------- #
class ObjectStorageBackend(StorageBackend):
    """Replit App / Object Storage. ``replit`` import is lazy + local.

    Fails closed: if the SDK is missing or no bucket is configured, every call
    raises :class:`StorageUnavailableError` rather than degrading to local files.
    """

    name = "replit_app_storage"

    def __init__(self, prefix: str = DEFAULT_PREFIX, client=None) -> None:
        super().__init__(prefix)
        self._client = client

    # -- client / availability -------------------------------------------- #
    def _get_client(self):
        if self._client is not None:
            return self._client
        try:  # lazy, local import — never on the Kaggle runtime path
            from replit.object_storage import Client  # type: ignore
        except Exception as exc:  # SDK not installed
            raise StorageUnavailableError(
                "replit.object_storage SDK is not importable; install "
                "'replit-object-storage' and configure a bucket."
            ) from exc
        try:
            self._client = Client()
        except Exception as exc:  # no default bucket configured, etc.
            raise StorageUnavailableError(
                "Replit Object Storage client could not be created "
                "(no bucket provisioned?): " + str(exc)
            ) from exc
        return self._client

    def ensure_available(self) -> None:
        """Eagerly verify the backend is usable (used to fail closed)."""
        client = self._get_client()
        try:
            client.list()
        except Exception as exc:
            raise StorageUnavailableError(
                "Replit Object Storage is configured but not reachable: " + str(exc)
            ) from exc

    # -- primitives -------------------------------------------------------- #
    def exists(self, key: str) -> bool:
        client = self._get_client()
        name = self._full(key)
        try:
            return bool(client.exists(name))
        except AttributeError:  # older SDK without exists()
            try:
                client.download_as_bytes(name)
                return True
            except Exception:
                return False
        except Exception:
            return False

    def read_bytes(self, key: str) -> bytes:
        client = self._get_client()
        try:
            return client.download_as_bytes(self._full(key))
        except Exception as exc:
            raise FileNotFoundError(key) from exc

    def write_bytes(self, key: str, data: bytes) -> None:
        client = self._get_client()
        client.upload_from_bytes(self._full(key), bytes(data))

    def list(self, prefix: str = "") -> list[str]:
        client = self._get_client()
        head = self.prefix + "/" if self.prefix else ""
        want = str(prefix).strip("/")
        out: list[str] = []
        for obj in client.list():
            full = getattr(obj, "name", obj)
            full = str(full)
            if head and not full.startswith(head):
                continue
            rel = full[len(head):]
            if not want or rel == want or rel.startswith(want + "/"):
                out.append(rel)
        return sorted(out)

    def delete(self, key: str) -> None:
        client = self._get_client()
        try:
            client.delete(self._full(key))
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Factory + guards
# --------------------------------------------------------------------------- #
_LOCAL_NAMES = {"local", "local_file", "file", "localfile"}
_MEMORY_NAMES = {"memory", "fake", "inmemory", "in_memory"}
_OBJECT_NAMES = {
    "replit_app_storage", "app_storage", "object_storage",
    "replit_object_storage", "objectstorage",
}


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def assert_no_auto_submit(cfg=None) -> None:
    """Refuse to proceed if auto-submit is requested via env or config."""
    if _truthy(os.environ.get("TOURNAMENT_AUTO_SUBMIT")):
        raise AutoSubmitRefusedError(
            "TOURNAMENT_AUTO_SUBMIT is set truthy; refusing — Pass 37 performs "
            "NO auto-submit and NO upload."
        )
    if cfg is not None and getattr(cfg, "auto_submit", False) is True:
        raise AutoSubmitRefusedError(
            "config.auto_submit is True; refusing — Pass 37 performs NO "
            "auto-submit and NO upload."
        )


def assert_no_kaggle_upload() -> None:
    """Refuse if any explicit Kaggle upload/submit flag is requested via env."""
    for var in ("TOURNAMENT_KAGGLE_UPLOAD", "KAGGLE_UPLOAD", "KAGGLE_SUBMIT"):
        if _truthy(os.environ.get(var)):
            raise AutoSubmitRefusedError(
                f"{var} is set truthy; refusing — Pass 37 never uploads or "
                "submits to Kaggle."
            )


def resolve_settings(env=None, backend=None, prefix=None) -> dict:
    """Resolve (env, backend, prefix) from explicit args then env vars."""
    env = (env or os.environ.get("TOURNAMENT_ENV") or "dev").strip().lower()
    production = env == "production"
    if backend is None:
        backend = os.environ.get("TOURNAMENT_STORAGE_BACKEND")
    if backend is None:
        backend = "replit_app_storage" if production else "local"
    backend = backend.strip().lower()
    prefix = prefix or os.environ.get("TOURNAMENT_STORAGE_PREFIX") or DEFAULT_PREFIX
    return {"env": env, "production": production, "backend": backend, "prefix": prefix}


def get_storage_backend(
    env=None, backend=None, prefix=None, *, local_root=None, client=None
) -> StorageBackend:
    """Build a storage backend, failing closed for production misconfigurations."""
    s = resolve_settings(env, backend, prefix)
    production, backend, prefix = s["production"], s["backend"], s["prefix"]

    if backend in _LOCAL_NAMES:
        if production:
            raise ProductionStorageError(
                "production requires persistent storage; refusing the local-file "
                "backend (the deployed filesystem is NOT durable)."
            )
        return LocalFileStorageBackend(root=local_root, prefix=prefix)

    if backend in _MEMORY_NAMES:
        if production:
            raise ProductionStorageError(
                "production refuses the in-memory backend (not durable)."
            )
        return InMemoryStorageBackend(prefix=prefix)

    if backend in _OBJECT_NAMES:
        be = ObjectStorageBackend(prefix=prefix, client=client)
        be.ensure_available()  # fail closed if SDK/bucket missing
        return be

    raise StorageError(f"unknown storage backend {backend!r}")
