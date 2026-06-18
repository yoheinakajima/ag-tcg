"""Dry-run submission queue builder (Pass 7B, Part I).

LOCAL ONLY. This builds a candidate tarball under
``data/submissions/candidates/`` and records a *dry-run* queue at
``data/submission_queue.json``. It NEVER uploads or submits to Kaggle.

Queue invariants (from the Pass 7B spec):

* ``queue`` holds at most 1 candidate.
* ``auto_submit_enabled = false`` / ``require_manual_approval_for_submit = true``
  / ``upload_performed = false`` always.
* A candidate with any crash/timeout/stale game cannot be queued.
* A control/anchor can never be queued.
* Only ``scout_promising`` or better is eligible; otherwise the queue is empty
  with a recorded reason.
"""

from __future__ import annotations

import json
import tarfile
import time
from pathlib import Path

from . import run_state as rs

_ELIGIBLE_LABELS = ("scout_promising", "promotable")
_QUEUE_PATH = Path("data/submission_queue.json")
_CANDIDATES_DIR = Path("data/submissions/candidates")


def _branch_path_for(run_id: str, candidate_id: str, artifacts_root=None) -> str | None:
    for cs in rs.load_candidate_states(run_id, artifacts_root):
        if cs.candidate_id == candidate_id:
            return cs.branch_path
    return None


def _build_tarball(branch_dir: Path, candidate_id: str) -> dict:
    """Build a Kaggle-shaped main.py+deck.csv tarball. Returns inspect info."""
    main_py = branch_dir / "main.py"
    deck_csv = branch_dir / "deck.csv"
    if not main_py.exists() or not deck_csv.exists():
        return {"built": False, "error": f"missing main.py/deck.csv in {branch_dir}"}
    _CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    out = _CANDIDATES_DIR / f"{candidate_id}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(main_py, arcname="main.py")
        tar.add(deck_csv, arcname="deck.csv")
    with tarfile.open(out, "r:gz") as tar:
        members = sorted(m.name for m in tar.getmembers())
    return {
        "built": True,
        "tarball": str(out),
        "members": members,
        "size_bytes": out.stat().st_size,
    }


def _select_candidate(rank: dict) -> tuple[dict | None, str]:
    """Pick the single best eligible candidate or explain why none qualify."""
    cands = rank.get("candidates", [])
    if not cands:
        return None, "no candidates in ranking"
    eligible = []
    for c in cands:
        if c.get("role") != "candidate":
            continue
        if c.get("promotion_label") not in _ELIGIBLE_LABELS:
            continue
        if c.get("crashes") or c.get("timeouts") or c.get("stale"):
            continue
        eligible.append(c)
    if not eligible:
        best = cands[0]
        return None, (
            f"no candidate reached scout_promising with zero crash/timeout/stale; "
            f"best was {best.get('candidate_id')} "
            f"(label={best.get('promotion_label')}, "
            f"crash={best.get('crashes')}, timeout={best.get('timeouts')}, "
            f"stale={best.get('stale')})"
        )
    eligible.sort(
        key=lambda c: (
            c.get("adjusted_win_rate") if c.get("adjusted_win_rate") is not None else -1.0,
            c.get("games_completed", 0),
        ),
        reverse=True,
    )
    return eligible[0], "selected top eligible candidate"


def build_dry_run_queue(
    run_id: str,
    rank: dict,
    artifacts_root=None,
    queue_path: Path = _QUEUE_PATH,
) -> dict:
    """Build the dry-run queue from a ranking dict. Writes ``queue_path``."""
    selected, reason = _select_candidate(rank)
    queue: list[dict] = []
    if selected is not None:
        cid = selected["candidate_id"]
        branch_path = _branch_path_for(run_id, cid, artifacts_root)
        tar_info = (
            _build_tarball(Path(branch_path), cid)
            if branch_path
            else {"built": False, "error": "no branch_path for candidate"}
        )
        if tar_info.get("built"):
            queue.append(
                {
                    "candidate_id": cid,
                    "run_id": run_id,
                    "branch_path": branch_path,
                    "promotion_label": selected.get("promotion_label"),
                    "adjusted_win_rate": selected.get("adjusted_win_rate"),
                    "games_completed": selected.get("games_completed"),
                    "wilson_95": selected.get("wilson_95"),
                    "crashes": selected.get("crashes"),
                    "timeouts": selected.get("timeouts"),
                    "stale": selected.get("stale"),
                    "tarball": tar_info.get("tarball"),
                    "tarball_members": tar_info.get("members"),
                    "tarball_size_bytes": tar_info.get("size_bytes"),
                    "status": "queued_dry_run",
                }
            )
        else:
            reason = f"selected {cid} but tarball build failed: {tar_info.get('error')}"

    doc = {
        "schema": "ptcg_dry_run_submission_queue_v1",
        "generated_at": time.time(),
        "run_id": run_id,
        "stage": rank.get("stage"),
        "auto_submit_enabled": False,
        "require_manual_approval_for_submit": True,
        "upload_performed": False,
        "max_queue_size": 1,
        "active_control": rank.get("control"),
        "queue": queue[:1],
        "queued_candidate_count": len(queue[:1]),
        "selection_reason": reason,
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    return doc
