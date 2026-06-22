#!/usr/bin/env python3
"""PASS 46K (Part E) — larger-N edge analysis (Wilson / seat / Fisher).

Turns the Part-D larger-N ledger (carried 46J + new 46K, NEVER silently mixed) into the
falsifiable statistics the pre-registered plan promised, for EVERY panel:

  * Wilson 95% interval on the subject's COMBINED decisive win rate (and the carried-only and
    new-only rates, so a future reader can see the larger-N evidence did not depend on the
    carried rows alone);
  * per-seat decisive split + a seat-confound flag (edge that reverses with seat);
  * invalid / error / soft-timeout counts + an unsafe-invalid flag;
  * the pre-registered edge label (unsafe_invalid > seat_confounded > confirmed_edge >
    directional_edge > no_edge, the residual).

Cross-panel attribution (does the planner's edge over the parent EXCEED the generic scorers'?):
  * the DIRECT head-to-head arm  spec_vs_generic_ov  (and spec_vs_generic_floor corroborator);
  * a one-sided Fisher-exact INCREMENT comparing the specialist's parent-beating rate against
    each generic scorer's parent-beating rate (ov_vs_parent, floor_vs_parent).

Self-mirror noise controls (parent_vs_parent, spec_vs_spec), if run, must straddle 0.50
(Wilson CI contains 0.50) or a measured practical edge cannot be fully trusted.

LOCAL / READ-ONLY: no games, no mutation, no upload, no events. Public references are NOT in
this analysis (Part F, benchmark-only). Decisive win-rate is a LOCAL feasibility/ordering signal
only — NOT a Kaggle / leaderboard / strength / parity claim; role buckets / contexts are
observable heuristic labels (no exact-damage / lethal / KO / missed-KO / Boss-gust / spread /
best-action). Writes data/experiments/pass46k_edge_analysis.{json,md}.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46k_eval_plan.json"
JSONL = EXP / "pass46k_diamond_confirmation_games.jsonl"

PRACTICAL_PANEL = "spec_vs_parent"
ATTRIBUTION_PANEL = "spec_vs_generic_ov"
FLOOR_H2H_PANEL = "spec_vs_generic_floor"
OV_PARENT_PANEL = "ov_vs_parent"
FLOOR_PARENT_PANEL = "floor_vs_parent"
NOISE_PANELS = ("parent_vs_parent", "spec_vs_spec")


def wilson(k: int, n: int, z: float) -> tuple:
    if n == 0:
        return (None, None, None)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(p, 4), round(center - half, 4), round(center + half, 4))


def fisher_right(a: int, b: int, c: int, d: int):
    """One-sided (right-tail) Fisher exact p: row1 (a,b) has HIGHER success share."""
    n = a + b + c + d
    if n == 0:
        return None
    r1, c1, r2 = a + b, a + c, c + d
    denom = math.comb(n, c1)
    if denom == 0:
        return None
    hi = min(r1, c1)
    return round(sum(math.comb(r1, k) * math.comb(r2, c1 - k)
                     for k in range(a, hi + 1)) / denom, 6)


def _load_panels() -> dict:
    rows = []
    if JSONL.exists():
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("type") == "result":
                rows.append(r)
    panels: dict[str, dict] = {}
    for r in rows:
        pid = r["panel_id"]
        d = panels.setdefault(pid, {
            "subject_id": r.get("subject_id"), "opponent_id": r.get("opponent_id"),
            "total": 0, "invalid": 0, "errors": 0, "soft_timeouts": 0, "draws": 0,
            "decisive": 0, "subj_wins": 0,
            "carried_decisive": 0, "carried_wins": 0, "new_decisive": 0, "new_wins": 0,
            "seat": {0: {"d": 0, "w": 0}, 1: {"d": 0, "w": 0}}})
        carried = bool(r.get("carried"))
        d["total"] += 1
        if r.get("invalid"):
            d["invalid"] += 1
            if r.get("subject_error"):
                d["errors"] += 1
            if str(r.get("error", "")).startswith("soft_timeout"):
                d["soft_timeouts"] += 1
            continue
        if r.get("decisive"):
            d["decisive"] += 1
            seat = int(r.get("subject_seat", 0))
            d["seat"][seat]["d"] += 1
            won = r.get("winner") == "subject"
            if carried:
                d["carried_decisive"] += 1
            else:
                d["new_decisive"] += 1
            if won:
                d["subj_wins"] += 1
                d["seat"][seat]["w"] += 1
                if carried:
                    d["carried_wins"] += 1
                else:
                    d["new_wins"] += 1
        else:
            d["draws"] += 1
    return panels


def analyse_panel(pid: str, d: dict, th: dict) -> dict:
    z = th["wilson_z"]
    dec, wins = d["decisive"], d["subj_wins"]
    point, wlo, whi = wilson(wins, dec, z)
    cp, _, _ = wilson(d["carried_wins"], d["carried_decisive"], z)
    npt, nlo, nhi = wilson(d["new_wins"], d["new_decisive"], z)
    s0, s1 = d["seat"][0], d["seat"][1]
    s0_wr = round(s0["w"] / s0["d"], 4) if s0["d"] else None
    s1_wr = round(s1["w"] / s1["d"], 4) if s1["d"] else None
    invalid_rate = round(d["invalid"] / d["total"], 4) if d["total"] else 0.0
    unsafe_invalid = (d["invalid"] > th["invalid_abs_tol"]
                      and invalid_rate > th["invalid_rate_tol"])
    seat_confounded = False
    if s0_wr is not None and s1_wr is not None:
        hi, lo = th["seat_confound_hi"], th["seat_confound_lo"]
        seat_confounded = ((s0_wr >= hi and s1_wr <= lo) or (s1_wr >= hi and s0_wr <= lo))
    if unsafe_invalid:
        label = "unsafe_invalid"
    elif seat_confounded:
        label = "seat_confounded"
    elif wlo is not None and wlo > th["confirm_wilson_low"]:
        label = "confirmed_edge"
    elif (point is not None and point >= th["directional_point"]
          and wlo is not None and wlo <= th["confirm_wilson_low"]):
        label = "directional_edge"
    else:
        label = "no_edge"
    noise_clean = None
    if pid in NOISE_PANELS and dec > 0:
        noise_clean = (wlo is not None and whi is not None
                       and wlo <= th["noise_ci_must_contain"] <= whi)
    return {
        "panel_id": pid, "subject_id": d["subject_id"], "opponent_id": d["opponent_id"],
        "n_total": d["total"], "n_decisive": dec, "n_invalid": d["invalid"],
        "n_errors": d["errors"], "n_soft_timeouts": d["soft_timeouts"], "n_draws": d["draws"],
        "invalid_rate": invalid_rate, "subject_wins": wins,
        "point": point, "wilson_low": wlo, "wilson_high": whi,
        "carried_decisive": d["carried_decisive"], "carried_wins": d["carried_wins"],
        "carried_point": cp,
        "new_decisive": d["new_decisive"], "new_wins": d["new_wins"], "new_point": npt,
        "new_wilson_low": nlo, "new_wilson_high": nhi,
        "seat0": {"decisive": s0["d"], "wins": s0["w"], "win_rate": s0_wr},
        "seat1": {"decisive": s1["d"], "wins": s1["w"], "win_rate": s1_wr},
        "seat_confounded": seat_confounded, "unsafe_invalid": unsafe_invalid,
        "noise_clean": noise_clean, "edge_label": label,
    }


def main() -> int:
    if not PLAN_JSON.exists():
        raise SystemExit(f"missing eval plan: {PLAN_JSON}")
    if not JSONL.exists():
        raise SystemExit(f"missing games ledger: {JSONL}")
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    th = plan["thresholds"]
    panels_raw = _load_panels()
    analyses = {pid: analyse_panel(pid, d, th) for pid, d in panels_raw.items()}

    practical = analyses.get(PRACTICAL_PANEL)
    attribution = analyses.get(ATTRIBUTION_PANEL)
    floor_h2h = analyses.get(FLOOR_H2H_PANEL)

    # One-sided Fisher INCREMENT: specialist beats parent at a HIGHER rate than each generic.
    increments = {}
    if practical and practical["n_decisive"]:
        sw = practical["subject_wins"]
        sl = practical["n_decisive"] - sw
        for gen in (OV_PARENT_PANEL, FLOOR_PARENT_PANEL):
            g = analyses.get(gen)
            if g and g["n_decisive"]:
                gw = g["subject_wins"]
                gl = g["n_decisive"] - gw
                p_val = fisher_right(sw, sl, gw, gl)
                increments[gen] = {
                    "spec_vs_parent": [sw, sl], "generic_vs_parent": [gw, gl],
                    "spec_parent_rate": practical["point"], "generic_parent_rate": g["point"],
                    "fisher_right_p": p_val,
                    "significant_at_0_05": bool(p_val is not None and p_val < th["fisher_alpha"]),
                    "interpretation": (
                        "specialist beats the parent significantly MORE often than this "
                        "generic scorer does — the increment is the planner's, not the "
                        "generic scorer's" if (p_val is not None and p_val < th["fisher_alpha"])
                        else "NO significant increment over this generic scorer at beating "
                             "the parent")}

    practical_label = practical["edge_label"] if practical else "missing"
    attribution_label = attribution["edge_label"] if attribution else "missing"
    attribution_point = attribution["point"] if attribution else None
    fisher_ov_sig = increments.get(OV_PARENT_PANEL, {}).get("significant_at_0_05", False)
    attributable = bool(attribution_label in ("confirmed_edge", "directional_edge")
                        or fisher_ov_sig)
    attribution_negative = bool(
        attribution_point is not None and attribution_point < 0.5
        and attribution and attribution["n_decisive"]
        >= _min_acc(plan, ATTRIBUTION_PANEL))

    noise_required = practical_label in ("confirmed_edge", "directional_edge")
    noise_results = {p: analyses[p]["noise_clean"] for p in NOISE_PANELS if p in analyses}
    noise_clean = all(v for v in noise_results.values()) if noise_results else None

    gating_reached_min = bool(
        practical and attribution
        and practical["n_decisive"] >= _min_acc(plan, PRACTICAL_PANEL)
        and attribution["n_decisive"] >= _min_acc(plan, ATTRIBUTION_PANEL))

    decision_inputs = {
        "practical_panel": PRACTICAL_PANEL, "practical_label": practical_label,
        "practical_point": practical["point"] if practical else None,
        "practical_wilson_low": practical["wilson_low"] if practical else None,
        "attribution_panel": ATTRIBUTION_PANEL, "attribution_label": attribution_label,
        "attribution_point": attribution_point,
        "attribution_wilson_low": attribution["wilson_low"] if attribution else None,
        "head_to_head_floor_label": floor_h2h["edge_label"] if floor_h2h else None,
        "practical_confirmed": practical_label == "confirmed_edge",
        "practical_directional": practical_label == "directional_edge",
        "attribution_confirmed": attribution_label == "confirmed_edge",
        "attribution_directional": attribution_label == "directional_edge",
        "attribution_negative": attribution_negative,
        "attributable_to_planner": attributable,
        "fisher_ov_increment_significant": fisher_ov_sig,
        "any_gating_unsafe_invalid": any(
            a and a["edge_label"] == "unsafe_invalid" for a in (practical, attribution)),
        "gating_reached_min_acceptable": gating_reached_min,
        "noise_required": noise_required, "noise_results": noise_results,
        "noise_clean": noise_clean,
    }

    all_ok = practical is not None and attribution is not None
    data = {
        "pass": "46K", "part": "E", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "references_in_analysis": False, "thresholds": th, "panels": analyses,
        "attribution_increments_fisher": increments, "decision_inputs": decision_inputs,
        "caveat": ("Decisive win-rate is a LOCAL feasibility/ordering signal only — NOT a "
                   "Kaggle / leaderboard / strength / parity claim. Public references are "
                   "benchmark-only and EXCLUDED here. Carried (46J) and new (46K) rates are "
                   "reported separately. Role buckets / contexts are observable heuristic "
                   "labels (no exact-damage / lethal / KO / missed-KO / Boss-gust / spread / "
                   "best-action)."),
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46k_edge_analysis.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def fmt(a: dict) -> str:
        return (f"| `{a['panel_id']}` | {a['point']} | [{a['wilson_low']}, {a['wilson_high']}] "
                f"| {a['n_decisive']} ({a['carried_decisive']}c+{a['new_decisive']}n) | "
                f"{a['new_point']} | {a['seat0']['win_rate']} | {a['seat1']['win_rate']} | "
                f"{a['seat_confounded']} | {a['n_invalid']} | **{a['edge_label']}** |")

    order = [PRACTICAL_PANEL, ATTRIBUTION_PANEL, FLOOR_H2H_PANEL,
             OV_PARENT_PANEL, FLOOR_PARENT_PANEL, *NOISE_PANELS]
    md = [
        "# Pass 46K (Part E) — larger-N edge analysis (Wilson / seat / Fisher)", "",
        "_LOCAL / READ-ONLY. Wilson 95% intervals (combined carried+new, plus new-only), "
        "per-seat splits + seat-confound, invalid/error/timeout counts, and the pre-registered "
        "edge labels for every panel, plus one-sided Fisher INCREMENT tests of whether the "
        "specialist beats the real parent more often than each generic scorer does. Decisive "
        "win-rate is a LOCAL feasibility/ordering signal only — NOT a Kaggle / leaderboard / "
        "strength / parity claim. Public references are benchmark-only and EXCLUDED here. Role "
        "buckets / contexts are observable heuristic labels — no exact-damage / lethal / KO / "
        "missed-KO / Boss-gust / spread / best-action._", "",
        "## Per-panel edge labels (combined; new-only win rate shown for replication)",
        "| panel | point | Wilson 95% | decisive (c+n) | new wr | seat0 | seat1 | seat-conf "
        "| invalid | label |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for pid in order:
        if pid in analyses:
            md.append(fmt(analyses[pid]))
    md += ["", "## Attribution increments (one-sided Fisher, combined)",
           "| generic baseline | spec W-L vs parent | generic W-L vs parent | spec rate | "
           "generic rate | Fisher p | significant |",
           "|---|:---:|:---:|:---:|:---:|:---:|:---:|"]
    for gen, inc in increments.items():
        md.append(f"| `{gen}` | {inc['spec_vs_parent'][0]}-{inc['spec_vs_parent'][1]} | "
                  f"{inc['generic_vs_parent'][0]}-{inc['generic_vs_parent'][1]} | "
                  f"{inc['spec_parent_rate']} | {inc['generic_parent_rate']} | "
                  f"{inc['fisher_right_p']} | {inc['significant_at_0_05']} |")
    md += ["", "## Decision inputs (Part H applies the frozen rule)",
           f"- PRACTICAL (`{PRACTICAL_PANEL}`): **{practical_label}** "
           f"(point {decision_inputs['practical_point']}, Wilson_low "
           f"{decision_inputs['practical_wilson_low']})",
           f"- ATTRIBUTION (`{ATTRIBUTION_PANEL}`): **{attribution_label}** "
           f"(point {attribution_point}); attributable_to_planner: {attributable}; "
           f"attribution_negative: {attribution_negative}",
           f"- gating reached min_acceptable: {gating_reached_min}",
           f"- noise required: {noise_required} | results: {noise_results} | clean: "
           f"{noise_clean}", "",
           f"**all_ok = {all_ok}**"]
    (EXP / "pass46k_edge_analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "practical_label": practical_label,
                      "attribution_label": attribution_label,
                      "attributable": attributable, "attribution_negative": attribution_negative,
                      "fisher_ov_p": increments.get(OV_PARENT_PANEL, {}).get("fisher_right_p"),
                      "noise_required": noise_required, "noise_results": noise_results,
                      "noise_clean": noise_clean,
                      "gating_reached_min": gating_reached_min}, indent=2))
    return 0 if all_ok else 1


def _min_acc(plan: dict, pid: str) -> int:
    for p in plan.get("panels", []) + plan.get("conditional_noise_controls", []):
        if p["panel_id"] == pid:
            return p.get("min_acceptable_decisive", 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
