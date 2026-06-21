#!/usr/bin/env python3
"""PASS 43 — Part B: Pass-42 probation visibility audit (READ-ONLY).

For each Pass-42 *generated* probation candidate, establish — honestly and without
mutating anything — where it currently is visible:

  * locally: tarball present + git-tracked + sha256 matches the Pass-42 manifest;
    registered in candidate_pool.json and in the local event ledger.
  * production: present in the live Object Storage candidate_pool.json / events
    ledger (read-only pull); whether its status would make it schedulable.
  * deploy image: whether the published Scheduled-Deployment image carries the
    tarball. This is UNVERIFIABLE from here (tarballs ride the deploy filesystem,
    not Object Storage, and the live image predates Pass 42) → conservative "no".

Each candidate is classified into exactly one bucket:
  production_ready | local_only_needs_republish | object_storage_missing |
  missing_tarball | manifest_mismatch | unsafe_to_register

This script NEVER writes to Object Storage and NEVER mutates local state. It only
reads. Output: data/experiments/pass43_probation_visibility_audit.{json,md}.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament.pool import (  # noqa: E402
    SCHEDULABLE_STATUSES, PROBATION,
)
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    get_storage_backend, StorageError,
)

TDIR = REPO / "data" / "tournament"
EXP = REPO / "data" / "experiments"
SUBMISSIONS = REPO / "data" / "submissions"
MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
LOCAL_POOL = TDIR / "candidate_pool.json"
LOCAL_LEDGER = TDIR / "events.jsonl"

REGISTER_EVENT = "TournamentParticipantRegistered"
GENERATED_EVENT = "CandidateGenerated"
STATUS_EVENT = "CandidateStatusChanged"


def _sha256_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_tracked(rel_path: str) -> bool:
    try:
        rc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            cwd=str(REPO), capture_output=True, text=True).returncode
        return rc == 0
    except Exception:  # noqa: BLE001
        return False


def _load_local_pool() -> dict:
    try:
        return json.loads(LOCAL_POOL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _pool_index(pool_obj: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in (pool_obj.get("candidates") or []):
        cid = c.get("candidate_id")
        if cid:
            out[cid] = c
    return out


def _ledger_registered_ids(lines: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Return (registered_ids, generated_ids, status_changed_ids) from raw lines."""
    registered: set[str] = set()
    generated: set[str] = set()
    status_changed: set[str] = set()
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        et = ev.get("event_type") or ev.get("type")
        p = ev.get("payload") or {}
        if et == REGISTER_EVENT:
            cid = (p.get("candidate") or {}).get("candidate_id") or p.get("candidate_id")
            if cid:
                registered.add(cid)
        elif et == GENERATED_EVENT:
            cid = p.get("candidate_id") or p.get("generated_candidate_id")
            if cid:
                generated.add(cid)
        elif et == STATUS_EVENT:
            cid = p.get("candidate_id")
            if cid:
                status_changed.add(cid)
    return registered, generated, status_changed


def _read_prod_state() -> dict:
    """Read-only pull of prod candidate_pool.json + events.jsonl (no game sidecars)."""
    result: dict = {
        "read_ok": False, "error": None, "backend": None,
        "pool_index": {}, "registered": [], "generated": [], "status_changed": [],
    }
    try:
        backend = get_storage_backend(env="production", backend="replit_app_storage")
        result["backend"] = getattr(backend, "name", "replit_app_storage")
        pool_obj = {}
        if backend.exists("candidate_pool.json"):
            pool_obj = json.loads(backend.read_text("candidate_pool.json"))
        idx = _pool_index(pool_obj)
        ledger_lines: list[str] = []
        if backend.exists("events.jsonl"):
            ledger_lines = backend.read_text("events.jsonl").splitlines()
        reg, gen, sc = _ledger_registered_ids(ledger_lines)
        result.update({
            "read_ok": True,
            "pool_index": {k: {"status": v.get("status"),
                               "tarball_path": v.get("tarball_path")}
                           for k, v in idx.items()},
            "registered": sorted(reg), "generated": sorted(gen),
            "status_changed": sorted(sc),
        })
    except StorageError as exc:
        result["error"] = f"StorageError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _classify(rec: dict) -> tuple[str, str]:
    """Return (classification, rationale). Conservative; deploy-visibility unproven."""
    if not rec["tarball_exists_local"]:
        return "missing_tarball", "tarball absent on local filesystem"
    if rec["manifest_sha256"] and rec["local_sha256"] != rec["manifest_sha256"]:
        return "manifest_mismatch", "local tarball sha256 != Pass-42 manifest sha256"
    if not (rec["in_local_pool"] and rec["in_local_ledger"]):
        return ("unsafe_to_register",
                "incomplete LOCAL provenance (not in pool and/or ledger)")
    # Local provenance complete + bytes verified from here on.
    if rec["prod_read_ok"]:
        in_prod = rec["in_prod_pool"] and rec["in_prod_ledger"]
        if in_prod and rec["deploy_image_has_tarball"] is True:
            return "production_ready", "present in prod OS and tarball deploy-visible"
        if in_prod and rec["deploy_image_has_tarball"] is not True:
            return ("unsafe_to_register",
                    "ALREADY in prod OS but tarball deploy-visibility UNVERIFIED — "
                    "schedulable-with-missing-tarball risk; needs republish+verify")
        # Not in prod OS at all.
        if rec["git_tracked"]:
            return ("local_only_needs_republish",
                    "locally complete + git-tracked; absent from prod OS; deploy "
                    "image predates Pass 42 → republish (bakes tarball) then register")
        return ("object_storage_missing",
                "absent from prod OS AND not git-tracked — republish would not "
                "carry the tarball; git-add required before any registration")
    # Prod unreadable → cannot claim prod presence; safe no-mutate path.
    if rec["git_tracked"]:
        return ("local_only_needs_republish",
                "prod OS unreadable (fail-closed); locally complete + git-tracked; "
                "treat as not-in-prod → republish required before registration")
    return ("object_storage_missing",
            "prod OS unreadable and tarball not git-tracked")


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    man_by_id: dict[str, dict] = {}
    for c in manifest.get("candidates", []):
        cid = c.get("generated_candidate_id")
        if cid:
            man_by_id[cid] = c

    local_pool = _load_local_pool()
    local_idx = _pool_index(local_pool)

    # Authoritative target set: generated candidates that are status==probation locally.
    target_ids = sorted(
        cid for cid, c in local_idx.items()
        if c.get("status") == PROBATION and cid.startswith("generated_")
    )

    local_lines = (LOCAL_LEDGER.read_text(encoding="utf-8").splitlines()
                   if LOCAL_LEDGER.is_file() else [])
    loc_reg, loc_gen, loc_sc = _ledger_registered_ids(local_lines)

    prod = _read_prod_state()

    records = []
    for cid in target_ids:
        pool_entry = local_idx.get(cid, {})
        man = man_by_id.get(cid, {})
        tarball_path = (pool_entry.get("tarball_path")
                        or man.get("generated_tarball_path"))
        # Normalise: pool stores 'generated_pass42/<id>.tar.gz' (relative to
        # data/submissions/); manifest stores 'data/submissions/generated_pass42/...'.
        if tarball_path and tarball_path.startswith("data/submissions/"):
            rel_sub = tarball_path[len("data/submissions/"):]
        else:
            rel_sub = tarball_path or ""
        abs_tarball = SUBMISSIONS / rel_sub if rel_sub else None
        repo_rel = (f"data/submissions/{rel_sub}" if rel_sub else "")
        local_sha = _sha256_file(abs_tarball) if abs_tarball else None
        man_sha = man.get("generated_tarball_sha256")

        prod_entry = prod["pool_index"].get(cid, {}) if prod["read_ok"] else {}
        rec = {
            "candidate_id": cid,
            "parent_candidate_id": (pool_entry.get("parent_candidate_id")
                                    or man.get("parent_candidate_id")),
            "family_id": pool_entry.get("family_id") or man.get("family_id"),
            "tarball_path": tarball_path,
            "tarball_repo_rel": repo_rel,
            "tarball_exists_local": bool(abs_tarball and abs_tarball.is_file()),
            "local_sha256": local_sha,
            "manifest_sha256": man_sha,
            "sha_match": bool(man_sha and local_sha == man_sha),
            "git_tracked": _git_tracked(repo_rel) if repo_rel else False,
            "deck_changing": bool(man.get("deck_changing")),
            "in_local_pool": cid in local_idx,
            "local_status": pool_entry.get("status"),
            "in_local_ledger": cid in loc_reg,
            "local_generated_event": cid in loc_gen,
            "prod_read_ok": prod["read_ok"],
            "in_prod_pool": cid in prod["pool_index"] if prod["read_ok"] else None,
            "prod_status": prod_entry.get("status") if prod["read_ok"] else None,
            "in_prod_ledger": (cid in prod["registered"]) if prod["read_ok"] else None,
            "prod_schedulable_by_status": (
                prod_entry.get("status") in SCHEDULABLE_STATUSES
                if prod["read_ok"] and prod_entry else (None if prod["read_ok"] else None)
            ),
            # Tarballs ride the deploy filesystem, not Object Storage; the live image
            # predates Pass 42 and cannot be inspected from here → conservative.
            "deploy_image_has_tarball": None,  # None == UNVERIFIABLE (treated as no)
        }
        cls, why = _classify(rec)
        rec["classification"] = cls
        rec["rationale"] = why
        records.append(rec)

    classes = sorted({r["classification"] for r in records})
    all_local_only = bool(records) and all(
        r["classification"] == "local_only_needs_republish" for r in records)

    out = {
        "pass": "pass43_partB_probation_visibility_audit",
        "tournament_id": local_pool.get("tournament_id"),
        "n_candidates": len(records),
        "expected_count": 3,
        "prod_read": {"read_ok": prod["read_ok"], "backend": prod["backend"],
                      "error": prod["error"]},
        "classifications_present": classes,
        "all_local_only_needs_republish": all_local_only,
        "candidates": records,
    }
    (EXP / "pass43_probation_visibility_audit.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b) -> str:
        return "UNVERIFIED" if b is None else ("yes" if b else "no")

    md = [
        "# PASS 43 — Part B: Pass-42 probation visibility audit (read-only)",
        "",
        f"- candidates audited: **{len(records)}** (expected 3)",
        f"- prod Object Storage read: **{yn(prod['read_ok'])}** "
        f"(backend `{prod['backend']}`{'' if not prod['error'] else '; ERROR: ' + prod['error']})",
        f"- classifications present: `{classes}`",
        f"- all classified `local_only_needs_republish`: **{yn(all_local_only)}**",
        "",
        "> Tarballs are resolved by the runner from the DEPLOY FILESYSTEM "
        "(`data/submissions/<tarball_path>`), NOT from Object Storage. The live "
        "Scheduled-Deployment image predates Pass 42, so deploy-image tarball "
        "presence is **UNVERIFIABLE** here and treated conservatively as absent.",
        "",
    ]
    for r in records:
        md += [
            f"## {r['candidate_id']}",
            f"- parent: `{r['parent_candidate_id']}`  family: `{r['family_id']}`  "
            f"deck-changing: {yn(r['deck_changing'])}",
            f"- tarball: `{r['tarball_repo_rel']}`",
            f"- tarball exists local: **{yn(r['tarball_exists_local'])}**  "
            f"sha256==manifest: **{yn(r['sha_match'])}**  git-tracked: **{yn(r['git_tracked'])}**",
            f"- local pool: **{yn(r['in_local_pool'])}** (status `{r['local_status']}`)  "
            f"local ledger registered: **{yn(r['in_local_ledger'])}**",
            f"- prod pool: **{yn(r['in_prod_pool'])}** (status `{r['prod_status']}`)  "
            f"prod ledger registered: **{yn(r['in_prod_ledger'])}**  "
            f"prod schedulable-by-status: **{yn(r['prod_schedulable_by_status'])}**",
            f"- deploy image has tarball: **{yn(r['deploy_image_has_tarball'])}**",
            f"- **classification: `{r['classification']}`** — {r['rationale']}",
            "",
        ]
    (EXP / "pass43_probation_visibility_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(
        "pass43 visibility audit: "
        f"n={len(records)} prod_read_ok={prod['read_ok']} "
        f"classes={classes} all_local_only={all_local_only}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
