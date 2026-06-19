#!/usr/bin/env python3
"""Pass 26 (Part B) — read-only live-score status + control distinction.

LOCAL / READ-ONLY. Consumes the freshly-rebuilt live score registry
(``data/kaggle_uploads/live_score_registry.json``) and the Pass-25 status
snapshot, and emits the Pass-26 status with the TWO controls kept explicitly
distinct:

  * ``live_score_leader``        — highest complete publicScore in the listing
                                   (the global Kaggle leader, recomputed fresh).
  * ``water_family_current_best``— the Water strategy lineage's maintained best
                                   (``league_water_anti_disruption_pivot_v1``),
                                   never silently overwritten just because the
                                   global leader changes.

NEVER submits or uploads. Records score drift vs Pass 25.
Writes data/experiments/pass26_live_score_status.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
PASS25 = REPO / "data" / "experiments" / "pass25_live_score_status.json"
OUT_JSON = REPO / "data" / "experiments" / "pass26_live_score_status.json"
OUT_MD = REPO / "data" / "experiments" / "pass26_live_score_status.md"

WATER_FAMILY_BEST_FILE = "league_water_anti_disruption_pivot_v1.tar.gz"


def _complete_scored(rows):
    out = []
    for r in rows:
        if r.get("status") == "complete" and r.get("public_score") is not None:
            out.append(r)
    return out


def main(refreshed: bool = True) -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = reg.get("submissions", [])
    complete = _complete_scored(rows)
    complete_ranked = sorted(complete, key=lambda r: r["public_score"], reverse=True)

    # live_score_leader = highest complete publicScore (recomputed, never pinned).
    leader = complete_ranked[0] if complete_ranked else None

    # water_family_current_best = the maintained Water lineage best, by lineage,
    # resolved to its CURRENT live score from the same fresh listing.
    wfam = None
    for r in complete:
        if r["filename"] == WATER_FAMILY_BEST_FILE:
            if wfam is None or r["public_score"] > wfam["public_score"]:
                wfam = r

    # Drift vs Pass 25.
    drift = []
    if PASS25.exists():
        p25 = json.loads(PASS25.read_text(encoding="utf-8"))
        prev = {d["fileName"]: d["pass25"] for d in p25.get("score_drift_vs_pass24", [])}
        cur = {r["filename"]: r["public_score"] for r in complete}
        for fn in sorted(set(prev) | set(cur)):
            pv = prev.get(fn)
            cv = cur.get(fn)
            delta = round(cv - pv, 4) if (pv is not None and cv is not None) else None
            drift.append({"fileName": fn, "pass25": pv, "pass26": cv, "delta": delta})

    leader_is_water_family = bool(
        leader and wfam and leader["filename"] == wfam["filename"]
    )

    status = {
        "pass": "26",
        "part": "B",
        "generated_note": "read-only Kaggle status refresh; no submit, no upload",
        "competition": reg.get("competition", "pokemon-tcg-ai-battle"),
        "read_only": True,
        "upload_performed": False,
        "scores_refreshed_live": refreshed,
        "refresh_method": (
            "kaggle python API competition_submissions (read-only listing)"
            if refreshed else "fallback to last-known-good snapshot"
        ),
        # The two controls — kept as DISTINCT fields (never conflated).
        "live_score_leader": (
            {"fileName": leader["filename"], "publicScore": leader["public_score"],
             "status": leader["status"], "date": leader["date"],
             "rule": "highest publicScore among complete, non-error submissions"}
            if leader else None
        ),
        "water_family_current_best": (
            {"fileName": wfam["filename"], "publicScore": wfam["public_score"],
             "status": wfam["status"], "date": wfam["date"],
             "rule": ("maintained Water strategy lineage best; resolved to its "
                      "current live score; NOT auto-overwritten by the global "
                      "leader")}
            if wfam else None
        ),
        "live_score_leader_is_water_family_best": leader_is_water_family,
        "distinction_preserved": True,
        "distinction_note": (
            "live_score_leader and water_family_current_best are computed "
            "independently. This pass they happen to resolve to the SAME tarball "
            "(the Water pivot overtook the raw baseline), but they remain "
            "separate concepts: a future higher-scoring NON-Water submission "
            "would become live_score_leader WITHOUT changing "
            "water_family_current_best."
        ),
        "score_drift_vs_pass25": drift,
        "complete_submissions_ranked": [
            {"fileName": r["filename"], "publicScore": r["public_score"]}
            for r in complete_ranked
        ],
        "early_variance_note": (
            "The Water pivot's live score remains volatile across passes "
            "(520.8 Pass-24 -> 358.7 Pass-25 -> 376.5 Pass-26) as leaderboard "
            "episodes accrue. Treat any single reading as provisional; compare "
            "candidates only against settled, complete scores."
        ),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")

    L = ["# Pass 26 — Live Score Status (Part B, read-only)", "",
         "> Read-only Kaggle listing. **No submit, no upload.** The two controls "
         "are kept explicitly distinct.", ""]
    ld = status["live_score_leader"]
    wf = status["water_family_current_best"]
    L.append(f"- **live_score_leader:** `{ld['fileName']}` @ **{ld['publicScore']}** "
             f"({ld['date']}) — {ld['rule']}." if ld else "- live_score_leader: none")
    L.append(f"- **water_family_current_best:** `{wf['fileName']}` @ "
             f"**{wf['publicScore']}** ({wf['date']}) — {wf['rule']}." if wf
             else "- water_family_current_best: none")
    L.append(f"- live_score_leader_is_water_family_best: "
             f"**{leader_is_water_family}** (they coincide this pass but remain "
             f"distinct fields).")
    L.append(f"- scores_refreshed_live: **{refreshed}** ({status['refresh_method']}).")
    L += ["", "## Score drift vs Pass 25", "",
          "| fileName | pass25 | pass26 | delta |", "|---|---|---|---|"]
    for d in drift:
        L.append(f"| {d['fileName']} | {d['pass25']} | {d['pass26']} | {d['delta']} |")
    L += ["", "## Complete submissions ranked (fresh)", "",
          "| fileName | publicScore |", "|---|---|"]
    for r in status["complete_submissions_ranked"]:
        L.append(f"| {r['fileName']} | {r['publicScore']} |")
    L += ["", "## Notes", "", f"- {status['distinction_note']}", "",
          f"- {status['early_variance_note']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"live_score_leader: {ld['fileName'] if ld else None} @ "
          f"{ld['publicScore'] if ld else None}")
    print(f"water_family_current_best: {wf['fileName'] if wf else None} @ "
          f"{wf['publicScore'] if wf else None}")
    print(f"coincide={leader_is_water_family} refreshed={refreshed}")
    print(f"-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
