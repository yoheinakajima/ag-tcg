#!/usr/bin/env python3
"""Pass 27 (Part B) — read-only live-score status + control distinction.

LOCAL / READ-ONLY. Consumes the live score registry
(``data/kaggle_uploads/live_score_registry.json``) and the Pass-26 status
snapshot, and emits the Pass-27 status with the TWO controls kept explicitly
distinct:

  * ``live_score_leader``        — highest complete publicScore in the listing
                                   (the global Kaggle leader, recomputed fresh).
  * ``water_family_current_best``— the Water strategy lineage's maintained best
                                   (``league_water_anti_disruption_pivot_v1``),
                                   resolved to its CURRENT live score; NEVER
                                   silently overwritten just because the global
                                   leader changes.

This pass is a PORTFOLIO / core-gameplay generalization pass, NOT a promotion
decision: the live score is reported for context only and never gates a build.
NEVER submits or uploads. Records score drift vs Pass 26.
Writes data/experiments/pass27_live_score_status.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
PASS26 = REPO / "data" / "experiments" / "pass26_live_score_status.json"
OUT_JSON = REPO / "data" / "experiments" / "pass27_live_score_status.json"
OUT_MD = REPO / "data" / "experiments" / "pass27_live_score_status.md"

WATER_FAMILY_BEST_FILE = "league_water_anti_disruption_pivot_v1.tar.gz"


def _complete_scored(rows):
    out = []
    for r in rows:
        if r.get("status") == "complete" and r.get("public_score") is not None:
            try:
                r = {**r, "public_score": float(r["public_score"])}
            except (TypeError, ValueError):
                continue
            out.append(r)
    return out


def main(refreshed: bool = False) -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = reg.get("submissions", [])
    complete = _complete_scored(rows)
    complete_ranked = sorted(complete, key=lambda r: r["public_score"], reverse=True)

    leader = complete_ranked[0] if complete_ranked else None
    wfam = None
    for r in complete:
        if r["filename"] == WATER_FAMILY_BEST_FILE:
            if wfam is None or r["public_score"] > wfam["public_score"]:
                wfam = r

    # Drift vs Pass 26.
    drift = []
    if PASS26.exists():
        p26 = json.loads(PASS26.read_text(encoding="utf-8"))
        prev = {}
        for r in p26.get("complete_submissions_ranked", []):
            prev[r["fileName"]] = r["publicScore"]
        cur = {r["filename"]: r["public_score"] for r in complete}
        for fn in sorted(set(prev) | set(cur)):
            pv, cv = prev.get(fn), cur.get(fn)
            delta = round(cv - pv, 4) if (pv is not None and cv is not None) else None
            drift.append({"fileName": fn, "pass26": pv, "pass27": cv, "delta": delta})

    leader_is_water_family = bool(
        leader and wfam and leader["filename"] == wfam["filename"])

    status = {
        "pass": "27", "part": "B",
        "generated_note": "read-only Kaggle status refresh; no submit, no upload",
        "competition": reg.get("competition", "pokemon-tcg-ai-battle"),
        "read_only": True, "upload_performed": False,
        "is_promotion_decision": False,
        "promotion_note": ("Pass 27 is a portfolio / core-gameplay generalization "
                           "pass. The live score is context only and never gates a "
                           "build or a promotion."),
        "scores_refreshed_live": refreshed,
        "refresh_method": (
            "kaggle python API competition_submissions (read-only listing)"
            if refreshed else
            "fallback to last-known-good registry snapshot "
            f"(generated {reg.get('generated_at')}); no live Kaggle call this pass"),
        "live_score_leader": (
            {"fileName": leader["filename"], "publicScore": leader["public_score"],
             "status": leader["status"], "date": leader["date"],
             "classification": leader.get("classification"),
             "rule": "highest publicScore among complete, non-error submissions"}
            if leader else None),
        "water_family_current_best": (
            {"fileName": wfam["filename"], "publicScore": wfam["public_score"],
             "status": wfam["status"], "date": wfam["date"],
             "classification": wfam.get("classification"),
             "rule": ("maintained Water strategy lineage best; resolved to its "
                      "current live score; NOT auto-overwritten by the global "
                      "leader")}
            if wfam else None),
        "live_score_leader_is_water_family_best": leader_is_water_family,
        "distinction_preserved": True,
        "distinction_note": (
            "live_score_leader and water_family_current_best are computed "
            "independently and kept as separate fields. A future higher-scoring "
            "NON-Water submission would become live_score_leader WITHOUT changing "
            "water_family_current_best."),
        "score_drift_vs_pass26": drift,
        "complete_submissions_ranked": [
            {"fileName": r["filename"], "publicScore": r["public_score"],
             "classification": r.get("classification")} for r in complete_ranked],
        "early_variance_note": (
            "The Water pivot's live score remains volatile across passes as "
            "leaderboard episodes accrue. Treat any single reading as provisional; "
            "compare candidates only against settled, complete scores."),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")

    ld, wf = status["live_score_leader"], status["water_family_current_best"]
    L = ["# Pass 27 — Live Score Status (Part B, read-only)", "",
         "> Read-only Kaggle listing. **No submit, no upload.** Portfolio pass — "
         "the live score is context only and does NOT gate any build or promotion. "
         "The two controls are kept explicitly distinct.", "",
         (f"- **live_score_leader:** `{ld['fileName']}` @ **{ld['publicScore']}** "
          f"({ld['date']}) — {ld['rule']}." if ld else "- live_score_leader: none"),
         (f"- **water_family_current_best:** `{wf['fileName']}` @ "
          f"**{wf['publicScore']}** ({wf['date']}) — {wf['rule']}." if wf
          else "- water_family_current_best: none"),
         f"- live_score_leader_is_water_family_best: **{leader_is_water_family}**.",
         f"- scores_refreshed_live: **{refreshed}** ({status['refresh_method']}).",
         "", "## Score drift vs Pass 26", "",
         "| fileName | pass26 | pass27 | delta |", "|---|---|---|---|"]
    for d in drift:
        L.append(f"| {d['fileName']} | {d['pass26']} | {d['pass27']} | {d['delta']} |")
    L += ["", "## Complete submissions ranked (read-only)", "",
          "| fileName | publicScore | classification |", "|---|---|---|"]
    for r in status["complete_submissions_ranked"]:
        L.append(f"| {r['fileName']} | {r['publicScore']} | {r['classification']} |")
    L += ["", "## Notes", "", f"- {status['promotion_note']}", "",
          f"- {status['distinction_note']}", "",
          f"- {status['early_variance_note']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"live_score_leader: {ld['fileName'] if ld else None} @ "
          f"{ld['publicScore'] if ld else None}")
    print(f"water_family_current_best: {wf['fileName'] if wf else None} @ "
          f"{wf['publicScore'] if wf else None}")
    print(f"coincide={leader_is_water_family} refreshed={refreshed} "
          f"-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
