#!/usr/bin/env python3
"""Pass 10B Part G -- tiny evaluation smoke to prove cabt eval is back.

This is INFRASTRUCTURE PROOF ONLY. Results are NOT used for promotion. It:

  1. Reads the dynamic active control from the live score registry.
  2. Runs active-control vs itself, 1 game per seat.
  3. If a validator-passing Pass 10 candidate tarball is available, runs that
     candidate vs the active control, 1 game per seat.

If cabt is not genuinely available (per scripts/diagnose_cabt.py), it writes a
blocked status and runs nothing.

Writes:
    data/experiments/pass10b_eval_smoke.json
    data/experiments/pass10b_eval_smoke.md

No upload, no submission, no candidate generation.
"""

from __future__ import annotations

import json
import signal
import tarfile
import tempfile
import time
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import REPO_ROOT

OUT_JSON = REPO_ROOT / "data" / "experiments" / "pass10b_eval_smoke.json"
OUT_MD = REPO_ROOT / "data" / "experiments" / "pass10b_eval_smoke.md"
REGISTRY = REPO_ROOT / "data" / "kaggle_uploads" / "live_score_registry.json"
DIAG = REPO_ROOT / "data" / "experiments" / "cabt_diagnostic.json"
CANDIDATE_TARBALL = (REPO_ROOT / "data" / "submissions" / "candidates"
                     / "combo_full_safety_v3_fixed.tar.gz")

GAME_TIMEOUT_SECONDS = 30


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise _Timeout()


def _active_control_dir() -> Path:
    """Map the registry's active control to a local baseline dir."""
    default = REPO_ROOT / "data" / "baselines" / "v1_kaggle_349_8"
    if not REGISTRY.exists():
        return default
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    ac = reg.get("active_control") or {}
    desc = (ac.get("description") or "").lower()
    fname = (ac.get("filename") or "").lower()
    # v2 (deck_energy_trim_light) only if the registry explicitly names it.
    if "deck_energy_trim_light" in desc or "deck_energy_trim_light" in fname:
        v2 = REPO_ROOT / "data" / "baselines" / "v2_kaggle_479_1_deck_energy_trim_light"
        if v2.exists():
            return v2
    return default


def _run_game(agent_a: str, agent_b: str) -> dict:
    from kaggle_environments import make
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_SECONDS)
    try:
        env = make("cabt")
        env.run([agent_a, agent_b])
        last = env.steps[-1]
        rewards = [s.get("reward") for s in last]
        statuses = [s.get("status") for s in last]
        return {"ok": True, "steps": len(env.steps), "rewards": rewards,
                "statuses": statuses, "timeout": False}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "game exceeded watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _validate_candidate(tarball: Path) -> bool:
    if not tarball.exists():
        return False
    try:
        from scripts.validate_candidate_tarball import validate  # type: ignore
    except Exception:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_candidate_tarball",
            REPO_ROOT / "scripts" / "validate_candidate_tarball.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        validate = mod.validate
    return validate(str(tarball)) == 0


def _extract_agent(tarball: Path, dest: Path) -> Path:
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202 (our own build artifact)
    main = dest / "main.py"
    if not main.exists():
        # find nested main.py
        for p in dest.rglob("main.py"):
            return p
    return main


def run_smoke() -> dict:
    rep: dict = {"pass": "10b", "generated_at": time.time(),
                 "note": "infrastructure proof only; NOT used for promotion"}

    # cabt availability gate (genuine -- from diagnostic).
    cabt_available = False
    if DIAG.exists():
        cabt_available = bool(json.loads(DIAG.read_text()).get("cabt_available"))
    rep["cabt_available"] = cabt_available

    if not cabt_available:
        rep["status"] = "blocked"
        rep["reason"] = "cabt_unavailable"
        rep["smoke_attempted"] = False
        rep["can_run_future_meta_eval"] = False
        return rep

    rep["status"] = "ok"
    rep["smoke_attempted"] = True
    ctrl_dir = _active_control_dir()
    ctrl_agent = str(ctrl_dir / "main.py")
    rep["active_control_dir"] = str(ctrl_dir.relative_to(REPO_ROOT))

    # 1. active vs active, one game per seat.
    rep["active_vs_active"] = [
        {"seat_layout": "control@0 vs control@1", **_run_game(ctrl_agent, ctrl_agent)},
        {"seat_layout": "control@1 vs control@0 (swapped)", **_run_game(ctrl_agent, ctrl_agent)},
    ]

    # 2. candidate vs control, validator-gated, one game per seat.
    cand_block: dict = {"tarball": str(CANDIDATE_TARBALL.relative_to(REPO_ROOT))
                        if CANDIDATE_TARBALL.exists() else None}
    if CANDIDATE_TARBALL.exists() and _validate_candidate(CANDIDATE_TARBALL):
        cand_block["validator_passed"] = True
        with tempfile.TemporaryDirectory() as tmp:
            cand_agent = str(_extract_agent(CANDIDATE_TARBALL, Path(tmp)))
            cand_block["games"] = [
                {"seat_layout": "candidate@0 vs control@1",
                 **_run_game(cand_agent, ctrl_agent)},
                {"seat_layout": "candidate@1 vs control@0",
                 **_run_game(ctrl_agent, cand_agent)},
            ]
    else:
        cand_block["validator_passed"] = (
            False if CANDIDATE_TARBALL.exists() else None)
        cand_block["games"] = []
        cand_block["note"] = ("no validator-passing candidate available; "
                              "candidate leg skipped (this is fine for a smoke)")
    rep["candidate_vs_control"] = cand_block

    rep["can_run_future_meta_eval"] = True
    return rep


def _render_md(rep: dict) -> str:
    L = ["# Pass 10B Evaluation Smoke", ""]
    L.append(f"- Status: **{rep['status']}**"
             + (f" (reason: {rep.get('reason')})" if rep.get("reason") else ""))
    L.append(f"- cabt available: {rep['cabt_available']}")
    L.append(f"- Smoke attempted: {rep.get('smoke_attempted')}")
    L.append(f"- Can run future meta eval: {rep.get('can_run_future_meta_eval')}")
    L.append(f"- Note: {rep['note']}")
    if rep.get("active_vs_active"):
        L.append("")
        L.append("## Active control vs itself")
        for g in rep["active_vs_active"]:
            L.append(f"- {g['seat_layout']}: steps={g.get('steps')} "
                     f"rewards={g.get('rewards')} ok={g.get('ok')}")
    cvc = rep.get("candidate_vs_control")
    if cvc:
        L.append("")
        L.append("## Candidate vs active control (validator-gated)")
        L.append(f"- tarball: {cvc.get('tarball')}")
        L.append(f"- validator passed: {cvc.get('validator_passed')}")
        for g in cvc.get("games", []):
            L.append(f"- {g['seat_layout']}: steps={g.get('steps')} "
                     f"rewards={g.get('rewards')} ok={g.get('ok')}")
        if cvc.get("note"):
            L.append(f"- {cvc['note']}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    rep = run_smoke()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_render_md(rep), encoding="utf-8")
    print(f"Pass 10B eval smoke: {rep['status']}")
    print(f"Wrote {OUT_JSON.relative_to(REPO_ROOT)} and {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
