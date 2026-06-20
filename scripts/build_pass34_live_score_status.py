#!/usr/bin/env python3
"""Pass 34 (Part B) — read-only live-score status. LOCAL / READ-ONLY.

Attempts a READ-ONLY Kaggle submissions listing (no submit, no upload). Order of
attempts: Python KaggleApi -> `kaggle` CLI -> last-known-good live-score registry
snapshot. publicScore is coerced safely to float; only complete, scored rows feed
the rankings. Keeps the four distinct controls (leader / water best / dragapult
best / portfolio reference) computed independently, plus the Pass-33
water_basic_density_v1 dry-run queue state. NO promotion decision is made here.
Writes data/experiments/pass34_live_score_status.{json,md} and (read-only) tee
logs to data/kaggle_uploads/status_before_pass34.{log,csv} on a live read.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "kaggle_uploads" / "live_score_registry.json"
PREV = REPO / "data" / "experiments" / "pass33_live_score_status.json"
QUEUE = REPO / "data" / "submission_queue.json"
OUT_JSON = REPO / "data" / "experiments" / "pass34_live_score_status.json"
OUT_MD = REPO / "data" / "experiments" / "pass34_live_score_status.md"
KU = REPO / "data" / "kaggle_uploads"
COMP = "pokemon-tcg-ai-battle"

WATER_FAMILY_BEST_FILE = "league_water_anti_disruption_pivot_v1.tar.gz"
PORTFOLIO_REFERENCE_FILE = "league_water_core_reference.tar.gz"
DRAGAPULT_FAMILY_PREFIX = "league_dragapult"


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _tee_rows(rows: list[dict]) -> None:
    KU.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fileName", "date", "status", "publicScore"])
    for r in rows:
        w.writerow([r.get("filename"), r.get("date"), r.get("status"),
                    r.get("public_score_raw")])
    (KU / "status_before_pass34.csv").write_text(buf.getvalue(), encoding="utf-8")
    (KU / "status_before_pass34.log").write_text(
        "read-only Kaggle submissions listing (no submit, no upload)\n"
        f"competition={COMP}\nrows={len(rows)}\n\n" + buf.getvalue(),
        encoding="utf-8")


def _from_api() -> list[dict] | None:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception:
        return None
    try:
        api = KaggleApi()
        api.authenticate()
        subs = api.competition_submissions(COMP)
    except Exception:
        return None
    rows = []
    for s in subs:
        fn = getattr(s, "fileName", None) or getattr(s, "fileNameNullable", None)
        raw = getattr(s, "publicScore", None)
        if raw is None:
            raw = getattr(s, "publicScoreNullable", None)
        rows.append({
            "filename": fn,
            "date": str(getattr(s, "date", "") or ""),
            "status": str(getattr(s, "status", "") or "").lower(),
            "public_score_raw": raw,
            "public_score": _safe_float(raw),
        })
    return rows or None


def _from_cli() -> list[dict] | None:
    try:
        proc = subprocess.run(
            ["kaggle", "competitions", "submissions", COMP, "-v"],
            capture_output=True, text=True, timeout=40)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    rows = []
    for r in csv.DictReader(io.StringIO(proc.stdout)):
        rows.append({
            "filename": r.get("fileName"),
            "date": r.get("date", ""),
            "status": (r.get("status") or "").lower(),
            "public_score_raw": r.get("publicScore"),
            "public_score": _safe_float(r.get("publicScore")),
        })
    return rows or None


def _from_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = []
    for r in reg.get("submissions", []):
        rows.append({
            "filename": r.get("filename"),
            "date": r.get("date", ""),
            "status": (r.get("status") or "").lower(),
            "public_score_raw": r.get("public_score"),
            "public_score": _safe_float(r.get("public_score")),
        })
    return rows


def _resolve_rows() -> tuple[list[dict], str, bool]:
    rows = _from_api()
    if rows:
        _tee_rows(rows)
        return rows, "python KaggleApi competition_submissions (read-only listing)", True
    rows = _from_cli()
    if rows:
        _tee_rows(rows)
        return rows, "kaggle CLI competitions submissions (read-only listing)", True
    return (_from_registry(),
            "fallback to last-known-good live_score_registry snapshot; "
            "no successful live Kaggle call this pass", False)


def _complete_scored(rows):
    return [r for r in rows
            if r.get("status") == "complete" and r.get("public_score") is not None]


def _best(rows, predicate):
    best = None
    for r in rows:
        if predicate(r) and (best is None
                             or r["public_score"] > best["public_score"]):
            best = r
    return best


def _fld(r, rule):
    if not r:
        return None
    return {"fileName": r["filename"], "publicScore": r["public_score"],
            "status": r["status"], "date": r["date"], "rule": rule}


def _density_v1_queue_state() -> dict:
    """Read the Pass-33 dry-run queue state for water_basic_density_v1."""
    state = {"present_in_queue": False, "disposition": None,
             "auto_submit_enabled": None, "upload_performed": None,
             "note": "queue file missing"}
    if not QUEUE.exists():
        return state
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    entry = next((e for e in q.get("queue", [])
                  if e.get("candidate_id") == "water_basic_density_v1"), None)
    state.update({
        "present_in_queue": entry is not None,
        "disposition": entry.get("disposition") if entry else None,
        "auto_submit_enabled": q.get("auto_submit_enabled"),
        "require_manual_approval_for_submit":
            q.get("require_manual_approval_for_submit"),
        "upload_performed": q.get("upload_performed"),
        "queue_stage": q.get("stage"),
        "note": ("Pass-33 HELD dry-run probe, never submitted; carried into Pass 34 "
                 "as a held future calibration probe."),
    })
    return state


def main() -> int:
    rows, method, refreshed = _resolve_rows()
    complete = _complete_scored(rows)
    ranked = sorted(complete, key=lambda r: r["public_score"], reverse=True)
    leader = ranked[0] if ranked else None
    wfam = _best(complete, lambda r: r["filename"] == WATER_FAMILY_BEST_FILE)
    pref = _best(complete, lambda r: r["filename"] == PORTFOLIO_REFERENCE_FILE)
    drag = _best(complete,
                 lambda r: (r["filename"] or "").startswith(DRAGAPULT_FAMILY_PREFIX))

    drift = []
    if PREV.exists():
        prev_doc = json.loads(PREV.read_text(encoding="utf-8"))
        prev = {c["fileName"]: c.get("publicScore")
                for c in prev_doc.get("complete_submissions_ranked", [])}
        cur = {r["filename"]: r["public_score"] for r in complete}
        for fn in sorted(set(prev) | set(cur)):
            pv, cv = prev.get(fn), cur.get(fn)
            delta = round(cv - pv, 4) if (pv is not None and cv is not None) else None
            drift.append({"fileName": fn, "pass33": pv, "pass34": cv, "delta": delta})

    drag_above_water = bool(
        drag and wfam and drag["public_score"] > wfam["public_score"])

    status = {
        "pass": "34", "part": "B",
        "generated_note": "read-only Kaggle status; no submit, no upload",
        "competition": COMP,
        "read_only": True, "upload_performed": False, "no_upload": True,
        "is_promotion_decision": False,
        "promotion_note": ("Pass 34 is a NEW-DECK INTAKE pass. The live score is "
                           "context only and never gates a build or a promotion."),
        "scores_refreshed_live": refreshed,
        "refresh_method": method,
        "stale_caveat": (None if refreshed else
                         "Live Kaggle read FAILED this pass; values below are the "
                         "last-known-good registry snapshot and may be STALE."),
        "live_score_leader": _fld(
            leader, "highest publicScore among complete, non-error submissions"),
        "water_family_current_best": _fld(
            wfam, "maintained Water-lineage anchor; NOT auto-overwritten by the "
            "global leader"),
        "dragapult_family_best": _fld(
            drag, "best Dragapult-family submission's current live score"),
        "portfolio_reference": _fld(
            pref, "in-portfolio Water reference the internal tournament is "
            "calibrated around (NOT a Kaggle leaderboard signal)"),
        "dragapult_above_water": drag_above_water,
        "dragapult_vs_water_note": (
            "Read from THIS fresh listing, not hardcoded. "
            + (f"Dragapult {drag['public_score']} "
               f"{'>' if drag_above_water else '<='} "
               f"Water {wfam['public_score']}."
               if (drag and wfam) else "one side missing from listing.")),
        "water_basic_density_v1_queue_state": _density_v1_queue_state(),
        "distinction_preserved": True,
        "distinction_note": (
            "live_score_leader, water_family_current_best, dragapult_family_best "
            "and portfolio_reference are computed independently and kept as "
            "separate fields."),
        "internal_tournament_caveat": (
            "The internal tournament in this pass is NOT the Kaggle leaderboard: "
            "internal win rates and live publicScore are different measurements "
            "and must never be conflated."),
        "score_drift_vs_pass33": drift,
        "complete_submissions_ranked": [
            {"fileName": r["filename"], "publicScore": r["public_score"],
             "date": r["date"]} for r in ranked],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")

    ld, wf, dr, pr = (status["live_score_leader"],
                      status["water_family_current_best"],
                      status["dragapult_family_best"],
                      status["portfolio_reference"])
    dq = status["water_basic_density_v1_queue_state"]
    L = ["# Pass 34 — Live Score Status (Part B, read-only)", "",
         "> Read-only Kaggle status. **No submit, no upload.** The live score is "
         "context only and gates NOTHING here. The internal tournament is NOT the "
         "Kaggle leaderboard.", "",
         (f"- **live_score_leader:** `{ld['fileName']}` @ **{ld['publicScore']}** "
          f"({ld['date']})." if ld else "- live_score_leader: none"),
         (f"- **water_family_current_best:** `{wf['fileName']}` @ "
          f"**{wf['publicScore']}** ({wf['date']})." if wf
          else "- water_family_current_best: none"),
         (f"- **dragapult_family_best:** `{dr['fileName']}` @ "
          f"**{dr['publicScore']}** ({dr['date']})." if dr
          else "- dragapult_family_best: none"),
         (f"- **portfolio_reference:** `{pr['fileName']}` @ **{pr['publicScore']}** "
          f"({pr['date']})." if pr else "- portfolio_reference: none"),
         f"- **dragapult_above_water:** **{drag_above_water}** "
         f"({status['dragapult_vs_water_note']})",
         f"- **water_basic_density_v1 queue state:** present={dq['present_in_queue']}, "
         f"disposition={dq['disposition']}, upload_performed={dq['upload_performed']}.",
         f"- scores_refreshed_live: **{refreshed}** ({method}).",
         (f"- **STALE CAVEAT:** {status['stale_caveat']}" if status['stale_caveat']
          else "- live read succeeded; values are fresh."),
         f"- upload_performed: **False**.",
         "", "## Score drift vs Pass 33", "",
         "| fileName | pass33 | pass34 | delta |", "|---|---|---|---|"]
    for d in drift:
        L.append(f"| {d['fileName']} | {d['pass33']} | {d['pass34']} | {d['delta']} |")
    L += ["", "## Complete submissions ranked (read-only)", "",
          "| fileName | publicScore | date |", "|---|---|---|"]
    for r in status["complete_submissions_ranked"]:
        L.append(f"| {r['fileName']} | {r['publicScore']} | {r['date']} |")
    L += ["", "## Notes", "", f"- {status['promotion_note']}", "",
          f"- {status['internal_tournament_caveat']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"live_score_leader: {ld['fileName'] if ld else None} @ "
          f"{ld['publicScore'] if ld else None}")
    print(f"water_family_current_best: {wf['fileName'] if wf else None} @ "
          f"{wf['publicScore'] if wf else None}")
    print(f"dragapult_above_water={drag_above_water} refreshed={refreshed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
