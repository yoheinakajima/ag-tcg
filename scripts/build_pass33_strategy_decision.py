#!/usr/bin/env python3
"""Pass 33 (Part K) — strategy decision + dry-run submission queue (max 1). LOCAL.

Turns the Pass-33 composition stress test (Parts C-J) into a single, gated,
HUMAN-APPROVAL-REQUIRED dry-run queue entry for the best next probe candidate among
OUR existing/derived decks. STRICT: auto_submit disabled, manual approval required,
upload_performed=false, queue size <= 1. Nothing is uploaded or submitted; this only
records what a human could choose to submit later.

Probe selection (derived honestly from the Pass-33 evidence):
  * water_basic_density_v1 — the composition variant that halves mulligan / no-Basic
    risk (no_basic_p 0.346 -> 0.191) while preserving the core engine. In the internal
    composition tournament it tops Stage-2 among the focused top-4 and edges the Water
    best in the replay-derived meta sanity (weighted 0.68 vs 0.6403, no collapses). Its
    head-to-head vs the Water best is a statistical TIE (child adj win_rate 0.50,
    Wilson95 [0.30, 0.70]) — i.e. no regression but not a clear win. It is therefore
    queued as a candidate_for_deeper_confirmation / future calibration probe ONLY.

Gating (all must hold for an entry to be queued):
  * candidate validators PASS (tarball + entrypoint) and NOT blocked_from_league
  * candidate smoke-clean across self + control
  * candidate tournament-eligible in Part F
  * candidate is the Part-K recommended probe
  * candidate is NOT a clone/replay deck and uses only validated card ids
  * candidate shows no major H2H regression vs the active Water control

Writes data/experiments/pass33_strategy_decision.{json,md} and overwrites
data/submission_queue.json with the single HELD dry-run entry.
"""
from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass33"
QUEUE = REPO / "data" / "submission_queue.json"

VALIDATION = EXP / "pass33_candidate_validation.json"
SMOKE = EXP / "pass33_live_smoke.json"
RANK1 = EXP / "pass33_composition_rankings.json"
RANK2 = EXP / "pass33_composition_rankings_stage2.json"
PARENT_CHILD = EXP / "pass33_parent_child_confirmations.json"
META = EXP / "pass33_meta_sanity.json"
MANIFEST = EXP / "pass33_composition_variants_manifest.json"
AUDIT = EXP / "pass33_deck_composition_audit.json"

PROBE = "water_basic_density_v1"
ACTIVE_CONTROL = "league_water_anti_disruption_pivot_v1"
WATER_REF = "league_water_core_reference"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tarball_contents(tar: Path) -> list[str]:
    with tarfile.open(tar, "r:gz") as t:
        return sorted(m.name for m in t.getmembers() if m.isfile())


def _smoke_clean(smoke: dict, cid: str) -> bool:
    row = (smoke.get("results") or {}).get(cid) or {}
    if row.get("blocked_from_league"):
        return False
    per = row.get("per_opponent") or {}
    if not per:
        return False
    return all(bool(v.get("clean")) for v in per.values())


def main() -> int:
    val = _read(VALIDATION) or {}
    smoke = _read(SMOKE) or {}
    rank1 = _read(RANK1) or {}
    rank2 = _read(RANK2) or {}
    pc = _read(PARENT_CHILD) or {}
    meta = _read(META) or {}
    manifest = _read(MANIFEST) or {}
    audit = _read(AUDIT) or {}

    vres = (val.get("results") or {}).get(PROBE) or {}
    elig = set(smoke.get("tournament_eligible") or [])
    standings = {r["id"]: r for r in rank1.get("standings", [])}
    standings2 = {r["id"]: r for r in rank2.get("standings", [])}
    meta_pd = meta.get("per_deck") or {}

    # parent/child: water_best vs density_v1
    pc_row = next((c for c in pc.get("confirmations", [])
                   if c.get("key") == "water_best__vs__density_v1"), {})
    child_wr = pc_row.get("child_adj_win_rate")
    # "no major regression": child within/above the tie band vs the control.
    no_regression = (child_wr is not None) and (child_wr >= 0.45)

    def _collapses(deck: dict) -> list[str]:
        return sorted(sf for sf, r in (deck.get("per_archetype") or {}).items()
                      if (r.get("win_rate") or 0.0) < 0.10)

    s1 = standings.get(PROBE, {})
    s2 = standings2.get(PROBE, {})
    m = meta_pd.get(PROBE, {})
    m_ctrl = meta_pd.get(ACTIVE_CONTROL, {})
    probe_collapses = _collapses(m)
    meta_supports = (
        m.get("weighted_meta_score") is not None
        and m_ctrl.get("weighted_meta_score") is not None
        and m["weighted_meta_score"] >= m_ctrl["weighted_meta_score"]
        and not probe_collapses
    )

    # tournament_strong derived from real performance, not mere presence: the probe
    # must appear in BOTH stages, post a non-losing focused (Stage-2) record, and
    # have a clean run with zero invalid/timeout games in both stages.
    s2_wr = s2.get("adj_win_rate")
    tournament_strong = (
        bool(s1) and bool(s2)
        and s2_wr is not None and s2_wr >= 0.50
        and (s1.get("invalids") or 0) == 0 and (s1.get("timeouts") or 0) == 0
        and (s2.get("invalids") or 0) == 0 and (s2.get("timeouts") or 0) == 0
    )

    # not_clone_or_invented_ids derived from evidence (manifest provenance + audit):
    #   * manifest row exists with our-own provenance (build_variant/reuse from a
    #     candidates_pass* parent) — NOT an opponent clone, and
    #   * the composition audit reports zero unknown/unverified card ids.
    mrow = next((r for r in (manifest.get("results") or [])
                 if r.get("candidate_id") == PROBE), {})
    arow = next((d for d in (audit.get("decks") or [])
                 if d.get("candidate_id") == PROBE), {})
    parent_tarball = mrow.get("parent_tarball") or ""
    own_provenance = (
        mrow.get("disposition") in {"build_variant", "existing_reuse"}
        and mrow.get("kind") in {"built", "reused"}
        and "candidates_pass" in parent_tarball
    )
    ids_verified = arow.get("unknown_card_ids") == []
    not_clone_or_invented_ids = bool(own_provenance and ids_verified)

    notes: list[str] = []
    gates = {
        "validators_passed": bool(vres.get("passed")),
        "not_blocked_from_league": not bool(vres.get("blocked_from_league")),
        "tournament_eligible": PROBE in elig,
        "smoke_clean": _smoke_clean(smoke, PROBE),
        "tournament_strong": bool(tournament_strong),
        "meta_sanity_supports": bool(meta_supports),
        "no_major_h2h_regression": bool(no_regression),
        "not_clone_or_invented_ids": not_clone_or_invented_ids,
    }
    all_gates = all(gates.values())

    queue_entry = None
    if all_gates:
        tar = CAND / f"{PROBE}.tar.gz"
        queue_entry = {
            "candidate_id": PROBE,
            "tarball_path": str(tar.relative_to(REPO)),
            "tarball_contents": _tarball_contents(tar),
            "disposition": "candidate_for_deeper_confirmation",
            "reason": (
                "Pass-33 composition stress test: best next human-approved probe "
                "among OUR decks. Halves no-Basic / mulligan risk (no_basic_p "
                "0.346 -> 0.191) while preserving the validated core engine "
                "(721/722/723/1121). Tops Stage-2 of the internal composition "
                f"tournament (adj win_rate {s2.get('adj_win_rate')}, Wilson95 "
                f"{s2.get('wilson')}) and edges the Water control in replay-derived "
                f"meta sanity (weighted {m.get('weighted_meta_score')} vs control "
                f"{m_ctrl.get('weighted_meta_score')}, 0 collapses). Head-to-head vs "
                f"the Water control is a TIE (child adj win_rate {child_wr}, Wilson95 "
                f"{pc_row.get('child_wilson')}) — no regression but not a clear win, so "
                "this is a deeper-confirmation / future calibration probe ONLY. Reused "
                "verbatim core with extra LEGAL Basics — NOT a clone of any opponent "
                "and no invented card ids."),
            "local_adjusted_win_rate_stage1": s1.get("adj_win_rate"),
            "wilson_95_ci_stage1": s1.get("wilson"),
            "local_adjusted_win_rate_stage2_focused": s2.get("adj_win_rate"),
            "wilson_95_ci_stage2": s2.get("wilson"),
            "weighted_meta_score": m.get("weighted_meta_score"),
            "weighted_meta_score_control": m_ctrl.get("weighted_meta_score"),
            "h2h_vs_control_child_win_rate": child_wr,
            "h2h_vs_control_verdict": pc_row.get("verdict", "inconclusive_tie"),
            "tarball_valid": vres.get("tarball_rc") == 0,
            "entrypoint_valid": vres.get("entrypoint_rc") == 0,
            "smoke_status": "PASS",
            "is_clone_or_replay_deck": False,
            "recommended_kaggle_message": (
                f"{PROBE}: Water core with denser Basic line (mulligan-risk "
                "reduction). LOCAL internal tournament + replay-derived meta sanity "
                "lead/tie among our decks; surrogate numbers only. Human review "
                "required before any submission."),
            "upload_performed": False,
            "auto_submit_enabled": False,
            "require_manual_approval_for_submit": True,
        }
    else:
        notes.append("No entry queued: failed gates -> "
                     + ", ".join(k for k, v in gates.items() if not v))

    queue = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": f"run_pass33_composition_stress_{time.strftime('%Y%m%d_%H%M%S')}",
        "stage": "pass33_deck_composition_stress_test",
        "auto_submit_enabled": False,
        "require_manual_approval_for_submit": True,
        "upload_performed": False,
        "no_more_submissions_today": True,
        "max_queue_size": 1,
        "active_control": ACTIVE_CONTROL,
        "decision": (
            "queue_density_v1_for_deeper_confirmation" if queue_entry
            else "keep_water_control_no_candidate_queued"),
        "queue": [queue_entry] if queue_entry else [],
        "queued_candidate_count": 1 if queue_entry else 0,
        "selection_reason": (
            f"Pass 33 composition stress test: {'one' if queue_entry else 'zero'} "
            "HELD dry-run recommendation"
            + (f" ({PROBE}) as candidate_for_deeper_confirmation." if queue_entry
               else " (gates not satisfied).")
            + " auto_submit_enabled=false and require_manual_approval_for_submit=true "
            "— NO upload is performed and a human must approve before any submission."),
    }
    assert len(queue["queue"]) <= 1, "dry-run queue must hold at most 1 entry"
    QUEUE.write_text(json.dumps(queue, indent=2), encoding="utf-8")

    decision = {
        "pass": "33", "part": "K", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "recommended_probe_candidate": PROBE,
        "disposition": "candidate_for_deeper_confirmation",
        "gates": gates, "all_gates_passed": all_gates,
        "queued_candidate_count": queue["queued_candidate_count"],
        "queue_max": 1, "active_control": ACTIVE_CONTROL,
        "human_approval_required": True, "auto_submit_enabled": False,
        "evidence": {
            "stage1_adj_win_rate": s1.get("adj_win_rate"),
            "stage1_wilson": s1.get("wilson"),
            "stage2_adj_win_rate": s2.get("adj_win_rate"),
            "stage2_wilson": s2.get("wilson"),
            "weighted_meta_score": m.get("weighted_meta_score"),
            "weighted_meta_score_control": m_ctrl.get("weighted_meta_score"),
            "h2h_vs_control_child_win_rate": child_wr,
            "h2h_vs_control_wilson": pc_row.get("child_wilson"),
        },
        "decision_labels": {
            "build_water_basic_density_next": "DONE (built v1/v2 in Part E)",
            "keep_water_as_reference": True,
            "future_kaggle_probe_candidate": PROBE,
            "candidate_for_deeper_confirmation": PROBE,
            "dragapult_above_water": False,
        },
        "notes": notes,
        "decision": (
            f"Queue {PROBE} as the single HELD dry-run probe candidate "
            "(candidate_for_deeper_confirmation), pending human approval. No "
            "upload/submit performed." if queue_entry
            else "No candidate queued; gates unmet. Keep Water control."),
        "rejected_alternatives": {
            "water_basic_density_v2": ("Built but not the probe: deeper Basic line "
                                       "(16 Basics) under-performs v1 H2H "
                                       "(parent_better) — over-dilutes the engine."),
            "league_dragapult_v1_search_only": ("Strong meta-sanity score but its live "
                                                "Kaggle completion is BELOW the Water "
                                                "control (dragapult_above_water=False); "
                                                "not promoted."),
            "league_water_anti_disruption_pivot_v1": ("The active Water control / "
                                                      "reference, intentionally not the "
                                                      "probe."),
            "effect_loop_exit_guard_v1": ("Venusaur loop-guard reuse: lower meta-sanity "
                                          "score; bottleneck is the generic pilot, not "
                                          "the decklist."),
            "durant": "Blocked from league by design (deckout pilot mismatch).",
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass33_strategy_decision.json").write_text(
        json.dumps(decision, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 33 — strategy decision + dry-run queue (Part K)", "",
         "> LOCAL ONLY — HELD dry-run entry, NO upload, human approval required. "
         "NOT a Kaggle leaderboard. Surrogate/internal numbers only.", "",
         f"- recommended probe candidate: **{PROBE}**",
         "- disposition: **candidate_for_deeper_confirmation** (future calibration "
         "probe only)",
         f"- all gates passed: **{all_gates}**",
         f"- queued candidate count: **{queue['queued_candidate_count']}** "
         f"(max {queue['max_queue_size']})",
         f"- active control: **{ACTIVE_CONTROL}**",
         "- auto_submit_enabled: **False**  require_manual_approval_for_submit: "
         "**True**  upload_performed: **False**", "",
         "## Gates", "| gate | passed |", "|---|---|"]
    for k, v in gates.items():
        L.append(f"| {k} | {v} |")
    L += ["", "## Evidence (internal/surrogate only)",
          f"- Stage-1 adj win_rate: {s1.get('adj_win_rate')} "
          f"(Wilson95 {s1.get('wilson')})",
          f"- Stage-2 focused adj win_rate: {s2.get('adj_win_rate')} "
          f"(Wilson95 {s2.get('wilson')})",
          f"- meta-sanity weighted: {m.get('weighted_meta_score')} vs control "
          f"{m_ctrl.get('weighted_meta_score')} (collapses: "
          f"{probe_collapses or 'none'})",
          f"- H2H vs control: child win_rate {child_wr} "
          f"(Wilson95 {pc_row.get('child_wilson')}) — TIE / no regression",
          "", "## Decision", decision["decision"], "",
          "## Rejected alternatives"]
    for k, v in decision["rejected_alternatives"].items():
        L.append(f"- **{k}** — {v}")
    if notes:
        L += ["", "## Notes"] + [f"- {n}" for n in notes]
    L.append("")
    (EXP / "pass33_strategy_decision.md").write_text("\n".join(L), encoding="utf-8")

    print(f"strategy decision: probe={PROBE} all_gates={all_gates} "
          f"queued={queue['queued_candidate_count']} (max 1) upload_performed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
