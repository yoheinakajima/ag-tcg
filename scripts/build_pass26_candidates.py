#!/usr/bin/env python3
"""Pass 26 — Part I: candidate build / honest block.

Reads the Part-G trigger-coverage gate. Candidates are built ONLY if at least
one opportunity class is ``build_allowed``. On this corpus NO class clears the
gate, so this script writes a BLOCKED manifest and produces NO tarballs (the
honest `no_build_no_trigger` outcome). No Kaggle upload, no GitHub push, no
invented card ids.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
RUNS = REPO / "candidates_pass26"

# The two micro-candidates that WOULD have been designed if a hook had passed.
PROPOSED = [
    {
        "candidate_id": "water_action_opportunity_guard_v1",
        "intended_hook": "discard_preserve_line_failure",
        "intended_context": 8,
        "blocked_reason": (
            "discard_preserve_line_failure has only 1 high-confidence + 1 medium "
            "loss window (< the 2-high-confidence-loss-window bar); the medium "
            "window discarded a Mega with no Snover line in play (uncastable), so "
            "preserving it would not have helped."),
    },
    {
        "candidate_id": "water_action_opportunity_guard_v2",
        "intended_hook": "bench_backup_available_unplayed",
        "intended_context": 0,
        "blocked_reason": (
            "bench_backup_available_unplayed has 75 windows but lives in "
            "broad-Main (ctx0), which must stay delegated, and is already covered "
            "by the proven base hook `emergency_backup_bench`. Not narrow / not "
            "fixture-isolable as a NEW lever."),
    },
]


def main() -> int:
    gate = json.loads((EXP / "pass26_trigger_coverage.json").read_text(
        encoding="utf-8"))
    any_allowed = gate.get("any_build_allowed", False)
    RUNS.mkdir(exist_ok=True)

    manifest = {
        "schema": "activegraph.pass26.candidate_manifest/v1",
        "pass": 26,
        "decision": "no_build_no_trigger" if not any_allowed else "build",
        "any_trigger_coverage_passed": any_allowed,
        "candidates_built": [],
        "candidates_blocked": [c["candidate_id"] for c in PROPOSED],
        "tarballs": [],
        "no_tarballs_reason": (
            "No opportunity class cleared the Part-G trigger-coverage gate, so no "
            "runtime hook is justified by replay evidence. Building a candidate "
            "would mean shipping a guard that provably never fires (or fires only "
            "in broad-Main, which must stay delegated)."),
        "blocked_candidate_detail": PROPOSED,
        "no_invented_ids": True,
        "root_main_py_untouched": True,
        "root_deck_csv_untouched": True,
        "upload_performed": False,
        "github_push_performed": False,
        "no_upload": True,
        "source": "data/experiments/pass26_trigger_coverage.json",
    }
    if any_allowed:                       # defensive; not reached this corpus
        manifest["note"] = ("A class passed the gate -- candidate construction "
                            "would run here. Re-examine before shipping.")

    (RUNS / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    md = [
        "# Pass 26 — Candidate Manifest (BLOCKED: no_build_no_trigger)",
        "",
        f"- decision: **{manifest['decision']}**",
        f"- any trigger-coverage passed: {any_allowed}",
        "- candidates built: **none**",
        "- tarballs: **none**",
        f"- {manifest['no_tarballs_reason']}",
        "",
        "## Blocked candidates (would-have-been)",
        "",
        "| candidate | intended hook | ctx | why blocked |",
        "| --- | --- | --- | --- |",
    ]
    for c in PROPOSED:
        md.append(f"| `{c['candidate_id']}` | `{c['intended_hook']}` | "
                  f"{c['intended_context']} | {c['blocked_reason']} |")
    md += ["", "No invented card ids. Root `main.py` / `deck.csv` untouched. "
           "No upload, no GitHub push (`no_upload=true`)."]
    (RUNS / "manifest.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    tarballs = list(RUNS.glob("*.tar.gz"))
    assert not tarballs, f"unexpected tarballs present: {tarballs}"
    print(f"manifest -> {RUNS.relative_to(REPO)}/manifest.{{json,md}} "
          f"(decision={manifest['decision']}, tarballs=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
