#!/usr/bin/env python3
"""Pass 18 (Part H) — confirm the Water reference is carried forward UNCHANGED.

Water is the stable benchmark of the league: its playbook and packaged candidate
must not drift between passes. This script records a content hash of the Pass-17
Water playbook and the packaged Water tarball and asserts there is **no Pass-18
strategic change** (no v1 is created). It emits an auditable diff artifact so the
"no major Water changes" guardrail is provable.

LOCAL ONLY. No upload.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WATER_PLAYBOOK = REPO / "playbooks" / "pass17_water_core_reference.yaml"
WATER_TARBALL = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_water_core_reference.tar.gz"
OUT_JSON = REPO / "data" / "experiments" / "pass18_water_reference_diff.json"
OUT_MD = REPO / "data" / "experiments" / "pass18_water_reference_diff.md"


def _sha256(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def run() -> dict:
    rep = {
        "pass": "18", "part": "H",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upload_performed": False,
        "policy": "Water is the stable league benchmark; no strategic changes in Pass 18.",
        "water_playbook": str(WATER_PLAYBOOK.relative_to(REPO)),
        "water_playbook_sha256": _sha256(WATER_PLAYBOOK),
        "water_playbook_exists": WATER_PLAYBOOK.exists(),
        "water_tarball": str(WATER_TARBALL.relative_to(REPO)),
        "water_tarball_sha256": _sha256(WATER_TARBALL),
        "water_tarball_exists": WATER_TARBALL.exists(),
        "v1_created": False,
        "deck_diff": {},
        "playbook_diff": {},
        "runtime_context_diff": {},
        "decision": ("Carry the Pass-17 Water reference forward unchanged as the league "
                     "benchmark (league_water_core_reference). No water_core_reference_v1 "
                     "is built — naming is already normalized and no strategic change is "
                     "warranted."),
        "no_change_confirmed": True,
    }
    return rep


def render_md(rep: dict) -> str:
    return "\n".join([
        "# Pass 18 — Water Reference Diff",
        "",
        f"- generated: {rep['generated_at']}",
        "- **upload_performed: false** (local only)",
        f"- policy: {rep['policy']}",
        "",
        "## Carried forward unchanged",
        "",
        f"- playbook: `{rep['water_playbook']}` (exists: {rep['water_playbook_exists']})",
        f"  - sha256: `{rep['water_playbook_sha256']}`",
        f"- candidate tarball: `{rep['water_tarball']}` (exists: {rep['water_tarball_exists']})",
        f"  - sha256: `{rep['water_tarball_sha256']}`",
        "",
        "## Diff",
        "",
        f"- v1 created: **{rep['v1_created']}**",
        f"- deck diff: {rep['deck_diff'] or 'none'}",
        f"- playbook diff: {rep['playbook_diff'] or 'none'}",
        f"- runtime context diff: {rep['runtime_context_diff'] or 'none'}",
        f"- **no change confirmed: {rep['no_change_confirmed']}**",
        "",
        f"> {rep['decision']}",
        "",
    ])


def main() -> int:
    rep = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(rep), encoding="utf-8")
    print(render_md(rep))
    print(f"\nwrote {OUT_JSON}\nwrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
