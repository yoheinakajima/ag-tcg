#!/usr/bin/env python3
"""PASS 44 — Part A: post-republish safety preflight (STOP-GATE).

The operator has republished the Scheduled Deployment from the current commit, which
should bake the git-tracked Pass-42 tarballs into the deploy image. This re-asserts
every hard safety invariant BEFORE any production mutation and folds in the
post-republish evidence (tarballs exist locally, sha-match the Pass-42 manifest, and
are git-tracked at HEAD).

It consumes the refreshed ``pass43_safety_preflight.json`` (Pass-43 Part A re-run with
``--reuse-health`` against the live prod snapshot) for the shared hard checks, and adds
the candidate-availability checks specific to this pass.

Read-only. NO upload/submit/push/root-mutation/generation. STOP if any hard check fails.
Output: data/experiments/pass44_post_republish_safety_preflight.{json,md}
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PRE43 = EXP / "pass43_safety_preflight.json"
PASS42_MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
POOL = REPO / "data" / "tournament" / "candidate_pool.json"
DOTREPLIT = REPO / ".replit"

TARGET_IDS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "--no-optional-locks", *args],
                              capture_output=True, text=True, cwd=str(REPO),
                              timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _manifest_index() -> dict[str, dict]:
    man = json.loads(PASS42_MANIFEST.read_text(encoding="utf-8"))
    return {c["generated_candidate_id"]: c for c in man.get("candidates", [])}


def _tarball_checks() -> dict:
    idx = _manifest_index()
    head = _git("rev-parse", "HEAD")
    tracked = set(_git("ls-files", "--", "data/submissions/generated_pass42/").splitlines())
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    cands = pool.get("candidates") or pool
    if isinstance(cands, dict):
        cands = list(cands.values())
    status = {c.get("candidate_id"): c.get("status") for c in cands}

    rows = []
    for cid in TARGET_IDS:
        rec = idx.get(cid, {})
        rel = rec.get("generated_tarball_path") or (
            f"data/submissions/generated_pass42/{cid}.tar.gz")
        fp = REPO / rel
        actual = _sha256(fp)
        want = rec.get("generated_tarball_sha256")
        rows.append({
            "candidate_id": cid,
            "tarball_repo_rel": rel,
            "exists_local": fp.is_file(),
            "sha256": actual,
            "manifest_sha256": want,
            "sha_match": bool(actual and want and actual == want),
            "git_tracked": rel in tracked,
            "local_status": status.get(cid),
            "is_probation": status.get(cid) == "probation",
        })
    all_ok = bool(rows) and all(
        r["exists_local"] and r["sha_match"] and r["git_tracked"] and r["is_probation"]
        for r in rows)
    return {"head_commit": head, "candidates": rows, "all_ok": all_ok}


def _replit_storage_backend_check() -> dict:
    txt = DOTREPLIT.read_text(encoding="utf-8") if DOTREPLIT.is_file() else ""
    uses_app_storage = "replit_app_storage" in txt
    uses_tick = "tournament_deployment_tick.py" in txt
    uses_production = '"--production"' in txt or "--production" in txt
    return {"replit_app_storage": uses_app_storage,
            "deployment_tick": uses_tick, "production_flag": uses_production,
            "all_ok": uses_app_storage and uses_tick and uses_production}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    if not PRE43.is_file():
        raise SystemExit("missing pass43_safety_preflight.json — run Pass-43 Part A "
                         "(re-run with --reuse-health) first")
    pre = json.loads(PRE43.read_text(encoding="utf-8"))

    root_unchanged = bool(pre.get("root_unchanged"))
    deploy = pre.get("deployment_config", {})
    deploy_ok = bool(deploy.get("all_ok"))
    storage = _replit_storage_backend_check()
    auto_submit_off = bool(pre.get("auto_submit_check", {}).get("all_ok"))
    health = pre.get("prod_health", {})
    prod_reachable = health.get("source") == "prod" or bool(health.get("healthy"))
    health_green = bool(health.get("healthy"))
    no_forbidden = bool(pre.get("ledger_event_scan", {}).get("all_ok"))
    refs_absent = bool(pre.get("reference_absence", {}).get("all_ok"))
    tarballs = _tarball_checks()

    checks = {
        "1_root_byte_identical": root_unchanged,
        "2_replit_scheduled_deployment_unchanged": deploy_ok and storage["all_ok"],
        "3_auto_submit_false": auto_submit_off,
        "4_prod_object_storage_reachable": prod_reachable,
        "5_prod_health_green_or_sample_warn_only": health_green,
        "6_no_forbidden_events_in_scope": no_forbidden,
        "7_public_references_absent": refs_absent,
        "8_pass42_tarballs_exist_and_match_manifest": all(
            r["exists_local"] and r["sha_match"] for r in tarballs["candidates"]),
        "9_pass42_tarballs_git_tracked": all(
            r["git_tracked"] for r in tarballs["candidates"]),
    }
    safe = all(checks.values())

    out = {
        "pass": "pass44_partA_post_republish_safety_preflight",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "production_mutation_performed_here": False, "tarball_mutation": False,
        "promotion_performed": False, "generation_performed": False,
        "head_commit": tarballs["head_commit"],
        "republished_by_operator": True,
        "checks": checks,
        "replit_storage_backend_check": storage,
        "tarball_availability": tarballs,
        "shared_pass43_preflight": {
            "preflight_safe": pre.get("preflight_safe"),
            "prod_health_healthy": health.get("healthy"),
            "prod_health_reused": health.get("reused"),
            "prod_health_hard_failures": health.get("hard_failures"),
            "prod_health_warnings": health.get("warnings"),
        },
        "preflight_safe": safe,
        "stop_required": not safe,
        "start_application_not_started_expected": True,
    }
    (EXP / "pass44_post_republish_safety_preflight.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# PASS 44 — Part A: post-republish safety preflight (STOP-GATE)", "",
        "> Read-only OPS gate re-asserted AFTER the operator republished the Scheduled "
        "Deployment from the current commit. NO upload, NO submit, NO push, NO root/"
        "tarball mutation, NO candidate generation, NO promotion. Internal diagnostics; "
        "NOT a Kaggle leaderboard or strength claim.", "",
        f"- HEAD commit: `{out['head_commit']}`",
        f"- **preflight safe: {yn(safe)}**  stop required: **{yn(out['stop_required'])}**",
        "",
        "## Hard checks",
    ]
    labels = {
        "1_root_byte_identical": "root main.py/deck.csv byte-identical to baseline",
        "2_replit_scheduled_deployment_unchanged":
            ".replit scheduled deployment unchanged (target=scheduled, deployment "
            "tick, --production, replit_app_storage, not root main.py)",
        "3_auto_submit_false": "auto_submit OFF (+ positive control)",
        "4_prod_object_storage_reachable": "production Object Storage reachable",
        "5_prod_health_green_or_sample_warn_only":
            "production health green (0 hard failures; sample-size warnings tolerated)",
        "6_no_forbidden_events_in_scope":
            "no SubmissionQueued/SubmissionUploaded/KaggleScoreUpdated/CandidatePromoted "
            "in scope",
        "7_public_references_absent":
            "public references absent from pool / scheduler / lineage / promotion set",
        "8_pass42_tarballs_exist_and_match_manifest":
            "Pass-42 tarballs exist locally and sha256-match the Pass-42 manifest",
        "9_pass42_tarballs_git_tracked": "Pass-42 tarballs git-tracked at HEAD",
    }
    for k, v in checks.items():
        md.append(f"- {labels[k]}: **{yn(v)}**")
    md += ["", "## Pass-42 candidate tarball availability", ""]
    for r in tarballs["candidates"]:
        md += [
            f"### `{r['candidate_id']}`",
            f"- repo path: `{r['tarball_repo_rel']}`",
            f"- exists local: **{yn(r['exists_local'])}**  sha256==manifest: "
            f"**{yn(r['sha_match'])}**  git-tracked: **{yn(r['git_tracked'])}**",
            f"- local status: `{r['local_status']}` (probation: {yn(r['is_probation'])})",
            "",
        ]
    md += [
        "## Root 'Start application' workflow",
        "- frozen Kaggle entrypoint; not-started is EXPECTED and is **never** started "
        "by this pass.", "",
        "## Shared Pass-43 preflight (re-run, --reuse-health)",
        f"- pass43 preflight_safe: **{yn(pre.get('preflight_safe'))}**",
        f"- prod health healthy: **{yn(health.get('healthy'))}** "
        f"(reused artifact: {yn(health.get('reused'))})",
        f"- prod health hard failures: {health.get('hard_failures') or 'none'}",
        f"- prod health warnings: {health.get('warnings') or 'none'}",
    ]
    (EXP / "pass44_post_republish_safety_preflight.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass44 partA preflight: safe={safe} stop_required={not safe} "
          f"tarballs_ok={tarballs['all_ok']} health_green={health_green}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
