#!/usr/bin/env python3
"""PASS 46F (Part D) — interpretable offline calibration of the turn scorer.

Turns the Pass-46F Part-C label dataset (oracle one-step scores per action
family) into a calibrated, fully explainable score profile for
``turn_scorer.py``. The calibration is deterministic and transparent:

    calibrated_weight(family) =
        structural_prior(family)
        + GAIN * clamp(robust_median(family) / MEDIAN_REF, -1, +1)   [if n >= MIN_N]

* ``structural_prior`` — a small, fixed "make progress, end the turn LAST"
  ordering. It is the floor that keeps board-development families (which pay off
  over MULTIPLE turns and therefore show ~0 ONE-step visible delta) ranked above
  ending the turn even when the one-step oracle is silent.
* The oracle component uses the ROBUST MEDIAN, never the mean: a few branches
  score huge under fabricated hidden zones (e.g. select_card mean 112 vs median
  0), and the mean would overfit those. ``MEDIAN_REF`` = 8.0 = "one energy
  attached" — a natural, interpretable unit.
* Families with < MIN_N supported samples fall back to the structural prior alone
  (insufficient evidence to calibrate).

Also computes an HONEST IN-SAMPLE alignment metric: on the calibration frames,
does the calibrated profile pick actions with higher oracle one-step value than
the uncalibrated ``generic_progress_v0`` baseline? (In-sample fit only —
generalization is tested by actual gameplay in Part H, never claimed here.)

LOCAL / READ-ONLY. No mutation, no upload, no candidate generation, no events.
Runnable standalone and importable (``run_calibration() -> dict``).
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import turn_scorer as TS  # noqa: E402

EXP = REPO / "data" / "experiments"
LABELS = EXP / "pass46f_turn_label_dataset.json"

GAIN = 1.0
MEDIAN_REF = 8.0
MIN_N = 5

# Small fixed "make progress, end turn LAST" prior (family -> weight).
STRUCTURAL_PRIOR = {
    "use_ability": 0.6, "attach_energy": 0.5, "play_from_hand": 0.4,
    "play_in_play": 0.4, "attack": 0.35, "move_energy": 0.3,
    "select_card": 0.3, "effect_choice": 0.2, "unknown": 0.1, "end_turn": -0.5,
}


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _robust_family_stats(rows):
    by_fam: dict[str, list[float]] = {}
    for r in rows:
        if not r.get("supported"):
            continue
        by_fam.setdefault(r.get("candidate_family", "unknown"), []).append(
            float(r.get("oracle_score") or 0.0))
    stats = {}
    for fam, xs in by_fam.items():
        s = sorted(xs)
        stats[fam] = {
            "n": len(s),
            "mean": round(statistics.fmean(s), 4),
            "median": round(statistics.median(s), 4),
            "positive_rate": round(sum(1 for v in s if v > 0) / len(s), 4),
            "min": round(s[0], 4), "max": round(s[-1], 4),
        }
    return stats


def run_calibration() -> dict:
    if not LABELS.exists():
        raise SystemExit("missing label dataset; run Part C first")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    rows = labels.get("rows") or []
    fam_stats = _robust_family_stats(rows)

    baseline = TS.baseline_profile()
    base_w = baseline["weights"]

    # Build calibrated weights over every feature key.
    weights = {"bias": 0.0}
    per_family_calc = {}
    for fam, fkey in TS.FAMILY_FEATURE.items():
        prior = STRUCTURAL_PRIOR.get(fam, 0.0)
        st = fam_stats.get(fam)
        if st and st["n"] >= MIN_N:
            oracle_component = GAIN * _clamp(st["median"] / MEDIAN_REF, -1.0, 1.0)
            used = "structural_prior + oracle_median"
        else:
            oracle_component = 0.0
            used = "structural_prior_only_insufficient_evidence"
        w = round(prior + oracle_component, 4)
        weights[fkey] = w
        per_family_calc[fam] = {
            "feature_key": fkey, "structural_prior": prior,
            "oracle_median": (st["median"] if st else None),
            "oracle_n": (st["n"] if st else 0),
            "oracle_component": round(oracle_component, 4),
            "calibrated_weight": w, "baseline_weight": base_w.get(fkey),
            "delta_vs_baseline": round(w - (base_w.get(fkey) or 0.0), 4),
            "rule": used,
        }

    profile = {
        "profile_id": "search_calibrated_v0",
        "schema_version": TS.PROFILE_SCHEMA_VERSION,
        "calibrated": True,
        "source": "offline_search_oracle_calibration",
        "calibration": {
            "method": "structural_prior + GAIN*clamp(median/MEDIAN_REF,-1,1)",
            "gain": GAIN, "median_ref": MEDIAN_REF, "min_n": MIN_N,
            "robust_statistic": "median (mean rejected: fabricated-hidden-state "
            "outliers, e.g. select_card mean>>median)",
            "label_dataset": "pass46f_turn_label_dataset.json",
            "n_candidate_items": labels.get("n_candidate_items"),
            "n_supported_items": labels.get("n_supported_items"),
        },
        "weights": weights,
        "structural_prior": STRUCTURAL_PRIOR,
        "no_online_search": True,
        "unsupported_claims": TS.unsupported_scorer_claims(),
    }

    # ---- HONEST in-sample alignment metric: baseline vs calibrated picks ----
    frames: dict[tuple, list[dict]] = {}
    for r in rows:
        if not r.get("supported"):
            continue
        key = (r.get("trace"), r.get("step"), r.get("seat"))
        frames.setdefault(key, []).append(r)

    def _pick(cands, w):
        best = None
        for c in cands:
            fkey = TS.FAMILY_FEATURE.get(c.get("candidate_family", "unknown"),
                                         "fam_other")
            sc = w.get(fkey, 0.0)
            idx = (c.get("selected") or [10 ** 9])[0]
            key = (sc, -idx)
            if best is None or key > best[0]:
                best = (key, c)
        return best[1] if best else None

    base_scores, cal_scores = [], []
    agree = 0
    n_frames_eval = 0
    for key, cands in frames.items():
        if len({c.get("candidate_family") for c in cands}) < 2:
            continue  # trivial: only one family available
        n_frames_eval += 1
        bp = _pick(cands, base_w)
        cp = _pick(cands, weights)
        if bp is not None:
            base_scores.append(float(bp.get("oracle_score") or 0.0))
        if cp is not None:
            cal_scores.append(float(cp.get("oracle_score") or 0.0))
        if bp is not None and cp is not None and bp.get("selected") == cp.get("selected"):
            agree += 1

    def _ms(xs):
        return {"n": len(xs),
                "mean": round(statistics.fmean(xs), 4) if xs else None,
                "median": round(statistics.median(xs), 4) if xs else None}

    base_ms, cal_ms = _ms(base_scores), _ms(cal_scores)
    in_sample = {
        "n_nontrivial_frames": n_frames_eval,
        "agreement_rate": round(agree / n_frames_eval, 4) if n_frames_eval else None,
        "baseline_pick_oracle_score": base_ms,
        "calibrated_pick_oracle_score": cal_ms,
        "median_improvement": (
            round((cal_ms["median"] or 0) - (base_ms["median"] or 0), 4)
            if base_ms["median"] is not None else None),
        "mean_improvement": (
            round((cal_ms["mean"] or 0) - (base_ms["mean"] or 0), 4)
            if base_ms["mean"] is not None else None),
        "note": "IN-SAMPLE fit on calibration frames only; NOT a generalization or "
        "win-rate claim. Real gameplay is evaluated in Part H.",
    }

    data = {
        "pass": "46f", "part": "D", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "candidate_generated": False,
        "baseline_profile_id": baseline["profile_id"],
        "calibrated_profile": profile,
        "family_oracle_stats": fam_stats,
        "per_family_calc": per_family_calc,
        "in_sample_alignment": in_sample,
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46f_score_profile.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46F — Part D: interpretable search-calibrated score profile", "",
        "_Deterministic calibration of `turn_scorer.py` from the Part-C oracle "
        "label dataset. Robust MEDIAN (not mean) + a fixed structural prior. "
        "LOCAL / READ-ONLY; no online search, no upload, no generation, no events. "
        "No best-action / damage / lethal claim._", "",
        f"method: `structural_prior + {GAIN}*clamp(median/{MEDIAN_REF}, -1, 1)` "
        f"(min_n={MIN_N})", "",
        "## Per-family calibration (baseline -> calibrated)",
        "| family | prior | oracle median (n) | calibrated | baseline | delta |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for fam, c in sorted(per_family_calc.items(),
                         key=lambda kv: -kv[1]["calibrated_weight"]):
        md.append(f"| {fam} | {c['structural_prior']} | {c['oracle_median']} "
                  f"({c['oracle_n']}) | {c['calibrated_weight']} | "
                  f"{c['baseline_weight']} | {c['delta_vs_baseline']:+} |")
    md += [
        "", "## In-sample alignment (calibrated vs baseline picks)",
        f"- non-trivial frames: {in_sample['n_nontrivial_frames']}",
        f"- agreement rate: {in_sample['agreement_rate']}",
        f"- baseline pick oracle score: {base_ms}",
        f"- calibrated pick oracle score: {cal_ms}",
        f"- median improvement: {in_sample['median_improvement']} | "
        f"mean improvement: {in_sample['mean_improvement']}",
        f"- _{in_sample['note']}_",
    ]
    (EXP / "pass46f_score_profile.md").write_text("\n".join(md) + "\n",
                                                  encoding="utf-8")

    print(json.dumps({
        "profile_id": profile["profile_id"],
        "weights": weights,
        "in_sample_alignment": {k: in_sample[k] for k in (
            "n_nontrivial_frames", "agreement_rate", "median_improvement",
            "mean_improvement")},
    }, indent=2, default=str))
    return data


if __name__ == "__main__":
    run_calibration()
