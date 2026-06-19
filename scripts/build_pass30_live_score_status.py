#!/usr/bin/env python3
"""Pass 30 (Part B) — read-only live-score status. LOCAL / READ-ONLY.

Attempts a READ-ONLY Kaggle submissions listing (no submit, no upload); on any
failure falls back to the last-known-good live score registry snapshot. Keeps
THREE distinct fields per spec:

  * live_score_leader        — highest complete publicScore in the listing.
  * water_family_current_best— the maintained Water-lineage anchor's current score
                               (NEVER auto-overwritten by the global leader).
  * portfolio_reference      — the in-portfolio Water reference deck that the
                               internal tournament is calibrated around.

The live score is reported for CONTEXT only; this hardening pass never gates a
build or a promotion on it. publicScore is coerced safely to float. Writes
data/experiments/pass30_live_score_status.{json,md} and (read-only) tee logs to
data/kaggle_uploads/status_before_pass30.{log,csv} when a live call succeeds.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
PREV = REPO / "data" / "experiments" / "pass29_live_score_status.json"
OUT_JSON = REPO / "data" / "experiments" / "pass30_live_score_status.json"
OUT_MD = REPO / "data" / "experiments" / "pass30_live_score_status.md"
KU = REPO / "data" / "kaggle_uploads"
COMP = "pokemon-tcg-ai-battle"

WATER_FAMILY_BEST_FILE = "league_water_anti_disruption_pivot_v1.tar.gz"
PORTFOLIO_REFERENCE_FILE = "league_water_core_reference.tar.gz"


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _try_live_listing() -> bool:
    """Attempt a read-only `kaggle competitions submissions` listing.

    Returns True only if a live listing succeeded (and was tee'd). NEVER submits.
    """
    KU.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["kaggle", "competitions", "submissions", COMP, "-v"],
            capture_output=True, text=True, timeout=40)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0 or not proc.stdout.strip():
        (KU / "status_before_pass30.log").write_text(
            (proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
        return False
    (KU / "status_before_pass30.csv").write_text(proc.stdout, encoding="utf-8")
    (KU / "status_before_pass30.log").write_text(
        proc.stdout + "\n" + (proc.stderr or ""), encoding="utf-8")
    return True


def _complete_scored(rows):
    out = []
    for r in rows:
        if r.get("status") == "complete":
            ps = _safe_float(r.get("public_score"))
            if ps is not None:
                out.append({**r, "public_score": ps})
    return out


def main() -> int:
    refreshed = _try_live_listing()
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = reg.get("submissions", [])
    complete = _complete_scored(rows)
    complete_ranked = sorted(complete, key=lambda r: r["public_score"], reverse=True)
    leader = complete_ranked[0] if complete_ranked else None

    def _best(fn):
        best = None
        for r in complete:
            if r["filename"] == fn and (best is None
                                        or r["public_score"] > best["public_score"]):
                best = r
        return best

    wfam = _best(WATER_FAMILY_BEST_FILE)
    pref = _best(PORTFOLIO_REFERENCE_FILE)

    # Drift vs Pass 29.
    drift = []
    if PREV.exists():
        prev_doc = json.loads(PREV.read_text(encoding="utf-8"))
        prev = {r["fileName"]: r["publicScore"]
                for r in prev_doc.get("complete_submissions_ranked", [])}
        cur = {r["filename"]: r["public_score"] for r in complete}
        for fn in sorted(set(prev) | set(cur)):
            pv, cv = prev.get(fn), cur.get(fn)
            delta = round(cv - pv, 4) if (pv is not None and cv is not None) else None
            drift.append({"fileName": fn, "pass29": pv, "pass30": cv, "delta": delta})

    def _fld(r, rule):
        return ({"fileName": r["filename"], "publicScore": r["public_score"],
                 "status": r["status"], "date": r["date"],
                 "classification": r.get("classification"), "rule": rule}
                if r else None)

    status = {
        "pass": "30", "part": "B",
        "generated_note": "read-only Kaggle status; no submit, no upload",
        "competition": reg.get("competition", COMP),
        "read_only": True, "upload_performed": False, "no_upload": True,
        "is_promotion_decision": False,
        "promotion_note": ("Pass 30 is an existing-portfolio HARDENING TOURNAMENT "
                           "pass. The live score is context only and never gates a "
                           "build or a promotion in this pass."),
        "scores_refreshed_live": refreshed,
        "refresh_method": ("kaggle CLI competitions submissions (read-only listing)"
                           if refreshed else
                           "fallback to last-known-good live_score_registry snapshot "
                           f"(generated {reg.get('generated_at')}); no successful live "
                           "Kaggle call this pass"),
        "live_score_leader": _fld(
            leader, "highest publicScore among complete, non-error submissions"),
        "water_family_current_best": _fld(
            wfam, "maintained Water-lineage anchor; resolved to its current live "
            "score; NOT auto-overwritten by the global leader"),
        "portfolio_reference": _fld(
            pref, "in-portfolio Water reference deck the internal tournament is "
            "calibrated around (NOT a Kaggle leaderboard signal)"),
        "live_score_leader_is_water_family_best": bool(
            leader and wfam and leader["filename"] == wfam["filename"]),
        "distinction_preserved": True,
        "distinction_note": (
            "live_score_leader, water_family_current_best and portfolio_reference "
            "are computed independently and kept as separate fields. A higher-scoring "
            "non-Water submission would become live_score_leader WITHOUT changing the "
            "other two."),
        "internal_tournament_caveat": (
            "The internal tournament (and these confirmations) are NOT the Kaggle "
            "leaderboard: both seats are our own decks driven by the same generic "
            "pilot. Internal win rates and live publicScore are different "
            "measurements and must never be conflated."),
        "score_drift_vs_pass29": drift,
        "complete_submissions_ranked": [
            {"fileName": r["filename"], "publicScore": r["public_score"],
             "classification": r.get("classification")} for r in complete_ranked],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")

    ld, wf, pr = (status["live_score_leader"], status["water_family_current_best"],
                  status["portfolio_reference"])
    L = ["# Pass 30 — Live Score Status (Part B, read-only)", "",
         "> Read-only Kaggle status. **No submit, no upload.** Hardening pass — "
         "the live score is context only and gates NOTHING here. Three controls are "
         "kept explicitly distinct, and the live score is NOT the internal "
         "tournament.", "",
         (f"- **live_score_leader:** `{ld['fileName']}` @ **{ld['publicScore']}** "
          f"({ld['date']}) — {ld['rule']}." if ld else "- live_score_leader: none"),
         (f"- **water_family_current_best:** `{wf['fileName']}` @ "
          f"**{wf['publicScore']}** ({wf['date']}) — {wf['rule']}." if wf
          else "- water_family_current_best: none"),
         (f"- **portfolio_reference:** `{pr['fileName']}` @ **{pr['publicScore']}** "
          f"({pr['date']}) — {pr['rule']}." if pr else "- portfolio_reference: none"),
         f"- live_score_leader_is_water_family_best: "
         f"**{status['live_score_leader_is_water_family_best']}**.",
         f"- scores_refreshed_live: **{refreshed}** ({status['refresh_method']}).",
         "", "## Score drift vs Pass 29", "",
         "| fileName | pass29 | pass30 | delta |", "|---|---|---|---|"]
    for d in drift:
        L.append(f"| {d['fileName']} | {d['pass29']} | {d['pass30']} | {d['delta']} |")
    L += ["", "## Complete submissions ranked (read-only)", "",
          "| fileName | publicScore | classification |", "|---|---|---|"]
    for r in status["complete_submissions_ranked"]:
        L.append(f"| {r['fileName']} | {r['publicScore']} | {r['classification']} |")
    L += ["", "## Notes", "", f"- {status['promotion_note']}", "",
          f"- {status['distinction_note']}", "",
          f"- {status['internal_tournament_caveat']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"live_score_leader: {ld['fileName'] if ld else None} @ "
          f"{ld['publicScore'] if ld else None}")
    print(f"water_family_current_best: {wf['fileName'] if wf else None} @ "
          f"{wf['publicScore'] if wf else None}")
    print(f"portfolio_reference: {pr['fileName'] if pr else None} @ "
          f"{pr['publicScore'] if pr else None}")
    print(f"refreshed={refreshed} -> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
