#!/usr/bin/env python3
"""PASS 46C — single cabt game trace worker (subprocess-isolated). LOCAL ONLY.

Runs ONE cabt game from two pre-extracted agent ``main.py`` paths and writes the FULL
``env.steps`` decision-frame trace to an output JSON (flushed + fsync'd). Subprocess
isolation lets the parent hard-kill a natively-wedged game (open_spiel C hangs cannot
be interrupted by the in-process SIGALRM watchdog) without corrupting parent state.

NO upload, NO submission, NO production Object Storage, NO event emission, NO network
deck copying. Reads two local agent directories; writes exactly one local JSON file.

Usage: _pass46c_trace_worker.py <a_main> <b_main> <out_json> <game_timeout_s>
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time


class _Timeout(Exception):
    pass


def _alarm(_s, _f):  # pragma: no cover - signal handler
    raise _Timeout()


def main() -> int:
    a_main, b_main, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    gt = int(sys.argv[4])
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(gt)
    t0 = time.time()
    rec: dict = {"ok": False, "timeout": False, "error": None, "steps": None}
    try:
        from kaggle_environments import make
        env = make("cabt")
        env.run([a_main, b_main])
        steps = env.steps
        last = steps[-1]
        rec = {
            "ok": True, "timeout": False, "error": None,
            "n_steps": len(steps),
            "rewards": [s.get("reward") for s in last],
            "statuses": [s.get("status") for s in last],
            "steps": steps,
        }
    except _Timeout:
        rec = {"ok": False, "timeout": True, "error": "watchdog", "steps": None}
    except Exception as exc:  # noqa: BLE001
        rec = {"ok": False, "timeout": False, "error": repr(exc), "steps": None}
    finally:
        signal.alarm(0)
    rec["elapsed_s"] = round(time.time() - t0, 3)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    sys.stdout.write(json.dumps({"ok": rec["ok"], "n_steps": rec.get("n_steps")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
