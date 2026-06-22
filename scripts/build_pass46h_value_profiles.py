#!/usr/bin/env python3
"""PASS 46H (Part E) — interpretable per-family value profiles + offline MEASUREMENT.
LOCAL / read-only.

Consumes the Pass-46H Part-D dataset (``pass46h_option_value_dataset.json``) and the
measurement role map. For each of the three profiles
(``family_only_floor_v1`` / ``option_value_v1`` / ``conservative_option_value_v1``) it
measures, on the HEADLINE rows (family-homogeneous, single-index, resolvable, INTERNAL
options grouped by decision frame):

* **oracle top-1 agreement** — how often the profile's within-family pick is the option
  with the highest oracle one-step score in that frame (tie -> lowest option index).
* **median oracle lift vs the floor** — median of (oracle_score[profile pick] -
  oracle_score[floor pick]) across decisive frames.
* **divergence vs the floor** — fraction of frames where the profile's pick differs from
  the floor's pick (the floor cannot differentiate WITHIN a homogeneous family, so it
  deterministically takes the lowest index; this is the inertness baseline).

The >= 5% top-1-change gate (charter): does ``option_value_v1`` change the within-family
pick on >= 5% of decisive frames AND not REDUCE oracle agreement vs the floor?

This is an IN-SAMPLE OFFLINE measurement on a SMALL panel (Diamond is absent; only
internal Water/Lightning frames carry oracle labels). It is NOT a win-rate, strength, or
generalization claim — real gameplay is screened in Parts G-I. Oracle scores are
ASSUMPTION-BASED; never exact. No exact-damage / lethal / missed-KO / Boss-gust / spread /
best-action claim. No mutation, no upload, no candidate generation, no events.

Writes data/experiments/pass46h_value_profiles.{json,md}. Importable:
``run_profiles() -> dict``.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.analysis import option_value_features as OV  # noqa: E402

EXP = REPO / "data" / "experiments"
D_DATASET = EXP / "pass46h_option_value_dataset.json"
D_ROLE_MAP = EXP / "pass46h_measurement_role_map.json"

MIN_DECISIVE_FRAMES = 5  # coverage floor below which the result is INCONCLUSIVE
TOP1_CHANGE_GATE = 0.05  # charter >= 5% within-family pick change


def _scorable(feat_row: dict) -> dict:
    """Reconstruct a score_option-ready feature dict from a stored Part-D feat_row."""
    f = dict(feat_row or {})
    f.setdefault("bias", 1.0)
    return f


def _pick(options, profile):
    """Return the selected option index maximising the profile score (tie -> lowest)."""
    best = None
    for opt in options:
        sc = OV.score_option(_scorable(opt["features"]), profile)
        key = (sc, -opt["sel_idx"])
        if best is None or key > best[0]:
            best = (key, opt["sel_idx"], opt)
    return best[1], best[2]


def _oracle_best(options):
    best = None
    for opt in options:
        sc = opt["oracle_score"]
        sc = float(sc) if isinstance(sc, (int, float)) else float("-inf")
        key = (sc, -opt["sel_idx"])
        if best is None or key > best[0]:
            best = (key, opt["sel_idx"], sc)
    return best[1], best[2]


def run_profiles() -> dict:
    data = json.loads(D_DATASET.read_text(encoding="utf-8"))
    role_map = json.loads(D_ROLE_MAP.read_text(encoding="utf-8"))
    rows = data.get("rows") or []

    profiles = OV.default_profiles(role_map)

    # group headline-internal single-index resolvable rows by decision frame
    frames = defaultdict(list)
    for r in rows:
        if not (r.get("group_homogeneous") and r.get("single_index")
                and r.get("resolvable") and r.get("is_internal")):
            continue
        sel = r.get("selected") or []
        if not (len(sel) == 1 and isinstance(sel[0], int)):
            continue
        frames[(r["trace"], r["step"], r["seat"])].append({
            "sel_idx": sel[0],
            "oracle_score": r.get("oracle_score"),
            "features": r.get("features"),
            "family": r.get("candidate_family"),
        })

    # only frames with a genuine within-family CHOICE (>= 2 resolvable options)
    choice_frames = {k: v for k, v in frames.items() if len(v) >= 2}
    # decisive = the oracle actually prefers one option (scores differ)
    decisive_frames = {}
    for k, opts in choice_frames.items():
        scs = [o["oracle_score"] for o in opts
               if isinstance(o["oracle_score"], (int, float))]
        if len(set(scs)) >= 2:
            decisive_frames[k] = opts

    floor = profiles["family_only_floor_v1"]
    floor_picks = {k: _pick(opts, floor)[0] for k, opts in choice_frames.items()}

    results = {}
    for pid, prof in profiles.items():
        agree = 0
        lifts = []
        diverge = 0
        n_dec = 0
        per_frame = []
        for k, opts in choice_frames.items():
            pick_idx, pick_opt = _pick(opts, prof)
            ob_idx, ob_score = _oracle_best(opts)
            pick_oscore = pick_opt["oracle_score"]
            pick_oscore = float(pick_oscore) if isinstance(
                pick_oscore, (int, float)) else float("nan")
            is_decisive = k in decisive_frames
            if is_decisive:
                n_dec += 1
                if pick_idx == ob_idx or pick_oscore == ob_score:
                    agree += 1
                fp = floor_picks[k]
                fo = next((o["oracle_score"] for o in opts if o["sel_idx"] == fp), None)
                if isinstance(fo, (int, float)) and isinstance(pick_oscore, float):
                    lifts.append(pick_oscore - float(fo))
                if pick_idx != fp:
                    diverge += 1
            per_frame.append({
                "frame": [k[0], k[1], k[2]], "family": opts[0]["family"],
                "n_options": len(opts), "pick_idx": pick_idx,
                "oracle_best_idx": ob_idx, "decisive": is_decisive,
                "agree": bool(is_decisive and (pick_idx == ob_idx
                                               or pick_oscore == ob_score)),
            })
        results[pid] = {
            "scoring_mode": prof["scoring_mode"],
            "n_choice_frames": len(choice_frames),
            "n_decisive_frames": n_dec,
            "oracle_top1_agreement": round(agree / n_dec, 4) if n_dec else None,
            "median_oracle_lift_vs_floor": round(statistics.median(lifts), 4)
            if lifts else 0.0,
            "divergence_vs_floor": round(diverge / n_dec, 4) if n_dec else 0.0,
            "per_frame": per_frame,
        }

    floor_agree = results["family_only_floor_v1"]["oracle_top1_agreement"]
    ov = results["option_value_v1"]
    cons = results["conservative_option_value_v1"]
    n_dec = ov["n_decisive_frames"]

    coverage_sufficient = n_dec >= MIN_DECISIVE_FRAMES
    changes_picks = ov["divergence_vs_floor"] >= TOP1_CHANGE_GATE
    improves = (ov["oracle_top1_agreement"] is not None and floor_agree is not None
                and ov["oracle_top1_agreement"] >= floor_agree
                and ov["median_oracle_lift_vs_floor"] >= 0.0)

    if not coverage_sufficient:
        signal = "inconclusive_tiny_coverage"
    elif changes_picks and improves and ov["oracle_top1_agreement"] > floor_agree:
        signal = "option_value_promising"
    elif changes_picks and improves:
        signal = "option_value_changes_picks_neutral_oracle"
    elif not changes_picks:
        signal = "option_value_inert_like_floor"
    else:
        signal = "option_value_changes_picks_worse_oracle"

    out = {
        "pass": "46H", "part": "E_value_profiles",
        "local_only": True, "no_upload": True, "read_only": True,
        "min_decisive_frames_floor": MIN_DECISIVE_FRAMES,
        "top1_change_gate": TOP1_CHANGE_GATE,
        "schema_version": OV.PROFILE_SCHEMA_VERSION,
        "coverage_sufficient": coverage_sufficient,
        "option_value_changes_picks": changes_picks,
        "option_value_improves_oracle": improves,
        "floor_oracle_top1_agreement": floor_agree,
        "results": results,
        "signal": signal,
        "option_value_priors": OV.OPTION_VALUE_PRIORS,
        "caveats": [
            "IN-SAMPLE OFFLINE measurement on a SMALL panel; NOT a win-rate / strength / "
            "generalization claim. Real gameplay is screened in Parts G-I.",
            "The floor cannot differentiate WITHIN a homogeneous family, so it takes the "
            "lowest option index — this IS the documented 46G within-family inertness.",
            "Diamond is absent from the oracle-labelled panel; it transfers the SAME "
            "deck-agnostic role-bucket priors via its own role map.",
            "Oracle scores ASSUMPTION-BASED (fabricated hidden zones); never exact. "
            "No exact-damage / lethal / missed-KO / Boss-gust / spread / best-action claim.",
        ],
        "unsupported_claims": OV.unsupported_scorer_claims(),
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_value_profiles.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# PASS 46H — Part E: Interpretable Value Profiles + Oracle Measurement", "",
        f"- Schema `{out['schema_version']}`; decisive-frame floor "
        f"{MIN_DECISIVE_FRAMES}; top-1 change gate {TOP1_CHANGE_GATE:.0%}.",
        f"- Coverage sufficient: **{coverage_sufficient}** "
        f"({ov['n_decisive_frames']} decisive of {ov['n_choice_frames']} choice frames).",
        f"- **Signal: `{signal}`**.", "",
        "## Per-profile (decisive frames)", "",
        "| profile | mode | top-1 agree | median lift vs floor | divergence vs floor |",
        "|---|---|---|---|---|",
    ]
    for pid, res in results.items():
        md.append(
            f"| `{pid}` | {res['scoring_mode']} | {res['oracle_top1_agreement']} | "
            f"{res['median_oracle_lift_vs_floor']} | {res['divergence_vs_floor']} |")
    md += ["", "## Gates", "",
           f"- option_value changes picks (>= {TOP1_CHANGE_GATE:.0%}): "
           f"**{changes_picks}** (divergence {ov['divergence_vs_floor']}).",
           f"- option_value improves/holds oracle agreement: **{improves}** "
           f"(floor {floor_agree} -> option_value {ov['oracle_top1_agreement']}).", "",
           "## Caveats", ""]
    md += [f"- {c}" for c in out["caveats"]]
    (EXP / "pass46h_value_profiles.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def main() -> int:
    o = run_profiles()
    r = o["results"]
    print(f"OK: signal={o['signal']} coverage_ok={o['coverage_sufficient']} "
          f"floor_agree={o['floor_oracle_top1_agreement']} "
          f"ov_agree={r['option_value_v1']['oracle_top1_agreement']} "
          f"ov_div={r['option_value_v1']['divergence_vs_floor']} "
          f"cons_agree={r['conservative_option_value_v1']['oracle_top1_agreement']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
