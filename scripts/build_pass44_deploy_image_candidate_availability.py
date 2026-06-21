#!/usr/bin/env python3
"""PASS 44 — Part B: deploy-image candidate availability (read-only).

Consolidates the post-republish evidence that the three Pass-42 probation candidates
are now safe to register into production Object Storage:

  * the Pass-44 republish attestation (tarballs git-tracked at the published commit,
    sha256-match the Pass-42 manifest, tarball + root paths clean → baked into image),
  * the re-run Pass-43 Part B visibility audit (deploy_image_has_tarball now True from
    that attestation; every candidate still local_only_needs_republish — absent from
    prod OS), and
  * the re-run Pass-43 Part C decision (now case_1_deploy_visible_os_missing →
    proceed_to_part_d, mutate_prod_os).

The deploy-image inference is evidence-based, not byte-proven; the BINDING runtime
proof is the Part E controlled production tick. Read-only. NO mutation/upload/push.
Output: data/experiments/pass44_deploy_image_candidate_availability.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
ATTEST = EXP / "pass44_republish_attestation.json"
AUDIT = EXP / "pass43_probation_visibility_audit.json"
DECISION = EXP / "pass43_deployment_availability_decision.json"


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    att = json.loads(ATTEST.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    dec = json.loads(DECISION.read_text(encoding="utf-8"))

    att_by_id = {c["candidate_id"]: c for c in att.get("candidates", [])}
    aud_by_id = {c["candidate_id"]: c for c in audit.get("candidates", [])}

    rows = []
    for cid in sorted(aud_by_id):
        a = att_by_id.get(cid, {})
        u = aud_by_id.get(cid, {})
        baked = u.get("deploy_image_has_tarball") is True
        os_missing = (u.get("in_prod_pool") is False) or (u.get("in_prod_ledger") is False)
        safe = bool(baked and os_missing and u.get("sha_match")
                    and u.get("git_tracked") and u.get("in_local_pool")
                    and u.get("in_local_ledger"))
        rows.append({
            "candidate_id": cid,
            "git_tracked_at_published_commit": a.get("git_tracked_at_published_commit"),
            "sha_match": u.get("sha_match"),
            "tarball_path_clean": a.get("tarball_path_clean"),
            "deploy_image_has_tarball": u.get("deploy_image_has_tarball"),
            "deploy_image_attestation": u.get("deploy_image_attestation"),
            "in_prod_pool": u.get("in_prod_pool"),
            "in_prod_ledger": u.get("in_prod_ledger"),
            "local_status": u.get("local_status"),
            "classification": u.get("classification"),
            "availability": ("safe_to_register_after_republish" if safe
                             else "not_yet_safe"),
        })

    decision = dec.get("decision", {})
    all_safe = bool(rows) and all(
        r["availability"] == "safe_to_register_after_republish" for r in rows)
    proceed = bool(decision.get("proceed_to_part_d") and decision.get("mutate_prod_os"))

    out = {
        "pass": "pass44_partB_deploy_image_candidate_availability",
        "read_only": True, "no_upload": True, "mutation_performed": False,
        "head_commit": att.get("head_commit"),
        "published_commit": att.get("published_commit"),
        "head_is_published_commit": att.get("head_is_published_commit"),
        "pass43_decision_case": dec.get("case"),
        "proceed_to_part_d": decision.get("proceed_to_part_d"),
        "mutate_prod_os": decision.get("mutate_prod_os"),
        "republish_required": decision.get("republish_required"),
        "candidates": rows,
        "all_safe_to_register_after_republish": all_safe,
        "ready_to_register": all_safe and proceed,
        "binding_runtime_proof": "Part E controlled production tick (not this artifact)",
        "start_application_not_started_expected": True,
    }
    (EXP / "pass44_deploy_image_candidate_availability.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# PASS 44 — Part B: deploy-image candidate availability", "",
        "> Read-only. Consolidates the post-republish evidence that the 3 Pass-42 "
        "probation candidates are safe to register into production Object Storage. The "
        "deploy-image presence is INFERRED from git-tracked-at-published-commit + clean "
        "tree; the binding runtime proof is the Part E controlled production tick. NO "
        "mutation / upload / push here.", "",
        f"- HEAD == published commit: **{yn(out['head_is_published_commit'])}** "
        f"(`{out['head_commit']}`)",
        f"- Pass-43 decision case: `{out['pass43_decision_case']}`",
        f"- proceed to registration (Part D): **{yn(out['proceed_to_part_d'])}**  "
        f"mutate prod OS: **{yn(out['mutate_prod_os'])}**  "
        f"republish required: **{yn(out['republish_required'])}**",
        f"- **all safe to register after republish: {yn(all_safe)}**  "
        f"ready to register: **{yn(out['ready_to_register'])}**",
        "", "## Per-candidate availability", "",
    ]
    for r in rows:
        md += [
            f"### `{r['candidate_id']}`  → **{r['availability']}**",
            f"- git-tracked at published commit: **{yn(r['git_tracked_at_published_commit'])}**"
            f"  sha256==manifest: **{yn(r['sha_match'])}**"
            f"  tarball path clean: **{yn(r['tarball_path_clean'])}**",
            f"- deploy image has tarball: **{yn(r['deploy_image_has_tarball'])}** "
            f"(`{r['deploy_image_attestation']}`)",
            f"- in prod pool: **{yn(r['in_prod_pool'])}**  in prod ledger: "
            f"**{yn(r['in_prod_ledger'])}**  local status: `{r['local_status']}`",
            f"- audit classification: `{r['classification']}`",
            "",
        ]
    md += [
        "## Note",
        "- Every candidate is absent from prod Object Storage (deploy image now carries "
        "the tarball) → registering the pool entries is safe and will not create "
        "schedulable-with-missing-tarball error games. Part E confirms this at runtime.",
    ]
    (EXP / "pass44_deploy_image_candidate_availability.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass44 partB availability: all_safe={all_safe} "
          f"ready_to_register={out['ready_to_register']} case={out['pass43_decision_case']}")
    return 0 if out["ready_to_register"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
