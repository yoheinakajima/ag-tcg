#!/usr/bin/env python3
"""Pass 14 — deterministic core-competency gate.

Grades a candidate against the reduced-model core-competency fixtures by importing
the candidate's extracted ``main.py`` and calling its embedded
``core_pilot_decide(kind, board, options)``. A candidate that exposes no such layer
(e.g. the active control) provably lacks the competence: its hard fixtures FAIL
(informative) and advisory fixtures are NA.

Hard failures block evaluation and the upload queue -> this script exits non-zero
when the candidate under test has any hard failure.

Outputs ``data/reports/pass14_core_gate.json`` and ``.md`` (paths overridable).

Usage:
    python scripts/run_core_competency_gate.py --candidate PATH/TO/candidate.tar.gz
    python scripts/run_core_competency_gate.py --candidate-dir PATH/TO/extracted_dir
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.ptcg_activegraph.pilot import fixtures as FX  # noqa: E402

DEFAULT_FIXTURES = REPO / "data" / "fixtures" / "core_competency"
DEFAULT_JSON = REPO / "data" / "reports" / "pass14_core_gate.json"
DEFAULT_MD = REPO / "data" / "reports" / "pass14_core_gate.md"


def _import_candidate(main_path: Path):
    """Import an extracted candidate main.py with cwd set to its dir."""
    old_cwd = os.getcwd()
    added = str(main_path.parent)
    sys.path.insert(0, added)
    os.chdir(main_path.parent)
    try:
        spec = importlib.util.spec_from_file_location("candidate_core_gate", main_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["candidate_core_gate"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        os.chdir(old_cwd)
        if added in sys.path:
            sys.path.remove(added)


def _grade_dir(cand_dir: Path, fixtures_dir: Path, candidate_id: str) -> dict:
    main_path = cand_dir / "main.py"
    if not main_path.exists():
        raise FileNotFoundError(f"no main.py in {cand_dir}")
    mod = _import_candidate(main_path)
    fn = getattr(mod, "core_pilot_decide", None)
    has_layer = callable(fn)

    def decide_fn(kind, board, options):
        return fn(kind, board, options)

    fxs = FX.load_fixtures(fixtures_dir)
    summary = FX.grade_all(fxs, decide_fn if has_layer else (lambda *a: {}),
                           has_layer=has_layer)
    summary["candidate_id"] = candidate_id
    summary["has_core_pilot_layer"] = has_layer
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def grade_candidate(candidate: str | None, candidate_dir: str | None,
                    fixtures_dir: Path) -> dict:
    if candidate_dir:
        cdir = Path(candidate_dir)
        return _grade_dir(cdir, fixtures_dir, cdir.name)
    tb = Path(candidate)  # type: ignore[arg-type]
    if not tb.exists():
        raise FileNotFoundError(f"tarball not found: {tb}")
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tb, "r:gz") as tar:
            tar.extractall(tmp)  # noqa: S202 (our own build artifact)
        return _grade_dir(Path(tmp), fixtures_dir, tb.name)


def _render_md(summary: dict) -> str:
    lines = [
        f"# Pass 14 — Core-Competency Gate: `{summary['candidate_id']}`",
        "",
        f"- generated: {summary['generated_at']}",
        f"- core-pilot layer present: **{summary['has_core_pilot_layer']}**",
        f"- total: {summary['total']}  pass: {summary['passed']}  "
        f"fail: {summary['failed']}  advisory: {summary['advisory']}  na: {summary['na']}",
        f"- hard failures: **{summary['hard_failures']}**  -> gate "
        f"**{'PASS' if summary['ok'] else 'FAIL'}**",
        "",
        "| status | id | kind | hard | detail |",
        "|---|---|---|---|---|",
    ]
    for r in summary["rows"]:
        lines.append(f"| {r['status']} | {r['id']} | {r['kind']} | "
                     f"{r['hard']} | {r['detail']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--candidate", help="path to candidate .tar.gz")
    g.add_argument("--candidate-dir", help="path to an extracted candidate dir")
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--out-json", default=str(DEFAULT_JSON))
    ap.add_argument("--out-md", default=str(DEFAULT_MD))
    args = ap.parse_args()

    summary = grade_candidate(args.candidate, args.candidate_dir, Path(args.fixtures))

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.out_md).write_text(_render_md(summary), encoding="utf-8")

    print(_render_md(summary))
    print(f"\nwrote {args.out_json}\nwrote {args.out_md}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
