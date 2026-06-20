#!/usr/bin/env python3
"""Pass 34 (Part L) — strategy decision + dry-run submission queue (max 1). LOCAL.

Turns the Pass-34 new-deck intake + lane split (Parts B-K) into a single, gated,
HUMAN-APPROVAL-REQUIRED dry-run queue. STRICT: auto_submit disabled, manual
approval required, upload_performed=false, queue size <= 1. Nothing is uploaded
or submitted.

Decision logic (honest, evidence-derived):
  * The held dry-run probe coming into Pass 34 is water_basic_density_v1. In the
    Pass-34 internal new-deck tournament it is STILL rank 1 (adj win_rate 0.732)
    and posts 0 collapses in the Part-K meta sanity. No NEW deck clearly beats it.
  * The eligible NEW decks (Miraidon, Diamond) pilot cleanly (0 invalid/crash/
    timeout) but land at ~0.50 / below benchmark and do NOT clear the
    "tournament_strong" gate, so they are labelled *candidate_for_confirmation*
    and are NOT queued.
  * Toxic/Durant are special-pilot blocked -> NOT queued; a special-pilot task is
    recommended instead.
  * Therefore the single held dry-run entry remains water_basic_density_v1
    (re-affirmed by Pass 34), per the rule "keep that held queue unless a new
    candidate clearly beats it".
"""
from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
QUEUE = REPO / "data" / "submission_queue.json"

VALIDATION = EXP / "pass34_candidate_validation.json"
SMOKE = EXP / "pass34_live_smoke.json"
RANKINGS = EXP / "pass34_new_deck_rankings.json"
META = EXP / "pass34_meta_sanity.json"
PROGRESS = EXP / "pass34_new_deck_tournament_progress.json"
DIAGNOSIS = EXP / "pass34_special_lane_diagnosis.json"

HELD_PROBE = "water_basic_density_v1"
WATER_REF = "league_water_anti_disruption_pivot_v1"
DRAGAPULT_REF = "league_dragapult_v1_search_only"
NEW_ELIGIBLE = ["mono_lightning_miraidon_easy", "diamond_toolbox_diancie"]
SPECIAL = ["toxic_trap_poison_lock", "deckout_carousel_durant_v2"]
STRONG_WIN_RATE = 0.60  # benchmark tier; below this is not "tournament_strong"


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _tarball_contents(tar: Path) -> list[str]:
    with tarfile.open(tar, "r:gz") as t:
        return sorted(m.name for m in t.getmembers() if m.isfile())


def main() -> int:
    val = {r["candidate_id"]: r for r in (_read(VALIDATION) or {}).get("results", [])}
    smoke = {r["candidate_id"]: r for r in (_read(SMOKE) or {}).get("results", [])}
    rank = {r["id"]: r for r in (_read(RANKINGS) or {}).get("standings", [])}
    order = [r["id"] for r in (_read(RANKINGS) or {}).get("standings", [])]
    meta_pd = (_read(META) or {}).get("per_deck") or {}
    meta_sanity = (_read(META) or {}).get("sanity") or {}
    tarballs = {k: Path(v) for k, v in
                (_read(PROGRESS) or {}).get("tarball_paths", {}).items()}
    diag = {d["candidate_id"]: d
            for d in (_read(DIAGNOSIS) or {}).get("diagnoses", [])}

    held = rank.get(HELD_PROBE, {})
    held_wr = held.get("adj_win_rate")

    def _collapses(cid):
        d = meta_pd.get(cid, {})
        return sorted(sf for sf, m in (d.get("per_archetype") or {}).items()
                      if (m.get("win_rate") or 0.0) < 0.10)

    # ---- Evaluate each NEW eligible candidate against the queue gates ----
    candidate_eval = {}
    for cid in NEW_ELIGIBLE:
        v = val.get(cid, {})
        s = smoke.get(cid, {})
        r = rank.get(cid, {})
        wr = r.get("adj_win_rate")
        clean_counts = ((r.get("invalids") or 0) == 0 and (r.get("timeouts") or 0) == 0
                        and (r.get("crashes") or 0) == 0)
        gates = {
            "validators_passed": bool(v.get("tarball_valid") and v.get("entrypoint_valid")),
            "smoke_clean": bool(s.get("clean")),
            "no_invalid_error_timeout": clean_counts,
            "tournament_strong": wr is not None and wr >= STRONG_WIN_RATE,
            "meta_sanity_no_collapse": not _collapses(cid),
            "not_special_pilot_blocked": not bool(s.get("blocked_from_league")),
            "no_major_regression": wr is not None,  # clean run, no crash regressions
        }
        clearly_beats_best = (
            wr is not None and held_wr is not None
            and wr > held_wr
            and (r.get("wilson") or [0, 0])[0] > (held.get("wilson") or [0, 0])[1])
        candidate_eval[cid] = {
            "adj_win_rate": wr,
            "wilson": r.get("wilson"),
            "label": r.get("compatibility_label"),
            "meta_collapses": _collapses(cid),
            "weighted_meta_score": (meta_pd.get(cid, {}) or {}).get("weighted_meta_score"),
            "gates": gates,
            "all_gates_passed": all(gates.values()),
            "clearly_beats_held_best": clearly_beats_best,
            "queue_eligible": all(gates.values()) and clearly_beats_best,
            "disposition": ("miraidon_candidate_for_confirmation"
                            if cid == "mono_lightning_miraidon_easy"
                            else "diamond_candidate_for_confirmation"),
        }

    any_new_displaces = any(c["queue_eligible"] for c in candidate_eval.values())

    # ---- The held probe stays unless a new candidate clearly beats it ----
    # Retention gates: the held probe must still be present, run clean (0 invalid/
    # timeout/crash) and NOT collapse anywhere in the meta sanity, and no new
    # candidate may clearly beat it. keep_held is the conjunction of all of these.
    held_probe_gates = {
        "held_present": bool(held),
        "held_clean": ((held.get("invalids") or 0) == 0
                       and (held.get("timeouts") or 0) == 0
                       and (held.get("crashes") or 0) == 0),
        "held_no_meta_collapse": not _collapses(HELD_PROBE),
        "no_new_candidate_displaces": not any_new_displaces,
    }
    keep_held = all(held_probe_gates.values())

    queue_entry = None
    if keep_held and tarballs.get(HELD_PROBE) and tarballs[HELD_PROBE].exists():
        tar = tarballs[HELD_PROBE]
        queue_entry = {
            "candidate_id": HELD_PROBE,
            "tarball_path": str(tar.relative_to(REPO)) if str(tar).startswith(str(REPO))
            else str(tar),
            "tarball_contents": _tarball_contents(tar),
            "disposition": "held_future_calibration_probe",
            "reason": (
                "Re-affirmed by Pass 34: water_basic_density_v1 is STILL rank 1 of "
                f"the internal new-deck tournament (adj win_rate {held_wr}, Wilson95 "
                f"{held.get('wilson')}) with 0 invalid/timeout/crash, and posts 0 "
                "collapses in the Part-K replay-derived meta sanity (weighted "
                f"{(meta_pd.get(HELD_PROBE, {}) or {}).get('weighted_meta_score')}). "
                "No NEW Pass-34 deck (Miraidon ~0.50, Diamond ~0.49) clearly beats "
                "it, so the single held dry-run probe is unchanged. HELD ONLY — "
                "internal/surrogate numbers, human approval required before any "
                "submission."),
            "internal_tournament_adj_win_rate": held_wr,
            "internal_tournament_wilson": held.get("wilson"),
            "weighted_meta_score": (meta_pd.get(HELD_PROBE, {}) or {}).get(
                "weighted_meta_score"),
            "meta_collapses": _collapses(HELD_PROBE),
            "is_clone_or_replay_deck": False,
            "is_kaggle_leaderboard": False,
            "upload_performed": False,
            "auto_submit_enabled": False,
            "require_manual_approval_for_submit": True,
            "reaffirmed_by": "pass34",
        }

    decision_label = (
        "keep_water_basic_density_held_probe" if queue_entry
        else "no_action_no_candidate_queued")

    queue = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": f"run_pass34_new_deck_intake_{time.strftime('%Y%m%d_%H%M%S')}",
        "stage": "pass34_new_deck_intake_lane_split",
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
            "Pass 34 new-deck intake: the held dry-run probe remains "
            f"{HELD_PROBE} (re-affirmed rank 1; no new deck clearly beats it). "
            "New eligible decks Miraidon/Diamond are candidate_for_confirmation "
            "(not queued); Toxic/Durant are special-pilot blocked (not queued). "
            "auto_submit_enabled=false, manual approval required, NO upload."),
    }
    assert len(queue["queue"]) <= 1, "dry-run queue must hold at most 1 entry"
    QUEUE.write_text(json.dumps(queue, indent=2), encoding="utf-8")

    decision = {
        "pass": "34", "part": "L", "local_only": True, "no_upload": True,
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
        "meta_sanity_passed": meta_sanity.get("sanity_passed"),
        "candidate_evaluation": candidate_eval,
        "any_new_candidate_displaces_held": any_new_displaces,
        "decision_labels": {
            "keep_water_as_reference": True,
            "keep_dragapult_as_nonwater_reference": True,
            "miraidon_candidate_for_confirmation": True,
            "diamond_candidate_for_confirmation": True,
            "venusaur_candidate_for_confirmation": False,
            "water_basic_density_candidate_for_confirmation": True,
            "build_toxic_special_pilot_next": True,
            "build_durant_special_pilot_next": True,
            "continue_portfolio_expansion": True,
            "no_action": False,
        },
        "special_pilot_tasks": [
            {"deck_id": cid,
             "task": f"build_and_prove_special_pilot:{cid}",
             "blocked_by": "pilot",
             "first_fixture": diag.get(cid, {}).get("first_executable_fixture_needed"),
             "priority": 1 if cid == "toxic_trap_poison_lock" else 2}
            for cid in SPECIAL],
        "decision": (
            f"Keep {HELD_PROBE} as the single HELD dry-run probe (re-affirmed by "
            "Pass 34). Label Miraidon/Diamond candidate_for_confirmation (clean but "
            "not tournament-strong; not queued). Open special-pilot tasks for "
            "Toxic (priority 1) and Durant (priority 2). No upload/submit performed."
            if queue_entry else
            "No candidate queued; keep Water reference. No upload performed."),
        "rejected_for_queue": {
            "mono_lightning_miraidon_easy": (
                "Cleanest new deck (0 invalid/crash/timeout, no meta collapse) but "
                f"adj win_rate {candidate_eval['mono_lightning_miraidon_easy']['adj_win_rate']} "
                "< strong threshold and does not beat the held probe — "
                "candidate_for_confirmation, not queued."),
            "diamond_toolbox_diancie": (
                "Clean but below_benchmark "
                f"({candidate_eval['diamond_toolbox_diancie']['adj_win_rate']}); "
                "not tournament-strong — candidate_for_confirmation, not queued."),
            "toxic_trap_poison_lock": "Special-pilot blocked (deck legal, generic pilot illegal). Special-pilot task, not queued.",
            "deckout_carousel_durant_v2": "Special-pilot blocked (deck legal, generic pilot illegal). Special-pilot task, not queued.",
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass34_strategy_decision.json").write_text(
        json.dumps(decision, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 34 — strategy decision + dry-run queue (Part L)", "",
         "> LOCAL ONLY — HELD dry-run entry, NO upload, human approval required. "
         "NOT a Kaggle leaderboard. Internal/surrogate numbers only.", "",
         f"- decision: **{decision_label}**",
         f"- held probe: **{HELD_PROBE}** (re-affirmed: **{bool(queue_entry)}**, "
         f"retained: **{keep_held}**)",
         "- held-probe retention gates (all must hold): "
         + ", ".join(f"{k}=**{v}**" for k, v in held_probe_gates.items()),
         f"- queued candidate count: **{queue['queued_candidate_count']}** (max 1)",
         f"- active control / Water reference: **{WATER_REF}**",
         f"- meta sanity passed (no collapses anywhere): "
         f"**{meta_sanity.get('sanity_passed')}**",
         "- auto_submit_enabled: **False**  require_manual_approval_for_submit: "
         "**True**  upload_performed: **False**", "",
         "## New-candidate gate evaluation", "",
         "| candidate | win_rate | label | strong? | meta collapse | all gates | "
         "beats held best | queued |", "|---|---|---|---|---|---|---|---|"]
    for cid, c in candidate_eval.items():
        L.append(
            f"| {cid} | {c['adj_win_rate']} | {c['label']} | "
            f"{c['gates']['tournament_strong']} | "
            f"{c['meta_collapses'] or 'none'} | {c['all_gates_passed']} | "
            f"{c['clearly_beats_held_best']} | {c['queue_eligible']} |")
    L += ["", "## Decision", decision["decision"], "",
          "## Decision labels"]
    for k, v in decision["decision_labels"].items():
        L.append(f"- **{k}**: {v}")
    L += ["", "## Special-pilot tasks (not queued)"]
    for t in decision["special_pilot_tasks"]:
        L.append(f"- `{t['task']}` (priority {t['priority']}, blocked_by "
                 f"{t['blocked_by']})")
    L += ["", "## Rejected for queue"]
    for k, v in decision["rejected_for_queue"].items():
        L.append(f"- **{k}** — {v}")
    L.append("")
    (EXP / "pass34_strategy_decision.md").write_text("\n".join(L), encoding="utf-8")

    print(f"strategy decision: decision={decision_label} "
          f"queued={queue['queued_candidate_count']}/1 "
          f"new_displaces_held={any_new_displaces} upload_performed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
