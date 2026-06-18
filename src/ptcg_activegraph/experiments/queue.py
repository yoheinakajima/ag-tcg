"""Submission queue: select promotable candidates and (optionally) upload.

Safety is the whole point of this module:

* ``auto_submit_enabled`` MUST be true before any real upload runs.
* ``require_manual_approval_for_submit`` true => dry-run only, print the exact
  command a human would run.
* ``kaggle_daily_submission_limit`` / ``max_per_day`` cap how many uploads.
* A candidate is never queued unless it passed package verify AND smoke AND has
  no crashes/timeouts in the local batch.

With the shipped defaults (auto-submit disabled, manual approval required), this
module never uploads anything — it only builds tarballs and prints the plan.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..graph.event_store import EventStore
from ..graph.events import EventType, new_event
from .ranker import is_control_entry

QUEUE_JSON = Path("data/submission_queue.json")
CANDIDATES_DIR = Path("data/submissions/candidates")


def is_promotable(entry: dict) -> bool:
    """A ranked entry is promotable only if it cleared every hard gate.

    Controls and anchors (v2 active control, v1 legacy baseline, integrity
    anchors) are never promotable — they are baselines, not submission targets.
    """
    if entry.get("rejected"):
        return False
    if entry.get("score") is None:
        return False
    if is_control_entry(entry):
        return False
    return True


def _queue_rank_key(e: dict) -> tuple:
    """Order queue candidates: promotable first, then confirmation, by score."""
    label = e.get("label", "")
    tier = 0 if label == "promotable" else (1 if label == "confirmation_promising" else 2)
    score = e.get("score")
    score = score if isinstance(score, (int, float)) else -1e9
    return (tier, -score)


def select_for_queue(ranked: list[dict], max_per_day: int) -> list[dict]:
    """Select submission-safe candidates, strongest first.

    Promotable candidates are preferred; if there are fewer than the daily cap,
    strong ``confirmation_promising`` survivors fill the remaining slots so the
    queue is never empty when there is a defensible candidate to confirm. Every
    selected entry still cleared all hard gates (never rejected, has a score).
    """
    eligible = [e for e in ranked if is_promotable(e)
                and e.get("label") in ("promotable", "confirmation_promising")]
    eligible.sort(key=_queue_rank_key)
    return eligible[: max(0, int(max_per_day))]


def _risk_notes(e: dict) -> list[str]:
    """Conservative, human-readable cautions for a queued candidate."""
    notes: list[str] = []
    games = int(e.get("games_completed") or 0)
    if e.get("label") == "confirmation_promising":
        notes.append("Not yet promotable: 80% lower bound does not clear 0.50 — "
                     "submit only if you accept an unconfirmed edge.")
    if games < 40:
        notes.append(f"Sample is small ({games} games); local estimate is noisy.")
    seatd = e.get("seat_balance_delta")
    if seatd is not None and abs(seatd) >= 0.25:
        notes.append(f"Large seat imbalance (Δ={seatd:+.2f}); strength may depend "
                     "on going first/second.")
    if (e.get("fallbacks") or 0) > 0:
        notes.append("Recorded agent fallbacks during play — verify runtime stability.")
    notes.append("Local cabt is a proxy for the hidden Kaggle ladder; treat as a "
                 "directional signal, not a guaranteed score gain.")
    return notes


def build_queue(
    ranked: list[dict],
    config,
    runs_by_branch: dict[str, str],
    event_store: EventStore | None = None,
) -> dict:
    """Build (and persist) the submission queue plan. Never uploads.

    ``runs_by_branch`` maps branch_id -> run_dir so we can locate/package each
    candidate's files. Returns the plan dict written to data/submission_queue.json.
    """
    from ..packaging.make_submission import SubmissionError, build_submission

    store = event_store or EventStore()
    settings = config.settings
    sq = config.submission_queue

    auto = bool(settings.get("auto_submit_enabled", False))
    manual = bool(settings.get("require_manual_approval_for_submit", True))
    daily_limit = int(settings.get("kaggle_daily_submission_limit", 3))
    max_per_day = min(int(sq.get("max_per_day", daily_limit)), daily_limit)
    msg_tpl = settings.get("submission_message_template", "{branch_id}: {hypothesis}")
    queue_enabled = bool(sq.get("enabled", True))

    selected = select_for_queue(ranked, max_per_day) if queue_enabled else []

    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    candidates = []
    for e in selected:
        branch_id = e["branch_id"]
        run_dir = Path(runs_by_branch.get(branch_id, ""))
        tarball = None
        package_error = None
        if run_dir and (run_dir / "main.py").exists():
            try:
                # Submit-ready tarball lives under data/submissions/candidates/
                # (the run dir keeps its own copy too). main.py + deck.csv only.
                out = CANDIDATES_DIR / f"{branch_id}.tar.gz"
                build_submission(
                    main_py=run_dir / "main.py",
                    deck_csv=run_dir / "deck.csv",
                    out_path=out,
                )
                tarball = str(out)
            except SubmissionError as exc:
                package_error = str(exc)
        hypothesis = e.get("hypothesis") or e.get("seam_id", "")
        message = msg_tpl.format(branch_id=branch_id, hypothesis=hypothesis)
        kaggle_cmd = (
            "python .pythonlibs/bin/kaggle competitions submit "
            "-c pokemon-tcg-ai-battle "
            f"-f {tarball} -m {message!r}"
        ) if tarball else None
        w80 = e.get("wilson80") or [None, None]
        risk_notes = _risk_notes(e)
        candidates.append({
            "branch_id": branch_id,
            "rank": e.get("rank"),
            "score": e.get("score"),
            "label": e.get("label"),
            "seam_id": e.get("seam_id"),
            "kind": e.get("kind"),
            "hypothesis": hypothesis,
            "run_dir": str(run_dir),
            "tarball": tarball,
            "package_error": package_error,
            "focused_metrics": {
                "games_completed": e.get("games_completed"),
                "win_rate": e.get("win_rate"),
                "adjusted_win_rate": e.get("adjusted_win_rate"),
                "wilson80": w80,
                "wilson95": e.get("wilson95"),
                "seat_balance_delta": e.get("seat_balance_delta"),
                "candidate_p0_win_rate": e.get("candidate_p0_win_rate"),
                "candidate_p1_win_rate": e.get("candidate_p1_win_rate"),
            },
            "interpretation": e.get("interpretation"),
            "risk_notes": risk_notes,
            "suggested_message": message,
            "message": message,
            "kaggle_command": kaggle_cmd,
            "uploaded": False,
        })
        store.append(new_event(
            EventType.SubmissionQueued,
            payload={"branch_id": branch_id, "rank": e.get("rank"),
                     "label": e.get("label"), "tarball": tarball,
                     "auto_submit": auto},
            tags=["experiment", "queue"],
        ))

    will_upload = auto and not manual
    plan = {
        "auto_submit_enabled": auto,
        "require_manual_approval_for_submit": manual,
        "kaggle_daily_submission_limit": daily_limit,
        "max_per_day": max_per_day,
        "queue_enabled": queue_enabled,
        "will_upload": will_upload,
        "mode": "UPLOAD" if will_upload else "DRY-RUN",
        "candidates": candidates,
    }
    QUEUE_JSON.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_JSON.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    return plan
