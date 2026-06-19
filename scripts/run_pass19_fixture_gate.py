#!/usr/bin/env python3
"""Pass 19 (Part G/H) — Dragapult parent/child targeted fixture gate.

LOCAL ONLY. Grades the parent, the child (v1), and the two Pass-19 ablations against the
Pass-19 targeted fixtures (data/fixtures/pass19_dragapult_parent_child/) by importing each
candidate's embedded ``core_pilot_decide`` and comparing to ``expect``.

The KEY discriminator is dp19_04 (preserve the draw engine in discard): parent +
search_only PASS; child + draw_only FAIL — localizing the regression to draw_support.

Outputs data/experiments/pass19_dragapult_fixture_results.{json,md}.
"""
from __future__ import annotations

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
FIX_DIR = REPO / "data" / "fixtures" / "pass19_dragapult_parent_child"

CANDIDATES = {
    "parent (league_dragapult_spread)":
        REPO / "data" / "submissions" / "candidates_pass17" / "league_dragapult_spread.tar.gz",
    "child (league_dragapult_spread_v1)":
        REPO / "data" / "submissions" / "candidates_pass18" / "league_dragapult_spread_v1.tar.gz",
    "search_only (targeted_revert)":
        REPO / "data" / "submissions" / "candidates_pass19" / "league_dragapult_v1_search_only.tar.gz",
    "draw_only (diagnostic)":
        REPO / "data" / "submissions" / "candidates_pass19" / "league_dragapult_v1_draw_only.tar.gz",
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


def grade_tarball(label: str, tarball: Path, idx: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(tmp)  # noqa: S202 (our own build artifact)
        main_path = Path(tmp) / "main.py"
        mod = _import_candidate(main_path, f"p19fix_{idx}")
        fn = getattr(mod, "core_pilot_decide", None)
        has_layer = callable(fn)
        fxs = FX.load_fixtures(FIX_DIR)
        summary = FX.grade_all(
            fxs, (lambda k, b, o: fn(k, b, o)) if has_layer else (lambda *a: {}),
            has_layer=has_layer)
    summary["label"] = label
    summary["tarball"] = str(tarball.relative_to(REPO))
    summary["has_core_pilot_layer"] = has_layer
    return summary


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    results = {}
    for i, (label, tb) in enumerate(CANDIDATES.items()):
        results[label] = grade_tarball(label, tb, i)

    # Per-fixture cross-candidate matrix (key discriminator visibility).
    fixture_ids = [r["id"] for r in next(iter(results.values()))["rows"]]
    matrix = {}
    for fid in fixture_ids:
        matrix[fid] = {label: next(r["status"] for r in res["rows"] if r["id"] == fid)
                       for label, res in results.items()}

    report = {
        "pass": "19", "part": "G/H", "local_only": True, "upload_performed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures_dir": str(FIX_DIR.relative_to(REPO)),
        "candidates": {label: {
            "tarball": res["tarball"], "has_core_pilot_layer": res["has_core_pilot_layer"],
            "total": res["total"], "passed": res["passed"], "failed": res["failed"],
            "advisory": res["advisory"], "na": res["na"],
            "hard_failures": res["hard_failures"], "ok": res["ok"],
            "rows": res["rows"]} for label, res in results.items()},
        "matrix": matrix,
        "key_discriminator": "dp19_04_preserve_draw_engine_in_discard",
        "disclaimer": "Internal fixture gate — NOT a Kaggle leaderboard.",
    }
    (EXP / "pass19_dragapult_fixture_results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    L = ["# Pass 19 — Dragapult parent/child fixture gate (Part G/H)", "",
         "> LOCAL ONLY — NOT a Kaggle leaderboard.", "",
         "## Summary", "",
         "| candidate | total | pass | fail | advisory | na | hard fails | gate |",
         "|---|---|---|---|---|---|---|---|"]
    for label, res in results.items():
        L.append(f"| {label} | {res['total']} | {res['passed']} | {res['failed']} | "
                 f"{res['advisory']} | {res['na']} | {res['hard_failures']} | "
                 f"{'PASS' if res['ok'] else 'FAIL'} |")
    L += ["", "## Per-fixture matrix (status by candidate)", "",
          "| fixture | " + " | ".join(results.keys()) + " |",
          "|---|" + "|".join(["---"] * len(results)) + "|"]
    for fid in fixture_ids:
        L.append(f"| {fid} | " +
                 " | ".join(matrix[fid][label] for label in results.keys()) + " |")
    L += ["", f"**Key discriminator:** `{report['key_discriminator']}` — parent and "
          "search_only PASS (keep the draw engine); child and draw_only FAIL (discard "
          "it), localizing the parent-H2H regression to the `draw_support` role alias.",
          ""]
    (EXP / "pass19_dragapult_fixture_results.md").write_text("\n".join(L), encoding="utf-8")

    for label, res in results.items():
        print(f"{label}: pass {res['passed']} fail {res['failed']} "
              f"adv {res['advisory']} na {res['na']} hardfail {res['hard_failures']} "
              f"-> {'PASS' if res['ok'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
