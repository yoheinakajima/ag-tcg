#!/usr/bin/env python3
"""PASS 44 — Part C: key-scoped production probation registration (CONDITIONAL).

Registers the three Pass-42 *generated probation* candidates into the PRODUCTION
Object Storage tournament state — same idempotent, gated, fail-closed transaction as
Pass-43 Part D (``build_pass43_production_probation_registration.py``), but using a
KEY-SCOPED push so it completes well within the interactive tool boundary.

Why key-scoped: the production snapshot now carries ~950 game sidecars. The Pass-43
primitive mirrors ALL of them into a temp dir (pull), re-uploads ALL of them (push),
and re-verifies ALL of them — three serial passes over the whole snapshot (~5 min).
That cannot run safely inside a 2-minute tool call, and a prod mutation must NEVER be
killed mid-transaction (the 30-min lease would not be released, stalling the daemon).

This runner instead:
  * pulls ONLY the ledger + bootstrap pool + config (a handful of objects),
  * rebuilds the ledger/pool/projections from events in a temp dir (no sidecars),
  * reuses the ALREADY-VERIFIED remote manifest entries for every unchanged sidecar
    and recomputes entries only for the handful of files it actually rewrites,
  * uploads + verifies ONLY those changed keys.

It NEVER re-hashes or re-uploads the sidecars, so the transaction is seconds, not
minutes. Correctness is guarded fail-closed BEFORE acquiring the lease:
  * the remote manifest key-set must exactly equal the live backend key-set, and
  * the rebuilt pool size must equal (remote pool size + newly-registered count);
either mismatch aborts WITHOUT mutating production.

Gating (identical to Pass-43 Part D): Part C decision == case_1 (mutate_prod_os AND
proceed_to_part_d) AND Part A safety preflight green. HARD guardrails: no_upload=true
on every event; NEVER CandidatePromoted/SubmissionQueued/SubmissionUploaded/
KaggleScoreUpdated; never a protected status; never overwrites a divergent remote
ledger; never deletes remote keys. Idempotent.

Output: data/experiments/pass44_production_probation_registration_apply.{json,md}
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import build_pass43_production_probation_registration as R  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament import projections as projmod  # noqa: E402
from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    get_storage_backend, StorageError)

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"
DECISION = EXP / "pass43_deployment_availability_decision.json"
PREFLIGHT = EXP / "pass43_safety_preflight.json"
LOCAL_LEDGER = TDIR / "events.jsonl"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _event_no_upload(ev: dict) -> bool:
    if ev.get("no_upload") is True:
        return True
    return bool((ev.get("payload") or {}).get("no_upload") is True)


def _apply_keyscoped(target_ids: list[str], captured: dict[str, list[dict]]) -> dict:
    backend = get_storage_backend(env="production", backend="replit_app_storage")

    # ---- fail-closed key-set consistency check (read-only, BEFORE lease) ---- #
    remote_manifest = backend.get_json(sync.MANIFEST_KEY) or {}
    man_files = remote_manifest.get("files") or []
    man_keys = {f["key"] for f in man_files}
    listed = {k for k in backend.list()
              if not k.startswith(sync.LOCK_PREFIX) and k != sync.MANIFEST_KEY}
    if man_keys != listed:
        raise StorageError(
            "prod manifest/key-set drift; refusing key-scoped push: "
            f"listed_not_in_manifest={sorted(listed - man_keys)[:5]} "
            f"manifest_not_in_listed={sorted(man_keys - listed)[:5]}")

    lease = lease_mod.acquire_lease(backend, tick_id=None)
    tmp = Path(tempfile.mkdtemp(prefix="pass44_reg_"))
    tmp_root = tmp / "tournament"
    tmp_root.mkdir(parents=True, exist_ok=True)
    saved_proj_dir = projmod.PROJ_DIR
    result: dict = {"applied": False}
    try:
        projmod.PROJ_DIR = tmp_root / "projections"

        base_remote_hash = sync.remote_events_hash(backend)
        remote_raw = (sync.parse_events_text(backend.read_text(sync.EVENTS_KEY))
                      if backend.exists(sync.EVENTS_KEY) else [])
        remote_ids = {e.get("event_id") for e in remote_raw}
        remote_pool = (json.loads(backend.read_text(sync.POOL_KEY))
                       if backend.exists(sync.POOL_KEY) else {"candidates": []})
        remote_pool_count = len(remote_pool.get("candidates", []))
        # seed config so its manifest entry stays exact after rebuild
        if backend.exists(sync.CONFIG_KEY):
            (tmp_root / sync.CONFIG_KEY).write_bytes(backend.read_bytes(sync.CONFIG_KEY))

        to_add: list[dict] = []
        per_cand: list[dict] = []
        newly: list[str] = []
        for gid in target_ids:
            want = R._registration_snapshot(captured[gid], gid) or {}
            if R._already_registered(remote_raw, gid, want):
                per_cand.append({"candidate_id": gid, "action": "already_registered"})
                continue
            add = [ev for ev in captured[gid] if ev.get("event_id") not in remote_ids]
            to_add.extend(add)
            newly.append(gid)
            per_cand.append({"candidate_id": gid, "action": "register",
                             "events_added": len(add)})

        # ---- hard guardrails on the exact event set we are about to push ---- #
        bad = [ev.get("event_type") for ev in to_add
               if ev.get("event_type") in R.FORBIDDEN_EVENT_TYPES]
        if bad:
            raise StorageError(f"refusing: forbidden event types in to_add: {bad}")
        missing_no_upload = [ev.get("event_id") for ev in to_add
                             if not _event_no_upload(ev)]
        if missing_no_upload:
            raise StorageError(
                f"refusing: events missing no_upload=true: {missing_no_upload}")
        for ev in to_add:
            if ev.get("event_type") == R.REG_T:
                snap = (ev.get("payload") or {}).get("candidate") or {}
                if snap.get("status") in R.PROTECTED_STATUSES:
                    raise StorageError(
                        f"refusing: registration with protected status "
                        f"{snap.get('status')} for {snap.get('candidate_id')}")

        if not to_add:
            result.update({"applied": False, "reason": "idempotent_no_new_events",
                           "per_candidate": per_cand})
            return result

        merged, recon = sync.reconcile_events(to_add, remote_raw)
        (tmp_root / sync.EVENTS_KEY).write_text(sync.dump_events(merged),
                                                encoding="utf-8")
        rebuild = R._rebuild_into(tmp_root)

        # ---- fail-closed pool-size invariant ---- #
        expected_pool = remote_pool_count + len(newly)
        if rebuild["registered_candidates"] != expected_pool:
            raise StorageError(
                f"pool-size invariant failed: rebuilt="
                f"{rebuild['registered_candidates']} expected={expected_pool} "
                f"(remote={remote_pool_count} + new={len(newly)})")

        # ---- defensive drift re-check (we hold the lease, so unexpected) ---- #
        status = "clean"
        current_remote_hash = sync.remote_events_hash(backend)
        if current_remote_hash is not None and current_remote_hash != base_remote_hash:
            remote2 = sync.parse_events_text(backend.read_text(sync.EVENTS_KEY))
            merged, recon = sync.reconcile_events(merged, remote2)
            (tmp_root / sync.EVENTS_KEY).write_text(sync.dump_events(merged),
                                                    encoding="utf-8")
            R._rebuild_into(tmp_root)
            status = "merged"

        # ---- key-scoped manifest: reuse remote entries for unchanged keys ---- #
        changed_keys = sync.collect_local_keys(tmp_root)  # events, pool, config, projections/*
        changed_set = set(changed_keys)
        # No sidecar/runs keys are in changed_set, so they are preserved verbatim.
        files = [f for f in man_files if f["key"] not in changed_set]
        for k in changed_keys:
            data = (tmp_root / k).read_bytes()
            files.append({"key": k, "size": len(data), "sha256": _sha256_bytes(data)})
        files.sort(key=lambda f: f["key"])
        new_manifest = {
            "schema": "pass37_storage_manifest_v1",
            "generated_at": time.time(),
            "tick_id": lease.tick_id,
            "status": status,
            "no_upload": True,
            "auto_submit": False,
            "base_remote_hash": base_remote_hash,
            "event_count": len(merged),
            "last_event_id": merged[-1].get("event_id") if merged else None,
            "files": files,
        }

        uploaded = backend.upload_dir(tmp_root, changed_keys)
        backend.write_text(sync.MANIFEST_KEY,
                           json.dumps(new_manifest, indent=2, sort_keys=True))

        verify = backend.verify(tmp_root, changed_keys)
        rb = backend.get_json(sync.MANIFEST_KEY) or {}
        manifest_ok = (rb.get("event_count") == len(merged)
                       and len(rb.get("files", [])) == len(files))
        if not verify["ok"] or not manifest_ok:
            raise StorageError(
                f"post-push verification failed: verify={verify} "
                f"manifest_ok={manifest_ok}")

        result.update({
            "applied": True,
            "reconcile": recon,
            "status": status,
            "uploaded_count": len(uploaded),
            "uploaded_keys": uploaded,
            "verify_ok": verify["ok"],
            "verify_checked": verify["checked"],
            "manifest_event_count": rb.get("event_count"),
            "manifest_file_count": len(rb.get("files", [])),
            "pool_count_after": rebuild["registered_candidates"],
            "pool_count_before": remote_pool_count,
            "newly_registered": newly,
            "per_candidate": per_cand,
        })
        return result
    finally:
        projmod.PROJ_DIR = saved_proj_dir
        try:
            lease_mod.release_lease(backend, lease)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    apply_flag = "--apply" in sys.argv[1:]

    decision = json.loads(DECISION.read_text(encoding="utf-8"))
    dec = decision.get("decision", {})
    safe_to_apply = bool(dec.get("mutate_prod_os") and dec.get("proceed_to_part_d"))
    case = decision.get("case")

    preflight = (json.loads(PREFLIGHT.read_text(encoding="utf-8"))
                 if PREFLIGHT.is_file() else {})
    root_safe = bool(preflight.get("preflight_safe")
                     and not preflight.get("stop_required"))

    target_ids = R._target_ids()
    local_raw = (sync.parse_events_text(LOCAL_LEDGER.read_text(encoding="utf-8"))
                 if LOCAL_LEDGER.is_file() else [])
    captured = {gid: R._capture_candidate_events(local_raw, gid) for gid in target_ids}
    would_register = {gid: {
        "events_captured": len(captured[gid]),
        "registration_present_local":
            R._registration_snapshot(captured[gid], gid) is not None,
    } for gid in target_ids}

    do_apply = bool(apply_flag and safe_to_apply and root_safe and target_ids)
    apply_result = None
    skip_reason = None
    if do_apply:
        apply_result = _apply_keyscoped(target_ids, captured)
    else:
        if not apply_flag:
            skip_reason = "dry-run (no --apply flag)"
        elif not safe_to_apply:
            skip_reason = (f"Part C decision not safe to mutate prod OS (case={case}, "
                           f"mutate_prod_os={dec.get('mutate_prod_os')}, "
                           f"proceed_to_part_d={dec.get('proceed_to_part_d')})")
        elif not root_safe:
            skip_reason = "Part A safety preflight not green"
        elif not target_ids:
            skip_reason = "no generated probation candidates found locally"

    production_mutated = bool(do_apply and apply_result and apply_result.get("applied"))
    out = {
        "pass": "pass44_partC_production_probation_registration_apply",
        "method": "key_scoped_push",
        "case": case,
        "safe_to_apply": safe_to_apply,
        "root_safe": root_safe,
        "apply_flag": apply_flag,
        "apply_skipped": not do_apply,
        "skip_reason": skip_reason,
        "n_targets": len(target_ids),
        "target_ids": target_ids,
        "would_register": would_register,
        "apply_result": apply_result,
        "guardrails": {
            "no_kaggle_or_promotion_events_in_scope": True,
            "no_upload_only": True,
            "protected_statuses_untouched": True,
            "sidecars_untouched": True,
            "production_mutated": production_mutated,
        },
        "start_application_not_started_expected": True,
    }
    (EXP / "pass44_production_probation_registration_apply.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b) -> str:
        return "yes" if b else "no"

    md = [
        "# PASS 44 — Part C: production probation registration (key-scoped)", "",
        "> Same idempotent, gated, fail-closed transaction as Pass-43 Part D, but with "
        "a KEY-SCOPED push (only the rewritten ledger/pool/projection keys are uploaded "
        "and verified; the ~950 unchanged game sidecars are preserved verbatim via the "
        "already-verified remote manifest entries). NO upload-to-Kaggle, NO submit, NO "
        "promotion, NO protected-status mutation, NO sidecar/tarball/ root mutation.", "",
        f"- Part C case: `{case}`",
        f"- safe to apply (Part C): **{yn(safe_to_apply)}**  root safe (Part A): "
        f"**{yn(root_safe)}**  --apply: **{yn(apply_flag)}**",
        f"- **apply skipped: {yn(out['apply_skipped'])}**"
        + (f" — {skip_reason}" if skip_reason else ""),
        f"- **production mutated: {yn(production_mutated)}**",
        "",
        "## Targets",
        "",
        "| candidate | events captured (local) | local registration present |",
        "|---|---|---|",
    ]
    for gid in target_ids:
        w = would_register[gid]
        md.append(f"| `{gid}` | {w['events_captured']} | "
                  f"{yn(w['registration_present_local'])} |")
    if apply_result is not None:
        md += ["", "## Apply result", "",
               f"```json\n{json.dumps(apply_result, indent=2)}\n```"]
    (EXP / "pass44_production_probation_registration_apply.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass44 registration(keyscoped): apply_skipped={out['apply_skipped']} "
          f"safe_to_apply={safe_to_apply} root_safe={root_safe} "
          f"apply_flag={apply_flag} targets={len(target_ids)} "
          f"mutated={production_mutated} "
          f"reason={skip_reason} "
          f"result={None if not apply_result else {k: apply_result.get(k) for k in ('applied','status','uploaded_count','verify_ok','manifest_event_count','pool_count_before','pool_count_after')}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
