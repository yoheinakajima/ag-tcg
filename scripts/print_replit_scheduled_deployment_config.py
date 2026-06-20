#!/usr/bin/env python3
"""Pass 37 (Phase F) — Replit Scheduled Deployment config generator.

Prints (and writes) the *exact* guidance for running the standing tournament
engine as a Replit **Scheduled Deployment** backed by **persistent storage**.

This is documentation/configuration ONLY. It performs no Kaggle upload, no
submit, no auto-submit, and no candidate generation. Internal diagnostics only —
the tournament's internal scores are NOT the Kaggle leaderboard. The bounded tick
must be deployed as a *Scheduled Deployment* (a cron-like bounded job), never as
an always-on web server, and never via the root "Start application" workflow.

Outputs:
- stdout: human-readable guidance
- data/experiments/pass37_scheduled_deployment_config.json
- data/experiments/pass37_scheduled_deployment_config.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

# --- exact, bounded production run command (mirrors T-E worker contract) ---
RUN_COMMAND = (
    "python scripts/tournament_deployment_tick.py "
    "--max-games 20 --max-seconds 900 "
    "--storage-backend replit_app_storage --production"
)

# Build command. Replit's nix Python is an externally-managed environment, so a
# plain `pip install` is blocked — `--user --break-system-packages` is the
# verified-working incantation (it installs into the writable .pythonlibs /
# PYTHONUSERBASE, which the runtime python keeps on sys.path; confirmed in this
# workspace and required because uv targets the read-only Nix store). The worker
# puts src/ on sys.path itself, so an editable `-e .` install is NOT required —
# and pyproject sets [tool.uv] package=false so the automatic `uv sync` does not
# try (and fail) to editable-install the root package into the read-only store.
# Deps: the Replit Object Storage SDK (`replit-object-storage`) + PyYAML (config
# loader) + kaggle-environments (its bundled "cabt" env IS the game engine the
# per-game subprocess drives via make("cabt"); the standalone `cabt` module is
# not needed). --no-games / dry-run never touch the game engine.
BUILD_COMMAND = (
    "python -m pip install --user --break-system-packages "
    "replit-object-storage pyyaml kaggle-environments==1.30.1"
)

# The 10 exact Publishing setup steps (also mirrored in
# docs/PERSISTENT_TOURNAMENT_DAEMON.md).
SETUP_STEPS = [
    "Open the Publishing (Deployments) tool in this Repl.",
    "Choose deployment type = Scheduled Deployment "
    "(NOT Autoscale, NOT Reserved VM / Always-on, NOT Static).",
    "Set the schedule to run every 2 hours (cron `0 */2 * * *`); leave the "
    "timezone at the UTC default.",
    "Set the job timeout to ~25 minutes — keep it BELOW the 30-min lease TTL so "
    "the lease always outlives a tick (the run command caps work at "
    "--max-seconds 900 = 15 min, comfortably below the timeout).",
    "Set the build command: "
    f"`{BUILD_COMMAND}`.",
    "Set the run command (one bounded tick, fails closed without persistent "
    f"storage): `{RUN_COMMAND}`.",
    "Secrets: none are required for tournament-only operation. Do NOT add "
    "Kaggle credentials — there is no upload/submit. (Only future read-only "
    "score refresh would ever need KAGGLE_USERNAME/KAGGLE_KEY, read-only.)",
    "Click 'Run Now' once to execute a single tick immediately and validate the "
    "end-to-end pull/lease/tick/reconcile/push flow.",
    "Inspect the Scheduled Deployment logs, then the synced projections "
    "(data/tournament/projections/rankings.md) to confirm progress; verify the "
    "logs show no_upload=true and no auto-submit.",
    "If the run failed, fix the cause and republish; never enable auto-submit, "
    "never upload, never convert this into an always-on server.",
]

CONFIG = {
    "pass": "37",
    "phase": "F",
    "purpose": (
        "Run the Pass 36 standing tournament engine as a Replit Scheduled "
        "Deployment backed by persistent storage. Internal diagnostics only."
    ),
    "internal_only": True,
    "not_kaggle_leaderboard": True,
    "no_upload": True,
    "no_auto_submit": True,
    "no_candidate_generation": True,
    "deployment_type": "scheduled",
    "deployment_type_label": "Scheduled Deployment",
    "not_deployment_types": ["autoscale", "reserved_vm", "always_on", "static"],
    "do_not_use_start_application_workflow_as_server": True,
    "schedule": {
        "every": "2 hours",
        "cron": "0 */2 * * *",
        "timezone": "UTC (default)",
        "rationale": (
            "Interval (2h) > lease TTL > job timeout so a lease cannot outlive "
            "its owning tick and ticks never overlap."
        ),
    },
    "job_timeout_minutes": {"min": 20, "max": 28, "recommended": 25},
    "build_command": BUILD_COMMAND,
    "run_command": RUN_COMMAND,
    "run_command_notes": (
        "Bounded tick: --max-games 20 caps scheduling, --max-seconds 900 caps "
        "wall-clock (well under the ~25 min job timeout, which stays below the "
        "30 min lease TTL), "
        "--storage-backend replit_app_storage uses persistent Object Storage, "
        "--production makes the worker fail CLOSED if storage is unavailable."
    ),
    "secrets": {
        "required_for_tournament_only": [],
        "kaggle_required": False,
        "kaggle_note": (
            "Kaggle credentials are NOT required and must not be added for "
            "tournament-only runs (no upload, no submit). Only a hypothetical "
            "future read-only score refresh would read KAGGLE_USERNAME / "
            "KAGGLE_KEY, and only read-only."
        ),
    },
    "persistent_storage": {
        "backend": "replit_app_storage (Replit App / Object Storage)",
        "why": (
            "The deployed filesystem is NOT durable across scheduled runs. "
            "Production state (events.jsonl, projections, runs, games, pool, "
            "manifest) MUST live in persistent storage; data/tournament/ is only "
            "a disposable per-run working directory."
        ),
        "provisioning": (
            "Provision an Object Storage bucket via the App Storage blueprint "
            "(cost-bearing — confirm with the user before provisioning). Until a "
            "bucket exists, --production fails closed by design."
        ),
        "fail_closed": True,
    },
    "monitoring": [
        "Scheduled Deployment logs (per-run stdout/stderr; confirm no_upload "
        "and no auto-submit, and a clean lease acquire/release).",
        "data/tournament/projections/rankings.md after each sync (pulled from "
        "persistent storage; rebuilt from the event log).",
        "data/tournament/projections/scheduler_queue.md for remaining work.",
        "data/experiments/pass37_deployment_tick_smoke.{json,md} written by the "
        "worker each run.",
    ],
    "safety_contract": {
        "no_upload": True,
        "no_submit": True,
        "no_auto_submit": True,
        "auto_submit_refused": True,
        "no_candidate_generation": True,
        "root_main_py_unchanged": True,
        "root_deck_csv_unchanged": True,
        "internal_scores_not_kaggle": True,
        "deploy_only_as_scheduled_bounded_tick": True,
        "production_state_must_use_persistent_storage": True,
    },
    "setup_steps": SETUP_STEPS,
}


def render_md(cfg: dict) -> str:
    sched = cfg["schedule"]
    timeout = cfg["job_timeout_minutes"]
    lines = [
        "# Pass 37 — Replit Scheduled Deployment config (Phase F)",
        "",
        "> Internal diagnostics only. **NOT a Kaggle leaderboard.** "
        "**NO upload, NO submit, NO auto-submit, no candidate generation.** "
        "Deploy ONLY as a Replit *Scheduled Deployment* bounded tick — never an "
        "always-on server, never the root \"Start application\" workflow.",
        "",
        "## Deployment type",
        f"- Use **{cfg['deployment_type_label']}** (cron-like bounded job).",
        "- Do NOT use Autoscale, Reserved VM / Always-on, or Static.",
        "",
        "## Schedule",
        f"- Every **{sched['every']}** (cron `{sched['cron']}`).",
        f"- Timezone: **{sched['timezone']}**.",
        f"- {sched['rationale']}",
        "",
        "## Job timeout",
        f"- **{timeout['min']}-{timeout['max']} minutes** "
        f"(recommended {timeout['recommended']}).",
        "- Keep the job timeout **below the 30-min lease TTL** so a lease always "
        "outlives its owning tick (invariant: interval > TTL > job timeout).",
        "- The run command caps work at `--max-seconds 900` (15 min), "
        "comfortably below the timeout.",
        "",
        "## Build command",
        "```bash",
        cfg["build_command"],
        "```",
        "",
        "## Run command (one bounded tick)",
        "```bash",
        cfg["run_command"],
        "```",
        f"- {cfg['run_command_notes']}",
        "",
        "## Secrets",
        "- **None required** for tournament-only operation.",
        "- **Kaggle credentials are NOT required** and must not be added "
        "(no upload, no submit).",
        f"- {cfg['secrets']['kaggle_note']}",
        "",
        "## Persistent storage (required for production)",
        f"- Backend: **{cfg['persistent_storage']['backend']}**.",
        f"- {cfg['persistent_storage']['why']}",
        f"- {cfg['persistent_storage']['provisioning']}",
        "- **Do not rely on the deployment filesystem; production state must use "
        "persistent storage.** The `--production` worker fails CLOSED when "
        "storage is unavailable.",
        "",
        "## Monitoring",
        *[f"- {m}" for m in cfg["monitoring"]],
        "",
        "## Exact setup steps (Publishing UI)",
        *[f"{i}. {s}" for i, s in enumerate(cfg["setup_steps"], start=1)],
        "",
        "## Safety contract",
        "- no upload · no submit · no auto-submit (refused) · no candidate "
        "generation.",
        "- root `main.py`/`deck.csv` unchanged; internal scores are NOT the "
        "Kaggle leaderboard.",
        "- deploy only as a Scheduled Deployment bounded tick; production state "
        "must use persistent storage.",
        "",
    ]
    return "\n".join(lines)


def render_stdout(cfg: dict) -> str:
    sched = cfg["schedule"]
    timeout = cfg["job_timeout_minutes"]
    out = [
        "=== Replit Scheduled Deployment config — Pass 37 (Phase F) ===",
        "Internal diagnostics only. NOT a Kaggle leaderboard.",
        "NO upload · NO submit · NO auto-submit · no candidate generation.",
        "",
        f"Deployment type : {cfg['deployment_type_label']} "
        "(NOT Autoscale / Reserved VM / Static)",
        f"Schedule        : every {sched['every']} (cron {sched['cron']}), "
        f"tz {sched['timezone']}",
        f"Job timeout     : {timeout['min']}-{timeout['max']} min "
        f"(recommended {timeout['recommended']})",
        "",
        "Build command:",
        f"  {cfg['build_command']}",
        "",
        "Run command (one bounded tick):",
        f"  {cfg['run_command']}",
        "",
        "Secrets: none for tournament-only. Kaggle NOT required (no upload/submit).",
        "",
        "Persistent storage: " + cfg["persistent_storage"]["backend"],
        "  Do NOT rely on the deployment filesystem; production state must use "
        "persistent storage. --production fails CLOSED without it.",
        "",
        "Setup steps:",
        *[f"  {i}. {s}" for i, s in enumerate(cfg["setup_steps"], start=1)],
        "",
        "Monitoring:",
        *[f"  - {m}" for m in cfg["monitoring"]],
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Print/write the Replit Scheduled Deployment config for the "
        "standing tournament engine (internal-only; no upload/submit).",
    )
    ap.add_argument(
        "--no-write", action="store_true",
        help="Only print to stdout; do not write data/experiments artifacts.",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Print the config as JSON to stdout instead of the text summary.",
    )
    args = ap.parse_args()

    if args.json:
        print(json.dumps(CONFIG, indent=2))
    else:
        print(render_stdout(CONFIG))

    if not args.no_write:
        EXP.mkdir(parents=True, exist_ok=True)
        (EXP / "pass37_scheduled_deployment_config.json").write_text(
            json.dumps(CONFIG, indent=2) + "\n", encoding="utf-8")
        (EXP / "pass37_scheduled_deployment_config.md").write_text(
            render_md(CONFIG), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
