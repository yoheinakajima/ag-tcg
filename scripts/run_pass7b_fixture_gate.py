#!/usr/bin/env python3
"""Pass 7B fixture gate for the 4 targeted policy candidates.

Re-uses the Pass-6 Stage-0 decision-fixture grader
(``scripts/test_candidate_on_fixtures.py``) to grade the four policy
candidates that Pass 7B intends to scout, plus the v2 anchor for reference.

The gate is honest about what the fixtures can and cannot prove:

* ``legality_gate`` is a HARD pre-cabt gate. A candidate that fails legality on
  any frozen prompt, or whose ``agent`` raises, is rejected before any (slow)
  cabt game.
* preferences are ADVISORY. v2 is expected to fail some of them; a v3 policy
  aims to convert those fails to passes. We record them, we do not reject on
  them.

Secret-Box step-11 nuance (preserved): the step-11 discard prompt has
``minCount == maxCount == n_options == 3`` so the ONLY legal selection is all
three options. A setup piece (Snover 722) cannot be spared. This is a *forced*
discard recorded as ``forced_all`` / ``na`` — NOT a policy failure, and the
real "is it safe to play Secret Box at all" seam is a pre-play decision that
this in-resolution fixture cannot represent. The secret-box candidates are
therefore graded as legality-pass with an explicit note that their target seam
is not covered by the forced fixture.

LOCAL ONLY. Reads candidate main.py files and the frozen fixtures; writes
``data/experiments/pass7b_fixture_gate.json`` and ``.md``. Never mutates root
main.py / deck.csv or any candidate.

Usage:
    python scripts/run_pass7b_fixture_gate.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from test_candidate_on_fixtures import evaluate_candidate_on_fixtures

RUNS_ROOT = "experiments/runs_pass6"
FIXTURES_DIR = "data/replay_fixtures"
OUT_JSON = "data/experiments/pass7b_fixture_gate.json"
OUT_MD = "data/experiments/pass7b_fixture_gate.md"

# Branch-id suffix => human note about which decision seam the candidate targets
# and which frozen fixture(s) (if any) actually exercise that seam.
POLICY_CANDIDATES = [
    {
        "candidate_id": "policy_effect_resolution_v3",
        "targets": "effect-resolution search/discard choices",
        "covered_fixtures": ["step17_mega_signal_search", "step28_ultra_ball_discard"],
        "seam_covered": True,
    },
    {
        "candidate_id": "policy_secret_box_safety_v1",
        "targets": "Secret Box pre-play safety (avoid bricking setup)",
        "covered_fixtures": [],
        "seam_covered": False,
        "note": (
            "Target seam is a PRE-PLAY decision (whether to play Secret Box). "
            "The only secret-box fixture (step11) is a forced 3-of-3 discard "
            "(forced_all/na) and cannot represent that choice; result advisory."
        ),
    },
    {
        "candidate_id": "combo_effect_resolution_v3__deckout_guard_v2",
        "targets": "effect resolution + near-deckout search restraint",
        "covered_fixtures": ["step17_mega_signal_search", "step112_low_deck_search"],
        "seam_covered": True,
    },
    {
        "candidate_id": "combo_effect_resolution_v3__secret_box_safety",
        "targets": "effect resolution + Secret Box safety",
        "covered_fixtures": ["step17_mega_signal_search", "step28_ultra_ball_discard"],
        "seam_covered": True,
        "note": (
            "Secret-Box half of the seam is pre-play (not in the forced step11 "
            "fixture); effect-resolution half is covered by step17/step28."
        ),
    },
]

ANCHOR = {
    "candidate_id": "pass6_control_v2_anchor",
    "targets": "v2 active control (baseline reference, not scouted as a winner)",
    "covered_fixtures": [],
    "seam_covered": False,
    "is_anchor": True,
}


def _resolve_run_dir(candidate_id: str, runs_root: str) -> str | None:
    root = Path(runs_root)
    if not root.is_dir():
        return None
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.endswith(candidate_id):
            return str(child)
    return None


def _advisory_findings(report: dict) -> list[dict]:
    out: list[dict] = []
    for fx in report.get("fixtures", []):
        pref = fx.get("preference", {})
        if pref.get("result") == "fail":
            out.append(
                {
                    "fixture": fx.get("id"),
                    "kind": pref.get("kind"),
                    "detail": pref.get("detail"),
                }
            )
    return out


def run_gate(runs_root: str = RUNS_ROOT, fixtures_dir: str = FIXTURES_DIR) -> dict:
    candidates = POLICY_CANDIDATES + [ANCHOR]
    results: list[dict] = []
    missing: list[str] = []
    for spec in candidates:
        cid = spec["candidate_id"]
        run_dir = _resolve_run_dir(cid, runs_root)
        if run_dir is None:
            missing.append(cid)
            results.append(
                {
                    "candidate_id": cid,
                    "run_dir": None,
                    "status": "missing",
                    "legality_gate": False,
                    "targets": spec.get("targets"),
                }
            )
            continue
        report = evaluate_candidate_on_fixtures(run_dir, fixtures_dir)
        legality = bool(report.get("legality_gate"))
        advisory = _advisory_findings(report)
        results.append(
            {
                "candidate_id": cid,
                "run_dir": run_dir,
                "is_anchor": bool(spec.get("is_anchor", False)),
                "status": "pass" if legality else "fail",
                "legality_gate": legality,
                "targets": spec.get("targets"),
                "seam_covered": spec.get("seam_covered", False),
                "covered_fixtures": spec.get("covered_fixtures", []),
                "note": spec.get("note"),
                "preference_pass": report.get("preference_pass", 0),
                "preference_fail": report.get("preference_fail", 0),
                "preference_na": report.get("preference_na", 0),
                "advisory_findings": advisory,
                "n_fixtures": report.get("n_fixtures", 0),
                "load_error": report.get("load_error"),
            }
        )

    policy_results = [r for r in results if not r.get("is_anchor")]
    passed = [r["candidate_id"] for r in policy_results if r["status"] == "pass"]
    failed = [r["candidate_id"] for r in policy_results if r["status"] == "fail"]
    return {
        "stage": "pass7b_fixture_gate",
        "runs_root": runs_root,
        "fixtures_dir": fixtures_dir,
        "n_candidates": len(POLICY_CANDIDATES),
        "passed": passed,
        "failed": failed,
        "missing": missing,
        "results": results,
        "secret_box_step11_nuance": (
            "step11 discard is minCount==maxCount==n_options==3 (forced_all/na); "
            "all three options must be selected, a setup Snover cannot be spared. "
            "Not a policy failure; the secret-box safety seam is a pre-play "
            "decision the in-resolution fixtures cannot represent."
        ),
    }


def _format_md(summary: dict) -> str:
    lines: list[str] = []
    lines.append("# Pass 7B Fixture Gate")
    lines.append("")
    lines.append(
        f"Stage `{summary['stage']}` — graded {summary['n_candidates']} policy "
        f"candidates (+ v2 anchor) against the frozen decision fixtures in "
        f"`{summary['fixtures_dir']}`."
    )
    lines.append("")
    lines.append(f"- legality PASS: {', '.join(summary['passed']) or 'none'}")
    lines.append(f"- legality FAIL: {', '.join(summary['failed']) or 'none'}")
    if summary["missing"]:
        lines.append(f"- MISSING: {', '.join(summary['missing'])}")
    lines.append("")
    lines.append("## Per-candidate")
    lines.append("")
    for r in summary["results"]:
        tag = " (anchor)" if r.get("is_anchor") else ""
        lines.append(f"### {r['candidate_id']}{tag}")
        if r["status"] == "missing":
            lines.append("- status: **MISSING** (no run dir resolved)")
            lines.append("")
            continue
        lines.append(f"- status: **{r['status'].upper()}** (legality_gate)")
        lines.append(f"- targets: {r.get('targets')}")
        lines.append(
            f"- seam covered by fixtures: {'yes' if r.get('seam_covered') else 'NO (advisory)'}"
        )
        if r.get("covered_fixtures"):
            lines.append(f"- covering fixtures: {', '.join(r['covered_fixtures'])}")
        lines.append(
            f"- advisory preferences: {r['preference_pass']} pass / "
            f"{r['preference_fail']} fail / {r['preference_na']} na"
        )
        for f in r.get("advisory_findings", []):
            lines.append(
                f"  - advisory FAIL `{f['fixture']}` ({f['kind']}): {f['detail']}"
            )
        if r.get("note"):
            lines.append(f"- note: {r['note']}")
        lines.append("")
    lines.append("## Secret Box step-11 nuance")
    lines.append("")
    lines.append(summary["secret_box_step11_nuance"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs-root", default=RUNS_ROOT)
    parser.add_argument("--fixtures-dir", default=FIXTURES_DIR)
    parser.add_argument("--out-json", default=OUT_JSON)
    parser.add_argument("--out-md", default=OUT_MD)
    args = parser.parse_args()

    summary = run_gate(args.runs_root, args.fixtures_dir)
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.out_md).write_text(_format_md(summary), encoding="utf-8")
    print(json.dumps({
        "passed": summary["passed"],
        "failed": summary["failed"],
        "missing": summary["missing"],
        "out_json": args.out_json,
        "out_md": args.out_md,
    }, indent=2))
    return 0 if not summary["failed"] and not summary["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
