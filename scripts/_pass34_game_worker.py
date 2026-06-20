#!/usr/bin/env python3
"""Pass 34 — single-game worker. LOCAL. Runs ONE cabt game in an isolated
process so the parent can enforce a HARD wall-clock timeout (the in-process
SIGALRM watchdog cannot interrupt a hang inside native open_spiel C code).

Usage: python3 _pass34_game_worker.py <agent_a_main.py> <agent_b_main.py> <timeout_s>
Prints a single JSON line with the game result to stdout.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    agent_a, agent_b, timeout_s = sys.argv[1], sys.argv[2], int(sys.argv[3])
    mev = _load("run_meta_pool_eval")
    mev.GAME_TIMEOUT_S = timeout_s
    result = mev._run_game(agent_a, agent_b)
    sys.stdout.write(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
