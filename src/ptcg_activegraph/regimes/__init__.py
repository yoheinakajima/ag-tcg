"""Regimes: failure class -> patch seam -> validation -> promotion.

Regimes constrain *how* the system is allowed to improve. A failure is
classified into a regime category, which determines which code seams a patch
may touch, which validation protocol it must pass, and what promotion rule
gates it into the runtime. See ``docs/REGIMES.md``.
"""

from .taxonomy import (
    ALLOWED_PATCH_SEAMS,
    FAILURE_TAGS,
    REGIME_CATEGORIES,
    RegimeCategory,
    FailureTag,
    PatchSeam,
    regime_for_tags,
)
from .classifier import classify_events, classify_summary, FailureClassification
from .patch_plan import PatchPlan, new_patch_plan
from .validation import ValidationProtocol, PromotionRule, STANDARD_PROTOCOLS

__all__ = [
    "ALLOWED_PATCH_SEAMS",
    "FAILURE_TAGS",
    "REGIME_CATEGORIES",
    "RegimeCategory",
    "FailureTag",
    "PatchSeam",
    "regime_for_tags",
    "classify_events",
    "classify_summary",
    "FailureClassification",
    "PatchPlan",
    "new_patch_plan",
    "ValidationProtocol",
    "PromotionRule",
    "STANDARD_PROTOCOLS",
]
