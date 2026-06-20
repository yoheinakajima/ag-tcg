#!/usr/bin/env python3
"""Pass 38 (Part J) — operator runbook completeness check.

OPS / read-only. Verifies docs/REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md exists and
covers every required operational topic (config, concurrency invariant, guardrails,
publish, monitor, troubleshoot, incident, recovery), plus that the exact deploy
run/build commands in the runbook match the live ``.replit`` deployment block (so
the runbook can never silently drift from reality).

Writes data/experiments/pass38_operator_runbook_check.{json,md}. NO upload, NO
submit, NO root mutation, NO candidate generation.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
RUNBOOK = REPO / "docs" / "REPLIT_SCHEDULED_DEPLOYMENT_RUNBOOK.md"

REQUIRED_SECTIONS = [
    "What this is",
    "Deployment configuration",
    "Concurrency invariant",
    "Safety guardrails",
    "How to publish",
    "How to monitor",
    "Routine operations",
    "Troubleshooting",
    "Incident reference",
    "Reset / recovery",
    'What "healthy" means',
]
REQUIRED_PHRASES = [
    "NOT a Kaggle leaderboard",
    "Scheduled Deployment",
    "package = false",
    "--user --break-system-packages",
    "kaggle-environments==1.30.1",
    "fails CLOSED",
    "check_tournament_health.py",
    "special_pilot_only",
    'Start application',
]


def main() -> int:
    exists = RUNBOOK.is_file()
    text = RUNBOOK.read_text(encoding="utf-8") if exists else ""

    sections = {s: (s in text) for s in REQUIRED_SECTIONS}
    phrases = {p: (p in text) for p in REQUIRED_PHRASES}

    # cross-check that the EXACT live .replit run/build commands appear verbatim in
    # the runbook (whitespace-normalized), so the docs cannot silently drift from the
    # deployed commands.
    dep = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8")).get("deployment", {})
    run_cmd = " ".join(str(x) for x in (dep.get("run") or []))
    build_cmd = " ".join(str(x) for x in (dep.get("build") or []))
    norm = " ".join(text.split())
    run_args_in_runbook = bool(run_cmd) and run_cmd in norm
    build_in_runbook = bool(build_cmd) and build_cmd in norm

    all_sections = all(sections.values())
    all_phrases = all(phrases.values())
    check_ok = (exists and all_sections and all_phrases
                and run_args_in_runbook and build_in_runbook)

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "J", "read_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "runbook_path": str(RUNBOOK.relative_to(REPO)),
        "runbook_exists": exists,
        "required_sections": sections,
        "required_phrases": phrases,
        "replit_run_command": run_cmd,
        "replit_build_command": build_cmd,
        "run_command_matches_replit": run_args_in_runbook,
        "build_command_matches_replit": build_in_runbook,
        "all_sections_present": all_sections,
        "all_phrases_present": all_phrases,
        "check_ok": check_ok,
    }
    (EXP / "pass38_operator_runbook_check.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Operator runbook check (Part J)", "",
        "> OPS / read-only. Confirms the Scheduled Deployment runbook exists, covers "
        "every required operational topic, and that its deploy commands match the "
        "live `.replit` block. Internal diagnostics; NOT a Kaggle leaderboard.", "",
        f"- runbook: `{payload['runbook_path']}` exists: **{yn(exists)}**",
        f"- all required sections present: **{yn(all_sections)}**",
        f"- all required phrases present: **{yn(all_phrases)}**",
        f"- run command matches `.replit`: **{yn(run_args_in_runbook)}**",
        f"- build command matches `.replit`: **{yn(build_in_runbook)}**", "",
        "## Required sections",
        "| section | present |", "|---|---|",
        *[f"| {s} | {yn(v)} |" for s, v in sections.items()], "",
        "## Required phrases",
        "| phrase | present |", "|---|---|",
        *[f"| `{p}` | {yn(v)} |" for p, v in phrases.items()], "",
        f"## Verdict: check_ok = **{yn(check_ok)}**",
    ]
    (EXP / "pass38_operator_runbook_check.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"runbook check: ok={check_ok} exists={exists} sections={all_sections} "
          f"phrases={all_phrases} run_match={run_args_in_runbook} "
          f"build_match={build_in_runbook}")
    return 0 if check_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
