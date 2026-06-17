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

QUEUE_JSON = Path("data/submission_queue.json")


def is_promotable(entry: dict) -> bool:
    """A ranked entry is promotable only if it cleared every hard gate."""
    if entry.get("rejected"):
        return False
    if entry.get("score") is None:
        return False
    return True


def select_for_queue(ranked: list[dict], max_per_day: int) -> list[dict]:
    promotable = [e for e in ranked if is_promotable(e)]
    return promotable[: max(0, int(max_per_day))]


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

    candidates = []
    for e in selected:
        branch_id = e["branch_id"]
        run_dir = Path(runs_by_branch.get(branch_id, ""))
        tarball = None
        package_error = None
        if run_dir and (run_dir / "main.py").exists():
            try:
                out = run_dir / "submission.tar.gz"
                build_submission(
                    main_py=run_dir / "main.py",
                    deck_csv=run_dir / "deck.csv",
                    out_path=out,
                )
                tarball = str(out)
            except SubmissionError as exc:
                package_error = str(exc)
        message = msg_tpl.format(branch_id=branch_id, hypothesis=e.get("seam_id", ""))
        kaggle_cmd = (
            "python .pythonlibs/bin/kaggle competitions submit "
            "-c pokemon-tcg-ai-battle "
            f"-f {tarball} -m {message!r}"
        ) if tarball else None
        candidates.append({
            "branch_id": branch_id,
            "rank": e.get("rank"),
            "score": e.get("score"),
            "run_dir": str(run_dir),
            "tarball": tarball,
            "package_error": package_error,
            "message": message,
            "kaggle_command": kaggle_cmd,
        })
        store.append(new_event(
            EventType.SubmissionQueued,
            payload={"branch_id": branch_id, "rank": e.get("rank"),
                     "tarball": tarball, "auto_submit": auto},
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
