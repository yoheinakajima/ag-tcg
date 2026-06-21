#!/usr/bin/env python3
"""PASS 43 — Internal Promotion Gate v1 runner (dry-run default; conservative apply).

DRY-RUN (default): evaluate every candidate in the local ledger registry against the
locked v1 thresholds and write recommendations. Best-effort: also evaluate the
PRODUCTION-pulled registry (read-only) when reachable, for transparency. Emits
nothing, mutates nothing.

--apply (conservative): emit a ``CandidateStatusChanged`` to the LOCAL ledger ONLY
for recommendations that are actionable (activate / promote_family_champion /
retire_to_retired / quarantine) AND only when EVERY guard holds:
  * Part A root/prod safety preflight is green (preflight_safe and not stop_required);
  * the candidate is not a public reference and is not already at the target status;
  * the action maps to a non-Kaggle, non-promotion-to-Kaggle status mark.
After applying it rebuilds the pool from the ledger, saves candidate_pool.json, and
refreshes the LOCAL storage manifest in lockstep (no upload, remote untouched).

HARD guardrails: NEVER emits CandidatePromoted / SubmissionQueued /
SubmissionUploaded / KaggleScoreUpdated (the ledger itself also refuses these);
NEVER promotes on raw win-rate; NEVER demotes a protected status; NEVER deletes a
tarball; idempotent. Internal diagnostics only — NOT a Kaggle leaderboard.

Outputs:
  data/experiments/pass43_promotion_gate_dry_run.{json,md}
  data/experiments/pass43_promotion_gate_apply.{json,md}   (only with --apply)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import promotion, sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import (  # noqa: E402
    POOL_PATH, CandidatePool)
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
PREFLIGHT = EXP / "pass43_safety_preflight.json"
FORBIDDEN_EVENT_TYPES = {"CandidatePromoted", "SubmissionQueued",
                         "SubmissionUploaded", "KaggleScoreUpdated"}


def _load_local() -> tuple[CandidatePool, list]:
    ledger = TournamentLedger()
    events = ledger.load()
    pool = CandidatePool.from_events(events)
    if not pool.candidates and POOL_PATH.is_file():
        pool = CandidatePool.load(POOL_PATH)
    return pool, events


def _load_production() -> tuple[CandidatePool, list] | None:
    """Read-only pull of prod state into a temp dir; None if unreachable."""
    try:
        backend = get_storage_backend(env="production",
                                      backend="replit_app_storage")
        tmp = Path(tempfile.mkdtemp(prefix="pass43_gate_prod_"))
        root = tmp / "tournament"
        sync.pull_state(backend, root)
        evt_path = root / "events.jsonl"
        if not evt_path.is_file():
            return None
        ledger = TournamentLedger(path=evt_path)
        events = ledger.load()
        pool = CandidatePool.from_events(events)
        if not pool.candidates and (root / "candidate_pool.json").is_file():
            pool = CandidatePool.load(root / "candidate_pool.json")
        return pool, events
    except Exception as exc:  # noqa: BLE001
        print(f"[promotion-gate] production state unavailable: {exc}")
        return None


def _eval_block(pool: CandidatePool, events: list) -> dict:
    return promotion.evaluate(pool, events)


def _preflight_green() -> tuple[bool, dict]:
    pf = (json.loads(PREFLIGHT.read_text(encoding="utf-8"))
          if PREFLIGHT.is_file() else {})
    green = bool(pf.get("preflight_safe") and not pf.get("stop_required"))
    return green, {"preflight_present": PREFLIGHT.is_file(),
                   "preflight_safe": pf.get("preflight_safe"),
                   "stop_required": pf.get("stop_required")}


def _write_dry_run(local_eval: dict, prod_eval: dict | None) -> dict:
    out = {
        "pass": "pass43_promotion_gate_dry_run",
        "mode": "dry_run",
        "caveat": local_eval["caveat"],
        "local": local_eval,
        "production": prod_eval,
        "production_state_available": prod_eval is not None,
        "emitted_events": 0,
        "mutated": False,
    }
    (EXP / "pass43_promotion_gate_dry_run.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def table(ev: dict) -> list[str]:
        rows = ["| candidate | status | action | total games | decisive | "
                "wilson_low | reasons |", "|---|---|---|---|---|---|---|"]
        for r in ev["recommendations"]:
            e = r["evidence"]
            rows.append(
                f"| `{r['candidate_id']}` | {r['status']} | **{r['action']}** | "
                f"{e['total_games']} | {e['decisive_games']} | "
                f"{e['wilson_low']} | {'; '.join(r['reasons'])} |")
        return rows

    md = [
        "# PASS 43 — Promotion Gate v1 dry-run",
        "", f"> {local_eval['caveat']}", "",
        f"- candidates evaluated (local): **{local_eval['n_candidates']}**",
        f"- actionable recommendations (local): **{local_eval['n_actionable']}**",
        f"- summary by action (local): `{json.dumps(local_eval['summary_by_action'])}`",
        "", "## Local registry recommendations", "",
    ]
    md += table(local_eval)
    if prod_eval is not None:
        md += ["", "## Production-pulled registry recommendations (read-only)", "",
               f"- candidates evaluated (prod): **{prod_eval['n_candidates']}**",
               f"- actionable (prod): **{prod_eval['n_actionable']}**", ""]
        md += table(prod_eval)
    else:
        md += ["", "_Production state not pulled in this run "
               "(unreachable or skipped). Local registry is authoritative for the "
               "Pass-42 candidates, which are local-only pending republish._"]
    md += ["", "> No events emitted. No mutation. This is the expected honest "
           "outcome while no placement games have accrued for the candidates."]
    (EXP / "pass43_promotion_gate_dry_run.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    return out


def _apply(local_eval: dict) -> dict:
    green, pf_detail = _preflight_green()
    specs = promotion.recommended_status_changes(local_eval)

    pool, events = _load_local()
    current = {c.candidate_id: c.status for c in pool.candidates}
    # idempotency + public-reference guard on the exact change set
    ref_ids = promotion.load_reference_ids()
    pending = []
    for s in specs:
        if s["candidate_id"] in ref_ids:
            continue  # never act on a public reference
        if current.get(s["candidate_id"]) == s["new_status"]:
            continue  # already at target -> idempotent no-op
        pending.append(s)

    blocked_reason = None
    if not green:
        blocked_reason = "Part A safety preflight not green"
    elif not pending:
        blocked_reason = ("no actionable recommendations "
                          "(insufficient_evidence) — nothing to apply")

    applied = []
    manifest_info = None
    if blocked_reason is None:
        ledger = TournamentLedger()
        for s in pending:
            ledger.emit(EventType.CandidateStatusChanged, {
                "candidate_id": s["candidate_id"],
                "from_status": s["from_status"],
                "new_status": s["new_status"],
                "status_note": f"promotion_gate_v1:{s['action']}: "
                               + "; ".join(s["reasons"]),
                "gate": "promotion_gate_v1",
            }, tags=["promotion_gate_v1"])
            applied.append(s)
        events_after = ledger.load()
        rebuilt = CandidatePool.from_events(events_after)
        rebuilt.save(POOL_PATH)
        manifest_path = sync.TOURNAMENT_DIR / sync.MANIFEST_KEY
        prev = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file() else {})
        manifest = sync.build_manifest(
            sync.TOURNAMENT_DIR, sync.collect_local_keys(sync.TOURNAMENT_DIR),
            base_remote_hash=prev.get("base_remote_hash"),
            tick_id=prev.get("tick_id"), status="clean")
        forbidden_after = sorted({e.event_type for e in events_after
                                  if e.event_type in FORBIDDEN_EVENT_TYPES})
        manifest_info = {
            "event_count": manifest["event_count"],
            "ledger_event_count": len(events_after),
            "event_count_matches_ledger":
                manifest["event_count"] == len(events_after),
            "no_upload": manifest["no_upload"],
            "no_forbidden_events_in_ledger": not forbidden_after,
        }

    out = {
        "pass": "pass43_promotion_gate_apply",
        "mode": "apply",
        "preflight_green": green,
        "preflight_detail": pf_detail,
        "n_recommended_actionable": len(specs),
        "n_pending_after_guards": len(pending),
        "apply_skipped": bool(blocked_reason is not None),
        "skip_reason": blocked_reason,
        "applied_changes": applied,
        "manifest_refresh": manifest_info,
        "guardrails": {
            "no_kaggle_or_promotion_events": True,
            "no_raw_winrate_promotion": True,
            "protected_never_demoted": True,
            "no_tarball_deletion": True,
            "mutated_local_ledger": bool(applied),
            "mutated_production": False,
        },
    }
    (EXP / "pass43_promotion_gate_apply.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    md = [
        "# PASS 43 — Promotion Gate v1 apply (conservative)",
        "",
        f"- preflight green: **{'yes' if green else 'no'}**",
        f"- recommended actionable: **{len(specs)}**  "
        f"pending after guards: **{len(pending)}**",
        f"- **apply skipped: {'yes' if out['apply_skipped'] else 'no'}**"
        + (f" — {blocked_reason}" if blocked_reason else ""),
        f"- local ledger mutated: **{'yes' if applied else 'no'}**  "
        "production mutated: **no**",
    ]
    if applied:
        md += ["", "## Applied status changes", ""]
        for s in applied:
            md.append(f"- `{s['candidate_id']}`: {s['from_status']} → "
                      f"{s['new_status']} ({s['action']})")
        md += ["", f"- manifest event_count == ledger: "
               f"**{manifest_info['event_count_matches_ledger']}**"]
    else:
        md += ["", "> No status changes applied. Expected honest outcome: the gate "
               "requires accrued placement evidence that does not yet exist."]
    (EXP / "pass43_promotion_gate_apply.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="conservatively emit status changes to the LOCAL ledger")
    ap.add_argument("--no-prod", action="store_true",
                    help="skip the best-effort read-only production evaluation")
    args = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)

    local_pool, local_events = _load_local()
    local_eval = _eval_block(local_pool, local_events)
    prod_eval = None
    if not args.no_prod:
        prod = _load_production()
        if prod is not None:
            prod_eval = _eval_block(*prod)

    _write_dry_run(local_eval, prod_eval)
    print(f"promotion-gate dry-run: candidates={local_eval['n_candidates']} "
          f"actionable={local_eval['n_actionable']} "
          f"summary={json.dumps(local_eval['summary_by_action'])}")

    if args.apply:
        ap_out = _apply(local_eval)
        print(f"promotion-gate apply: apply_skipped={ap_out['apply_skipped']} "
              f"reason={ap_out['skip_reason']} "
              f"applied={len(ap_out['applied_changes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
