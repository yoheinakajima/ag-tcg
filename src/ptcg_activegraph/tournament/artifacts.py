"""Game trace sidecars + tarball extraction helpers.

Game sidecars are compact per-game JSON records written under
``data/tournament/games/``. We prefer zstd compression; if the ``zstandard``
package is unavailable in the lab environment we fall back to stdlib gzip and
record that fallback honestly (see ``sidecar_codec()``).

These are LOCAL cabt self-play traces only — never raw private Kaggle replay
payloads.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT_DIR = REPO_ROOT / "data" / "tournament"
GAMES_DIR = TOURNAMENT_DIR / "games"

try:  # zstd is not guaranteed in the lab image; gzip is the honest fallback.
    import zstandard as _zstd  # type: ignore

    _HAVE_ZSTD = True
except Exception:
    _HAVE_ZSTD = False


def sidecar_codec() -> str:
    """Return the codec actually in use: 'zstd' if available, else 'gzip'."""
    return "zstd" if _HAVE_ZSTD else "gzip"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_game_sidecar(game_id: str, record: dict) -> dict:
    """Write a compact compressed sidecar for one game; return path metadata.

    Returns ``{"path", "sha256", "codec", "bytes"}``. ``path`` is repo-relative.
    """
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("no_upload", True)
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    codec = sidecar_codec()
    if codec == "zstd":
        ext = "json.zst"
        blob = _zstd.ZstdCompressor(level=10).compress(raw)
    else:
        ext = "json.gz"
        blob = gzip.compress(raw)
    out = GAMES_DIR / f"{game_id}.{ext}"
    out.write_bytes(blob)
    return {
        "path": str(out.relative_to(REPO_ROOT)),
        "sha256": _sha256_bytes(blob),
        "codec": codec,
        "bytes": len(blob),
    }


def read_game_sidecar(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    blob = p.read_bytes()
    if str(p).endswith(".zst"):
        raw = _zstd.ZstdDecompressor().decompress(blob)
    else:
        raw = gzip.decompress(blob)
    return json.loads(raw.decode("utf-8"))


def extract_agent_main(tarball: str | Path, dest_dir: str | Path) -> str:
    """Extract a candidate tarball and return the path to its ``main.py``.

    Tarballs are immutable build artifacts; we only read them. Members are
    validated to stay within ``dest_dir`` (no path traversal).
    """
    tarball = Path(tarball)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"unsafe path in tarball: {m.name}")
        tar.extractall(dest)  # noqa: S202 - our own build artifact, validated above
    for cand in (dest / "main.py", *dest.rglob("main.py")):
        if cand.exists():
            return str(cand)
    raise FileNotFoundError(f"no main.py inside {tarball.name}")
