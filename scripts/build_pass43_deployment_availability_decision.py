#!/usr/bin/env python3
"""PASS 43 — Part C: Deployment availability decision.

Consumes the Part B visibility audit and decides — conservatively — whether it is
SAFE to register the Pass-42 probation candidates into the production Object Storage
state now, or whether a republish of the Scheduled Deployment must happen first.

The runner resolves a game's tarball from the DEPLOY FILESYSTEM
(``REPO_ROOT/data/submissions/<tarball_path>``), never from Object Storage. So a
pool entry registered into Object Storage is only safe if the deploy image actually
carries the tarball. Registering schedulable probation entries whose tarballs the
live image lacks would make the daemon emit missing-tarball error games.

Cases:
  1 deploy_visible + os_missing  -> proceed to Part D (safe registration)
  2 local_only / deploy_missing  -> do NOT mutate prod OS; emit republish steps
  3 prod_already_has_all         -> no-op; proceed to scheduler/projection verify
  4 inconsistent / conflict      -> STOP; conflict report (no mutation)

Expected case here = 2. This script NEVER mutates anything. Output:
data/experiments/pass43_deployment_availability_decision.{json,md}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
AUDIT = EXP / "pass43_probation_visibility_audit.json"


def _decide(records: list[dict], prod_read_ok: bool) -> tuple[str, dict]:
    classes = {r["classification"] for r in records}
    n = len(records)
    blockers = {"missing_tarball", "manifest_mismatch",
                "object_storage_missing", "unsafe_to_register"}

    # Case 4: any hard conflict, or a mix that we should not act on automatically.
    if classes & blockers:
        return "case_4_inconsistent_conflict", {
            "proceed_to_part_d": False,
            "mutate_prod_os": False,
            "republish_required": True,
            "stop": True,
            "reason": ("one or more candidates have hard provenance/availability "
                       f"conflicts: {sorted(classes & blockers)}"),
        }
    # Case 3: everything already safely live in prod OS with deploy-visible tarballs.
    if n and classes == {"production_ready"}:
        return "case_3_prod_already_has_all", {
            "proceed_to_part_d": False,
            "mutate_prod_os": False,
            "republish_required": False,
            "stop": False,
            "reason": ("all candidates already present in prod OS with deploy-visible "
                       "tarballs; proceed to scheduler/projection verification only"),
        }
    # Case 1: tarballs proven deploy-visible but pool entries missing from prod OS.
    if n and classes == {"local_only_needs_republish"} and all(
            r.get("deploy_image_has_tarball") is True for r in records):
        return "case_1_deploy_visible_os_missing", {
            "proceed_to_part_d": True,
            "mutate_prod_os": True,
            "republish_required": False,
            "stop": False,
            "reason": ("tarballs proven present in the deploy image but pool entries "
                       "absent from prod OS — safe to register"),
        }
    # Case 2 (expected): local-only; deploy image tarball presence unproven.
    if n and classes == {"local_only_needs_republish"}:
        return "case_2_local_only_block_republish", {
            "proceed_to_part_d": False,
            "mutate_prod_os": False,
            "republish_required": True,
            "stop": False,
            "reason": ("candidates are locally complete + git-tracked but absent from "
                       "prod OS and the live deploy image (published before Pass 42) "
                       "cannot be confirmed to carry the tarballs; registering now "
                       "would risk schedulable-with-missing-tarball error games"),
        }
    # Fallback: empty set or unexpected shape -> treat as conflict (fail closed).
    return "case_4_inconsistent_conflict", {
        "proceed_to_part_d": False,
        "mutate_prod_os": False,
        "republish_required": True,
        "stop": True,
        "reason": f"unexpected classification set {sorted(classes)} (n={n}, "
                  f"prod_read_ok={prod_read_ok})",
    }


def _republish_instructions(records: list[dict]) -> list[dict]:
    tarballs = [r["tarball_repo_rel"] for r in records]
    return [
        {
            "step": 1,
            "title": "Confirm the candidate tarballs are committed (already true)",
            "command": "git ls-files -- " + " ".join(tarballs),
            "expect": "all three paths printed (each is git-tracked, so the next "
                      "published image will bake them into data/submissions/)",
            "mutates": False,
        },
        {
            "step": 2,
            "title": "Republish the Scheduled Deployment from the current commit",
            "command": "(Replit UI) Deployments -> the tournament Scheduled "
                       "Deployment -> Republish from the current commit; run command "
                       "stays `python scripts/tournament_deployment_tick.py "
                       "--production`",
            "expect": "a NEW image is published whose filesystem now contains the "
                      "Pass-42 tarballs listed in step 1; .replit run/build unchanged",
            "mutates": True,
            "mutation_scope": "deploy image only (NOT root main.py/deck.csv, NOT "
                              "Object Storage state)",
        },
        {
            "step": 3,
            "title": "Confirm production health is still green post-republish",
            "command": "python scripts/check_tournament_health.py --mode prod "
                       "--out-json data/experiments/pass43_post_republish_health.json "
                       "--out-md data/experiments/pass43_post_republish_health.md",
            "expect": "healthy=True (0 hard failures); sample-size warnings tolerated",
            "mutates": False,
        },
        {
            "step": 4,
            "title": "Register the probation candidates into prod OS (Part D)",
            "command": "python scripts/build_pass43_production_probation_registration.py "
                       "--apply",
            "expect": "idempotent registration: missing "
                      "TournamentParticipantRegistered / CandidateStatusChanged(->"
                      "probation) folded into prod ledger; no_upload=true; NO "
                      "CandidatePromoted / SubmissionQueued / SubmissionUploaded / "
                      "KaggleScoreUpdated; projections + storage_manifest refreshed in "
                      "lockstep; sha-verified push; lease released",
            "mutates": True,
            "mutation_scope": "prod Object Storage tournament state only",
            "precondition": "ONLY after steps 2-3 succeed on the republished image",
        },
        {
            "step": 5,
            "title": "Verify the daemon can actually run the new candidates",
            "command": "python scripts/tournament_deployment_tick.py --max-games 3 "
                       "--max-seconds 240 --storage-backend replit_app_storage "
                       "--production",
            "expect": "exit 0; NO missing-tarball / error games for the three "
                      "candidate ids; any played candidate gets a game sidecar with a "
                      "matching artifact_sha256; manifest event_count == ledger length; "
                      "no upload/submit/promotion events",
            "mutates": True,
            "mutation_scope": "prod Object Storage tournament state (game ledger) only",
        },
    ]


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    records = audit.get("candidates", [])
    prod_read_ok = bool(audit.get("prod_read", {}).get("read_ok"))

    case, decision = _decide(records, prod_read_ok)
    instructions = (_republish_instructions(records)
                    if decision["republish_required"] else [])

    out = {
        "pass": "pass43_partC_deployment_availability_decision",
        "case": case,
        "decision": decision,
        "prod_read_ok": prod_read_ok,
        "n_candidates": len(records),
        "candidate_classifications": {
            r["candidate_id"]: r["classification"] for r in records},
        "operator_republish_instructions": instructions,
        "final_decision_hint": (
            "production_registration_blocked_republish_required"
            if decision["republish_required"] and not decision["proceed_to_part_d"]
            else ("production_probation_registered_promotion_gate_ready"
                  if decision["proceed_to_part_d"] else "no_op_proceed_to_verify")),
    }
    (EXP / "pass43_deployment_availability_decision.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    md = [
        "# PASS 43 — Part C: Deployment availability decision",
        "",
        f"- **case: `{case}`**",
        f"- proceed to Part D (registration): **{decision['proceed_to_part_d']}**",
        f"- mutate prod Object Storage now: **{decision['mutate_prod_os']}**",
        f"- republish required: **{decision['republish_required']}**",
        f"- stop (conflict): **{decision['stop']}**",
        f"- reason: {decision['reason']}",
        f"- final-decision hint: `{out['final_decision_hint']}`",
        "",
        "## Per-candidate classification",
    ]
    for cid, cls in out["candidate_classifications"].items():
        md.append(f"- `{cid}` -> `{cls}`")
    if instructions:
        md += ["", "## Operator republish + registration runbook",
               "",
               "> Tarballs ride the DEPLOY IMAGE filesystem, not Object Storage. The "
               "image must be republished (so it carries the Pass-42 tarballs) BEFORE "
               "any pool entries are registered into prod OS, or the daemon will emit "
               "missing-tarball error games.", ""]
        for s in instructions:
            md += [
                f"### Step {s['step']}: {s['title']}",
                f"- mutates: **{s['mutates']}**"
                + (f" (scope: {s['mutation_scope']})" if s.get("mutation_scope") else ""),
            ]
            if s.get("precondition"):
                md.append(f"- precondition: {s['precondition']}")
            md += [
                "```",
                s["command"],
                "```",
                f"- expect: {s['expect']}",
                "",
            ]
    (EXP / "pass43_deployment_availability_decision.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass43 deployment decision: case={case} "
          f"proceed_to_part_d={decision['proceed_to_part_d']} "
          f"mutate_prod_os={decision['mutate_prod_os']} "
          f"republish_required={decision['republish_required']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
