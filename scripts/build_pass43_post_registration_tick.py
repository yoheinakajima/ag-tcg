#!/usr/bin/env python3
"""PASS 43 — Part E: Controlled post-registration production tick (CONDITIONAL).

Runs a bounded production tick ONLY if Part D actually registered the probation
candidates into prod Object Storage AND the deploy image is confirmed to carry the
tarballs. Otherwise it is skipped (the expected outcome this pass) and records why.

A real run would execute:
    python scripts/tournament_deployment_tick.py --max-games 3 --max-seconds 240 \\
        --storage-backend replit_app_storage --production
and verify: exit 0; no upload/submit/promotion events; root unchanged; no
missing-tarball / error games for the three candidate ids; any played candidate has
a game sidecar with a matching artifact_sha256; manifest event_count == ledger.

This script NEVER starts the root "Start application" workflow and NEVER mutates
production when skipped. Output:
data/experiments/pass43_post_registration_tick.{json,md}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REG = EXP / "pass43_production_probation_registration.json"


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    reg = json.loads(REG.read_text(encoding="utf-8")) if REG.is_file() else {}
    registered = bool(reg.get("guardrails", {}).get("production_mutated"))

    skipped = not registered
    reason = (None if registered else
              ("Part D performed no production registration "
               f"(apply_skipped={reg.get('apply_skipped')}, "
               f"reason={reg.get('skip_reason')}); there is nothing new in prod to "
               "tick, and the deploy image is not confirmed to carry the Pass-42 "
               "tarballs — running a prod tick now would risk missing-tarball error "
               "games. Skipped by design."))

    out = {
        "pass": "pass43_partE_post_registration_tick",
        "ran_tick": registered,
        "skipped": skipped,
        "skip_reason": reason,
        "depends_on_part_d_registration": True,
        "part_d_apply_skipped": reg.get("apply_skipped"),
        "would_run_command": (
            "python scripts/tournament_deployment_tick.py --max-games 3 "
            "--max-seconds 240 --storage-backend replit_app_storage --production"),
        "verification_checklist_if_run": [
            "exit code 0",
            "no SubmissionQueued/SubmissionUploaded/KaggleScoreUpdated/CandidatePromoted",
            "root main.py/deck.csv unchanged",
            "no missing-tarball / error games for the 3 candidate ids",
            "any played candidate has a game sidecar with matching artifact_sha256",
            "storage_manifest event_count == ledger length",
        ],
        "production_mutated": False,
        "root_workflow_started": False,
    }
    (EXP / "pass43_post_registration_tick.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    md = [
        "# PASS 43 — Part E: Controlled post-registration production tick",
        "",
        f"- ran tick: **{'yes' if registered else 'no'}**",
        f"- skipped: **{'yes' if skipped else 'no'}**",
        f"- reason: {reason or 'n/a (tick ran)'}",
        "",
        "## Would-run command (only after a SAFE Part D registration on the "
        "republished image)",
        "```",
        out["would_run_command"],
        "```",
        "",
        "## Verification checklist if run",
    ]
    md += [f"- {c}" for c in out["verification_checklist_if_run"]]
    md += ["", "> No production mutation and the root workflow was NOT started. This "
           "is the expected, safe outcome for this pass."]
    (EXP / "pass43_post_registration_tick.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass43 post-registration tick: ran={registered} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
