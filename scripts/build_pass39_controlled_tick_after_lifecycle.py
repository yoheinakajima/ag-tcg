#!/usr/bin/env python3
"""Pass 39 — Part J (OPTIONAL): controlled tick after lifecycle.

A controlled tick is a deliberately-signed MANUAL run (``--max-games 3
--max-seconds 240``) — distinct from the scheduled signature (20/900) so it can
never be mistaken for a scheduled run. By DEFAULT this records a documented SKIP:

* The live tick path (``tournament_deployment_tick.py``) does NOT use
  ``lifecycle.py``; it only consumes ``CandidatePool.from_events``, which Pass 39
  already validates read-only in Part H (worklist rebuild) and Part I
  (fold determinism + synthetic CandidateStatusChanged + later-registration
  replace). A controlled tick would only exercise the unchanged cabt game engine
  while mutating prod state — low marginal value, real native-engine hang risk.
* The real Scheduled Deployment already exercises the full live tick path every
  20 minutes in production.

Pass ``--run`` to actually execute the controlled tick (lease -> pull -> 3 bounded
games -> rebuild -> push -> release) against prod. This NEVER uploads/submits and
NEVER touches the frozen root. NOT the scheduled signature.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CONTROLLED = ["--max-games", "3", "--max-seconds", "240"]
SCHEDULED_SIGNATURE = {"max_games": 20, "max_seconds": 900}
PRECONDITIONS = (
    "pass39_scheduled_tick_confirmation.json",
    "pass39_tournament_health.json",
    "pass39_lifecycle_plan.json",
    "pass39_lifecycle_apply.json",
    "pass39_scheduler_after_lifecycle.json",
    "pass39_event_projection_audit.json",
)


def _precheck() -> dict:
    out = {}
    for fn in PRECONDITIONS:
        p = EXP / fn
        ok = p.is_file()
        if ok:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                ok = d.get("ok", True) is not False
            except Exception:
                ok = False
        out[fn] = ok
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Controlled tick after lifecycle (optional).")
    ap.add_argument("--run", action="store_true",
                    help="actually execute the 3/240 controlled tick against prod.")
    ap.add_argument("--storage-backend", default="replit_app_storage")
    args = ap.parse_args()

    pre = _precheck()
    pre_ok = all(pre.values())
    payload = {
        "schema": "pass39_controlled_tick_after_lifecycle_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True,
        "auto_submit": False,
        "controlled_signature": {"max_games": 3, "max_seconds": 240},
        "scheduled_signature": SCHEDULED_SIGNATURE,
        "is_scheduled_signature": False,
        "preconditions": pre,
        "preconditions_ok": pre_ok,
    }

    if not args.run:
        payload["decision"] = "skipped"
        payload["prod_mutated"] = False
        payload["rationale"] = (
            "Controlled tick is OPTIONAL. The live tick path does not use the "
            "lifecycle module; it only consumes CandidatePool.from_events, already "
            "validated read-only in Parts H and I. A controlled tick would only "
            "exercise the unchanged cabt game engine while mutating prod state. The "
            "Scheduled Deployment already runs the full live path every 20 minutes.")
        payload["command_if_run"] = (
            "python scripts/tournament_deployment_tick.py "
            + " ".join(CONTROLLED)
            + " --storage-backend replit_app_storage --production")
    else:
        cmd = [sys.executable, str(REPO / "scripts" / "tournament_deployment_tick.py"),
               *CONTROLLED, "--storage-backend", args.storage_backend, "--production"]
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        payload["decision"] = "ran"
        payload["prod_mutated"] = proc.returncode == 0
        payload["returncode"] = proc.returncode
        payload["elapsed_s"] = round(time.time() - t0, 1)
        try:
            payload["tick_report"] = json.loads(proc.stdout.strip().splitlines()[-1]) \
                if proc.stdout.strip() else None
        except Exception:
            payload["tick_stdout_tail"] = proc.stdout[-2000:]
            payload["tick_stderr_tail"] = proc.stderr[-2000:]

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass39_controlled_tick_after_lifecycle.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md = [
        "# Pass 39 — Controlled tick after lifecycle (OPTIONAL)", "",
        "_Internal diagnostics only. NO upload, NO submit, NO auto-submit. "
        "Controlled signature (3/240) is NOT the scheduled signature (20/900)._", "",
        f"- decision: **{payload['decision']}**",
        f"- prod mutated: {payload['prod_mutated']}",
        f"- preconditions (B–I) ok: {pre_ok}",
        f"- controlled signature: {payload['controlled_signature']}  "
        f"(scheduled: {SCHEDULED_SIGNATURE})",
    ]
    if payload["decision"] == "skipped":
        md += ["", f"_Rationale:_ {payload['rationale']}", "",
               f"To run manually:\n\n```\n{payload['command_if_run']}\n```"]
    else:
        md += ["", f"- returncode: {payload.get('returncode')}  "
               f"elapsed: {payload.get('elapsed_s')}s"]
    (EXP / "pass39_controlled_tick_after_lifecycle.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"controlled-tick-after-lifecycle: decision={payload['decision']} "
          f"preconditions_ok={pre_ok} prod_mutated={payload['prod_mutated']}")
    return 0 if pre_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
