"""Tournament engine configuration (file-backed, with safe defaults).

Loads ``data/tournament/config.yaml`` if present; otherwise returns documented
defaults. Pure stdlib + PyYAML (already a repo dependency). No network access.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

try:  # PyYAML is a repo dependency; degrade gracefully if it ever vanishes.
    import yaml  # type: ignore

    _HAVE_YAML = True
except Exception:  # pragma: no cover - dependency present in this repo
    _HAVE_YAML = False

REPO_ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT_DIR = REPO_ROOT / "data" / "tournament"
DEFAULT_CONFIG_PATH = TOURNAMENT_DIR / "config.yaml"


@dataclass
class TournamentConfig:
    tournament_id: str = "ptcg_standing_tournament_v0"
    tick_max_games: int = 50
    tick_max_seconds: int = 900
    per_game_timeout_seconds: int = 90
    active_soft_cap: int = 16
    active_hard_cap: int = 24
    min_placement_games_per_candidate: int = 20
    min_parent_child_games_per_seat: int = 10
    top_bracket_size: int = 6
    exploration_ratio: float = 0.25
    auto_submit: bool = False
    max_dry_run_queue: int = 1
    sidecar_codec_preferred: str = "zstd"
    sidecar_codec_fallback: str = "gzip"

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path | None = None) -> TournamentConfig:
    """Load config from YAML, falling back to defaults for any missing key."""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    defaults = TournamentConfig()
    if not _HAVE_YAML or not p.exists():
        return defaults
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return defaults
    known = set(defaults.to_dict().keys())
    merged = {**defaults.to_dict(), **{k: v for k, v in raw.items() if k in known}}
    # auto_submit can never be silently enabled by a malformed file: it must be a
    # real boolean True to flip; anything else stays False.
    merged["auto_submit"] = raw.get("auto_submit", False) is True
    return TournamentConfig(**merged)
