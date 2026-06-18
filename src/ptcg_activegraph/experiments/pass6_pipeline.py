"""Pass 6 two-stage evaluation pipeline (LOCAL ONLY, never uploads).

The heavy cabt stages (scout games, focused games) reuse the existing,
already-tested stage machinery in ``scripts/run_experiment_batch.py`` +
``scripts/rank_candidates.py``. This module holds the *pure*, cabt-free pieces
that are specific to Pass 6 so they can be unit-tested without the engine:

* ``Stage 0`` -- the replay-fixture legality gate (a hard pre-filter run before
  any game is played; candidates whose runtime makes an illegal choice on a
  recorded decision are rejected up front).
* candidate selection (top-3, controls/anchors excluded), and
* a DRY-RUN submission queue (``max_per_day == 1``, ``auto_submit`` forced off).

Nothing here can upload: ``build_dry_run_queue`` hard-asserts the safety flags
and delegates packaging to ``queue.build_queue``, which only writes tarballs +
the plan JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import RUNS_ROOT
from .generator import (
    PASS6_CHAOS_BLOCKED,
    PASS6_CHAOS_SPECS,
    PASS6_COMBO_SPECS,
    PASS6_DECK_SPECS,
)
from .ranker import is_control_entry

DEFAULT_FIXTURES_DIR = Path("data/replay_fixtures")


def pass6_testable_branch_ids() -> list[str]:
    """All Pass-6 branch ids that are actually built (blocked chaos excluded)."""
    ids = [s["branch_id"] for s in PASS6_COMBO_SPECS]
    ids += [s["branch_id"] for s in PASS6_DECK_SPECS]
    ids += [s["branch_id"] for s in PASS6_CHAOS_SPECS]
    return ids


def pass6_blocked_branch_ids() -> list[str]:
    """Pass-6 branch ids honestly recorded as blocked (never generated/queued)."""
    return [s["branch_id"] for s in PASS6_CHAOS_BLOCKED]


def _default_fixture_evaluator(run_dir: Path, fixtures_dir: Path) -> dict:
    """Lazy import of the script-level fixture grader (keeps this import-light)."""
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[3] / "scripts" / "test_candidate_on_fixtures.py"
    spec = importlib.util.spec_from_file_location("_p6_fixture_grader", script)
    mod = importlib.util.module_from_spec(spec)
    # The script does ``import _bootstrap``; make scripts/ importable.
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        if str(script.parent) in sys.path:
            sys.path.remove(str(script.parent))
    return mod.evaluate_candidate_on_fixtures(run_dir, fixtures_dir)


def stage0_fixture_gate(
    run_dirs: list[Path] | list[str],
    fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
    evaluator: Callable[[Path, Path], dict] | None = None,
) -> dict:
    """Run the replay-fixture legality gate over each candidate run dir.

    Returns ``{branch_id: report}`` where ``report['legality_gate']`` is the hard
    pass/fail. The preference grade is advisory and never rejects a candidate.
    A candidate that FAILS the legality gate must be excluded from the cabt
    stages (it makes an illegal choice on a recorded decision).
    """
    from .branch import load_branch_yaml

    ev = evaluator or _default_fixture_evaluator
    fixtures_dir = Path(fixtures_dir)
    out: dict[str, dict] = {}
    for rd in run_dirs:
        rd = Path(rd)
        rep = ev(rd, fixtures_dir)
        # Key by the real branch_id (so downstream --only-branch matches), not
        # the timestamped run-dir name. Fall back to any id in the report, then
        # the run-dir name.
        b = load_branch_yaml(rd)
        bid = (b.branch_id if b is not None
               else rep.get("branch_id") or rd.name)
        rep.setdefault("branch_id", bid)
        out[bid] = rep
    return out


def stage0_survivors(gate_report: dict) -> list[str]:
    """Branch ids that cleared the Stage-0 legality gate (order-stable)."""
    return [bid for bid, rep in gate_report.items()
            if bool(rep.get("legality_gate"))]


def select_top3(ranked: list[dict], n: int = 3) -> list[dict]:
    """Top-N non-control, non-rejected candidates by rank (controls excluded).

    Controls (v2 active control, v1 legacy baseline) and integrity anchors are
    baselines, not candidates -- they are dropped here so the focused stage only
    spends its larger game budget on real candidates (the controls are still
    co-evaluated in the focused stage by the batch driver itself).
    """
    cand = [e for e in ranked
            if not is_control_entry(e)
            and not e.get("rejected")
            and e.get("candidate_rank") is not None]
    cand.sort(key=lambda e: e.get("candidate_rank", 1_000_000))
    return cand[: max(0, int(n))]


def build_dry_run_queue(
    ranked: list[dict],
    config,
    runs_by_branch: dict[str, str],
    event_store=None,
    max_per_day: int = 1,
) -> dict:
    """Build a DRY-RUN submission queue for Pass 6 (never uploads).

    Forces ``max_per_day`` (default 1) and hard-asserts that auto-submit is off
    and manual approval is required, so this can never upload regardless of how
    the queue settings drift. Delegates packaging/plan-writing to
    ``queue.build_queue``.
    """
    from . import queue as queue_mod

    settings = config.settings
    if bool(settings.get("auto_submit_enabled", False)) or \
       not bool(settings.get("require_manual_approval_for_submit", True)):
        raise RuntimeError(
            "Pass 6 is dry-run only: refusing to build a queue while "
            "auto_submit_enabled is true / manual approval is disabled."
        )
    # Cap to at most `max_per_day` without mutating the persisted config on disk.
    config.submission_queue = {
        **dict(config.submission_queue or {}),
        "enabled": True,
        "max_per_day": int(max_per_day),
    }
    plan = queue_mod.build_queue(ranked, config, runs_by_branch, event_store)
    assert plan["will_upload"] is False, "dry-run queue must never upload"
    return plan


def runs_by_branch(runs_root: Path | str = RUNS_ROOT) -> dict[str, str]:
    """Map branch_id -> run_dir for every candidate under ``runs_root``."""
    from .branch import list_runs, load_branch_yaml

    mapping: dict[str, str] = {}
    for rd in list_runs(runs_root):
        b = load_branch_yaml(rd)
        if b is not None:
            mapping[b.branch_id] = str(rd)
    return mapping
