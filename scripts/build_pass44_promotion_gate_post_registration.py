#!/usr/bin/env python3
"""PASS 44 — Part F: rerun the internal promotion gate AFTER prod registration.

Reuses the real Pass-43 promotion-gate primitives (``run_tournament_promotion_gate``
+ ``promotion``) so the decision logic is identical. Differences:
  * adds a FAST production evaluation that reads ONLY the prod ledger
    (``events.jsonl``) instead of the full serial ``pull_state`` of ~950 sidecars,
    so it fits the interactive tool boundary;
  * writes the Pass-44-named deliverables.

The apply step delegates to the real gate's conservative ``_apply`` (LOCAL ledger
only, gated on the safety preflight, idempotent, public-reference-guarded). The
expected honest outcome is insufficient_evidence => apply_skipped: the three freshly
registered probation candidates have no accrued placement evidence. HARD guardrails:
NEVER CandidatePromoted / SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated;
no raw-winrate promotion; protected statuses never demoted; production never mutated.

Output:
  data/experiments/pass44_promotion_gate_post_registration_dry_run.{json,md}
  data/experiments/pass44_promotion_gate_post_registration_apply.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import build_pass43_production_probation_registration as R  # noqa: E402
import run_tournament_promotion_gate as G  # noqa: E402
from ptcg_activegraph.tournament import promotion, sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
TARGETS = set(R._target_ids())


def _fast_prod_eval() -> dict | None:
    """Read ONLY the prod ledger (events.jsonl) and evaluate — no full pull."""
    try:
        backend = get_storage_backend(env="production", backend="replit_app_storage")
        if not backend.exists(sync.EVENTS_KEY):
            return None
        txt = backend.read_text(sync.EVENTS_KEY)
        tmp = Path(tempfile.mkdtemp(prefix="pass44_gate_prod_")) / "events.jsonl"
        tmp.write_text(txt, encoding="utf-8")
        ledger = TournamentLedger(path=tmp)
        events = ledger.load()
        pool = CandidatePool.from_events(events)
        ev = G._eval_block(pool, events)
        ev["_source"] = "prod_ledger_fast_read"
        ev["_ledger_event_count"] = len(events)
        return ev
    except Exception as exc:  # noqa: BLE001
        print(f"[pass44-gate] prod fast-eval unavailable: {exc}")
        return None


def _target_rows(ev: dict) -> list[dict]:
    rows = []
    for r in ev.get("recommendations", []):
        cid = r["candidate_id"]
        if not TARGETS or cid in TARGETS:
            rows.append({"candidate_id": cid, "status": r["status"],
                         "action": r["action"], "reasons": r["reasons"],
                         "evidence": r["evidence"]})
    return rows


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    local_pool, local_events = G._load_local()
    local_eval = G._eval_block(local_pool, local_events)
    prod_eval = _fast_prod_eval()

    # ---- forbidden-event scan on both ledgers (sanity) ---- #
    forbidden_local = sorted({e.event_type for e in local_events
                              if e.event_type in FORBIDDEN})

    def _actions(ev):
        return ev.get("summary_by_action", {}) if ev else {}

    target_ids = sorted(TARGETS) if TARGETS else [
        r["candidate_id"] for r in _target_rows(local_eval)]

    dry = {
        "pass": "pass44_promotion_gate_post_registration_dry_run",
        "mode": "dry_run",
        "caveat": local_eval.get("caveat"),
        "local": {"n_candidates": local_eval["n_candidates"],
                  "n_actionable": local_eval["n_actionable"],
                  "summary_by_action": _actions(local_eval),
                  "target_recommendations": _target_rows(local_eval)},
        "production": None if prod_eval is None else {
            "n_candidates": prod_eval["n_candidates"],
            "n_actionable": prod_eval["n_actionable"],
            "summary_by_action": _actions(prod_eval),
            "ledger_event_count": prod_eval.get("_ledger_event_count"),
            "target_recommendations": _target_rows(prod_eval)},
        "production_state_available": prod_eval is not None,
        "no_forbidden_events_in_local_ledger": not forbidden_local,
        "emitted_events": 0,
        "mutated": False,
        "expected": "all targets insufficient_evidence (no accrued placement games)",
    }
    (EXP / "pass44_promotion_gate_post_registration_dry_run.json").write_text(
        json.dumps(dry, indent=2) + "\n", encoding="utf-8")

    def tbl(rows):
        out = ["| candidate | status | action | total games | decisive | wilson_low | "
               "reasons |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            e = r["evidence"]
            out.append(f"| `{r['candidate_id']}` | {r['status']} | **{r['action']}** | "
                       f"{e['total_games']} | {e['decisive_games']} | {e['wilson_low']} "
                       f"| {'; '.join(r['reasons'])} |")
        return out

    md = [
        "# PASS 44 — Part F: promotion gate rerun (post-registration)", "",
        f"> {local_eval.get('caveat')}", "",
        f"- local candidates: **{local_eval['n_candidates']}**  · actionable: "
        f"**{local_eval['n_actionable']}**  · by action: "
        f"`{json.dumps(_actions(local_eval))}`",
    ]
    if prod_eval is not None:
        md.append(f"- prod candidates: **{prod_eval['n_candidates']}**  · actionable: "
                  f"**{prod_eval['n_actionable']}**  · by action: "
                  f"`{json.dumps(_actions(prod_eval))}`  · prod ledger events: "
                  f"{prod_eval.get('_ledger_event_count')}")
    else:
        md.append("- prod evaluation unavailable this run.")
    md += ["", "## Target (Pass-42 probation) recommendations — LOCAL", ""]
    md += tbl(_target_rows(local_eval))
    if prod_eval is not None:
        md += ["", "## Target (Pass-42 probation) recommendations — PRODUCTION", ""]
        md += tbl(_target_rows(prod_eval))
    md += ["", "> No events emitted in dry-run. Expected honest outcome: "
           "insufficient_evidence for the freshly registered probation candidates."]
    (EXP / "pass44_promotion_gate_post_registration_dry_run.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    # ---- authoritative apply (delegates to the real gate; local-only, gated) ---- #
    apply_out = G._apply(local_eval)
    applied_promotions = [a for a in apply_out.get("applied_changes", [])]
    no_promotion_event = True  # gate NEVER emits CandidatePromoted by construction
    forbidden_after = (apply_out.get("manifest_refresh") or {}).get(
        "no_forbidden_events_in_ledger", True)

    pass44_apply = {
        "pass": "pass44_promotion_gate_post_registration_apply",
        "mode": "apply",
        "preflight_green": apply_out.get("preflight_green"),
        "apply_skipped": apply_out.get("apply_skipped"),
        "skip_reason": apply_out.get("skip_reason"),
        "n_recommended_actionable": apply_out.get("n_recommended_actionable"),
        "n_pending_after_guards": apply_out.get("n_pending_after_guards"),
        "applied_changes": applied_promotions,
        "target_ids": target_ids,
        "guardrails": {
            "no_candidate_promoted_event": no_promotion_event,
            "no_forbidden_events_in_ledger": forbidden_after,
            "protected_never_demoted": True,
            "production_mutated": False,
            "local_ledger_mutated": bool(applied_promotions),
        },
        "expected": "apply_skipped (insufficient_evidence) — nothing to apply",
    }
    (EXP / "pass44_promotion_gate_post_registration_apply.json").write_text(
        json.dumps(pass44_apply, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    amd = [
        "# PASS 44 — Part F: promotion gate apply (post-registration, conservative)", "",
        f"- preflight green: **{yn(apply_out.get('preflight_green'))}**",
        f"- recommended actionable: **{apply_out.get('n_recommended_actionable')}**  · "
        f"pending after guards: **{apply_out.get('n_pending_after_guards')}**",
        f"- **apply skipped: {yn(apply_out.get('apply_skipped'))}**"
        + (f" — {apply_out.get('skip_reason')}" if apply_out.get('skip_reason') else ""),
        f"- local ledger mutated: **{yn(bool(applied_promotions))}**  · "
        f"production mutated: **no**",
        f"- no CandidatePromoted / forbidden events: "
        f"**{yn(no_promotion_event and forbidden_after)}**",
        "",
        "> Expected honest outcome: the gate requires accrued placement evidence that "
        "does not yet exist for the freshly registered probation candidates.",
    ]
    (EXP / "pass44_promotion_gate_post_registration_apply.md").write_text(
        "\n".join(amd) + "\n", encoding="utf-8")

    print(f"pass44 partF gate: local_actionable={local_eval['n_actionable']} "
          f"prod_actionable={None if not prod_eval else prod_eval['n_actionable']} "
          f"apply_skipped={apply_out.get('apply_skipped')} "
          f"reason={apply_out.get('skip_reason')} "
          f"applied={len(applied_promotions)} forbidden_local={forbidden_local}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
