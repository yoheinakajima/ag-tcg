#!/usr/bin/env python3
"""Batched cabt worker for the Pass-18 internal league (Part K).

Plays N cabt games between two candidate ``main.py`` agent files in a FRESH
process and writes the structured results (a JSON list) to a file. Batching the
games of one matchup-seat into a single process:

  * amortises the (~8s) kaggle_environments / OpenSpiel import over N games;
  * still bounds memory growth (a worker plays at most N games then exits, so the
    engine's per-process state accumulation never reaches the runaway regime that
    OOM-killed the single long-lived loop); and
  * lets the parent enforce a real timeout via ``subprocess`` (the SIGALRM
    watchdog does not reliably interrupt the engine's C code).

Usage: ``python _pass18_game_worker.py <main_first> <main_second> <count> <out_json>``
where seat 0 is ``main_first``. LOCAL ONLY — no upload.
"""

from __future__ import annotations

import json
import sys


def _play_one(make, agent_first: str, agent_second: str) -> dict:
    env = make("cabt")
    env.run([agent_first, agent_second])
    last = env.steps[-1]
    rewards = [s.get("reward") for s in last]
    statuses = [s.get("status") for s in env.state]
    legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
    return {"ok": legal, "steps": len(env.steps), "rewards": rewards,
            "statuses": statuses, "timeout": False, "invalid": not legal}


def main() -> int:
    agent_first, agent_second = sys.argv[1], sys.argv[2]
    count, out_path = int(sys.argv[3]), sys.argv[4]
    from kaggle_environments import make
    results = []
    for _ in range(count):
        try:
            results.append(_play_one(make, agent_first, agent_second))
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "timeout": False, "error": repr(exc)})
        # flush partial progress so a parent-side timeout still recovers games
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
