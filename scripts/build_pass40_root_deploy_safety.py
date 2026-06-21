#!/usr/bin/env python3
"""Pass 40 (Part A) — root / deploy / prod safety preflight.

OPS / verify-only. Re-confirms, WITHOUT mutating anything, the hard invariants
before Pass 40 (public Kaggle reference-agent INTAKE — benchmarks only, never our
candidates, never uploaded/submitted/promoted/mutated):

  * root ``main.py``/``deck.csv`` byte-identical to the frozen v1 baseline
    (data/baselines/v1_kaggle_349_8), both before AND after the verify run,
  * ``scripts/package_submission.py --verify-only`` passes and mutates nothing,
  * ``.replit [deployment]`` is the bounded *scheduled worker* (not the root
    Kaggle entrypoint): target=scheduled, run=tournament_deployment_tick.py with
    --production + replit_app_storage + the 20/900 bound signature; build installs
    deploy deps with --user/--break-system-packages incl. kaggle-environments,
  * ``pyproject.toml [tool.uv] package = false`` (Pass 37 EACCES fix),
  * the ``Start application`` workflow is still the frozen Kaggle entrypoint
    (python3 main.py) — not a server; not-started is EXPECTED and never started,
  * production tournament health (scripts/check_tournament_health.py --mode prod)
    is HEALTHY (0 hard failures) — this folds in the "no forbidden events" and
    "all events no_upload" hard invariants for the live object-storage snapshot.

Writes data/experiments/pass40_root_deploy_safety.{json,md} and (via the health
checker) pass40_tournament_health.{json,md}. Exit nonzero if any hard safety /
config / health check fails. NO upload, NO submit, NO push, NO root mutation, NO
candidate generation.
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

OPERATOR_CRON = "*/20 * * * *"
OPERATOR_CRON_NOTE = ("Scheduled Deployment cron set by the operator to "
                      "'*/20 * * * *' (every 20 min); the cron lives in deployment "
                      "settings, not in .replit. The 20/900 RUN signature is "
                      "unchanged.")
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
        "run_not_root_main": "main.py" not in run,
        "run_has_production": "--production" in run,
        "run_uses_object_storage": "replit_app_storage" in run_str,
        "run_bound_signature_20_900": bound == EXPECTED_RUN_BOUND,
        "build_user_install": "--user" in build,
        "build_break_system_packages": "--break-system-packages" in build,
        "build_has_object_storage": "replit-object-storage" in build,
        "build_has_pyyaml": "pyyaml" in build,
        "build_has_kaggle_env": "kaggle-environments" in build_str,
    }
    return {"deploymentTarget": dep.get("deploymentTarget"), "run": run,
            "build": build, "run_bound_signature": bound, "checks": checks,
            "all_ok": all(checks.values())}


def _check_pyproject_uv() -> dict:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    uv = data.get("tool", {}).get("uv", {}) or {}
    package_false = uv.get("package", None) is False
    return {"tool_uv_present": bool(uv), "package": uv.get("package", None),
            "package_false": package_false, "all_ok": package_false}


def _check_start_application_workflow() -> dict:
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


def _run_prod_health() -> dict:
    """Run the prod health checker (read-only) and parse its JSON verdict."""
    out_json = EXP / "pass40_tournament_health.json"
    out_md = EXP / "pass40_tournament_health.md"
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_tournament_health.py"),
         "--mode", "prod", "--out-json", str(out_json), "--out-md", str(out_md)],
        capture_output=True, text=True, cwd=str(REPO), timeout=180)
    parsed = {}
    try:
        parsed = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        parsed = {}
    return {
        "returncode": proc.returncode,
        "healthy": bool(parsed.get("healthy")),
        "source": parsed.get("source"),
        "hard_failures": parsed.get("hard_failures", []),
        "warnings": parsed.get("warnings", []),
        "stdout_tail": proc.stdout.strip().splitlines()[-6:],
        "out_json": str(out_json.relative_to(REPO)),
        "out_md": str(out_md.relative_to(REPO)),
    }


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
    health = _run_prod_health()

    config_ok = deploy["all_ok"] and uv["all_ok"] and start_wf["all_ok"]
    safe = root_unchanged and verify_passed and config_ok and health["healthy"]

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "40", "part": "A", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "operator_cron": OPERATOR_CRON, "operator_cron_note": OPERATOR_CRON_NOTE,
        "expected_run_bound": EXPECTED_RUN_BOUND,
        "root_main_py_unchanged": main_ok, "root_deck_csv_unchanged": deck_ok,
        "root_main_py_unchanged_after_verify": main_ok_after,
        "root_deck_csv_unchanged_after_verify": deck_ok_after,
        "package_verify_only_passed": verify_passed,
        "package_verify_returncode": proc.returncode,
        "package_verify_stdout_tail": proc.stdout.strip().splitlines()[-10:],
        "root_unchanged": root_unchanged,
        "deployment_config": deploy, "pyproject_uv": uv,
        "start_application_workflow": start_wf,
        "prod_health": health,
        "config_ok": config_ok,
        "root_and_deploy_safe": safe,
        "stop_required": not safe,
    }
    (EXP / "pass40_root_deploy_safety.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    dc = deploy["checks"]
    md = [
        "# Pass 40 — Root/deploy/prod safety preflight (Part A)", "",
        "> OPS / verify-only. Public reference-agent intake = benchmarks only. NO "
        "upload, NO submit, NO auto-submit, NO push, NO root/tarball mutation, NO "
        "candidate generation. Internal diagnostics; NOT a Kaggle leaderboard.", "",
        "## Scheduled cadence (operator-stated)",
        f"- cron: **`{OPERATOR_CRON}`** (every 20 min) — _{OPERATOR_CRON_NOTE}_",
        f"- expected RUN bound signature: max_games=**{EXPECTED_RUN_BOUND['max_games']}**, "
        f"max_seconds=**{EXPECTED_RUN_BOUND['max_seconds']}**", "",
        "## Root immutability",
        f"- root main.py byte-identical to baseline: **{yn(main_ok)}**",
        f"- root deck.csv byte-identical to baseline: **{yn(deck_ok)}**",
        f"- package verify-only passed: **{yn(verify_passed)}** "
        f"(returncode {proc.returncode})",
        f"- root unchanged AFTER verify-only: main=**{yn(main_ok_after)}** "
        f"deck=**{yn(deck_ok_after)}**", "",
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
        f"- build has replit-object-storage + pyyaml + kaggle-environments: "
        f"**{yn(dc['build_has_object_storage'] and dc['build_has_pyyaml'] and dc['build_has_kaggle_env'])}**",
        "",
        "## pyproject [tool.uv] (Pass 37 EACCES fix)",
        f"- [tool.uv] package = false: **{yn(uv['package_false'])}** "
        f"(value: `{uv['package']}`)", "",
        "## Root 'Start application' workflow",
        f"- still the frozen Kaggle entrypoint (python3 main.py): "
        f"**{yn(start_wf['is_frozen_kaggle_entrypoint'])}**",
        "- not-started is EXPECTED (Kaggle agent entrypoint, not a server); "
        "**never** started by this pass.", "",
        "## Production tournament health (--mode prod, read-only)",
        f"- source: `{health['source']}`",
        f"- healthy (0 hard failures): **{yn(health['healthy'])}**",
        f"- hard failures: {health['hard_failures'] or 'none'}",
        f"- warnings: {health['warnings'] or 'none'}",
        f"- artifacts: `{health['out_json']}`, `{health['out_md']}`", "",
        "## Verdict",
        f"- root + deploy config + prod health safe: **{yn(safe)}**",
        f"- stop required: **{yn(not safe)}**", "",
        "## package verify-only output (tail)", "```",
        *payload["package_verify_stdout_tail"], "```",
    ]
    (EXP / "pass40_root_deploy_safety.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"root+deploy+health: safe={safe} root_unchanged={root_unchanged} "
          f"verify={verify_passed} config_ok={config_ok} "
          f"healthy={health['healthy']} hard={health['hard_failures']} "
          f"warn={health['warnings']} stop_required={not safe}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
