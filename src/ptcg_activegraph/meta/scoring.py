"""Weighted meta-score and meta-pool loading.

``weighted_meta_score`` combines per-archetype win rates into a single number,
but ONLY over archetypes that have real, usable surrogate decks. Weight mass
that lands on blocked/unavailable archetypes is reported as missing coverage so
no candidate is ever ranked as if it had been tested against the full meta.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def weighted_meta_score(
    winrates: dict[str, float],
    weights: dict[str, float],
    available: set[str] | None = None,
) -> dict:
    """Return a weighted meta score over *available* archetypes only.

    Args:
        winrates: ``{archetype_key: win_rate_0_to_1}`` measured locally.
        weights:  ``{archetype_key: weight}`` (need not sum to 1).
        available: archetype keys that have a real surrogate deck. If ``None``,
            every archetype that appears in ``winrates`` is treated as available.

    Returns a dict with:
        weighted_meta_score: float in [0,1] over used archetypes, or ``None``
            when no archetype has data.
        coverage: fraction of total weight that landed on used archetypes.
        complete: ``True`` only when coverage == 1.0 (every weighted archetype
            had data) — i.e. the eval is not partial.
        used_archetypes / missing_archetypes / normalized_weights.
    """
    if available is None:
        available = set(winrates.keys())

    total_weight = sum(float(w) for w in weights.values()) or 0.0
    used = {
        k: float(weights[k])
        for k in weights
        if k in winrates and k in available and winrates.get(k) is not None
    }
    used_weight = sum(used.values())
    missing = [k for k in weights if k not in used]

    if used_weight <= 0 or total_weight <= 0:
        return {
            "weighted_meta_score": None,
            "coverage": 0.0,
            "complete": False,
            "used_archetypes": [],
            "missing_archetypes": missing,
            "normalized_weights": {},
        }

    normalized = {k: w / used_weight for k, w in used.items()}
    score = sum(normalized[k] * float(winrates[k]) for k in used)
    coverage = used_weight / total_weight
    return {
        "weighted_meta_score": score,
        "coverage": coverage,
        "complete": abs(coverage - 1.0) < 1e-9,
        "used_archetypes": sorted(used),
        "missing_archetypes": sorted(missing),
        "normalized_weights": normalized,
    }


def load_meta_pool(path: str | Path) -> dict:
    """Load ``experiments/meta_pool.yaml`` (best-effort)."""
    p = Path(path)
    if not p.exists() or yaml is None:
        return {}
    try:
        obj = yaml.safe_load(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def meta_pool_weights(pool: dict) -> dict[str, float]:
    """Extract ``{archetype: weight}`` from a loaded meta pool object."""
    weights: dict[str, float] = {}
    ew = pool.get("evaluation_weights") if isinstance(pool, dict) else None
    if isinstance(ew, dict):
        for k, v in ew.items():
            try:
                weights[k] = float(v)
            except (TypeError, ValueError):
                continue
    return weights
