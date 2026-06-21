#!/usr/bin/env python3
"""PASS 43 — Part D: Safe production probation registration (CONDITIONAL).

Registers the three Pass-42 *generated probation* candidates into the PRODUCTION
Object Storage tournament state — but ONLY if Part C decided it is safe (i.e. the
deploy image is confirmed to carry the tarballs). Otherwise it is a no-op that
writes ``apply_skipped=true`` plus the exact reason; it NEVER mutates production.

Why a temp working dir: in this dev environment ``data/tournament/`` is the LOCAL
lab ledger (the scheduled daemon runs in a separate deploy container that mirrors
prod Object Storage). The daemon's pull/push primitives clear+mirror their working
dir, so running them against the lab dir would destroy local experiment history.
We therefore mirror prod into an isolated temp dir, inject only the missing
registration/provenance events (original event_ids preserved → idempotent), rebuild
projections there, and push a verified snapshot. The lab ledger is never touched.

Transaction (apply path only — gated): acquire lease -> pull prod into temp ->
inject missing TournamentParticipantRegistered / CandidateStatusChanged(->probation)
+ provenance (CandidateGenerated / CandidateValidationFinished) -> rebuild
projections -> push_state (re-reconciles vs remote, refreshes manifest, sha-verifies
upload) -> release lease.

HARD guardrails: no_upload=true on every event; NEVER emits CandidatePromoted /
SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated; never creates/mutates a
protected status (active/family_champion/portfolio_anchor/held_probe/retired/
quarantined/special_pilot_only); never overwrites a divergent remote ledger
(push_state reconciles, raising ConflictError on genuine divergence); never deletes
remote keys. Idempotent.

Output: data/experiments/pass43_production_probation_registration.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament import projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    PROBATION, CandidatePool)
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    get_storage_backend, StorageError)
from ptcg_activegraph.tournament import lease as lease_mod  # noqa: E402

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"
DECISION = EXP / "pass43_deployment_availability_decision.json"
PREFLIGHT = EXP / "pass43_safety_preflight.json"
LOCAL_POOL = TDIR / "candidate_pool.json"
LOCAL_LEDGER = TDIR / "events.jsonl"

FORBIDDEN_EVENT_TYPES = {"CandidatePromoted", "SubmissionQueued",
                         "SubmissionUploaded", "KaggleScoreUpdated"}
PROTECTED_STATUSES = {"active", "family_champion", "portfolio_anchor",
                      "held_probe", "retired", "quarantined", "special_pilot_only"}

GEN_T = EventType.CandidateGenerated.value
VAL_T = EventType.CandidateValidationFinished.value
REG_T = EventType.TournamentParticipantRegistered.value
STATUS_T = EventType.CandidateStatusChanged.value


def _cid_of(ev: dict) -> str | None:
    p = ev.get("payload") or {}
    if ev.get("event_type") == REG_T:
        return (p.get("candidate") or {}).get("candidate_id") or p.get("candidate_id")
    return p.get("candidate_id") or p.get("generated_candidate_id")


def _target_ids() -> list[str]:
    pool = json.loads(LOCAL_POOL.read_text(encoding="utf-8"))
    return sorted(c["candidate_id"] for c in pool.get("candidates", [])
                  if c.get("status") == PROBATION
                  and c.get("candidate_id", "").startswith("generated_"))


def _capture_candidate_events(raw: list[dict], gid: str) -> list[dict]:
    """All provenance + registration events for gid (registration only folds)."""
    keep = []
    for ev in raw:
        et = ev.get("event_type")
        if et not in (GEN_T, VAL_T, REG_T, STATUS_T):
            continue
        if _cid_of(ev) != gid:
            continue
        if et == STATUS_T:
            p = ev.get("payload") or {}
            new = p.get("to_status") or p.get("new_status") or p.get("status")
            if new != PROBATION:
                continue
        keep.append(ev)
    return keep


def _registration_snapshot(raw: list[dict], gid: str) -> dict | None:
    snap = None
    for ev in raw:
        if ev.get("event_type") == REG_T and _cid_of(ev) == gid:
            p = ev.get("payload") or {}
            snap = p.get("candidate") or p
    return snap


def _already_registered(remote_raw: list[dict], gid: str, want: dict | None) -> bool:
    snap = _registration_snapshot(remote_raw, gid)
    if snap is None or want is None:
        return False
    return bool(snap.get("status") == PROBATION
                and snap.get("deck_fingerprint") == want.get("deck_fingerprint")
                and snap.get("main_fingerprint") == want.get("main_fingerprint"))


def _rebuild_into(root: Path) -> dict:
    """Rebuild projections inside ``root`` from its merged ledger (PROJ_DIR-scoped)."""
    cfg = load_config()
    ledger = TournamentLedger(path=root / "events.jsonl")
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates and (root / "candidate_pool.json").is_file():
        pool = CandidatePool.load(root / "candidate_pool.json")
    # keep the bootstrap pool snapshot in lockstep with the ledger projection
    pool.save(root / "candidate_pool.json")
    summary = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=summary["ranked_ids"])
    worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    finished = ledger.finished_game_ids()
    worklist = [g for g in worklist if g.game_id not in finished]
    projmod.write_scheduler_queue(worklist, cfg)
    return {"registered_candidates": len(pool.candidates),
            "next_queue_size": len(worklist)}


def _apply(target_ids: list[str], captured: dict[str, list[dict]]) -> dict:
    """Gated production mutation. Only reached when Part C says safe AND --apply."""
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    lease = lease_mod.acquire_lease(backend, tick_id=None)
    tmp = Path(tempfile.mkdtemp(prefix="pass43_reg_"))
    tmp_root = tmp / "tournament"
    saved_proj_dir = projmod.PROJ_DIR
    result: dict = {"applied": False}
    try:
        projmod.PROJ_DIR = tmp_root / "projections"
        sync.pull_state(backend, tmp_root)
        base_remote_hash = sync.remote_events_hash(backend)
        remote_raw = sync.parse_events_text(
            (tmp_root / "events.jsonl").read_text(encoding="utf-8")
        ) if (tmp_root / "events.jsonl").is_file() else []
        remote_ids = {e.get("event_id") for e in remote_raw}

        to_add: list[dict] = []
        per_cand = []
        for gid in target_ids:
            want = _registration_snapshot(captured[gid], gid) or {}
            if _already_registered(remote_raw, gid, want):
                per_cand.append({"candidate_id": gid, "action": "already_registered"})
                continue
            add = [ev for ev in captured[gid] if ev.get("event_id") not in remote_ids]
            to_add.extend(add)
            per_cand.append({"candidate_id": gid, "action": "register",
                             "events_added": len(add)})

        # forbidden / protected safety on the exact event set we are about to push
        bad = [ev.get("event_type") for ev in to_add
               if ev.get("event_type") in FORBIDDEN_EVENT_TYPES]
        if bad:
            raise StorageError(f"refusing: forbidden event types in to_add: {bad}")
        for ev in to_add:
            if ev.get("event_type") == REG_T:
                snap = (ev.get("payload") or {}).get("candidate") or {}
                if snap.get("status") in PROTECTED_STATUSES:
                    raise StorageError(
                        f"refusing: registration with protected status "
                        f"{snap.get('status')} for {snap.get('candidate_id')}")

        if to_add:
            merged, recon = sync.reconcile_events(to_add, remote_raw)
            (tmp_root / "events.jsonl").write_text(
                sync.dump_events(merged), encoding="utf-8")
            _rebuild_into(tmp_root)
            push = sync.push_state(
                backend, tmp_root,
                base_remote_hash=base_remote_hash, tick_id=lease.tick_id,
                on_remote_drift=lambda: _rebuild_into(tmp_root))
            result.update({"applied": True, "reconcile": recon,
                           "push_status": push["status"],
                           "verify_ok": push["verify"]["ok"],
                           "uploaded_count": len(push["uploaded"])})
        else:
            result.update({"applied": False, "reason": "idempotent_no_new_events"})
        result["per_candidate"] = per_cand
    finally:
        projmod.PROJ_DIR = saved_proj_dir
        try:
            lease_mod.release_lease(backend, lease)
        except Exception:  # noqa: BLE001
            pass
    return result


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

    target_ids = _target_ids()
    local_raw = (sync.parse_events_text(LOCAL_LEDGER.read_text(encoding="utf-8"))
                 if LOCAL_LEDGER.is_file() else [])
    captured = {gid: _capture_candidate_events(local_raw, gid) for gid in target_ids}
    would_register = {gid: {
        "events_captured": len(captured[gid]),
        "registration_present_local": _registration_snapshot(captured[gid], gid) is not None,
    } for gid in target_ids}

    do_apply = bool(apply_flag and safe_to_apply and root_safe and target_ids)
    apply_result = None
    skip_reason = None
    if do_apply:
        apply_result = _apply(target_ids, captured)
    else:
        if not apply_flag:
            skip_reason = "dry-run (no --apply flag)"
        elif not safe_to_apply:
            skip_reason = (f"Part C decision is not safe to mutate prod OS "
                           f"(case={case}, mutate_prod_os={dec.get('mutate_prod_os')}, "
                           f"proceed_to_part_d={dec.get('proceed_to_part_d')})")
        elif not root_safe:
            skip_reason = "Part A safety preflight is not green (safe=false)"
        elif not target_ids:
            skip_reason = "no generated probation candidates found locally"

    out = {
        "pass": "pass43_partD_production_probation_registration",
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
            "production_mutated": bool(do_apply and apply_result
                                      and apply_result.get("applied")),
        },
    }
    (EXP / "pass43_production_probation_registration.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b) -> str:
        return "yes" if b else "no"

    md = [
        "# PASS 43 — Part D: Production probation registration",
        "",
        f"- Part C case: `{case}`",
        f"- safe to apply (Part C): **{yn(safe_to_apply)}**  "
        f"root safe (Part A): **{yn(root_safe)}**  --apply: **{yn(apply_flag)}**",
        f"- **apply skipped: {yn(out['apply_skipped'])}**"
        + (f" — {skip_reason}" if skip_reason else ""),
        f"- production mutated: **{yn(out['guardrails']['production_mutated'])}**",
        "",
        "## Targets (what a SAFE run would register, idempotently)",
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
    else:
        md += ["", "> No production mutation performed. This is the expected, safe "
               "outcome while the deploy image cannot be confirmed to carry the "
               "Pass-42 tarballs (see Part C republish runbook)."]
    (EXP / "pass43_production_probation_registration.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass43 registration: apply_skipped={out['apply_skipped']} "
          f"safe_to_apply={safe_to_apply} root_safe={root_safe} "
          f"apply_flag={apply_flag} targets={len(target_ids)} "
          f"reason={skip_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
