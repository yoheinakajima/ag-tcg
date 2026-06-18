"""Meta-calibration layer: archetype labels and weighted meta scoring.

This package turns real Kaggle replays into opponent archetype labels and a
weighted evaluation target. It is deliberately honest about coverage: external
archetypes that have no real replay (and therefore no confirmed card ids) are
marked ``provisional``/``blocked`` and never contribute fabricated data.
"""

from .archetypes import (
    ARCHETYPES,
    ArchetypeStatus,
    archetype_table,
    build_archetypes_yaml_obj,
)
from .scoring import weighted_meta_score, load_meta_pool

__all__ = [
    "ARCHETYPES",
    "ArchetypeStatus",
    "archetype_table",
    "build_archetypes_yaml_obj",
    "weighted_meta_score",
    "load_meta_pool",
]
