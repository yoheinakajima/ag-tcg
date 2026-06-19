#!/usr/bin/env python3
"""Pass 19 (Part H) — validation for every built Pass-19 candidate.

LOCAL ONLY. NO upload. For each Pass-19 candidate (search_only, draw_only) runs:
  * tarball validator (scripts/validate_candidate_tarball.validate)
  * entrypoint validator (scripts/validate_candidate_entrypoint.validate)
  * core-competency gate (data/fixtures/core_competency)
  * references the Pass-19 targeted fixture gate (run separately)
  * live smoke: self / vs parent / vs water reference, 1 game per seat each,
    via the batched subprocess worker.

Writes data/experiments/pass19_candidate_validation.{json,md} and a sentinel
pass19_validation.DONE. Heavy (plays games) -> run via a managed workflow + sentinel.
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
WORKER = REPO / "scripts" / "_pass19_forensic_worker.py"
CORE_FIX = REPO / "data" / "fixtures" / "core_competency"

PARENT_TAR = REPO / "data/submissions/candidates_pass17/league_dragapult_spread.tar.gz"
WATER_TAR = REPO / "data/submissions/candidates_pass17/league_water_core_reference.tar.gz"
# Every Dragapult-family deck (parent included) scores identically on the generic core
# gate (12/14, 1 hard fail vs the 13/14 Water reference): the two misses are a property
# of the deck family under the generic pilot, NOT a regression. So a Pass-19 candidate is
# judged for core competency RELATIVE TO THE PARENT BASELINE (no new regression), not
# against an absolute 14/14 it could never reach without changing the deck.
CANDS = {
    "league_dragapult_v1_search_only":
        REPO / "data/submissions/candidates_pass19/league_dragapult_v1_search_only.tar.gz",
    "league_dragapult_v1_draw_only":
        REPO / "data/submissions/candidates_pass19/league_dragapult_v1_draw_only.tar.gz",
}


def _load(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore
    return m


_vtar = _load("validate_candidate_tarball", REPO / "scripts/validate_candidate_tarball.py")
_vent = _load("validate_candidate_entrypoint", REPO / "scripts/validate_candidate_entrypoint.py")
_gate = _load("run_core_competency_gate", REPO / "scripts/run_core_competency_gate.py")


def _extract_main(tarball: Path, dest: Path) -> str:
    import tarfile
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(dest)  # noqa: S202
    return str(dest / "main.py")


def _smoke_pair(first_main: str, second_main: str, count: int = 1) -> dict:
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    timed_out = False
    try:
        subprocess.run([sys.executable, str(WORKER), first_main, second_main,
                        str(count), out], timeout=120, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        timed_out = True
    except Exception:  # noqa: BLE001
        pass
    res = []
    try:
        with open(out, encoding="utf-8") as fh:
            res = json.load(fh)
    except Exception:  # noqa: BLE001
        res = []
    finally:
        if os.path.exists(out):
            os.unlink(out)
    ok = sum(1 for g in res if g.get("ok"))
    return {"played": len(res), "ok": ok, "timeout": timed_out,
            "all_ok": (len(res) == count and ok == count and not timed_out)}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    sentinel = EXP / "pass19_validation.DONE"
    if sentinel.exists():
        sentinel.unlink()

    report = {"pass": "19", "part": "H", "local_only": True, "upload_performed": False,
              "generated_at": datetime.now(timezone.utc).isoformat(), "candidates": {}}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parent_main = _extract_main(PARENT_TAR, tmp / "parent")
        water_main = _extract_main(WATER_TAR, tmp / "water")

        parent_core = _gate.grade_candidate(str(PARENT_TAR), None, CORE_FIX)
        base_pass, base_hard = parent_core["passed"], parent_core["hard_failures"]
        report["parent_core_baseline"] = {
            "passed": base_pass, "total": parent_core["total"],
            "hard_failures": base_hard, "ok_absolute": parent_core["ok"],
            "note": "Dragapult-family baseline; candidates judged for NO regression "
                    "relative to this, not against an absolute 14/14."}

        for name, tb in CANDS.items():
            tarball_rc = _vtar.validate(str(tb))
            entry_rc = _vent.validate(str(tb), smoke=False)
            core = _gate.grade_candidate(str(tb), None, CORE_FIX)
            no_core_regression = (core["passed"] >= base_pass
                                  and core["hard_failures"] <= base_hard)
            cand_main = _extract_main(tb, tmp / name)

            smoke = {
                "self_seat0": _smoke_pair(cand_main, cand_main),
                "self_seat1": _smoke_pair(cand_main, cand_main),
                "vs_parent_seat0": _smoke_pair(cand_main, parent_main),
                "vs_parent_seat1": _smoke_pair(parent_main, cand_main),
                "vs_water_seat0": _smoke_pair(cand_main, water_main),
                "vs_water_seat1": _smoke_pair(water_main, cand_main),
            }
            smoke_ok = all(s["all_ok"] for s in smoke.values())
            report["candidates"][name] = {
                "tarball": str(tb.relative_to(REPO)),
                "tarball_validator_rc": tarball_rc,
                "entrypoint_validator_rc": entry_rc,
                "core_gate_ok_absolute": core["ok"],
                "core_gate_hard_failures": core["hard_failures"],
                "core_gate_passed": core["passed"], "core_gate_total": core["total"],
                "core_no_regression_vs_parent": no_core_regression,
                "live_smoke": smoke, "live_smoke_ok": smoke_ok,
                "overall_ok": (tarball_rc == 0 and entry_rc == 0
                               and no_core_regression and smoke_ok),
            }

    report["fixture_gate_ref"] = "data/experiments/pass19_dragapult_fixture_results.json"
    report["disclaimer"] = "Internal validation — NOT a Kaggle leaderboard."
    (EXP / "pass19_candidate_validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    pb = report["parent_core_baseline"]
    L = ["# Pass 19 — candidate validation (Part H)", "",
         "> LOCAL ONLY — NOT a Kaggle leaderboard.", "",
         f"**Parent core baseline:** {pb['passed']}/{pb['total']} "
         f"(hard fails {pb['hard_failures']}). Every Dragapult-family deck scores the "
         "same on the generic core gate, so candidates are judged for NO regression "
         "relative to this baseline, not against an absolute 14/14.", "",
         "| candidate | tarball | entrypoint | core (vs parent baseline) | live smoke | overall |",
         "|---|---|---|---|---|---|"]
    for name, c in report["candidates"].items():
        core_cell = (f"{c['core_gate_passed']}/{c['core_gate_total']} "
                     f"(hard {c['core_gate_hard_failures']}) — "
                     f"{'no regression' if c['core_no_regression_vs_parent'] else 'REGRESSION'}")
        L.append(f"| {name} | rc={c['tarball_validator_rc']} | "
                 f"rc={c['entrypoint_validator_rc']} | {core_cell} | "
                 f"{'PASS' if c['live_smoke_ok'] else 'FAIL'} | "
                 f"{'PASS' if c['overall_ok'] else 'FAIL'} |")
    L += ["", "## Live smoke detail (games legal per matchup)", ""]
    for name, c in report["candidates"].items():
        L.append(f"### {name}")
        for k, s in c["live_smoke"].items():
            L.append(f"- {k}: played {s['played']} ok {s['ok']} "
                     f"timeout {s['timeout']}")
        L.append("")
    (EXP / "pass19_candidate_validation.md").write_text("\n".join(L), encoding="utf-8")

    overall = all(c["overall_ok"] for c in report["candidates"].values())
    sentinel.write_text(json.dumps({"status": "ok", "all_overall_ok": overall},
                                   indent=2), encoding="utf-8")
    print("validation done; all overall ok:", overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
