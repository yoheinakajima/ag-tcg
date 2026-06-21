#!/usr/bin/env python3
"""PASS 45 — Part G: optional controlled-tick DECISION (default SKIP).

Decides — transparently and conservatively — whether a tiny controlled production
tick is warranted to advance probation evidence. A manual tick is permitted ONLY if
the scheduled daemon (cron) is PROVEN stopped; if cron is live, a manual tick would
race the daemon and is forbidden by the Pass-45 charter.

Decision inputs come from Part B's soak audit (tick cadence + staleness) and Part D's
failure screen. The expected decision is SKIP: the daemon is demonstrably live and
healthy (recent ticks, ~0 hard-fail rate), so it is already accruing the evidence and
no manual intervention is warranted. This script performs NO tick; it only records
the decision.

Output:
  data/experiments/pass45_optional_controlled_tick_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
SOAK = EXP / "pass45_scheduled_daemon_soak_audit.json"
FAIL = EXP / "pass45_probation_failure_screen.json"

# a tick is only ever considered if no GameFinished has landed for this many minutes
CRON_STOPPED_STALENESS_MIN = 120.0


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    if not SOAK.is_file():
        raise SystemExit("missing pass45_scheduled_daemon_soak_audit.json (run Part B)")
    soak = json.loads(SOAK.read_text(encoding="utf-8"))
    fail = json.loads(FAIL.read_text(encoding="utf-8")) if FAIL.is_file() else {}

    staleness_s = soak.get("staleness_s")
    staleness = round(staleness_s / 60.0, 2) if staleness_s is not None else None
    soak_healthy = bool(soak.get("soak_healthy"))
    targets_accruing = bool(soak.get("targets_all_accruing")
                            or soak.get("targets_any_accruing"))
    any_runtime_failure = bool(fail.get("any_runtime_failure_detected"))

    cron_proven_stopped = (staleness is not None
                           and staleness >= CRON_STOPPED_STALENESS_MIN)
    cron_live = soak_healthy and staleness is not None \
        and staleness < CRON_STOPPED_STALENESS_MIN

    if cron_proven_stopped and not any_runtime_failure:
        decision = "tick_candidate_but_deferred"
        rationale = ("cron appears stopped, but per the Pass-45 charter a manual tick "
                     "is deferred unless explicitly approved; no tick performed.")
    elif cron_live:
        decision = "skip_daemon_live"
        rationale = (f"scheduled daemon is live and healthy (last tournament tick "
                     f"{staleness} min ago, < {CRON_STOPPED_STALENESS_MIN} min "
                     f"threshold); a manual tick would race the cron and is forbidden.")
    else:
        decision = "skip_insufficient_basis"
        rationale = "no clear basis to tick; default skip."

    controlled_tick_performed = False  # invariant: this pass NEVER ticks

    out = {
        "pass": "pass45_optional_controlled_tick_decision",
        "decision": decision,
        "controlled_tick_performed": controlled_tick_performed,
        "production_mutated": False,
        "cron_proven_stopped": cron_proven_stopped,
        "cron_live": cron_live,
        "staleness_minutes": staleness,
        "cron_stopped_staleness_threshold_min": CRON_STOPPED_STALENESS_MIN,
        "soak_healthy": soak_healthy,
        "targets_accruing": targets_accruing,
        "any_runtime_failure_detected": any_runtime_failure,
        "rationale": rationale,
    }
    (EXP / "pass45_optional_controlled_tick_decision.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    md = [
        "# PASS 45 — Part G: optional controlled-tick decision", "",
        f"- **decision: `{decision}`**",
        f"- controlled tick performed: **{'yes' if controlled_tick_performed else 'no'}**",
        f"- cron proven stopped: **{'yes' if cron_proven_stopped else 'no'}**  · "
        f"cron live: **{'yes' if cron_live else 'no'}**",
        f"- last tournament-tick staleness: **{staleness} min** "
        f"(stopped threshold {CRON_STOPPED_STALENESS_MIN} min)",
        f"- soak healthy: {soak_healthy}  · targets accruing: {targets_accruing}  · "
        f"runtime failure: {any_runtime_failure}", "",
        f"> {rationale}", "",
        "> The deployed Scheduled Deployment is the single writer of placement "
        "evidence. While it is live, Pass-45 does not perform any manual tick.",
    ]
    (EXP / "pass45_optional_controlled_tick_decision.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass45 partG: decision={decision} tick_performed={controlled_tick_performed} "
          f"cron_live={cron_live} staleness={staleness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
