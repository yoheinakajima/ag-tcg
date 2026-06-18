#!/usr/bin/env python3
"""Pass 8 fixture gate — a HARD promotion filter for policy candidates.

Grades every candidate ``main.py`` against the Pass 8 effect-resolution
fixtures (``data/fixtures/replay_80374966_effect_resolution.json``) and decides
whether the candidate is *eligible for promotion*. The decision is honest about
the two axes the fixtures cover:

* **legality** (always hard): the returned action must be a legal selection for
  every gradeable fixture and the agent must not raise.
* **preference severity**:
    - ``hard`` preference fixtures encode the exact safety mistakes that lost
      the replayed game (orphan Mega fetch, deckout draw, discarding a setup
      piece while energy fodder exists). Failing one BLOCKS promotion.
    - ``advisory`` preference fixtures are role/quality checks: failures are
      recorded as ``advisory_findings`` but never block.

``secret_box_forced_discard_all`` is ``forced_all`` → ``na`` and can never be a
failure. The non-gradeable ``secret_box_play_safety`` seam is skipped by the
grader (no deterministic prompt exists) and reported as documented coverage.

Per-candidate result fields (Part C):
    fixture_pass_count / fixture_fail_count / fixture_na_count
    fixture_advisory_findings
    hard_failures            (list — empty == eligible)
    promotable_gate          (bool — hard gate passed)

LOCAL ONLY. Reads candidate dirs + frozen fixtures; writes
``data/experiments/pass8_fixture_gate.json`` and ``.md``. Never mutates root
main.py / deck.csv or any candidate.

Usage:
    python scripts/run_pass8_fixture_gate.py
    python scripts/run_pass8_fixture_gate.py --runs-root experiments/runs_pass8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from test_candidate_on_fixtures import evaluate_candidate_on_fixtures

RUNS_ROOT = "experiments/runs_pass8"
FIXTURES_FILE = "data/fixtures/replay_80374966_effect_resolution.json"
V2_ANCHOR = "data/baselines/v2_kaggle_479_1_deck_energy_trim_light"
OUT_JSON = "data/experiments/pass8_fixture_gate.json"
OUT_MD = "data/experiments/pass8_fixture_gate.md"


def _load_severity_map(fixtures_file: str) -> dict[str, dict]:
    """fixture id -> {severity, kind, spec_case} for gradeable fixtures."""
    out: dict[str, dict] = {}
    try:
        data = json.loads(Path(fixtures_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    items = data.get("fixtures", []) if isinstance(data, dict) else []
    for fx in items:
        if not isinstance(fx, dict) or not fx.get("gradeable", True):
            continue
        out[fx.get("id")] = {
            "severity": fx.get("severity", "advisory"),
            "kind": fx.get("check", {}).get("preference", {}).get("kind"),
            "spec_case": fx.get("spec_case"),
        }
    return out


def _grade_candidate(candidate_id: str, run_dir: str, fixtures_file: str,
                     sev_map: dict[str, dict], is_anchor: bool) -> dict:
    report = evaluate_candidate_on_fixtures(run_dir, fixtures_file)
    fixture_pass = fixture_fail = fixture_na = 0
    advisory_findings: list[dict] = []
    hard_failures: list[dict] = []
    per_fixture: list[dict] = []

    for fx in report.get("fixtures", []):
        fid = fx.get("id")
        meta = sev_map.get(fid, {"severity": "advisory"})
        severity = meta.get("severity", "advisory")
        legal = bool(fx.get("legal"))
        pref = fx.get("preference", {})
        pref_result = pref.get("result", "na")

        if not legal:
            fixture_fail += 1
            hard_failures.append({
                "fixture": fid, "reason": "illegal selection",
                "detail": fx.get("legal_reason") or fx.get("error"),
            })
        elif pref_result == "pass":
            fixture_pass += 1
        elif pref_result == "fail":
            fixture_fail += 1
            finding = {"fixture": fid, "severity": severity,
                       "kind": pref.get("kind"), "detail": pref.get("detail")}
            if severity == "hard":
                hard_failures.append({
                    "fixture": fid, "reason": "hard preference fail",
                    "detail": pref.get("detail"),
                })
            else:
                advisory_findings.append(finding)
        else:  # na (forced_all, cannot-decline, etc.)
            fixture_na += 1

        per_fixture.append({
            "fixture": fid, "severity": severity, "legal": legal,
            "preference": pref_result, "detail": pref.get("detail"),
            "action": fx.get("action"),
        })

    promotable_gate = bool(report.get("loaded")) and not hard_failures
    return {
        "candidate_id": candidate_id,
        "run_dir": run_dir,
        "is_anchor": is_anchor,
        "loaded": bool(report.get("loaded")),
        "load_error": report.get("load_error"),
        "n_fixtures": report.get("n_fixtures", 0),
        "fixture_pass_count": fixture_pass,
        "fixture_fail_count": fixture_fail,
        "fixture_na_count": fixture_na,
        "fixture_advisory_findings": advisory_findings,
        "hard_failures": hard_failures,
        "promotable_gate": promotable_gate,
        "per_fixture": per_fixture,
    }


def _discover_candidates(runs_root: str) -> list[tuple[str, str]]:
    """Return (candidate_id, run_dir) for every dir under runs_root with main.py.

    candidate_id is the trailing branch id (dir name with any leading
    ``<timestamp>_`` stripped) so it matches the generator's branch ids.
    """
    root = Path(runs_root)
    out: list[tuple[str, str]] = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / "main.py").exists():
            continue
        name = child.name
        # strip a leading timestamp prefix like 20260618_040109_ab12cd_
        parts = name.split("_")
        # heuristic: branch id is everything after the run-id prefix; the
        # generator names dirs <branchid> or <ts>_<branchid>. Keep full name
        # as id when unsure (used only for display + matching by suffix).
        out.append((name, str(child)))
    return out


def run_gate(runs_root: str = RUNS_ROOT, fixtures_file: str = FIXTURES_FILE,
             anchor: str | None = V2_ANCHOR) -> dict:
    sev_map = _load_severity_map(fixtures_file)
    results: list[dict] = []
    for cid, run_dir in _discover_candidates(runs_root):
        results.append(_grade_candidate(cid, run_dir, fixtures_file, sev_map,
                                        is_anchor=False))
    if anchor and Path(anchor, "main.py").exists():
        results.append(_grade_candidate("v2_control_anchor", anchor,
                                        fixtures_file, sev_map, is_anchor=True))

    policy = [r for r in results if not r["is_anchor"]]
    eligible = [r["candidate_id"] for r in policy if r["promotable_gate"]]
    blocked = [r["candidate_id"] for r in policy if not r["promotable_gate"]]
    return {
        "stage": "pass8_fixture_gate",
        "runs_root": runs_root,
        "fixtures_file": fixtures_file,
        "n_gradeable_fixtures": len(sev_map),
        "n_hard_fixtures": sum(1 for m in sev_map.values()
                               if m["severity"] == "hard"),
        "n_candidates": len(policy),
        "eligible": eligible,
        "blocked": blocked,
        "results": results,
        "forced_discard_note": (
            "secret_box_forced_discard_all is forced_all/na and is never "
            "counted as a failure; secret_box_play_safety is a documented "
            "non-gradeable pre-play seam (skipped by the grader)."
        ),
    }


def _format_md(summary: dict) -> str:
    lines: list[str] = []
    lines.append("# Pass 8 Fixture Gate (hard promotion filter)")
    lines.append("")
    lines.append(
        f"Graded {summary['n_candidates']} candidate(s) against "
        f"{summary['n_gradeable_fixtures']} gradeable fixtures "
        f"({summary['n_hard_fixtures']} hard) in `{summary['fixtures_file']}`."
    )
    lines.append("")
    lines.append(f"- ELIGIBLE (hard gate passed): {', '.join(summary['eligible']) or 'none'}")
    lines.append(f"- BLOCKED: {', '.join(summary['blocked']) or 'none'}")
    lines.append("")
    lines.append("## Per-candidate")
    lines.append("")
    for r in summary["results"]:
        tag = " (anchor)" if r["is_anchor"] else ""
        gate = "PASS" if r["promotable_gate"] else "BLOCKED"
        lines.append(f"### {r['candidate_id']}{tag} — gate **{gate}**")
        if r.get("load_error"):
            lines.append(f"- LOAD ERROR: {r['load_error']}")
            lines.append("")
            continue
        lines.append(
            f"- fixtures: {r['fixture_pass_count']} pass / "
            f"{r['fixture_fail_count']} fail / {r['fixture_na_count']} na"
        )
        if r["hard_failures"]:
            for hf in r["hard_failures"]:
                lines.append(f"- HARD FAIL `{hf['fixture']}`: "
                             f"{hf['reason']} — {hf.get('detail')}")
        else:
            lines.append("- hard failures: none")
        for af in r["fixture_advisory_findings"]:
            lines.append(f"  - advisory `{af['fixture']}` ({af['kind']}): "
                         f"{af['detail']}")
        lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append(summary["forced_discard_note"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--runs-root", default=RUNS_ROOT)
    parser.add_argument("--fixtures-file", default=FIXTURES_FILE)
    parser.add_argument("--anchor", default=V2_ANCHOR)
    parser.add_argument("--out-json", default=OUT_JSON)
    parser.add_argument("--out-md", default=OUT_MD)
    args = parser.parse_args()

    summary = run_gate(args.runs_root, args.fixtures_file, args.anchor)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.out_md).write_text(_format_md(summary), encoding="utf-8")
    print(json.dumps({
        "eligible": summary["eligible"],
        "blocked": summary["blocked"],
        "n_candidates": summary["n_candidates"],
        "out_json": args.out_json,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
