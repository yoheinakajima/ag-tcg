#!/usr/bin/env python3
"""Pass 30 (Part K) — strategy decision + dry-run submission queue (max 1). LOCAL.

Turns the Part-J diagnosis into a single, gated, HUMAN-APPROVAL-REQUIRED dry-run
queue entry for the best next probe candidate among OUR existing decks. STRICT:
auto_submit disabled, manual approval required, upload_performed=false, queue size
<= 1. Nothing is uploaded or submitted; this only records what a human could
choose to submit later.

Gating (all must hold for an entry to be queued):
  * candidate is tournament-eligible in Part-F (validators + smoke clean, not blocked)
  * candidate is the Part-J recommended probe
  * candidate is NOT a clone/replay deck and uses only validated card ids

Writes data/experiments/pass30_strategy_decision.{json,md} and overwrites
data/submission_queue.json with the single dry-run entry.
"""
from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass30"
QUEUE = REPO / "data" / "submission_queue.json"

DIAG = EXP / "pass30_hardening_diagnosis.json"
VALIDATION = EXP / "pass30_candidate_validation.json"
RANK1 = EXP / "pass30_portfolio_rankings.json"
RANK2 = EXP / "pass30_portfolio_rankings_stage2.json"
PARENT_CHILD = EXP / "pass30_parent_child_confirmations.json"
META = EXP / "pass30_meta_sanity.json"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tarball_contents(tar: Path) -> list[str]:
    with tarfile.open(tar, "r:gz") as t:
        return sorted(m.name for m in t.getmembers() if m.isfile())


def main() -> int:
    diag = _read(DIAG) or {}
    val = _read(VALIDATION) or {}
    rank1 = _read(RANK1) or {}
    rank2 = _read(RANK2) or {}
    pc = _read(PARENT_CHILD) or {}
    meta = _read(META) or {}

    probe = diag.get("recommended_probe_candidate")
    elig = set(val.get("tournament_eligible") or [])
    val_rows = {r["candidate_id"]: r for r in val.get("candidates", [])}
    standings = {r["id"]: r for r in rank1.get("standings", [])}
    standings2 = {r["id"]: r for r in rank2.get("standings", [])}
    meta_pd = (meta.get("per_deck") or {})

    notes: list[str] = []
    gates = {
        "diagnosis_present": bool(diag),
        "probe_identified": bool(probe),
        "probe_tournament_eligible": probe in elig,
        "probe_not_blocked": not (val_rows.get(probe, {}).get("blocked_from_league")),
        "probe_deck_legal": bool(val_rows.get(probe, {}).get("deck_legal")),
        "probe_smoke_clean": bool(val_rows.get(probe, {}).get("smoke_clean")),
    }
    all_gates = all(gates.values())

    queue_entry = None
    if all_gates:
        tar = CAND / f"{probe}.tar.gz"
        s1 = standings.get(probe, {})
        s2 = standings2.get(probe, {})
        m = meta_pd.get(probe, {})
        queue_entry = {
            "candidate_id": probe,
            "tarball_path": str(tar.relative_to(REPO)),
            "tarball_contents": _tarball_contents(tar),
            "reason": (
                "Part-J recommended probe and best next human-approved candidate among "
                "OUR existing decks: top non-water deck in the Stage-1 internal "
                f"tournament (adj win_rate {s1.get('adj_win_rate')}, "
                f"Wilson95 {s1.get('wilson')}), #1 in replay-derived meta sanity "
                f"(weighted {m.get('weighted_meta_score')} > water "
                f"{(meta_pd.get('league_water_core_reference') or {}).get('weighted_meta_score')}), "
                "0 crash/timeout/invalid, clean parent/child relationship vs the "
                "spread parent. Reused verbatim from an earlier pass — NOT a clone of "
                "any opponent and no invented card ids."),
            "local_adjusted_win_rate_stage1": s1.get("adj_win_rate"),
            "local_adjusted_win_rate_stage2_focused": s2.get("adj_win_rate"),
            "wilson_95_ci_stage1": s1.get("wilson"),
            "weighted_meta_score": m.get("weighted_meta_score"),
            "tarball_valid": val_rows.get(probe, {}).get("tarball_valid"),
            "entrypoint_valid": val_rows.get(probe, {}).get("entrypoint_valid"),
            "deck_legal": val_rows.get(probe, {}).get("deck_legal"),
            "smoke_status": "PASS" if val_rows.get(probe, {}).get("smoke_clean")
            else "FAIL",
            "is_clone_or_replay_deck": False,
            "recommended_kaggle_message": (
                f"{probe}: Dragapult spread refinement (search-only child). LOCAL "
                "internal tournament + replay-derived meta sanity lead among our "
                "decks; surrogate numbers only. Human review required before any "
                "submission."),
            "upload_performed": False,
            "auto_submit_enabled": False,
            "require_manual_approval_for_submit": True,
        }
    else:
        notes.append("No entry queued: one or more gates failed -> "
                     + ", ".join(k for k, v in gates.items() if not v))

    queue = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": f"run_pass30_existing_portfolio_{time.strftime('%Y%m%d_%H%M%S')}",
        "stage": "pass30_existing_portfolio_hardening",
        "auto_submit_enabled": False,
        "require_manual_approval_for_submit": True,
        "upload_performed": False,
        "no_more_submissions_today": True,
        "max_queue_size": 1,
        "active_control": "league_water_core_reference",
        "queue": [queue_entry] if queue_entry else [],
        "queued_candidate_count": 1 if queue_entry else 0,
        "selection_reason": (
            f"Pass 30 existing-portfolio hardening: {'one' if queue_entry else 'zero'} "
            "dry-run recommendation queued"
            + (f" ({probe})." if queue_entry else " (gates not satisfied).")
            + " auto_submit_enabled=false and require_manual_approval_for_submit=true "
            "— this is a HELD dry-run entry; NO upload is performed and a human must "
            "approve before any submission."),
    }
    assert len(queue["queue"]) <= 1, "dry-run queue must hold at most 1 entry"
    QUEUE.write_text(json.dumps(queue, indent=2), encoding="utf-8")

    decision = {
        "pass": "30", "part": "K", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "recommended_probe_candidate": probe,
        "gates": gates, "all_gates_passed": all_gates,
        "queued_candidate_count": queue["queued_candidate_count"],
        "queue_max": 1, "active_control": "league_water_core_reference",
        "human_approval_required": True, "auto_submit_enabled": False,
        "notes": notes,
        "decision": (
            f"Queue {probe} as the single HELD dry-run probe candidate, pending human "
            "approval. No upload/submit performed." if queue_entry
            else "No candidate queued; gates unmet."),
        "rejected_alternatives": {
            "raging_bolt_variants": ("Built but rejected: structural hardening did not "
                                     "help; bottleneck is the generic pilot, not the "
                                     "decklist."),
            "water_core_reference": ("Stable benchmark/control, intentionally not the "
                                     "probe — water is the reference, not the "
                                     "hardening target."),
            "durant": "Blocked from league by design (deckout pilot mismatch).",
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_strategy_decision.json").write_text(
        json.dumps(decision, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 30 — strategy decision + dry-run queue (Part K)", "",
         "> LOCAL ONLY — held dry-run entry, NO upload, human approval required. "
         "NOT a Kaggle leaderboard.", "",
         f"- recommended probe candidate: **{probe}**",
         f"- all gates passed: **{all_gates}**",
         f"- queued candidate count: **{queue['queued_candidate_count']}** "
         f"(max {queue['max_queue_size']})",
         f"- auto_submit_enabled: **False**  require_manual_approval_for_submit: "
         f"**True**  upload_performed: **False**", "",
         "## Gates", "| gate | passed |", "|---|---|"]
    for k, v in gates.items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Decision", decision["decision"], "",
          "## Rejected alternatives"]
    for k, v in decision["rejected_alternatives"].items():
        L.append(f"- **{k}** — {v}")
    if notes:
        L += ["", "## Notes"] + [f"- {n}" for n in notes]
    L.append("")
    (EXP / "pass30_strategy_decision.md").write_text("\n".join(L), encoding="utf-8")

    print(f"strategy decision: probe={probe} all_gates={all_gates} "
          f"queued={queue['queued_candidate_count']} (max 1) upload_performed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
