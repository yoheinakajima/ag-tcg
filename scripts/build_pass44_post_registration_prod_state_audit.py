#!/usr/bin/env python3
"""PASS 44 — Part D: post-registration PRODUCTION state audit (READ-ONLY).

After Part C registered the three Pass-42 probation candidates into production Object
Storage, this verifies the production snapshot is correct, consistent, and free of any
forbidden / public-reference / never-schedule contamination. It mutates NOTHING.

Hard checks (all must pass):
  * each target present in prod candidate_pool.json with status == probation;
  * each target's TournamentParticipantRegistered event present in the prod ledger;
  * each target's pool tarball_path matches the Pass-42 manifest path, and the
    git-tracked tarball bytes hash to the Pass-42 manifest sha (tarball integrity);
  * pool reconstruction from the prod ledger is deterministic and reproduces the pool;
  * scheduler queue schedules at least one probation target (probation is schedulable);
  * NO public reference id appears in the pool, the scheduler queue, or as a parent;
  * NO NEVER_SCHEDULE-status candidate (retired/quarantined/special_pilot_only/invalid)
    appears in the scheduler queue;
  * manifest event_count == ledger length; manifest key-set == live backend key-set;
  * NO forbidden events (CandidatePromoted / SubmissionQueued / SubmissionUploaded /
    KaggleScoreUpdated) anywhere in the prod ledger;
  * all three registration events carry no_upload == true.

Output: data/experiments/pass44_post_registration_prod_state_audit.{json,md}
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import build_pass43_production_probation_registration as R  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    CandidatePool, NEVER_SCHEDULE, PROBATION)
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
SUB = REPO / "data" / "submissions"
PASS42_MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
REF_MANIFEST = REPO / "data" / "reference_agents" / "reference_agent_manifest.json"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
REG_T = "TournamentParticipantRegistered"
EXTERNAL_REFERENCE_STATUS = "external_reference"


def _sha256_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _as_events(raw: list[dict]):
    return [type("E", (), {
        "event_type": e.get("event_type"),
        "payload": e.get("payload") or {},
        "timestamp": e.get("timestamp"),
        "event_id": e.get("event_id"),
    })() for e in raw]


def _pool_ids(pool: CandidatePool) -> set[str]:
    cands = pool.candidates
    vals = cands.values() if isinstance(cands, dict) else cands
    return {c.candidate_id for c in vals}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    backend = get_storage_backend(env="production", backend="replit_app_storage")

    target_ids = R._target_ids()

    raw = sync.parse_events_text(backend.read_text(sync.EVENTS_KEY))
    pool_json = json.loads(backend.read_text(sync.POOL_KEY))
    manifest = backend.get_json(sync.MANIFEST_KEY) or {}
    queue = json.loads(backend.read_text("projections/scheduler_queue.json"))

    pass42 = json.loads(PASS42_MANIFEST.read_text(encoding="utf-8"))
    p42_by_id = {c["generated_candidate_id"]: c for c in pass42.get("candidates", [])}
    ref_raw = json.loads(REF_MANIFEST.read_text(encoding="utf-8"))
    ref_list = ref_raw.get("agents") or ref_raw.get("references") or []
    ref_ids = {a.get("agent_id") for a in ref_list}

    pool_by_id = {c["candidate_id"]: c for c in pool_json.get("candidates", [])}
    pool_ids = set(pool_by_id)
    pool_statuses = {c.get("status") for c in pool_json.get("candidates", [])}

    # ledger registration index
    reg_for = {}
    for e in raw:
        if e.get("event_type") == REG_T:
            cid = ((e.get("payload") or {}).get("candidate") or {}).get("candidate_id")
            if cid:
                reg_for.setdefault(cid, []).append(e)

    # ---- per-target checks ---- #
    per_target = {}
    for gid in target_ids:
        pc = pool_by_id.get(gid)
        man = p42_by_id.get(gid, {})
        man_path = man.get("generated_tarball_path", "")  # data/submissions/...
        man_sha = man.get("generated_tarball_sha256")
        rel = man_path[len("data/submissions/"):] if man_path.startswith(
            "data/submissions/") else man_path
        local_sha = _sha256_file(SUB / rel) if rel else None
        per_target[gid] = {
            "in_prod_pool": pc is not None,
            "status_probation": bool(pc and pc.get("status") == PROBATION),
            "registration_event_present": gid in reg_for,
            "registration_event_count": len(reg_for.get(gid, [])),
            "pool_tarball_path": pc.get("tarball_path") if pc else None,
            "pool_path_matches_manifest": bool(pc and pc.get("tarball_path") == rel),
            "tarball_sha_matches_manifest": bool(
                local_sha is not None and man_sha is not None
                and local_sha == man_sha),
            "manifest_tarball_sha": man_sha,
            "local_tarball_sha": local_sha,
        }

    # ---- determinism: rebuild pool from ledger twice ---- #
    p1 = _pool_ids(CandidatePool.from_events(_as_events(raw)))
    p2 = _pool_ids(CandidatePool.from_events(_as_events(raw)))
    rebuild_deterministic = (p1 == p2)
    rebuild_matches_snapshot = (p1 == pool_ids)
    rebuild_has_targets = all(gid in p1 for gid in target_ids)

    # ---- scheduler queue analysis ---- #
    q_items = queue.get("queue", []) if isinstance(queue, dict) else (queue or [])
    queue_cids = set()
    for it in q_items:
        for k in ("candidate_a", "candidate_b"):
            v = it.get(k)
            if v:
                queue_cids.add(v)
    queue_targets = sorted(queue_cids & set(target_ids))
    never_sched_in_queue = sorted(
        cid for cid in queue_cids
        if pool_by_id.get(cid, {}).get("status") in NEVER_SCHEDULE)
    ref_in_queue = sorted(ref_ids & queue_cids)
    ref_in_pool = sorted(ref_ids & pool_ids)
    ref_as_parent = sorted(
        c["candidate_id"] for c in pool_json.get("candidates", [])
        if c.get("parent_candidate_id") in ref_ids)

    # ---- ledger / manifest integrity ---- #
    forbidden_hits = sorted({e.get("event_type") for e in raw
                             if e.get("event_type") in FORBIDDEN})
    reg_events = [e for gid in target_ids for e in reg_for.get(gid, [])]

    def _no_upload(e):
        if e.get("no_upload") is True:
            return True
        return bool((e.get("payload") or {}).get("no_upload") is True)
    reg_all_no_upload = all(_no_upload(e) for e in reg_events) if reg_events else False
    non_no_upload_total = sum(0 if _no_upload(e) else 1 for e in raw)

    man_event_count = manifest.get("event_count")
    event_count_matches = (man_event_count == len(raw))
    man_keys = {f["key"] for f in manifest.get("files", [])}
    listed = {k for k in backend.list()
              if not k.startswith(sync.LOCK_PREFIX) and k != sync.MANIFEST_KEY}
    manifest_keyset_consistent = (man_keys == listed)

    # ---- aggregate ---- #
    all_targets_ok = all(
        t["in_prod_pool"] and t["status_probation"]
        and t["registration_event_present"]
        and t["pool_path_matches_manifest"] and t["tarball_sha_matches_manifest"]
        for t in per_target.values())
    checks = {
        "all_targets_in_pool_probation_registered_tarball_ok": all_targets_ok,
        "rebuild_deterministic": rebuild_deterministic,
        "rebuild_matches_snapshot": rebuild_matches_snapshot,
        "rebuild_has_targets": rebuild_has_targets,
        "scheduler_queue_schedules_a_probation_target": len(queue_targets) > 0,
        "no_public_reference_in_queue": not ref_in_queue,
        "no_public_reference_in_pool": not ref_in_pool,
        "no_public_reference_parent": not ref_as_parent,
        "no_external_reference_status_in_pool":
            EXTERNAL_REFERENCE_STATUS not in pool_statuses,
        "no_never_schedule_in_queue": not never_sched_in_queue,
        "no_forbidden_events": not forbidden_hits,
        "registration_events_all_no_upload": reg_all_no_upload,
        "manifest_event_count_matches_ledger": event_count_matches,
        "manifest_keyset_consistent": manifest_keyset_consistent,
    }
    all_ok = all(checks.values())

    out = {
        "pass": "pass44_partD_post_registration_prod_state_audit",
        "read_only": True,
        "all_ok": all_ok,
        "checks": checks,
        "n_targets": len(target_ids),
        "target_ids": target_ids,
        "per_target": per_target,
        "ledger_event_count": len(raw),
        "manifest_event_count": man_event_count,
        "pool_count": len(pool_ids),
        "scheduler_queue_count": len(q_items),
        "scheduler_queue_targets": queue_targets,
        "never_schedule_in_queue": never_sched_in_queue,
        "public_reference_ids": sorted(ref_ids),
        "public_reference_in_queue": ref_in_queue,
        "public_reference_in_pool": ref_in_pool,
        "public_reference_as_parent": ref_as_parent,
        "forbidden_event_hits": forbidden_hits,
        "non_no_upload_event_total": non_no_upload_total,
        "start_application_not_started_expected": True,
    }
    (EXP / "pass44_post_registration_prod_state_audit.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 44 — Part D: post-registration production state audit (read-only)", "",
        f"- **all checks pass: {yn(all_ok)}**",
        f"- prod ledger events: {len(raw)}  ·  manifest event_count: {man_event_count}"
        f"  ·  pool candidates: {len(pool_ids)}  ·  scheduler queue: {len(q_items)}",
        f"- scheduler queue schedules probation targets: "
        f"{queue_targets or 'none'}",
        "",
        "## Per-target",
        "",
        "| candidate | in pool | probation | registered | path match | tarball sha match |",
        "|---|---|---|---|---|---|",
    ]
    for gid in target_ids:
        t = per_target[gid]
        md.append(f"| `{gid}` | {yn(t['in_prod_pool'])} | {yn(t['status_probation'])} | "
                  f"{yn(t['registration_event_present'])} | "
                  f"{yn(t['pool_path_matches_manifest'])} | "
                  f"{yn(t['tarball_sha_matches_manifest'])} |")
    md += ["", "## Integrity & safety checks", ""]
    for k, v in checks.items():
        md.append(f"- {k}: **{yn(v)}**")
    md += [
        "", "## Reference / never-schedule screen", "",
        f"- public references in pool: {out['public_reference_in_pool'] or 'none'}",
        f"- public references in queue: {out['public_reference_in_queue'] or 'none'}",
        f"- public references as parent: {out['public_reference_as_parent'] or 'none'}",
        f"- never-schedule statuses in queue: "
        f"{out['never_schedule_in_queue'] or 'none'}",
        f"- forbidden event types in ledger: {out['forbidden_event_hits'] or 'none'}",
    ]
    (EXP / "pass44_post_registration_prod_state_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass44 partD audit: all_ok={all_ok} "
          f"targets_ok={all_targets_ok} queue_targets={queue_targets} "
          f"ref_leak={bool(ref_in_pool or ref_in_queue or ref_as_parent)} "
          f"never_sched_in_queue={never_sched_in_queue} "
          f"forbidden={forbidden_hits} evt_count_match={event_count_matches} "
          f"keyset_consistent={manifest_keyset_consistent}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
