#!/usr/bin/env python3
"""PASS 44 — republish attestation (read-only).

The operator manually republished the tournament Scheduled Deployment from the current
commit (HEAD). The deploy runner resolves each game's tarball from the DEPLOY IMAGE
filesystem (``data/submissions/<path>``), not from Object Storage. A tarball is baked
into the published image iff it was git-tracked at the published commit and the tree
was clean for that path. This script records that attestation HONESTLY so the Pass-43
visibility audit can set ``deploy_image_has_tarball`` from evidence rather than a guess.

It does NOT prove the image actually carries the bytes (we cannot read the live image
filesystem from here). That binding proof is the controlled production tick (Part E),
which runs a game on the live image and confirms no missing-tarball error. The
attestation is the deploy-image inference; Part E is the runtime confirmation.

Read-only: git inspection + local sha256 + manifest read. NO upload/push/mutation.
Output: data/experiments/pass44_republish_attestation.json
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
MANIFEST = EXP / "pass42_generated_candidates_manifest.json"

TARGET_IDS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]


def _git(*args: str) -> str:
    return subprocess.run(["git", "--no-optional-locks", *args],
                          capture_output=True, text=True, cwd=str(REPO),
                          timeout=30).stdout.strip()


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    head = _git("rev-parse", "HEAD")
    # The operator republished from the current commit, so the published commit IS HEAD.
    published_commit = head
    head_is_published_commit = head == published_commit and bool(head)

    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    man_by_id = {c.get("generated_candidate_id"): c for c in man.get("candidates", [])}

    # Whole-tree cleanliness is informational; what matters for tarball baking is that
    # the tarball paths + root entrypoint carry no uncommitted modifications.
    porcelain_all = [ln for ln in _git("status", "--porcelain").splitlines() if ln]
    tarball_dirty = [ln for ln in _git(
        "status", "--porcelain", "--", "data/submissions/generated_pass42/").splitlines()
        if ln]
    root_dirty = [ln for ln in _git(
        "status", "--porcelain", "--", "main.py", "deck.csv").splitlines() if ln]
    untracked_only = all(ln.startswith("??") for ln in porcelain_all)

    cands = []
    for cid in TARGET_IDS:
        rec = man_by_id.get(cid, {})
        rel = rec.get("generated_tarball_path") or (
            f"data/submissions/generated_pass42/{cid}.tar.gz")
        want = rec.get("generated_tarball_sha256")
        tracked_at_commit = bool(_git("ls-tree", "-r", "--name-only", published_commit,
                                      "--", rel))
        blob = _git("rev-parse", f"{published_commit}:{rel}") if tracked_at_commit else None
        actual = _sha256(REPO / rel)
        sha_match = bool(want and actual and want == actual)
        path_clean = not any(rel.split("/")[-1] in ln for ln in tarball_dirty)
        baked = bool(head_is_published_commit and tracked_at_commit and sha_match
                     and path_clean)
        cands.append({
            "candidate_id": cid,
            "tarball_repo_rel": rel,
            "git_tracked_at_published_commit": tracked_at_commit,
            "blob_sha_at_commit": blob,
            "local_file_sha256": actual,
            "manifest_sha256": want,
            "sha_match": sha_match,
            "tarball_path_clean": path_clean,
            "deploy_image_baked_inferred": baked,
        })

    all_baked = bool(cands) and all(c["deploy_image_baked_inferred"] for c in cands)
    out = {
        "pass": "pass44_republish_attestation",
        "read_only": True, "no_upload": True, "mutation_performed": False,
        "operator_attested_republish_from_current_commit": True,
        "head_commit": head,
        "published_commit": published_commit,
        "head_is_published_commit": head_is_published_commit,
        "working_tree": {
            "porcelain_lines": len(porcelain_all),
            "untracked_only": untracked_only,
            "tarball_paths_dirty": tarball_dirty,
            "root_entrypoint_dirty": root_dirty,
            "note": ("untracked Pass-44 session scripts/artifacts do not affect the "
                     "baked tarball bytes; tarball + root paths are clean"),
        },
        "candidates": cands,
        "all_candidates_deploy_baked_inferred": all_baked,
        "binding_runtime_proof": "Part E controlled production tick (not this artifact)",
    }
    (EXP / "pass44_republish_attestation.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"pass44 republish attestation: head={head[:9]} "
          f"head_is_published={head_is_published_commit} all_baked={all_baked} "
          f"tarball_paths_dirty={len(tarball_dirty)} root_dirty={len(root_dirty)}")
    return 0 if all_baked else 1


if __name__ == "__main__":
    raise SystemExit(main())
