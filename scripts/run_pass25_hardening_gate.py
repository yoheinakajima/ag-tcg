#!/usr/bin/env python3
"""Pass 25 (Part G) — Water live-control hardening fixture gate.

LOCAL ONLY. Grades the control (Pass-22 pivot) and the three Pass-25 candidates
against data/fixtures/pass25_water_hardening/ by importing each candidate's
embedded ``core_pilot_decide`` and comparing to ``expect``.

Two views are produced:

  * CROSS-CANDIDATE MATRIX (honest discriminator view): every fixture is graded
    against every candidate, so the genuine deltas are visible -- e.g. plv_01
    FAILs on the control + deckout_guard (no prize flag) but PASSes on the
    prize/hybrid guards; the dko_* draw-count fixtures PASS on every candidate at
    the decide layer.

  * PER-CANDIDATE ELIGIBILITY (conservative gate): a fixture only counts for a
    candidate when it is APPLICABLE to it --
        requires_flag: F     -> applies iff that candidate's flags[F] is truthy
        requires_context: C  -> applies iff C in that candidate's runtime_contexts
        (neither)            -> applies to all
    A candidate PASSes iff it has zero hard failures among its APPLICABLE
    fixtures. This is the honest reading: we never credit (or penalise) a
    candidate for a competency it does not deliver LIVE (e.g. deckout_guard
    carries no prize flag, so the prize-liability fixtures are NA for it; the
    prize guard does not wire ctx38, so the draw-count fixtures are NA for it).

Outputs data/experiments/pass25_hardening_gate.{json,md}. Exit non-zero iff any
candidate has an APPLICABLE hard failure.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.pilot import fixtures as FX  # noqa: E402

EXP = REPO / "data" / "experiments"
FIX_DIR = REPO / "data" / "fixtures" / "pass25_water_hardening"

# Control first (the live-active family reference), then the three candidates.
CANDIDATES = {
    "control (pass22 pivot)":
        REPO / "data" / "submissions" / "candidates_pass22"
        / "league_water_anti_disruption_pivot_v1.tar.gz",
    "deckout_guard_v1":
        REPO / "data" / "submissions" / "candidates_pass25" / "deckout_guard_v1.tar.gz",
    "prize_liability_guard_v1":
        REPO / "data" / "submissions" / "candidates_pass25"
        / "prize_liability_guard_v1.tar.gz",
    "hybrid_guard_v1":
        REPO / "data" / "submissions" / "candidates_pass25" / "hybrid_guard_v1.tar.gz",
}


def _import_candidate(main_path: Path, mod_name: str):
    old = os.getcwd()
    added = str(main_path.parent)
    sys.path.insert(0, added)
    os.chdir(main_path.parent)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, main_path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    finally:
        os.chdir(old)
        if added in sys.path:
            sys.path.remove(added)


def _applicable(fixture: dict, flags: dict, contexts: tuple) -> bool:
    rf = fixture.get("requires_flag")
    if rf is not None and not flags.get(rf):
        return False
    rc = fixture.get("requires_context")
    if rc is not None and rc not in contexts:
        return False
    return True


def grade_candidate(label: str, tarball: Path, fxs: list, idx: int) -> dict:
    if not tarball.exists():
        return {"label": label, "tarball": str(tarball), "error": "tarball missing",
                "has_core_pilot_layer": False, "ok": False, "rows": []}
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(tmp)  # noqa: S202 (our own build artifact)
        main_path = Path(tmp) / "main.py"
        mod = _import_candidate(main_path, f"p25gate_{idx}")
        fn = getattr(mod, "core_pilot_decide", None)
        has_layer = callable(fn)
        flags = dict((getattr(mod, "_CP_PLAYBOOK", {}) or {}).get("flags") or {})
        contexts = tuple(getattr(mod, "_CP_RUNTIME_CONTEXTS", ()) or ())

        rows = []
        for f in fxs:
            applic = _applicable(f, flags, contexts)
            r = FX.grade_fixture(f, (lambda k, b, o: fn(k, b, o)) if has_layer
                                 else (lambda *a: {}), has_layer=has_layer)
            r["applicable"] = applic
            r["requires_flag"] = f.get("requires_flag")
            r["requires_context"] = f.get("requires_context")
            rows.append(r)

    applic_rows = [r for r in rows if r["applicable"]]
    applic_hard_fail = [r for r in applic_rows
                        if r["hard"] and r["status"] == "fail"]
    return {
        "label": label,
        "tarball": str(tarball.relative_to(REPO)),
        "has_core_pilot_layer": has_layer,
        "flags": flags,
        "runtime_contexts": list(contexts),
        "applicable_total": len(applic_rows),
        "applicable_pass": sum(1 for r in applic_rows if r["status"] == "pass"),
        "applicable_fail": sum(1 for r in applic_rows if r["status"] == "fail"),
        "applicable_advisory": sum(1 for r in applic_rows if r["status"] == "advisory"),
        "applicable_na": len(rows) - len(applic_rows),
        "applicable_hard_failures": len(applic_hard_fail),
        "ok": len(applic_hard_fail) == 0,
        "rows": rows,
    }


def _cell(r: dict) -> str:
    if not r["applicable"]:
        return "NA"
    return {"pass": "PASS", "fail": "FAIL", "advisory": "adv", "na": "na"}.get(
        r["status"], r["status"])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-json", default=str(EXP / "pass25_hardening_gate.json"))
    ap.add_argument("--out-md", default=str(EXP / "pass25_hardening_gate.md"))
    ap_args = ap.parse_args()

    EXP.mkdir(parents=True, exist_ok=True)
    fxs = FX.load_fixtures(FIX_DIR)
    results = {label: grade_candidate(label, tb, fxs, i)
               for i, (label, tb) in enumerate(CANDIDATES.items())}

    fixture_ids = [f.get("id") for f in fxs]
    matrix = {}
    for fid in fixture_ids:
        matrix[fid] = {label: _cell(next(r for r in res["rows"] if r["id"] == fid))
                       for label, res in results.items()}

    all_ok = all(res["ok"] for res in results.values())
    report = {
        "pass": "25", "part": "G", "local_only": True, "no_upload": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures_dir": str(FIX_DIR.relative_to(REPO)),
        "gate_ok": all_ok,
        "candidates": {label: {k: v for k, v in res.items() if k != "rows"}
                       | {"rows": res["rows"]} for label, res in results.items()},
        "matrix": matrix,
        "honest_note": "plv_01 is the ONLY genuine prize-liability delta (control + "
                       "deckout_guard FAIL it; prize/hybrid PASS). plv_02/03/04 PASS "
                       "on the control too -- the proven base already fetches the "
                       "1-prize attacker in nearly all windows. dko_* PASS at the "
                       "decide layer for every candidate; only deckout_guard/hybrid "
                       "WIRE ctx38 so the clamp fires LIVE (applicability reflects this).",
        "disclaimer": "Internal fixture gate -- NOT a Kaggle leaderboard.",
    }
    Path(ap_args.out_json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    L = ["# Pass 25 — Water live-control hardening fixture gate (Part G)", "",
         "> LOCAL ONLY — NOT a Kaggle leaderboard.", "",
         f"- generated: {report['generated_at']}",
         f"- gate: **{'PASS' if all_ok else 'FAIL'}** "
         "(per-candidate APPLICABLE hard failures == 0)", "",
         "## Per-candidate eligibility (applicable fixtures only)", "",
         "| candidate | flags(prize) | ctx38 | applic | pass | fail | adv | na | "
         "hard fails | gate |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for label, res in results.items():
        prize = bool(res.get("flags", {}).get("prize_liability_search_pivot"))
        ctx38 = 38 in (res.get("runtime_contexts") or [])
        L.append(f"| {label} | {prize} | {ctx38} | {res['applicable_total']} | "
                 f"{res['applicable_pass']} | {res['applicable_fail']} | "
                 f"{res['applicable_advisory']} | {res['applicable_na']} | "
                 f"{res['applicable_hard_failures']} | "
                 f"{'PASS' if res['ok'] else 'FAIL'} |")
    L += ["", "## Cross-candidate matrix (honest discriminator view)",
          "", "NA = fixture not applicable to that candidate (flag/context not wired).",
          "", "| fixture | " + " | ".join(results.keys()) + " |",
          "|---|" + "|".join(["---"] * len(results)) + "|"]
    for fid in fixture_ids:
        L.append(f"| {fid} | " +
                 " | ".join(matrix[fid][label] for label in results.keys()) + " |")
    L += ["", "## Honest note", "", report["honest_note"], ""]
    Path(ap_args.out_md).write_text("\n".join(L), encoding="utf-8")

    for label, res in results.items():
        print(f"{label}: applic={res['applicable_total']} "
              f"pass={res['applicable_pass']} fail={res['applicable_fail']} "
              f"adv={res['applicable_advisory']} na={res['applicable_na']} "
              f"hardfail={res['applicable_hard_failures']} "
              f"-> {'PASS' if res['ok'] else 'FAIL'}")
    print(f"\ngate_ok={all_ok}\nwrote {ap_args.out_json}\nwrote {ap_args.out_md}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
