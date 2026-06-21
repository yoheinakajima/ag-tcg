#!/usr/bin/env python3
"""Pass 39 (Part A) — root/deploy safety preflight.

OPS/verify-only. Confirms, WITHOUT mutating anything, the same hard invariants
Pass 38 pinned, re-checked at the start of Pass 39 (which adds the candidate
lifecycle manager and must NOT touch the frozen Kaggle entrypoint):

  * root ``main.py``/``deck.csv`` byte-identical to the frozen v1 baseline
    (data/baselines/v1_kaggle_349_8), both before AND after the verify run,
  * ``scripts/package_submission.py --verify-only`` passes and mutates nothing,
  * ``.replit [deployment]`` is a *bounded scheduled worker* (not the root Kaggle
    entrypoint): target=scheduled, run=tournament_deployment_tick.py with
    --production + --storage-backend replit_app_storage and the 20/900 bound
    signature, build installs deploy deps with --user/--break-system-packages
    incl. kaggle-environments==1.30.1,
  * ``pyproject.toml [tool.uv] package = false`` (the Pass 37 EACCES fix),
  * the ``Start application`` workflow is the frozen Kaggle entrypoint (python3
    main.py) — NOT a server; not-started is EXPECTED and is never started here.

Cadence note: the user changed the Scheduled Deployment cron from ``0 */2 * * *``
to every 20 minutes (``*/20 * * * *``). The cron lives in the deployment settings,
not in ``.replit`` (which only carries the run/build commands), so this script
verifies the unchanged 20/900 RUN signature and records the operator-stated
20-minute cadence as context; it makes no claim it can read the cron from the repo.

Writes data/experiments/pass39_root_deploy_safety.{json,md}. Exit nonzero if any
hard safety/config check fails. NO upload, NO submit, NO push, NO root mutation,
NO candidate generation.
"""
from __future__ import annotations

import filecmp
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"

# Operator-stated Scheduled Deployment cadence (lives in deployment settings, not
# in .replit). Recorded as context; the script does not read it from the repo.
OPERATOR_CRON = "*/20 * * * *"
OPERATOR_CRON_NOTE = ("Scheduled Deployment cron changed by the operator from "
                      "'0 */2 * * *' (2h) to '*/20 * * * *' (every 20 min). The "
                      "cron is in deployment settings, not in .replit; the 20/900 "
                      "RUN signature below is unchanged.")
EXPECTED_RUN_BOUND = {"max_games": 20, "max_seconds": 900}


def _cmp(name: str) -> bool | None:
    root_f, base_f = REPO / name, BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return None
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return None


def _run_bound_signature(run: list) -> dict:
    """Extract the (max_games, max_seconds) bound from the deployment run args."""
    run = [str(x) for x in (run or [])]
    mg = ms = None
    for i, tok in enumerate(run):
        if tok == "--max-games" and i + 1 < len(run):
            mg = int(run[i + 1])
        elif tok == "--max-seconds" and i + 1 < len(run):
            ms = int(run[i + 1])
    return {"max_games": mg, "max_seconds": ms}


def _check_replit_deployment() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = data.get("deployment", {}) or {}
    run = dep.get("run", []) or []
    build = dep.get("build", []) or []
    run_str = " ".join(str(x) for x in run)
    build_str = " ".join(str(x) for x in build)
    bound = _run_bound_signature(run)
    checks = {
        "deployment_target_scheduled": dep.get("deploymentTarget") == "scheduled",
        "run_is_deployment_tick": "scripts/tournament_deployment_tick.py" in run_str,
        "run_not_root_main": "main.py" not in run,  # exact-token: never `python main.py`
        "run_has_production": "--production" in run,
        "run_uses_object_storage": "replit_app_storage" in run_str,
        "run_bound_signature_20_900": bound == EXPECTED_RUN_BOUND,
        "build_user_install": "--user" in build,
        "build_break_system_packages": "--break-system-packages" in build,
        "build_has_object_storage": "replit-object-storage" in build,
        "build_has_pyyaml": "pyyaml" in build,
        "build_has_kaggle_env_pinned": "kaggle-environments==1.30.1" in build_str,
    }
    return {
        "deploymentTarget": dep.get("deploymentTarget"),
        "run": run,
        "build": build,
        "run_bound_signature": bound,
        "checks": checks,
        "all_ok": all(checks.values()),
    }


def _check_pyproject_uv() -> dict:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    uv = data.get("tool", {}).get("uv", {}) or {}
    package_false = uv.get("package", None) is False
    return {"tool_uv_present": bool(uv), "package": uv.get("package", None),
            "package_false": package_false, "all_ok": package_false}


def _check_start_application_workflow() -> dict:
    """The root 'Start application' workflow must remain the frozen Kaggle agent
    entrypoint (python3 main.py), NOT a server. Not-started is expected; we never
    start it. We only assert the config still points at main.py."""
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    found = None
    for wf in data.get("workflows", {}).get("workflow", []) or []:
        if wf.get("name") == "Start application":
            tasks = wf.get("tasks", []) or []
            found = " ".join(str(t.get("args", "")) for t in tasks)
    is_kaggle_entrypoint = found is not None and "main.py" in found
    return {"workflow_args": found, "is_frozen_kaggle_entrypoint": is_kaggle_entrypoint,
            "started_here": False, "not_started_is_expected": True,
            "all_ok": is_kaggle_entrypoint}


def main() -> int:
    main_ok = _cmp("main.py")
    deck_ok = _cmp("deck.csv")

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "package_submission.py"),
         "--verify-only"],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    verify_passed = proc.returncode == 0

    main_ok_after = _cmp("main.py")
    deck_ok_after = _cmp("deck.csv")

    root_unchanged = (main_ok is True and deck_ok is True
                      and main_ok_after is True and deck_ok_after is True)

    deploy = _check_replit_deployment()
    uv = _check_pyproject_uv()
    start_wf = _check_start_application_workflow()

    config_ok = deploy["all_ok"] and uv["all_ok"] and start_wf["all_ok"]
    safe = root_unchanged and verify_passed and config_ok

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "39", "part": "A", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "operator_cron": OPERATOR_CRON,
        "operator_cron_note": OPERATOR_CRON_NOTE,
        "expected_run_bound": EXPECTED_RUN_BOUND,
        "root_main_py_unchanged": main_ok,
        "root_deck_csv_unchanged": deck_ok,
        "root_main_py_unchanged_after_verify": main_ok_after,
        "root_deck_csv_unchanged_after_verify": deck_ok_after,
        "package_verify_only_passed": verify_passed,
        "package_verify_returncode": proc.returncode,
        "package_verify_stdout_tail": proc.stdout.strip().splitlines()[-10:],
        "root_unchanged": root_unchanged,
        "deployment_config": deploy,
        "pyproject_uv": uv,
        "start_application_workflow": start_wf,
        "config_ok": config_ok,
        "root_and_deploy_safe": safe,
        "stop_required": not safe,
    }
    (EXP / "pass39_root_deploy_safety.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    dc = deploy["checks"]
    md = [
        "# Pass 39 — Root/deploy safety preflight (Part A)", "",
        "> OPS / verify-only. NO upload, NO submit, NO auto-submit, NO push, NO "
        "root mutation, NO candidate generation. Internal diagnostics; NOT a "
        "Kaggle leaderboard.", "",
        "## Scheduled cadence (operator-stated)",
        f"- cron: **`{OPERATOR_CRON}`** (every 20 min) — _{OPERATOR_CRON_NOTE}_",
        f"- expected RUN bound signature: max_games=**{EXPECTED_RUN_BOUND['max_games']}**, "
        f"max_seconds=**{EXPECTED_RUN_BOUND['max_seconds']}**", "",
        "## Root immutability",
        f"- root main.py byte-identical to baseline: **{yn(main_ok)}**",
        f"- root deck.csv byte-identical to baseline: **{yn(deck_ok)}**",
        f"- package verify-only passed: **{yn(verify_passed)}** "
        f"(returncode {proc.returncode})",
        f"- root unchanged AFTER verify-only: "
        f"main=**{yn(main_ok_after)}** deck=**{yn(deck_ok_after)}**", "",
        "## Scheduled deployment config (.replit [deployment])",
        f"- deploymentTarget == scheduled: **{yn(dc['deployment_target_scheduled'])}**",
        f"- run is the deployment tick (not root main.py): "
        f"**{yn(dc['run_is_deployment_tick'] and dc['run_not_root_main'])}**",
        f"- run has --production: **{yn(dc['run_has_production'])}**",
        f"- run uses replit_app_storage: **{yn(dc['run_uses_object_storage'])}**",
        f"- run bound signature == 20/900: **{yn(dc['run_bound_signature_20_900'])}** "
        f"(`{deploy['run_bound_signature']}`)",
        f"- build installs with --user/--break-system-packages: "
        f"**{yn(dc['build_user_install'] and dc['build_break_system_packages'])}**",
        f"- build has replit-object-storage + pyyaml: "
        f"**{yn(dc['build_has_object_storage'] and dc['build_has_pyyaml'])}**",
        f"- build pins kaggle-environments==1.30.1: "
        f"**{yn(dc['build_has_kaggle_env_pinned'])}**", "",
        "## pyproject [tool.uv] (Pass 37 EACCES fix)",
        f"- [tool.uv] package = false: **{yn(uv['package_false'])}** "
        f"(value: `{uv['package']}`)", "",
        "## Root 'Start application' workflow",
        f"- still the frozen Kaggle entrypoint (python3 main.py): "
        f"**{yn(start_wf['is_frozen_kaggle_entrypoint'])}**",
        "- not-started is EXPECTED (it is the Kaggle agent entrypoint, not a "
        "server); it is **never** started by this pass.", "",
        "## Verdict",
        f"- root + deploy config safe: **{yn(safe)}**",
        f"- stop required: **{yn(not safe)}**", "",
        "## package verify-only output (tail)", "```",
        *payload["package_verify_stdout_tail"], "```",
    ]
    (EXP / "pass39_root_deploy_safety.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"root+deploy: safe={safe} root_unchanged={root_unchanged} "
          f"verify={verify_passed} config_ok={config_ok} stop_required={not safe}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
