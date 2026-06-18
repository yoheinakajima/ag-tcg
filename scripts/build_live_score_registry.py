#!/usr/bin/env python3
"""Build a *dynamic* live-score / active-control registry from Kaggle status.

Pass 10B (Evaluation Recovery). Read-only: parses the saved output of
``kaggle competitions submissions -v`` (CSV) and produces:

    data/kaggle_uploads/live_score_registry.json
    data/kaggle_uploads/live_score_registry.md

The *active control* is chosen dynamically as the highest ``publicScore`` among
**complete, non-error** submissions -- never a hardcoded v1/v2 label. Candidate
submissions (combo/chaos/policy families) that score below the active control
are classified ``live_rejected`` and emit a ``CandidateRejected`` event.

This script NEVER uploads or submits anything. It only reads a CSV that was
produced by a prior read-only ``kaggle`` listing.

Usage:
    python scripts/build_live_score_registry.py
    python scripts/build_live_score_registry.py --csv data/kaggle_uploads/status_before_pass10b.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, REPO_ROOT
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import new_event

DEFAULT_CSV = REPO_ROOT / "data" / "kaggle_uploads" / "status_before_pass10b.csv"
REGISTRY_JSON = REPO_ROOT / "data" / "kaggle_uploads" / "live_score_registry.json"
REGISTRY_MD = REPO_ROOT / "data" / "kaggle_uploads" / "live_score_registry.md"

# Filename prefixes that identify *gameplay candidates* (as opposed to
# baselines like ``submission.tar.gz`` / ``deck_energy_trim_light.tar.gz``).
CANDIDATE_PREFIXES = (
    "combo", "chaos", "policy", "hand_", "bench_", "mill_", "status_",
    "discard_", "candidate",
)


def _is_candidate(filename: str) -> bool:
    name = (filename or "").lower()
    return any(name.startswith(p) for p in CANDIDATE_PREFIXES)


def parse_submissions_csv(text: str) -> list[dict[str, Any]]:
    """Parse ``kaggle competitions submissions -v`` CSV text into rows.

    Tolerates the leading ``Warning:`` line the CLI prints. Returns a list of
    dicts with normalized keys: filename, description, status, public_score
    (float|None), date, episodes (None -- not in CSV).
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # Drop any leading non-header noise (e.g. the API version warning).
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("fileName,"):
            start = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        score_raw = (raw.get("publicScore") or "").strip()
        try:
            score = float(score_raw) if score_raw else None
        except ValueError:
            score = None
        rows.append({
            "filename": (raw.get("fileName") or "").strip(),
            "description": (raw.get("description") or "").strip(),
            "status": (raw.get("status") or "").strip().lower(),
            "public_score": score,
            "date": (raw.get("date") or "").strip(),
            "episodes": None,
        })
    return rows


def select_active_control(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest public_score among complete, non-error, scored submissions."""
    complete_scored = [
        r for r in rows
        if r["status"] == "complete" and r["public_score"] is not None
    ]
    if not complete_scored:
        return None
    return max(complete_scored, key=lambda r: r["public_score"])


def classify_submissions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each row with a ``classification`` field (in place) + return."""
    active = select_active_control(rows)
    active_key = (active["filename"], active["date"]) if active else None
    active_score = active["public_score"] if active else None
    for r in rows:
        if (r["filename"], r["date"]) == active_key:
            r["classification"] = "active_control_candidate"
        elif r["status"] == "error":
            r["classification"] = "error"
        elif r["status"] == "pending":
            r["classification"] = "pending"
        elif r["status"] == "complete":
            if (
                _is_candidate(r["filename"])
                and r["public_score"] is not None
                and active_score is not None
                and r["public_score"] < active_score
            ):
                r["classification"] = "live_rejected"
            else:
                r["classification"] = "complete"
        else:
            r["classification"] = r["status"] or "unknown"
    return rows


def build_registry(rows: list[dict[str, Any]], *, competition: str) -> dict[str, Any]:
    rows = classify_submissions(rows)
    active = select_active_control(rows)
    counts = {
        "total": len(rows),
        "complete": sum(1 for r in rows if r["status"] == "complete"),
        "error": sum(1 for r in rows if r["status"] == "error"),
        "pending": sum(1 for r in rows if r["status"] == "pending"),
    }
    rejected = [
        {"filename": r["filename"], "public_score": r["public_score"],
         "date": r["date"], "reason": "below active control live score"}
        for r in rows if r["classification"] == "live_rejected"
    ]
    notes: list[str] = []
    if active is None:
        notes.append("No complete non-error scored submission found; active "
                     "control is ambiguous -- not guessed.")
    return {
        "competition": competition,
        "generated_at": time.time(),
        "source": "kaggle competitions submissions -v (read-only listing)",
        "submissions": rows,
        "counts": counts,
        "active_control": active,
        "rejected_candidates": rejected,
        "notes": notes,
    }


def _render_md(reg: dict[str, Any]) -> str:
    lines = ["# Live Score Registry (Pass 10B)", ""]
    lines.append(f"- Competition: `{reg['competition']}`")
    lines.append(f"- Source: {reg['source']}")
    c = reg["counts"]
    lines.append(f"- Submissions parsed: {c['total']} "
                 f"(complete={c['complete']}, error={c['error']}, pending={c['pending']})")
    ac = reg["active_control"]
    if ac:
        lines.append(f"- **Active control (dynamic):** `{ac['filename']}` "
                     f"score **{ac['public_score']}** ({ac['date']}) -- {ac['description']}")
    else:
        lines.append("- **Active control:** ambiguous / none (not guessed)")
    lines.append("")
    lines.append("| fileName | date | status | publicScore | classification | description |")
    lines.append("|---|---|---|---|---|---|")
    for r in reg["submissions"]:
        score = "" if r["public_score"] is None else r["public_score"]
        desc = (r["description"] or "")[:80].replace("|", "\\|")
        lines.append(f"| {r['filename']} | {r['date']} | {r['status']} | "
                     f"{score} | {r['classification']} | {desc} |")
    lines.append("")
    if reg["rejected_candidates"]:
        lines.append("## Live-rejected candidates")
        for r in reg["rejected_candidates"]:
            lines.append(f"- `{r['filename']}` score {r['public_score']} "
                         f"({r['date']}) -- {r['reason']}")
    lines.append("")
    if reg["notes"]:
        lines.append("## Notes")
        for n in reg["notes"]:
            lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def _emit_events(reg: dict[str, Any]) -> int:
    store = EventStore(LAB_EVENTS_PATH)
    events = []
    for r in reg["submissions"]:
        if r["status"] == "complete" and r["public_score"] is not None:
            events.append(new_event(
                "KaggleScoreUpdated",
                payload={"filename": r["filename"], "description": r["description"],
                         "live_score": r["public_score"], "date": r["date"],
                         "classification": r["classification"]},
            ))
    ac = reg["active_control"]
    if ac:
        events.append(new_event(
            "ActiveControlSelected",
            payload={"candidate_id": ac["filename"], "live_score": ac["public_score"],
                     "date": ac["date"], "description": ac["description"],
                     "selection_rule": "highest publicScore among complete non-error"},
        ))
    for r in reg["rejected_candidates"]:
        events.append(new_event(
            "CandidateRejected",
            payload={"candidate_id": r["filename"], "live_score": r["public_score"],
                     "active_control": ac["filename"] if ac else None,
                     "active_control_score": ac["public_score"] if ac else None,
                     "reason": r["reason"]},
        ))
    return store.append_many(events)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--competition", default="pokemon-tcg-ai-battle")
    parser.add_argument("--no-events", action="store_true",
                        help="skip emitting ActiveGraph events")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}. Run the read-only kaggle status "
              "listing first (Part B). Nothing fabricated.")
        return 2
    rows = parse_submissions_csv(csv_path.read_text(encoding="utf-8"))
    reg = build_registry(rows, competition=args.competition)

    REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_JSON.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    REGISTRY_MD.write_text(_render_md(reg), encoding="utf-8")

    n_events = 0 if args.no_events else _emit_events(reg)
    ac = reg["active_control"]
    print(f"Wrote {REGISTRY_JSON.relative_to(REPO_ROOT)} and "
          f"{REGISTRY_MD.relative_to(REPO_ROOT)}")
    print(f"Submissions: {reg['counts']}")
    if ac:
        print(f"Active control: {ac['filename']} @ {ac['public_score']}")
    else:
        print("Active control: AMBIGUOUS (none) -- not guessed")
    print(f"Rejected candidates: {[r['filename'] for r in reg['rejected_candidates']]}")
    print(f"Events emitted: {n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
