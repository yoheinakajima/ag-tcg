#!/usr/bin/env python3
"""Diagnose local cabt (Pokémon TCG battle) engine availability -- Pass 10B Part C.

Runs a battery of read-only checks and records exactly what works and what does
not, with full exception traces. Writes:

    data/experiments/cabt_diagnostic.json
    data/experiments/cabt_diagnostic.md

(The human-readable console transcript is tee'd to a .log by the caller.)

This never installs, uploads, or mutates anything. It only inspects the current
interpreter + installed packages.

Usage:
    python scripts/diagnose_cabt.py 2>&1 | tee data/experiments/cabt_diagnostic.log
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import platform
import sys
import traceback
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import REPO_ROOT

OUT_JSON = REPO_ROOT / "data" / "experiments" / "cabt_diagnostic.json"
OUT_MD = REPO_ROOT / "data" / "experiments" / "cabt_diagnostic.md"


def _pkg_version(name: str) -> str | None:
    try:
        return md.version(name)
    except Exception:
        return None


def _check(fn) -> dict:
    """Run a check, capturing ok/result/exception trace."""
    try:
        result = fn()
        return {"ok": True, "result": result, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": None,
                "error": "".join(traceback.format_exception_only(type(exc), exc)).strip(),
                "trace": traceback.format_exc()}


def _kenv_import():
    import kaggle_environments  # noqa: F401
    return getattr(kaggle_environments, "version", "unknown")


def _kenv_envs():
    import kaggle_environments as ke
    try:
        return sorted(ke.envs.keys())
    except Exception:
        return []


def _make_cabt():
    from kaggle_environments import make
    env = make("cabt")
    return {"name": str(getattr(env, "name", None)), "type": type(env).__name__}


def _cabt_module():
    mod = importlib.import_module("cabt")
    return {"file": getattr(mod, "__file__", None)}


def _active_control_agent() -> str | None:
    """Path to the active-control agent (v1 baseline) if present, else None."""
    cand = REPO_ROOT / "data" / "baselines" / "v1_kaggle_349_8" / "main.py"
    return str(cand) if cand.exists() else None


def _self_play_smoke():
    """Run a *real* self-play game via cabt to prove the engine actually plays.

    A bare ``reset()`` is not proof -- kaggle_environments can construct an
    Environment from a bundled spec without a working interpreter. Genuine
    availability requires ``env.run`` to finish with DONE statuses and finite
    rewards. Uses the active-control agent if available, else ``random``.
    """
    from kaggle_environments import make
    agent = _active_control_agent() or "random"
    env = make("cabt")
    env.run([agent, agent])
    last = env.steps[-1]
    statuses = [s.get("status") for s in last]
    rewards = [s.get("reward") for s in last]
    done = all(st == "DONE" for st in statuses)
    if not done:
        raise RuntimeError(f"game did not finish cleanly: statuses={statuses}")
    return {"agent": "active_control" if agent != "random" else "random",
            "steps": len(env.steps), "statuses": statuses, "rewards": rewards}


def run_diagnostic() -> dict:
    rep: dict = {}
    rep["python_version"] = sys.version
    rep["platform"] = platform.platform()
    rep["packages"] = {
        "kaggle": _pkg_version("kaggle"),
        "kaggle-environments": _pkg_version("kaggle-environments"),
        "open-spiel": _pkg_version("open-spiel") or _pkg_version("open_spiel"),
        "cabt": _pkg_version("cabt"),
    }

    checks: dict = {}
    checks["kaggle_environments_import"] = _check(_kenv_import)
    envs_check = _check(_kenv_envs)
    checks["environment_list"] = envs_check
    envs = envs_check.get("result") or []
    checks["cabt_in_environment_list"] = {
        "ok": "cabt" in envs, "result": "cabt" in envs, "error": None}
    checks["make_cabt"] = _check(_make_cabt)
    checks["cabt_module_import"] = _check(_cabt_module)
    # Only attempt self-play if make("cabt") succeeded.
    if checks["make_cabt"]["ok"]:
        checks["self_play_smoke"] = _check(_self_play_smoke)
    else:
        checks["self_play_smoke"] = {
            "ok": False, "result": None,
            "error": "skipped: make('cabt') unavailable", "trace": None}
    rep["checks"] = checks

    # Installed packages matching keywords (read-only inventory).
    matches = []
    for dist in md.distributions():
        try:
            nm = dist.metadata["Name"]
        except Exception:
            continue
        if nm and any(k in nm.lower() for k in ("kaggle", "open", "spiel", "cabt")):
            matches.append(f"{nm}=={_pkg_version(nm)}")
    rep["matching_packages"] = sorted(set(matches))

    cabt_available = bool(
        checks["make_cabt"]["ok"] and checks["self_play_smoke"]["ok"])
    rep["cabt_available"] = cabt_available
    rep["status"] = "available" if cabt_available else "blocked"
    rep["reason"] = None if cabt_available else "cabt_unavailable"
    return rep


def _render_md(rep: dict) -> str:
    L = ["# cabt Diagnostic (Pass 10B)", ""]
    L.append(f"- Status: **{rep['status']}**"
             + (f" (reason: {rep['reason']})" if rep["reason"] else ""))
    L.append(f"- Python: `{rep['python_version'].splitlines()[0]}`")
    L.append(f"- Platform: `{rep['platform']}`")
    L.append("")
    L.append("## Packages")
    for k, v in rep["packages"].items():
        L.append(f"- {k}: `{v}`")
    L.append("")
    L.append("## Checks")
    L.append("| check | ok | detail |")
    L.append("|---|---|---|")
    for name, c in rep["checks"].items():
        detail = c.get("error") or json.dumps(c.get("result"), default=str)
        detail = (detail or "")[:90].replace("|", "\\|").replace("\n", " ")
        L.append(f"| {name} | {'yes' if c['ok'] else 'no'} | {detail} |")
    L.append("")
    L.append("## Matching packages")
    for m in rep["matching_packages"]:
        L.append(f"- `{m}`")
    L.append("")
    return "\n".join(L)


def main() -> int:
    rep = run_diagnostic()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_render_md(rep), encoding="utf-8")

    print(f"\n=== cabt diagnostic: {rep['status']} ===")
    for k, v in rep["packages"].items():
        print(f"  {k}: {v}")
    for name, c in rep["checks"].items():
        print(f"  [{'OK ' if c['ok'] else 'XX '}] {name}"
              + (f" -- {c['error']}" if c.get("error") else ""))
    print(f"Wrote {OUT_JSON.relative_to(REPO_ROOT)} and {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
