#!/usr/bin/env python3
"""PASS 46I (Part E) — parent / floor / noise analysis + edge labels.

Turns the raw Part-D decisive-rate ledger into the falsifiable statistics the
pre-registered plan promised, for EVERY panel:

  * Wilson 95% interval on the subject's decisive win rate;
  * per-seat decisive split + a seat-confound flag (edge that reverses with seat);
  * invalid count / rate + an unsafe-invalid flag;
  * the pre-registered edge label (unsafe_invalid > seat_confounded > confirmed_edge >
    directional_edge > no_edge, the last being the exhaustive residual).

Cross-panel it answers the question the whole pass exists for — is any edge over the
real parent ATTRIBUTABLE to the per-option value features, or merely inherited from the
family-only floor?  Two complementary tests:

  * the DIRECT attribution arm  ov_vs_floor  (does the treatment beat its own floor?);
  * a Fisher-exact INCREMENT test comparing the treatment's parent-beating rate
    (ov_vs_parent) against the floor's parent-beating rate (floor_vs_parent) — a
    non-significant result means option-value adds nothing over the floor at beating
    the parent.

Self-mirror noise controls (parent_vs_parent, ov_vs_ov), if run, must straddle 0.50
(Wilson CI contains 0.50) or a measured practical edge cannot be trusted.

LOCAL / READ-ONLY: no games, no mutation, no upload, no events. Writes
data/experiments/pass46i_edge_analysis.{json,md}. Exit 0 iff analysis resolves.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46i_eval_plan.json"
JSONL = EXP / "pass46i_water_confirmation_games.jsonl"

TREATMENT = "cg_typed_water_option_value_v1"
ATTRIBUTION_PANEL = "ov_vs_floor"
PRACTICAL_PANEL = "ov_vs_parent"
FLOOR_PARENT_PANEL = "floor_vs_parent"
NOISE_PANELS = ("parent_vs_parent", "ov_vs_ov")


def wilson(k: int, n: int, z: float) -> tuple:
    if n == 0:
        return (None, None, None)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(p, 4), round(center - half, 4), round(center + half, 4))


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for table [[a,b],[c,d]] (fixed margins)."""
    row1, row2 = a + b, c + d
    col1, n = a + c, a + b + c + d
    if n == 0:
        return 1.0

    def prob(a_: int) -> float:
        b_ = row1 - a_
        c_ = col1 - a_
        d_ = row2 - c_
        if min(a_, b_, c_, d_) < 0:
            return 0.0
        return (math.comb(row1, a_) * math.comb(row2, c_)) / math.comb(n, col1)

    p_obs = prob(a)
    lo, hi = max(0, col1 - row2), min(col1, row1)
    total = sum(prob(a_) for a_ in range(lo, hi + 1)
                if prob(a_) <= p_obs * (1 + 1e-9))
    return min(1.0, round(total, 5))


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
            "total": 0, "invalid": 0, "draws": 0, "decisive": 0, "subj_wins": 0,
            "seat": {0: {"d": 0, "w": 0}, 1: {"d": 0, "w": 0}}})
        d["total"] += 1
        if r.get("invalid"):
            d["invalid"] += 1
            continue
        if r.get("decisive"):
            d["decisive"] += 1
            seat = int(r.get("subject_seat", 0))
            d["seat"][seat]["d"] += 1
            if r.get("winner") == "subject":
                d["subj_wins"] += 1
                d["seat"][seat]["w"] += 1
        else:
            d["draws"] += 1
    return panels


def analyse_panel(pid: str, d: dict, th: dict) -> dict:
    z = th["wilson_z"]
    dec = d["decisive"]
    wins = d["subj_wins"]
    point, wlo, whi = wilson(wins, dec, z)
    s0, s1 = d["seat"][0], d["seat"][1]
    s0_wr = round(s0["w"] / s0["d"], 4) if s0["d"] else None
    s1_wr = round(s1["w"] / s1["d"], 4) if s1["d"] else None
    invalid_rate = round(d["invalid"] / d["total"], 4) if d["total"] else 0.0
    unsafe_invalid = (d["invalid"] > th["invalid_abs_tol"]
                      and invalid_rate > th["invalid_rate_tol"])
    seat_confounded = False
    if s0_wr is not None and s1_wr is not None:
        hi, lo = th["seat_confound_hi"], th["seat_confound_lo"]
        seat_confounded = ((s0_wr >= hi and s1_wr <= lo)
                           or (s1_wr >= hi and s0_wr <= lo))

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
        "panel_id": pid, "subject_id": d["subject_id"],
        "opponent_id": d["opponent_id"], "n_total": d["total"],
        "n_decisive": dec, "n_invalid": d["invalid"], "n_draws": d["draws"],
        "invalid_rate": invalid_rate, "subject_wins": wins,
        "point": point, "wilson_low": wlo, "wilson_high": whi,
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

    attribution = analyses.get(ATTRIBUTION_PANEL)
    practical = analyses.get(PRACTICAL_PANEL)
    floor_parent = analyses.get(FLOOR_PARENT_PANEL)

    # Fisher-exact INCREMENT test: does option-value beat the parent MORE OFTEN than the
    # family-only floor does? Non-significant => the parent edge is the FLOOR's, not the
    # option-value layer's.
    increment = None
    if practical and floor_parent and practical["n_decisive"] and floor_parent["n_decisive"]:
        a = practical["subject_wins"]
        b = practical["n_decisive"] - a
        c = floor_parent["subject_wins"]
        dd = floor_parent["n_decisive"] - c
        p_val = fisher_exact_2x2(a, b, c, dd)
        increment = {
            "test": "Fisher-exact two-sided: ov-vs-parent wins vs floor-vs-parent wins",
            "ov_vs_parent": [a, b], "floor_vs_parent": [c, dd],
            "ov_parent_rate": practical["point"], "floor_parent_rate": floor_parent["point"],
            "p_value": p_val, "significant_at_0_05": p_val < 0.05,
            "interpretation": ("option-value beats the parent significantly more/less "
                               "often than the floor does"
                               if p_val < 0.05 else
                               "NO significant difference — any parent edge is inherited "
                               "from the family-only floor, not added by option-value"),
        }

    attribution_label = attribution["edge_label"] if attribution else "missing"
    practical_label = practical["edge_label"] if practical else "missing"
    noise_required = practical_label in ("confirmed_edge", "directional_edge")
    noise_results = {p: analyses[p]["noise_clean"] for p in NOISE_PANELS
                     if p in analyses}
    noise_clean = (all(v for v in noise_results.values())
                   if noise_results else None)

    decision_inputs = {
        "attribution_panel": ATTRIBUTION_PANEL, "attribution_label": attribution_label,
        "practical_panel": PRACTICAL_PANEL, "practical_label": practical_label,
        "attribution_beats_floor_confirmed": attribution_label == "confirmed_edge",
        "practical_beats_parent_confirmed": practical_label == "confirmed_edge",
        "practical_beats_parent_directional": practical_label == "directional_edge",
        "any_gating_unsafe_invalid": any(
            a and a["edge_label"] == "unsafe_invalid"
            for a in (attribution, practical)),
        "attribution_increment_significant": (increment["significant_at_0_05"]
                                              if increment else None),
        "noise_required": noise_required, "noise_results": noise_results,
        "noise_clean": noise_clean,
    }

    all_ok = attribution is not None and practical is not None
    data = {
        "pass": "46i", "part": "E", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "thresholds": th,
        "panels": analyses,
        "attribution_increment_fisher": increment,
        "decision_inputs": decision_inputs,
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_edge_analysis.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def fmt(a: dict) -> str:
        return (f"| `{a['panel_id']}` | {a['point']} | "
                f"[{a['wilson_low']}, {a['wilson_high']}] | {a['n_decisive']} | "
                f"{a['seat0']['win_rate']} | {a['seat1']['win_rate']} | "
                f"{a['seat_confounded']} | {a['n_invalid']} | **{a['edge_label']}** |")

    order = [ATTRIBUTION_PANEL, PRACTICAL_PANEL, FLOOR_PARENT_PANEL,
             "conservative_vs_ov", *NOISE_PANELS]
    md = [
        "# Pass 46I (Part E) — parent / floor / noise analysis", "",
        "_LOCAL / READ-ONLY. Wilson 95% intervals, per-seat splits + seat-confound, and "
        "the pre-registered edge labels for every panel, plus a Fisher-exact INCREMENT "
        "test of whether the option-value layer beats the real parent any more often than "
        "the family-only floor already does._", "",
        "## Per-panel edge labels",
        "| panel | point | Wilson 95% | decisive | seat0 wr | seat1 wr | seat-conf | "
        "invalid | label |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for pid in order:
        if pid in analyses:
            md.append(fmt(analyses[pid]))
    md += ["", "## Attribution increment (Fisher-exact)"]
    if increment:
        md += [
            f"- ov-vs-parent wins/losses: {increment['ov_vs_parent']} "
            f"(rate {increment['ov_parent_rate']})",
            f"- floor-vs-parent wins/losses: {increment['floor_vs_parent']} "
            f"(rate {increment['floor_parent_rate']})",
            f"- **two-sided p = {increment['p_value']}** "
            f"(significant@0.05: {increment['significant_at_0_05']})",
            f"- → {increment['interpretation']}",
        ]
    md += ["", "## Decision inputs",
           f"- ATTRIBUTION (`{ATTRIBUTION_PANEL}`): **{attribution_label}**",
           f"- PRACTICAL (`{PRACTICAL_PANEL}`): **{practical_label}**",
           f"- noise controls required: {noise_required} | results: {noise_results} | "
           f"clean: {noise_clean}", "",
           f"**all_ok = {all_ok}**"]
    (EXP / "pass46i_edge_analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_ok,
                      "attribution_label": attribution_label,
                      "practical_label": practical_label,
                      "attribution_increment_p": (increment["p_value"]
                                                  if increment else None),
                      "increment_significant": (increment["significant_at_0_05"]
                                                if increment else None),
                      "noise_required": noise_required, "noise_clean": noise_clean},
                     indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
