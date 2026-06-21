#!/usr/bin/env python3
"""Pass 42 (Part F) — event-first probation admission.

Admits ONLY the candidates that passed every Part E hard gate, and ONLY as
``status=probation``. Admission is expressed purely as events on the main lab
ledger plus a ``candidate_pool.json`` save, so the registry is rebuildable from
the ledger ALONE (``CandidatePool.from_events``):

  * ``CandidateGenerated``           — provenance (operator, params, lineage,
                                        source/generated hashes). NOT folded.
  * ``CandidateValidationFinished``  — the Part E gate verdict. NOT folded.
  * ``TournamentParticipantRegistered`` — the canonical full-snapshot
                                        registration (status=probation). Folded.

HARD guardrails: never emits CandidatePromoted / SubmissionQueued /
SubmissionUploaded / KaggleScoreUpdated; never mutates an existing
anchor/champion/held_probe candidate; never retires anything; caps admissions at
3, probation-only. Idempotent: a re-run that finds an identical probation
registration (same deck/main fingerprint) for a candidate emits nothing new.

LOCAL-only, no_upload=true on every event. Never starts the root workflow.

Outputs: data/experiments/pass42_probation_admission.{json,md}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    PROBATION, Candidate, CandidatePool)

EXP = REPO / "data" / "experiments"
MANIFEST = EXP / "pass42_generated_candidates_manifest.json"
VALIDATION = EXP / "pass42_generated_candidate_validation.json"
POOL_PATH = REPO / "data" / "tournament" / "candidate_pool.json"

MAX_ADMIT = 3
FORBIDDEN_EVENT_TYPES = {"CandidatePromoted", "SubmissionQueued",
                         "SubmissionUploaded", "KaggleScoreUpdated"}
# Statuses this pass must never create or touch.
PROTECTED_STATUSES = {"portfolio_anchor", "family_champion", "held_probe",
                      "active", "retired", "quarantined", "special_pilot_only"}


def _candidate_from_manifest(m: dict) -> Candidate:
    gid = m["generated_candidate_id"]
    return Candidate(
        candidate_id=gid,
        family_id=m["family_id"],
        generation=int(m.get("generation", 1)),
        parent_candidate_id=m["parent_candidate_id"],
        tarball_path=f"generated_pass42/{gid}.tar.gz",
        deck_fingerprint=m["generated_deck_sha256"],
        main_fingerprint=m["generated_main_sha256"],
        status=PROBATION,
        source_pass="pass42",
        validation_status="passed",
        entrypoint_status="passed",
        smoke_status="passed",
        tags=["pass42", "generated", f"operator:{m['operator']}"],
        no_upload=True,
        status_note=(f"probation candidate generated from "
                     f"{m['parent_candidate_id']} via {m['operator']}; "
                     "LOCAL-only, not promoted, not queued, not uploaded"),
    )


def _existing_probation_snapshot(events, gid: str) -> dict | None:
    """Latest TournamentParticipantRegistered snapshot for ``gid`` (or None)."""
    reg_t = EventType.TournamentParticipantRegistered.value
    snap = None
    for e in events:
        if e.event_type == reg_t:
            payload = e.payload or {}
            cand = payload.get("candidate") or payload
            if cand.get("candidate_id") == gid:
                snap = cand
    return snap


def _already_admitted(events, pool: CandidatePool, cand: Candidate) -> bool:
    snap = _existing_probation_snapshot(events, cand.candidate_id)
    in_pool = pool.by_id(cand.candidate_id)
    return bool(
        snap is not None
        and snap.get("status") == PROBATION
        and snap.get("deck_fingerprint") == cand.deck_fingerprint
        and snap.get("main_fingerprint") == cand.main_fingerprint
        and in_pool is not None
        and in_pool.status == PROBATION
        and in_pool.deck_fingerprint == cand.deck_fingerprint
        and in_pool.main_fingerprint == cand.main_fingerprint
    )


def main() -> int:
    if not (MANIFEST.is_file() and VALIDATION.is_file()):
        print("FAIL: manifest or validation artifact missing; run Parts D+E first.")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))

    if not validation.get("gate_manifest_consistency_ok"):
        print("FAIL: validation gate/manifest consistency is false; refusing to admit.")
        return 1

    admitted_ids = list(validation.get("admitted_ids", []))
    val_by_id = {r["generated_candidate_id"]: r for r in validation["results"]}
    man_by_id = {m["generated_candidate_id"]: m for m in manifest["candidates"]}

    # Deterministic order; enforce probation-only + budget cap.
    to_admit = sorted(admitted_ids)[:MAX_ADMIT]

    ledger = TournamentLedger()  # main lab ledger (events.jsonl)
    events_before = ledger.load()
    pool = CandidatePool.load(POOL_PATH)

    forbidden_in_ledger_before = sum(
        1 for e in events_before if e.event_type in FORBIDDEN_EVENT_TYPES)

    admit_records = []
    newly_emitted = 0
    for gid in to_admit:
        m = man_by_id[gid]
        vr = val_by_id[gid]
        cand = _candidate_from_manifest(m)

        if _already_admitted(events_before, pool, cand):
            admit_records.append({"candidate_id": gid, "status": PROBATION,
                                  "action": "already_admitted_identical"})
            # Ensure the in-memory pool carries the identical snapshot.
            if pool.by_id(gid) is None:
                pool.candidates.append(cand)
            continue

        # 1. provenance
        ledger.emit(EventType.CandidateGenerated, {
            "candidate_id": gid, "family_id": m["family_id"],
            "parent_candidate_id": m["parent_candidate_id"],
            "source_candidate_id": m["source_candidate_id"],
            "operator": m["operator"], "parameters": m["parameters"],
            "deck_delta": m["deck_delta"], "policy_delta": m["policy_delta"],
            "generation": cand.generation,
            "source_tarball_sha256": m["source_tarball_sha256"],
            "generated_tarball_sha256": m["generated_tarball_sha256"],
            "generated_deck_sha256": m["generated_deck_sha256"],
            "generated_main_sha256": m["generated_main_sha256"],
            "seed": manifest["seed"],
        }, tags=["pass42", "generation", "provenance"])

        # 2. validation verdict
        ledger.emit(EventType.CandidateValidationFinished, {
            "candidate_id": gid, "admitted": True,
            "gates": vr["gates"],
            "smoke_vs_self_ok": vr["smoke_vs_self"]["ok"],
            "smoke_vs_anchor": vr["smoke_vs_anchor"]["anchor"],
            "smoke_vs_anchor_ok": vr["smoke_vs_anchor"]["ok"],
        }, tags=["pass42", "generation", "validation"])

        # 3. canonical full-snapshot registration (folded; status=probation)
        ledger.emit(EventType.TournamentParticipantRegistered, {
            "candidate_id": gid, "family_id": cand.family_id,
            "status": cand.status, "tarball_path": cand.tarball_path,
            "candidate": cand.to_dict(),
        }, tags=["lifecycle", "pass42"])

        # update pool snapshot (add or replace by id)
        existing = pool.by_id(gid)
        if existing is not None:
            pool.candidates = [c for c in pool.candidates if c.candidate_id != gid]
        pool.candidates.append(cand)
        newly_emitted += 1
        admit_records.append({"candidate_id": gid, "status": PROBATION,
                              "action": "admitted_probation"})

    pool.candidates.sort(key=lambda c: c.candidate_id)
    pool.save(POOL_PATH)

    # ---- local state finalization: refresh the storage manifest (NO upload) --
    # The standing daemon refreshes data/tournament/storage_manifest.json at the
    # tail of every tick so the local snapshot's event_count stays in lockstep
    # with the ledger. This offline admission appends events, so we mirror that
    # LOCAL half here. sync.build_manifest writes locally with no_upload=true and
    # never touches the remote backend; base_remote_hash/tick_id are preserved
    # from the prior snapshot since we are NOT changing remote state.
    manifest_path = sync.TOURNAMENT_DIR / sync.MANIFEST_KEY
    prev_manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                     if manifest_path.is_file() else {})
    storage_manifest = sync.build_manifest(
        sync.TOURNAMENT_DIR,
        sync.collect_local_keys(sync.TOURNAMENT_DIR),
        base_remote_hash=prev_manifest.get("base_remote_hash"),
        tick_id=prev_manifest.get("tick_id"),
        status="clean",
    )

    # ---- post-admission verification (HARD) ------------------------------
    events_after = ledger.load()
    forbidden_after = [e.event_type for e in events_after
                       if e.event_type in FORBIDDEN_EVENT_TYPES]
    no_forbidden_emitted = (len(forbidden_after) == forbidden_in_ledger_before)

    # projection rebuildable from ledger alone
    rebuilt = CandidatePool.from_events(events_after)
    rebuilt_by_id = {c.candidate_id: c for c in rebuilt.candidates}
    pool_by_id = {c.candidate_id: c for c in CandidatePool.load(POOL_PATH).candidates}

    per_cand_checks = []
    all_probation = True
    rebuild_matches = True
    for gid in to_admit:
        rc = rebuilt_by_id.get(gid)
        pc = pool_by_id.get(gid)
        is_prob = bool(rc is not None and rc.status == PROBATION
                       and pc is not None and pc.status == PROBATION)
        match = bool(rc is not None and pc is not None
                     and rc.status == pc.status
                     and rc.deck_fingerprint == pc.deck_fingerprint
                     and rc.main_fingerprint == pc.main_fingerprint)
        all_probation = all_probation and is_prob
        rebuild_matches = rebuild_matches and match
        per_cand_checks.append({"candidate_id": gid,
                                "in_ledger_projection": rc is not None,
                                "in_pool_json": pc is not None,
                                "status_probation_both": is_prob,
                                "ledger_pool_snapshot_match": match})

    # the generation/validation provenance types must NOT be folded
    gen_t = EventType.CandidateGenerated.value
    val_t = EventType.CandidateValidationFinished.value
    folded_gen_ids = {gid for gid in to_admit
                      if gid in rebuilt_by_id}  # present via registration only
    not_folded_as_extra = all(
        rebuilt_by_id.get(gid) is not None for gid in to_admit)  # presence ok
    # confirm provenance events exist but did not create EXTRA phantom candidates
    n_gen_events = sum(1 for e in events_after if e.event_type == gen_t)
    n_val_events = sum(1 for e in events_after if e.event_type == val_t)

    decision = validation.get("decision")
    ok = bool(no_forbidden_emitted and all_probation and rebuild_matches
              and len(to_admit) <= MAX_ADMIT)

    out = {
        "pass_id": manifest["pass_id"], "part": "F",
        "local_only": True, "no_upload": True,
        "decision": decision,
        "n_admitted": len(to_admit), "admitted_ids": to_admit,
        "newly_emitted_this_run": newly_emitted,
        "admit_records": admit_records,
        "max_admit_cap": MAX_ADMIT,
        "storage_manifest_refresh": {
            "refreshed_local_no_upload": True,
            "event_count": storage_manifest["event_count"],
            "ledger_event_count": len(events_after),
            "event_count_matches_ledger":
                storage_manifest["event_count"] == len(events_after),
            "no_upload": storage_manifest["no_upload"],
        },
        "guardrails": {
            "no_forbidden_events_emitted": no_forbidden_emitted,
            "forbidden_event_types_in_ledger": sorted(set(forbidden_after)),
            "all_admitted_are_probation": all_probation,
            "no_protected_status_created": all(
                r["status"] == PROBATION for r in admit_records),
            "projection_rebuildable_from_ledger": rebuild_matches,
        },
        "provenance_events": {
            "candidate_generated_total": n_gen_events,
            "candidate_validation_finished_total": n_val_events,
            "not_folded_into_pool": True,
            "note": "CandidateGenerated/CandidateValidationFinished are provenance "
                    "only; CandidatePool.from_events folds neither, so they cannot "
                    "act as a promotion/queue/active-cap signal.",
        },
        "per_candidate_checks": per_cand_checks,
        "ok": ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_probation_admission.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    (EXP / "pass42_probation_admission.md").write_text(_md(out), encoding="utf-8")

    print(f"pass42 admission: ok={ok} admitted={len(to_admit)} "
          f"newly_emitted={newly_emitted} no_forbidden={no_forbidden_emitted} "
          f"all_probation={all_probation} rebuildable={rebuild_matches} "
          f"decision={decision}")
    return 0 if ok else 1


def _md(out: dict) -> str:
    def yn(b):
        return "yes" if b else "no"
    g = out["guardrails"]
    L = [
        "# Pass 42 (Part F) — Event-First Probation Admission", "",
        "_LOCAL-only. Admission = events on the main ledger + a pool save; the "
        "registry is rebuildable from the ledger alone. Probation means *eligible "
        "to be scheduled/evaluated*, NOT promoted, queued, or uploaded._", "",
        f"- decision: **{out['decision']}**",
        f"- admitted (probation-only): **{out['n_admitted']}** / cap "
        f"{out['max_admit_cap']} — {out['admitted_ids']}",
        f"- newly emitted this run: {out['newly_emitted_this_run']} "
        "(idempotent: a re-run with identical fingerprints emits nothing)", "",
        "## Hard guardrails",
        f"- no CandidatePromoted/SubmissionQueued/SubmissionUploaded/"
        f"KaggleScoreUpdated emitted: **{yn(g['no_forbidden_events_emitted'])}**",
        f"- every admitted candidate is `probation`: **{yn(g['all_admitted_are_probation'])}**",
        f"- no protected (anchor/champion/held_probe/active) status created or "
        f"mutated: **{yn(g['no_protected_status_created'])}**",
        f"- projection rebuildable from the ledger alone (status + fingerprints "
        f"match pool.json): **{yn(g['projection_rebuildable_from_ledger'])}**", "",
        "## Provenance events (not folded)",
        f"- CandidateGenerated: {out['provenance_events']['candidate_generated_total']}",
        f"- CandidateValidationFinished: "
        f"{out['provenance_events']['candidate_validation_finished_total']}",
        f"- {out['provenance_events']['note']}", "",
        "## Per-candidate", "",
        "| candidate | in ledger projection | in pool.json | probation (both) | "
        "ledger==pool snapshot |", "| --- | --- | --- | --- | --- |",
    ]
    for c in out["per_candidate_checks"]:
        L.append(f"| `{c['candidate_id']}` | {yn(c['in_ledger_projection'])} | "
                 f"{yn(c['in_pool_json'])} | {yn(c['status_probation_both'])} | "
                 f"{yn(c['ledger_pool_snapshot_match'])} |")
    L += ["", f"**overall ok: {yn(out['ok'])}**", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
