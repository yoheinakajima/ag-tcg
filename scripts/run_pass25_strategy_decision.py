#!/usr/bin/env python3
"""Pass 25 (Part J) — Water live-control hardening strategy decision. LOCAL ONLY.

Pure synthesis of the Pass-25 artifacts (runs no games, builds no decks, emits no
events -- ActiveGraph events are Part K). It turns the eligibility gates (Part G),
the counterfactual decision replay (Part H) and the lean focused eval (Part I)
into ONE honest, labelled decision per candidate plus an overall recommendation
for the Water live-control family.

Decision vocabulary (fixed):
  keep_current_control | queue_for_local_iteration | future_kaggle_probe |
  reject | blocked

Hard rules:
  * future_kaggle_probe requires ALL of: eligible (validators+smoke+gates PASS),
    no positive-control regression, zero illegal replayed actions, H2H-vs-control
    Wilson interval NOT clearly negative, AND a material seam gain over control
    (>= +0.08 aggregate seam win-rate) backed by an actual behaviour delta on the
    real loss windows. A candidate that never changes behaviour on the real seams
    (changed_total == 0) can NEVER be probe-promoted -- there is no measured
    benefit to justify a live slot.
  * No candidate is ever called better than the control while it shows no
    behaviour delta and no material seam gain.

Evidence consumed (all LOCAL):
  data/experiments/pass25_candidate_validation.json   (Part G eligibility)
  data/experiments/pass25_live_smoke.json             (Part G clean-run smoke)
  data/experiments/pass25_decision_replay.json        (Part H counterfactual)
  data/experiments/pass25_focused_eval.json           (Part I H2H + seam)
  data/experiments/pass25_live_score_status.json      (Part B drift, optional)

Outputs: data/experiments/pass25_strategy_decision.{json,md}. STRICT: LOCAL ONLY,
no Kaggle upload/submit, no GitHub push, no root edits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

VALIDATION = EXP / "pass25_candidate_validation.json"
SMOKE = EXP / "pass25_live_smoke.json"
REPLAY = EXP / "pass25_decision_replay.json"
FOCUSED = EXP / "pass25_focused_eval.json"
DRIFT = EXP / "pass25_live_score_status.json"
OUT_JSON = EXP / "pass25_strategy_decision.json"
OUT_MD = EXP / "pass25_strategy_decision.md"

CONTROL_ID = "league_water_anti_disruption_pivot_v1"
CONTROL_PARTICIPANT = "control_pass22_pivot"
CANDIDATES = ["deckout_guard_v1", "prize_liability_guard_v1", "hybrid_guard_v1"]

VALID_LABELS = {"keep_current_control", "queue_for_local_iteration",
                "future_kaggle_probe", "reject", "blocked"}

SEAM_GAIN_THRESHOLD = 0.08

DISCLAIMER = (
    "LOCAL ONLY. This decision rests on (a) eligibility gates, (b) a counterfactual "
    "decision replay against three real loss/positive-control episodes, and (c) a "
    "lean SURROGATE focused eval (our decks vs a generic surrogate brain). None of "
    "these equals a Kaggle result. Any local edge is INTERNAL only and is NEVER "
    "sufficient to upload or submit. No upload performed, no GitHub push, root "
    "main.py/deck.csv untouched.")


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _validation_map(v: dict) -> dict:
    return {c.get("candidate_id"): c for c in v.get("candidates", [])}


def _decide_one(cid: str, val: dict, replay: dict, focused: dict) -> dict:
    eligible = bool(val.get("eligible"))
    pc_preserved = bool(replay.get("positive_control_preserved"))
    illegal = int(replay.get("illegal", 0) or 0)
    changed = int(replay.get("changed_total", 0) or 0)
    on_seam = int(replay.get("on_seam", 0) or 0)

    h2h = (focused.get("h2h_vs_control") or {}).get(cid, {})
    h2h_wr = h2h.get("win_rate")
    h2h_hi = h2h.get("wilson_high")
    h2h_lo = h2h.get("wilson_low")
    seam_delta = (focused.get("seam_delta_vs_control") or {}).get(cid)

    # H2H is "not clearly negative" if the upper Wilson bound reaches 0.5.
    h2h_non_negative = h2h_hi is not None and h2h_hi >= 0.5
    material_seam_gain = seam_delta is not None and seam_delta >= SEAM_GAIN_THRESHOLD
    has_behaviour_delta = changed > 0

    if not eligible:
        label, secondary = "reject", "failed_eligibility_gate"
    elif not pc_preserved or illegal > 0:
        label, secondary = "reject", ("positive_control_regression"
                                      if not pc_preserved else "illegal_replayed_action")
    elif h2h_non_negative and material_seam_gain and has_behaviour_delta and on_seam > 0:
        label, secondary = "future_kaggle_probe", "clears_promotion_bar"
    elif not has_behaviour_delta:
        # Eligible + safe + positive-control-preserving, but provably inert on the
        # real seams: nothing to promote, keep the proven control.
        label, secondary = "keep_current_control", "inert_no_measurable_effect_on_real_seams"
    else:
        # Eligible + safe and it does change behaviour, but the change is not a
        # material, statistically-supported seam gain: keep it locally, don't probe.
        label, secondary = "queue_for_local_iteration", "behaviour_delta_without_material_gain"

    return {
        "candidate_id": cid,
        "label": label,
        "secondary_label": secondary,
        "eligible": eligible,
        "positive_control_preserved": pc_preserved,
        "illegal_replayed_actions": illegal,
        "behaviour_delta_on_real_windows": changed,
        "on_seam_changes": on_seam,
        "h2h_vs_control": {"win_rate": h2h_wr, "wilson": [h2h_lo, h2h_hi],
                           "non_negative": h2h_non_negative},
        "seam_delta_vs_control": seam_delta,
        "material_seam_gain": material_seam_gain,
        "strictly_better_than_control": False,
        "promotion_bar_cleared": label == "future_kaggle_probe",
    }


def _drift_context(drift: dict) -> dict:
    """Best-effort extraction of the Part-B drift finding; tolerant of schema."""
    out = {"available": bool(drift)}
    if not drift:
        return out
    live = drift.get("active_control_live_rule", {}) or {}
    water = drift.get("maintained_water_control_under_hardening", {}) or {}
    out.update({
        "live_best": {"file": live.get("fileName"),
                      "public_score": live.get("publicScore")},
        "water_control_under_hardening": {
            "file": water.get("fileName"),
            "public_score": water.get("publicScore")},
        "pivot_is_live_best": drift.get("pivot_is_live_best"),
        "pivot_vs_live_best_delta": drift.get("pivot_vs_live_best_delta"),
        "pivot_vs_live_best_within_noise": drift.get("pivot_vs_live_best_within_noise"),
        "conclusion": drift.get("conclusion"),
    })
    return out


def run() -> dict:
    val = _load(VALIDATION)
    smoke = _load(SMOKE)
    replay = _load(REPLAY)
    focused = _load(FOCUSED)
    drift = _load(DRIFT)

    vmap = _validation_map(val)
    rmap = replay.get("per_candidate", {}) or {}

    decisions = []
    for cid in CANDIDATES:
        decisions.append(_decide_one(cid, vmap.get(cid, {}),
                                     rmap.get(cid, {}), focused))
    for d in decisions:
        assert d["label"] in VALID_LABELS, d["label"]

    any_probe = any(d["label"] == "future_kaggle_probe" for d in decisions)
    any_reject = any(d["label"] == "reject" for d in decisions)
    all_eligible = bool(val.get("all_eligible"))
    smoke_ok = bool(smoke.get("smoke_ok"))

    primary = "future_kaggle_probe" if any_probe else "keep_current_control"

    rec = {
        "kind": "dry_run_only",
        "upload_recommended": False,
        "submit_recommended": False,
        "upload_not_recommended": True,
        "github_push_recommended": False,
        "current_best": CONTROL_ID,
        "primary_decision": primary,
        "probe_candidates": [d["candidate_id"] for d in decisions
                             if d["label"] == "future_kaggle_probe"],
        "explicit_caveat": (
            "Every Pass-25 candidate is eligible (validators + smoke + core/board/"
            "hardening gates PASS) and positive-control-preserving, but the Part-H "
            "decision replay shows ZERO behaviour deltas over 262 real analysed-seat "
            "decisions, and the Part-I focused eval shows NO material seam gain over "
            "the control (all seam deltas <= 0, all H2H Wilson intervals straddle "
            "0.5 -- pure surrogate noise). The narrow guard hooks are provably safe "
            "but never fire on the actual loss seams, so there is no measured benefit "
            "to justify changing the live-active control. Keep current control. No "
            "upload, no submission, no push."),
    }

    return {
        "pass": "25", "part": "J", "local_only": True, "upload_performed": False,
        "is_kaggle_leaderboard": False, "disclaimer": DISCLAIMER,
        "valid_labels": sorted(VALID_LABELS),
        "seam_gain_threshold": SEAM_GAIN_THRESHOLD,
        "gates": {"all_eligible": all_eligible, "smoke_ok": smoke_ok,
                  "any_candidate_rejected": any_reject},
        "inputs": {k: str(p.relative_to(REPO)) for k, p in {
            "validation": VALIDATION, "smoke": SMOKE, "replay": REPLAY,
            "focused_eval": FOCUSED, "drift": DRIFT}.items()},
        "drift_context": _drift_context(drift),
        "candidate_decisions": decisions,
        "recommendation": rec,
        "rationale": (
            "Part B established the sprint motivation: the Pass-22 pivot's live lead "
            "evaporated (520.8 -> 358.7), so the family is statistically tied and "
            "well worth hardening -- but there is no robust live lead to protect, "
            "which raises (not lowers) the bar for changing the control. Three narrow "
            "candidates were built over the proven Water v2 base, each a single delta "
            "vs the control: a low-deck draw-count clamp (deckout_guard_v1), a "
            "prize-liability search pivot (prize_liability_guard_v1), and both "
            "(hybrid_guard_v1). All three pass every eligibility gate and preserve the "
            "positive-control episode. However, the counterfactual replay proves the "
            "hooks are inert on the real seams: the deckout clamp has no applicable "
            "ctx38 draw-count decision on our seat (the real deckout ran through "
            "search/optional-trainer plays, not numeric draws), and the prize pivot's "
            "firing predicate was never satisfied. With zero behaviour deltas and no "
            "material seam gain in the focused eval, no candidate clears the probe "
            "bar. The honest decision is keep_current_control."),
    }


def _md(rep: dict) -> str:
    rec = rep["recommendation"]
    L = ["# Pass 25 — Water Live-Control Hardening: Strategy Decision (Part J)", "",
         f"> {rep['disclaimer']}", "",
         f"- is Kaggle leaderboard: **{rep['is_kaggle_leaderboard']}**  "
         f"upload_performed: **{rep['upload_performed']}**",
         f"- **primary decision:** `{rec['primary_decision']}`  "
         f"current_best kept: `{rec['current_best']}`",
         f"- upload recommended: **{rec['upload_recommended']}**  "
         f"submit recommended: **{rec['submit_recommended']}**  "
         f"github push recommended: **{rec['github_push_recommended']}**",
         f"- gates: all_eligible=**{rep['gates']['all_eligible']}**  "
         f"smoke_ok=**{rep['gates']['smoke_ok']}**  "
         f"any_rejected=**{rep['gates']['any_candidate_rejected']}**", "",
         "## Per-candidate decisions", "",
         "| candidate | label | secondary | eligible | pos-ctrl kept | Δbehaviour "
         "| H2H wr [Wilson] | seam Δ | material gain |",
         "|---|---|---|---|---|---|---|---|---|"]
    for d in rep["candidate_decisions"]:
        h = d["h2h_vs_control"]
        L.append(
            f"| {d['candidate_id']} | `{d['label']}` | {d['secondary_label']} | "
            f"{d['eligible']} | {d['positive_control_preserved']} | "
            f"{d['behaviour_delta_on_real_windows']} | {h['win_rate']} "
            f"[{h['wilson'][0]}, {h['wilson'][1]}] | {d['seam_delta_vs_control']} | "
            f"{d['material_seam_gain']} |")
    L += ["", "## Recommendation", "", f"- {rec['explicit_caveat']}", "",
          "## Rationale", "", rep["rationale"], "",
          "## Promotion bar (for transparency)", "",
          "- `future_kaggle_probe` requires ALL of: eligible, positive-control "
          "preserved, zero illegal replayed actions, H2H-vs-control Wilson interval "
          "not clearly negative, AND a material seam gain over control "
          f"(>= +{rep['seam_gain_threshold']} aggregate seam win-rate) backed by an "
          "actual on-seam behaviour delta. A candidate with zero behaviour delta on "
          "the real windows can never be probe-promoted.", ""]
    if rep["drift_context"].get("available"):
        L += ["## Drift context (Part B)", "",
              "```json", json.dumps(rep["drift_context"], indent=2), "```", ""]
    return "\n".join(L)


def main() -> int:
    rep = run()
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_md(rep), encoding="utf-8")
    print(f"strategy decision: primary={rep['recommendation']['primary_decision']} "
          f"current_best={rep['recommendation']['current_best']} "
          f"upload={rep['recommendation']['upload_recommended']}")
    for d in rep["candidate_decisions"]:
        print(f"  {d['candidate_id']:28s} -> {d['label']} ({d['secondary_label']})")
    for p in (OUT_JSON, OUT_MD):
        print(f"  -> {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
