#!/usr/bin/env python3
"""Pass 35 (T-M) — strategy decision + dry-run submission queue (max 1). LOCAL.

Turns the Pass-35 typed-layer evidence (T-D..T-L) into a single, gated,
HUMAN-APPROVAL-REQUIRED dry-run queue. STRICT: auto_submit disabled, manual
approval required, upload_performed=false, queue size <= 1. Nothing is uploaded
or submitted.

Decision logic (honest, control-calibrated):
  * Each Pass-35 candidate is a TYPED CHILD = its untyped parent + ONLY the typed
    board-aware override (deck byte-identical to parent). A child may displace the
    held dry-run probe ONLY if it CLEARLY beats its own parent — i.e. T-K marks it
    superiority_claim=true after its win-rate CI clears BOTH self-mirror noise
    floors (parent-mirror AND child-mirror).
  * T-K result: any_superiority_claim=FALSE (5 no_regression, 4 inconclusive). The
    typed layer is SAFE (firing probe: 0 illegal refinements across all decisions,
    ~2.5% live firing, always falls back) but shows NO reliable game-level strength
    gain at the achievable sample size. So NO typed child is queue-eligible.
  * T-L meta sanity passed (0 collapses for every child) — directional only.
  * Therefore the single held dry-run probe stays water_basic_density_v1 (untyped,
    carried from Pass 33/34), unchanged, per "keep the held queue unless a new
    candidate clearly beats it". No typed child is promoted; nothing is uploaded.
"""
from __future__ import annotations

import json
import os
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
QUEUE = REPO / "data" / "submission_queue.json"

VALIDATION = EXP / "pass35_candidate_validation.json"
BUILD = EXP / "pass35_candidate_build.json"
RANKINGS = EXP / "pass35_rankings.json"
META = EXP / "pass35_meta_sanity.json"
PARENT_CHILD = EXP / "pass35_parent_child.json"
FIRING = EXP / "pass35_typed_firing_probe.json"
AB_CONTROLS = EXP / "pass35_ab_controls.json"

HELD_PROBE = "water_basic_density_v1"
HELD_PROBE_TARBALL = "data/submissions/candidates_pass33/water_basic_density_v1.tar.gz"
WATER_REF = "league_water_anti_disruption_pivot_v1"
SPECIAL = ["toxic_trap_poison_lock", "deckout_carousel_durant_v2"]
COLLAPSE_THRESHOLD = 0.10


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tarball_contents(tar: Path) -> list[str]:
    with tarfile.open(tar, "r:gz") as t:
        return sorted(m.name for m in t.getmembers() if m.isfile())


def main() -> int:
    val = {r["id"]: r for r in (_read(VALIDATION) or {}).get("records", [])}
    val_all_ok = bool((_read(VALIDATION) or {}).get("all_ok"))
    build = {r.get("candidate_id"): r for r in (_read(BUILD) or {}).get("candidates", [])
             if r.get("built")}
    base_of = {r["candidate_id"]: r["id"] for r in (_read(BUILD) or {}).get("candidates", [])
               if r.get("built") and r.get("candidate_id")}
    order = [r["id"] for r in (_read(RANKINGS) or {}).get("overall_ranking", [])]
    meta = _read(META) or {}
    meta_pd = meta.get("per_deck") or {}
    meta_sanity = meta.get("sanity") or {}
    pc = _read(PARENT_CHILD) or {}
    pairs = {r["child_id"]: r for r in pc.get("pairs", [])}
    any_superiority = bool(pc.get("any_superiority_claim"))
    firing = _read(FIRING) or {}
    fire_totals = firing.get("totals") or {}
    typed_layer_safe = (firing.get("any_illegal_refinement") is False
                        and (fire_totals.get("illegal_refinements") or 0) == 0)

    def _collapses(child_id):
        d = meta_pd.get(child_id, {})
        return sorted(sf for sf, m in (d.get("per_archetype") or {}).items()
                      if (m.get("win_rate") or 0.0) < COLLAPSE_THRESHOLD)

    # ---- Evaluate each typed child against the queue-promotion gates ----
    candidate_eval = {}
    for child_id in order:
        p = pairs.get(child_id, {})
        v = val.get(base_of.get(child_id, ""), {})
        cls = p.get("classification")
        sup = bool(p.get("superiority_claim"))
        gates = {
            "validators_passed": bool(v.get("ok")),
            "deck_identical_to_parent": bool(p.get("deck_identical_to_parent")),
            "typed_layer_safe_no_illegal": typed_layer_safe,
            "no_regression_or_better": cls in ("improves", "no_regression"),
            "meta_sanity_no_collapse": not _collapses(child_id),
            "clearly_beats_parent": sup,  # control-calibrated superiority (T-K)
        }
        candidate_eval[child_id] = {
            "parent": p.get("parent_tarball"),
            "child_win_rate": p.get("child_win_rate"),
            "child_wilson": p.get("child_wilson"),
            "classification": cls,
            "superiority_claim": sup,
            "parent_mirror_win_rate": p.get("parent_mirror_win_rate"),
            "child_mirror_win_rate": p.get("child_mirror_win_rate"),
            "weighted_meta_score": (meta_pd.get(child_id, {}) or {}).get(
                "weighted_meta_score"),
            "meta_collapses": _collapses(child_id),
            "gates": gates,
            "all_gates_passed": all(gates.values()),
            "queue_eligible": all(gates.values()),  # requires clearly_beats_parent
            "disposition": ("queue_typed_child" if all(gates.values())
                            else "safe_no_regression_not_promotion_worthy"),
        }

    any_child_displaces = any(c["queue_eligible"] for c in candidate_eval.values())

    # ---- The held probe stays unless a typed child clearly beats its parent ----
    held_tar = REPO / HELD_PROBE_TARBALL
    held_probe_gates = {
        "held_tarball_present": held_tar.exists(),
        "meta_sanity_passed": bool(meta_sanity.get("sanity_passed")),
        "no_typed_child_displaces": not any_child_displaces,
    }
    keep_held = all(held_probe_gates.values())

    queue_entry = None
    if keep_held and held_tar.exists():
        queue_entry = {
            "candidate_id": HELD_PROBE,
            "tarball_path": HELD_PROBE_TARBALL,
            "tarball_contents": _tarball_contents(held_tar),
            "disposition": "held_future_calibration_probe",
            "reason": (
                "Carried unchanged from Pass 33/34. In Pass 35 every typed child is "
                "its untyped parent + ONLY a board-aware typed override; T-K finds "
                "any_superiority_claim=FALSE (5 no_regression, 4 inconclusive) once "
                "win-rate CIs are calibrated against the engine self-mirror noise "
                "floor, so NO typed child clearly beats its parent. The typed layer "
                "is SAFE (0 illegal refinements, always falls back) but not a "
                "measured strength gain, so the single held dry-run probe is "
                "unchanged. HELD ONLY — internal/surrogate numbers, human approval "
                "required before any submission."),
            "is_clone_or_replay_deck": False,
            "is_kaggle_leaderboard": False,
            "upload_performed": False,
            "auto_submit_enabled": False,
            "require_manual_approval_for_submit": True,
            "reaffirmed_by": "pass35",
        }

    decision_label = ("keep_water_basic_density_held_probe" if queue_entry
                      else "no_action_no_candidate_queued")

    queue = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": f"run_pass35_typed_strategy_{time.strftime('%Y%m%d_%H%M%S')}",
        "stage": "pass35_typed_board_aware_strategy_layer",
        "auto_submit_enabled": False,
        "require_manual_approval_for_submit": True,
        "upload_performed": False,
        "no_more_submissions_today": True,
        "max_queue_size": 1,
        "active_control": WATER_REF,
        "held_probe": HELD_PROBE,
        "decision": decision_label,
        "queue": [queue_entry] if queue_entry else [],
        "queued_candidate_count": 1 if queue_entry else 0,
        "selection_reason": (
            "Pass 35 typed-layer pass: NO typed child clearly beats its untyped "
            "parent (T-K any_superiority_claim=false, control-calibrated), so the "
            "held dry-run probe remains water_basic_density_v1 (untyped, carried). "
            "The typed layer is SAFE (0 illegal refinements) and meta-sane (0 "
            "collapses) but is not promotion-worthy. auto_submit_enabled=false, "
            "manual approval required, NO upload."),
    }
    assert len(queue["queue"]) <= 1, "dry-run queue must hold at most 1 entry"
    QUEUE.write_text(json.dumps(queue, indent=2), encoding="utf-8")

    decision = {
        "pass": "35", "task": "T-M", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "held_probe": HELD_PROBE,
        "held_probe_reaffirmed": bool(queue_entry),
        "held_probe_gates": held_probe_gates,
        "held_probe_retained": keep_held,
        "queued_candidate_count": queue["queued_candidate_count"],
        "queue_max": 1,
        "active_control": WATER_REF,
        "human_approval_required": True, "auto_submit_enabled": False,
        "ranking_order": order,
        "validation_all_ok": val_all_ok,
        "typed_layer_safe_no_illegal_refinements": typed_layer_safe,
        "typed_layer_firing_rate_pct": fire_totals.get("overall_firing_rate_pct"),
        "any_superiority_claim": any_superiority,
        "meta_sanity_passed": meta_sanity.get("sanity_passed"),
        "candidate_evaluation": candidate_eval,
        "any_typed_child_displaces_held": any_child_displaces,
        "decision_labels": {
            "keep_water_basic_density_held_probe": bool(queue_entry),
            "typed_layer_is_safe_to_keep": typed_layer_safe,
            "typed_layer_no_measured_strength_gain": not any_superiority,
            "no_typed_child_promoted_to_queue": not any_child_displaces,
            "keep_water_as_active_control": True,
            "no_upload_no_submit": True,
        },
        "special_pilot_note": (
            "Toxic/Durant remain special-pilot-only (executable=false) — never "
            "built, never queued; a dedicated special-pilot task is still the path "
            "for them."),
        "special_pilot_decks": SPECIAL,
        "decision": (
            f"Keep {HELD_PROBE} as the single HELD dry-run probe (carried, "
            "unchanged). The Pass-35 typed board-aware layer is adopted as SAFE "
            "(0 illegal refinements, always falls back, ~2.5% live firing) and "
            "meta-sane (0 collapses), but NO typed child clearly beats its untyped "
            "parent once calibrated against the self-mirror noise floor, so none is "
            "promoted to the queue. No upload/submit performed."
            if queue_entry else
            "No candidate queued; keep Water reference. No upload performed."),
        "rejected_for_queue": {
            child_id: (
                f"classification={c['classification']}, superiority_claim="
                f"{c['superiority_claim']} (child win-rate within the engine "
                "self-mirror noise floor) — typed layer safe/no-regression but not "
                "a control-calibrated strength gain; not queued.")
            for child_id, c in candidate_eval.items()
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass35_strategy_decision.json").write_text(
        json.dumps(decision, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 35 — strategy decision + dry-run queue (T-M)", "",
         "> LOCAL ONLY — HELD dry-run entry, NO upload, human approval required. "
         "NOT a Kaggle leaderboard. Internal/surrogate numbers only.", "",
         f"- decision: **{decision_label}**",
         f"- held probe: **{HELD_PROBE}** (re-affirmed: **{bool(queue_entry)}**, "
         f"retained: **{keep_held}**)",
         "- held-probe retention gates (all must hold): "
         + ", ".join(f"{k}=**{v}**" for k, v in held_probe_gates.items()),
         f"- queued candidate count: **{queue['queued_candidate_count']}** (max 1)",
         f"- active control / Water reference: **{WATER_REF}**",
         f"- validation all_ok: **{val_all_ok}**",
         f"- typed layer safe (0 illegal refinements): "
         f"**{typed_layer_safe}**  (live firing "
         f"{fire_totals.get('overall_firing_rate_pct')}%)",
         f"- any superiority claim (control-calibrated): **{any_superiority}**",
         f"- meta sanity passed (no collapses anywhere): "
         f"**{meta_sanity.get('sanity_passed')}**",
         "- auto_submit_enabled: **False**  require_manual_approval_for_submit: "
         "**True**  upload_performed: **False**", "",
         "## Typed-child queue-promotion gate evaluation", "",
         "| typed child | win_rate | classification | beats parent | meta collapse "
         "| all gates | queued |", "|---|---|---|---|---|---|---|"]
    for child_id, c in candidate_eval.items():
        L.append(
            f"| {child_id} | {c['child_win_rate']} | {c['classification']} | "
            f"{c['superiority_claim']} | {c['meta_collapses'] or 'none'} | "
            f"{c['all_gates_passed']} | {c['queue_eligible']} |")
    L += ["", "## Decision", decision["decision"], "",
          "## Decision labels"]
    for k, v in decision["decision_labels"].items():
        L.append(f"- **{k}**: {v}")
    L += ["", "## Special-pilot note", f"- {decision['special_pilot_note']}",
          "", "## Rejected for queue (typed children — safe, not promotion-worthy)"]
    for k, v in decision["rejected_for_queue"].items():
        L.append(f"- **{k}** — {v}")
    L.append("")
    (EXP / "pass35_strategy_decision.md").write_text("\n".join(L), encoding="utf-8")

    print(f"strategy decision: decision={decision_label} "
          f"queued={queue['queued_candidate_count']}/1 "
          f"any_superiority={any_superiority} "
          f"typed_layer_safe={typed_layer_safe} "
          f"child_displaces_held={any_child_displaces} upload_performed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
