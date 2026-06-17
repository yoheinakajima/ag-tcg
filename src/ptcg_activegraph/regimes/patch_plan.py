"""PatchPlan: a proposed improvement expressed as data, not code mutation.

A patch plan ties a failure/regime to the seams it is *allowed* to touch, a
hypothesis, the validation protocol it must pass, and the promotion rule that
gates it. The lab proposes plans; humans (or higher-level automation) review,
run validation, and promote. Nothing here auto-edits code.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .taxonomy import ALLOWED_PATCH_SEAMS, PatchSeam, RegimeCategory
from .validation import protocol_for_regime


@dataclass
class PatchPlan:
    patch_id: str
    target_regime: str
    failure_tags: list[str] = field(default_factory=list)
    allowed_patch_seams: list[str] = field(default_factory=list)
    hypothesis: str = ""
    validation_protocol: dict = field(default_factory=dict)
    promotion_rule: str = ""
    status: str = "proposed"  # proposed | validating | passed | rejected | promoted
    created_at: float = field(default_factory=time.time)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "target_regime": self.target_regime,
            "failure_tags": self.failure_tags,
            "allowed_patch_seams": self.allowed_patch_seams,
            "hypothesis": self.hypothesis,
            "validation_protocol": self.validation_protocol,
            "promotion_rule": self.promotion_rule,
            "status": self.status,
            "created_at": self.created_at,
            "notes": self.notes,
        }

    def allows(self, seam: str | PatchSeam) -> bool:
        s = seam.value if isinstance(seam, PatchSeam) else seam
        return s in self.allowed_patch_seams


def new_patch_plan(
    regime: str | RegimeCategory,
    failure_tags: list[str],
    hypothesis: str = "",
) -> PatchPlan:
    """Construct a patch plan with seams/protocol derived from the regime."""
    regime_val = regime.value if isinstance(regime, RegimeCategory) else regime
    try:
        regime_enum = RegimeCategory(regime_val)
    except ValueError:
        regime_enum = RegimeCategory.UNKNOWN

    seams = [s.value for s in ALLOWED_PATCH_SEAMS.get(regime_enum, [])]
    protocol = protocol_for_regime(regime_val)

    return PatchPlan(
        patch_id=f"patch_{uuid.uuid4().hex[:10]}",
        target_regime=regime_val,
        failure_tags=list(failure_tags or []),
        allowed_patch_seams=seams,
        hypothesis=hypothesis,
        validation_protocol=protocol.to_dict(),
        promotion_rule=f"Pass '{protocol.name}' and clear its thresholds before promotion.",
        status="proposed",
    )
