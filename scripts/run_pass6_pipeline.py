"""Pass 6 two-stage evaluation pipeline driver (LOCAL ONLY -- never uploads).

Stages:
  A. Generate Pass-6 candidates (policy v3 combos + deck variants + buildable
     chaos) into the runs root.
  0. Replay-fixture legality gate -- a hard pre-filter. Candidates whose runtime
     makes an illegal choice on a recorded decision are dropped before any game.
  1+2. SCOUT: package+smoke gate then 5 games/seat (seat-swap) in a killable
     subprocess (wall-clock timeout 90s/game) vs the v2 active control.
  3. FOCUSED: re-run the top-3 candidates (+ controls) at a larger budget.
  Q. Build a DRY-RUN submission queue (max 1, auto_submit forced off).

The cabt stages (1/2/3), ranking, and the queue run only with ``--run-eval``
(they need kaggle_environments). Without it, this prints the exact canonical
commands and stops after the fixture gate. Nothing here can upload.

Usage:
    python scripts/run_pass6_pipeline.py                 # generate + Stage 0 only
    python scripts/run_pass6_pipeline.py --run-eval      # full local pipeline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import RUNS_ROOT, load_config
from ptcg_activegraph.experiments import pass6_pipeline as p6

PY = sys.executable
SCRIPTS = Path(__file__).resolve().parent
STAGE0_REPORT = Path("data/experiments/pass6_stage0_fixture_gate.json")
PASS6_FOCUSED_RANKING_JSON = Path("data/experiments/pass6_focused_ranking.json")


def _run(cmd: list[str]) -> int:
    print("\n$ " + " ".join(cmd))
    return subprocess.call(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--runs-root", default=str(RUNS_ROOT))
    ap.add_argument("--fixtures-dir", default=str(p6.DEFAULT_FIXTURES_DIR))
    ap.add_argument("--skip-generate", action="store_true",
                    help="reuse existing Pass-6 run dirs instead of regenerating")
    ap.add_argument("--run-eval", action="store_true",
                    help="actually run the cabt scout/focused stages + queue "
                         "(needs kaggle_environments). Default: stop after Stage 0.")
    ap.add_argument("--scout-games-per-seat", type=int, default=5)
    ap.add_argument("--focused-games-per-seat", type=int, default=20)
    ap.add_argument("--game-timeout-seconds", type=int, default=90)
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    # The killable subprocess runner is the ONLY safe path: an in-process batch
    # is killed silently (no Python traceback) when any single game triggers a
    # C-level abort/segfault in cabt/OpenSpiel. The subprocess runner isolates
    # each game in its own process so one bad game cannot take down the batch.
    sp_flag = "--subprocess"

    runs_root = Path(args.runs_root)

    # --- Stage A: generate -------------------------------------------------
    if not args.skip_generate:
        rc = _run([PY, str(SCRIPTS / "generate_candidates.py"),
                   "--group", "pass6", "--runs-root", str(runs_root)])
        if rc != 0:
            print("generation failed; aborting.")
            return rc

    # Locate the Pass-6 run dirs (testable branch ids only).
    by_branch = p6.runs_by_branch(runs_root)
    testable = p6.pass6_testable_branch_ids()
    p6_run_dirs = [Path(by_branch[b]) for b in testable if b in by_branch]
    missing = [b for b in testable if b not in by_branch]
    if missing:
        print(f"  ! {len(missing)} Pass-6 branch(es) have no run dir: {missing}")
    print(f"\nStage 0: fixture legality gate over {len(p6_run_dirs)} candidate(s)...")

    # --- Stage 0: fixture legality gate -----------------------------------
    gate = p6.stage0_fixture_gate(p6_run_dirs, args.fixtures_dir)
    survivors = p6.stage0_survivors(gate)
    rejected = [b for b in gate if b not in survivors]
    STAGE0_REPORT.parent.mkdir(parents=True, exist_ok=True)
    STAGE0_REPORT.write_text(json.dumps({
        "survivors": survivors,
        "rejected": rejected,
        "reports": gate,
    }, indent=2, default=str), encoding="utf-8")
    for bid, rep in gate.items():
        mark = "ok " if rep.get("legality_gate") else "REJECT"
        print(f"  [{mark}] {bid:<44} "
              f"pref pass/fail/na={rep.get('preference_pass')}/"
              f"{rep.get('preference_fail')}/{rep.get('preference_na')}")
    print(f"  Stage 0: {len(survivors)} survivor(s), {len(rejected)} rejected. "
          f"(wrote {STAGE0_REPORT})")

    if not args.run_eval:
        print("\n--run-eval not set: stopping after Stage 0. Canonical cabt run:")
        print(f"  {PY} scripts/run_experiment_batch.py --stage pass6_scout "
              f"--subprocess --game-timeout-seconds {args.game_timeout_seconds} "
              f"--games-per-seat {args.scout_games_per_seat} "
              f"--only-branch {' '.join(survivors)}")
        print(f"  {PY} scripts/rank_candidates.py --stage pass6_scout")
        print(f"  {PY} scripts/run_experiment_batch.py --stage pass6_focused "
              f"--top {args.top} --games-per-seat {args.focused_games_per_seat} "
              f"--subprocess --game-timeout-seconds {args.game_timeout_seconds}")
        print(f"  {PY} scripts/rank_candidates.py --stage pass6_focused")
        print(f"  {PY} scripts/run_pass6_pipeline.py --run-eval --skip-generate")
        return 0

    # --- Stage 1+2: scout --------------------------------------------------
    if not survivors:
        print("No survivors after Stage 0; nothing to evaluate.")
        return 1
    # --only-branch uses action="append": repeat the flag once per survivor.
    only_branch_args: list[str] = []
    for b in survivors:
        only_branch_args += ["--only-branch", b]
    rc = _run([PY, str(SCRIPTS / "run_experiment_batch.py"),
               "--stage", "pass6_scout", sp_flag,
               "--game-timeout-seconds", str(args.game_timeout_seconds),
               "--games-per-seat", str(args.scout_games_per_seat),
               "--runs-root", str(runs_root),
               *only_branch_args])
    if rc != 0:
        print("scout stage failed; aborting before ranking.")
        return rc
    _run([PY, str(SCRIPTS / "rank_candidates.py"), "--stage", "pass6_scout"])

    # --- Stage 3: focused (top-N) -----------------------------------------
    rc = _run([PY, str(SCRIPTS / "run_experiment_batch.py"),
               "--stage", "pass6_focused", "--top", str(args.top),
               "--games-per-seat", str(args.focused_games_per_seat),
               sp_flag, "--game-timeout-seconds", str(args.game_timeout_seconds),
               "--runs-root", str(runs_root)])
    if rc != 0:
        print("focused stage failed; aborting before queue.")
        return rc
    _run([PY, str(SCRIPTS / "rank_candidates.py"), "--stage", "pass6_focused"])

    # --- Stage Q: DRY-RUN queue (max 1, never uploads) --------------------
    if not PASS6_FOCUSED_RANKING_JSON.exists():
        print(f"No focused ranking at {PASS6_FOCUSED_RANKING_JSON}; skipping queue.")
        return 0
    ranked = json.loads(PASS6_FOCUSED_RANKING_JSON.read_text(encoding="utf-8"))
    if isinstance(ranked, dict):
        ranked = ranked.get("candidates") or ranked.get("ranked") or []
    config = load_config()
    plan = p6.build_dry_run_queue(ranked, config, by_branch, max_per_day=1)
    print(f"\nStage Q: {plan['mode']} queue with {len(plan['candidates'])} "
          f"candidate(s); will_upload={plan['will_upload']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
