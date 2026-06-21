#!/usr/bin/env python3
"""PASS 46 — internal promotion gate v1 — production evidence DRY-RUN ONLY.

Reuses the real Pass-43 promotion-gate primitives (``run_tournament_promotion_gate``
+ ``promotion``) so the decision logic is byte-identical, and evaluates BOTH the local
registry and a FAST read-only production evaluation (reads ONLY the prod ledger
``events.jsonl``, never the game sidecars). DRY-RUN ONLY: it emits nothing, mutates
nothing, and NEVER calls the gate's ``--apply`` path. No CandidateStatusChanged /
CandidatePromoted / Submission* / KaggleScoreUpdated event under any circumstance.

The expected honest outcome is insufficient_evidence for the 3 Pass-42 probation
candidates.

Output:
  data/experiments/pass46_promotion_gate_dry_run.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import run_tournament_promotion_gate as G  # noqa: E402
from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
TARGETS = {
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
}


def _fast_prod_eval():
    try:
        backend = get_storage_backend(env="production", backend="replit_app_storage")
        if not backend.exists(sync.EVENTS_KEY):
            return None
        txt = backend.read_text(sync.EVENTS_KEY)
        tmp = Path(tempfile.mkdtemp(prefix="pass46_gate_prod_")) / "events.jsonl"
        tmp.write_text(txt, encoding="utf-8")
        events = TournamentLedger(path=tmp).load()
        pool = CandidatePool.from_events(events)
        ev = G._eval_block(pool, events)
        ev["_source"] = "prod_ledger_fast_read"
        ev["_ledger_event_count"] = len(events)
        return ev
    except Exception as exc:  # noqa: BLE001
        print(f"[pass46-gate] prod fast-eval unavailable: {exc}")
        return None


def _target_rows(ev):
    rows = []
    for r in ev.get("recommendations", []):
        cid = r["candidate_id"]
        if cid in TARGETS:
            rows.append({"candidate_id": cid, "status": r["status"],
                         "action": r["action"], "actionable": r["actionable"],
                         "reasons": r["reasons"], "checks": r["checks"],
                         "evidence": r["evidence"]})
    return rows


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    local_pool, local_events = G._load_local()
    local_eval = G._eval_block(local_pool, local_events)
    prod_eval = _fast_prod_eval()

    forbidden_local = sorted({e.event_type for e in local_events
                              if e.event_type in FORBIDDEN})

    def _actions(ev):
        return ev.get("summary_by_action", {}) if ev else {}

    prod_targets = _target_rows(prod_eval) if prod_eval else []
    local_targets = _target_rows(local_eval)
    any_target_actionable = any(r["actionable"] for r in prod_targets + local_targets)

    out = {
        "pass": "pass46_promotion_gate_dry_run",
        "mode": "dry_run_only",
        "apply_invoked": False,
        "emitted_events": 0,
        "mutated": False,
        "production_mutated": False,
        "caveat": local_eval.get("caveat"),
        "local": {"n_candidates": local_eval["n_candidates"],
                  "n_actionable": local_eval["n_actionable"],
                  "summary_by_action": _actions(local_eval),
                  "target_recommendations": local_targets},
        "production": None if prod_eval is None else {
            "n_candidates": prod_eval["n_candidates"],
            "n_actionable": prod_eval["n_actionable"],
            "summary_by_action": _actions(prod_eval),
            "ledger_event_count": prod_eval.get("_ledger_event_count"),
            "target_recommendations": prod_targets},
        "production_state_available": prod_eval is not None,
        "no_forbidden_events_in_local_ledger": not forbidden_local,
        "any_target_actionable": any_target_actionable,
        "thresholds": local_eval.get("thresholds"),
        "expected": "all targets insufficient_evidence (soak placement games far "
                    "below the locked v1 sample-size minimums)",
    }
    (EXP / "pass46_promotion_gate_dry_run.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def tbl(rows):
        o = ["| candidate | status | action | total | decisive | parent H2H | "
             "anchor dec | wilson_low | reasons |",
             "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            e = r["evidence"]
            o.append(f"| `{r['candidate_id']}` | {r['status']} | **{r['action']}** | "
                     f"{e['total_games']} | {e['decisive_games']} | "
                     f"{e['parent_h2h_games']} | {e['anchor_decisive']} | "
                     f"{e['wilson_low']} | {'; '.join(r['reasons'])} |")
        return o

    md = [
        "# PASS 46 — promotion gate v1 — production DRY-RUN ONLY", "",
        f"> {local_eval.get('caveat')}", "",
        "> DRY-RUN ONLY. The gate's `--apply` path is NEVER invoked. No "
        "CandidateStatusChanged, CandidatePromoted, or Kaggle event is emitted.", "",
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
    md += ["", "## Target (Pass-42 probation) recommendations — PRODUCTION", ""]
    md += tbl(prod_targets) if prod_targets else ["_production state unavailable_"]
    md += ["", "## Target (Pass-42 probation) recommendations — LOCAL", ""]
    md += tbl(local_targets)
    md += ["", f"- any target actionable: **{'yes' if any_target_actionable else 'no'}**",
           "", "> No events emitted; no apply path entered. Expected honest outcome: "
           "insufficient_evidence — the soak has not yet accrued the sample size the "
           "locked v1 gate requires."]
    (EXP / "pass46_promotion_gate_dry_run.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass46 gate dry-run: local_actionable={local_eval['n_actionable']} "
          f"prod_actionable={None if not prod_eval else prod_eval['n_actionable']} "
          f"any_target_actionable={any_target_actionable} "
          f"forbidden_local={forbidden_local}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
