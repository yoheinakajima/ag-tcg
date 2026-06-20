#!/usr/bin/env python3
"""Pass 38 (Part A) — root safety + scheduled-deployment config verification.

OPS/verify-only. Confirms, WITHOUT mutating anything:
  * root ``main.py``/``deck.csv`` byte-identical to the frozen v1 baseline,
  * ``scripts/package_submission.py --verify-only`` passes and does NOT mutate root,
  * ``.replit [deployment]`` is a *bounded scheduled worker* (not the root Kaggle
    entrypoint): target=scheduled, run=tournament_deployment_tick.py with
    --production + --storage-backend replit_app_storage, build installs the deploy
    deps with --user/--break-system-packages incl. kaggle-environments==1.30.1,
  * ``pyproject.toml [tool.uv] package = false`` (the Pass 37 EACCES fix),
  * the ``Start application`` workflow is the frozen Kaggle entrypoint (python3
    main.py) — NOT a server; not-started is EXPECTED and is never started here.

Writes evidence-derived artifacts:
- data/experiments/pass38_root_and_deploy_config.json
- data/experiments/pass38_root_and_deploy_config.md

Exit nonzero if any hard safety/config check fails. NO upload, NO submit, NO push,
NO root mutation, NO candidate generation.
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


def _cmp(name: str) -> bool | None:
    root_f, base_f = REPO / name, BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return None
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return None


def _check_replit_deployment() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = data.get("deployment", {}) or {}
    run = dep.get("run", []) or []
    build = dep.get("build", []) or []
    run_str = " ".join(str(x) for x in run)
    build_str = " ".join(str(x) for x in build)
    checks = {
        "deployment_target_scheduled": dep.get("deploymentTarget") == "scheduled",
        "run_is_deployment_tick": "scripts/tournament_deployment_tick.py" in run_str,
        "run_not_root_main": "main.py" not in run,  # exact-token: never `python main.py`
        "run_has_production": "--production" in run,
        "run_uses_object_storage": "replit_app_storage" in run_str,
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
        "pass": "38", "part": "A", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "baseline": str(BASELINE.relative_to(REPO)),
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
    (EXP / "pass38_root_and_deploy_config.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    dc = deploy["checks"]
    md = [
        "# Pass 38 — Root safety + scheduled-deployment config (Part A)", "",
        "> OPS / verify-only. NO upload, NO submit, NO auto-submit, NO push, NO "
        "root mutation, NO candidate generation. Internal diagnostics; NOT a "
        "Kaggle leaderboard.", "",
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
    (EXP / "pass38_root_and_deploy_config.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"root+deploy: safe={safe} root_unchanged={root_unchanged} "
          f"verify={verify_passed} config_ok={config_ok} stop_required={not safe}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
