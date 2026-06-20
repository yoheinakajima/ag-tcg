#!/usr/bin/env python3
"""Pass 35 — multi-game internal-tournament worker. LOCAL ONLY.

Imports the cabt engine ONCE, then plays a pre-extracted batch of games in order
until a wall-clock budget is hit, streaming one JSON line per game to a PERSISTENT
JSONL (flushed + fsync'd). Because completed games are durably on disk, the parent
harness may hard-kill this process at any time (native open_spiel C hangs cannot be
interrupted by the in-process SIGALRM watchdog) without losing finished games.

Each game emits a `start` marker BEFORE play and a `result` marker AFTER; a `start`
with no matching `result` marks a game that wedged the native engine, so the harness
can cap it after a few attempts instead of retrying forever.

Usage:
  _pass35_tourney_worker.py <spec.json> <out.jsonl> <budget_s> <game_timeout_s>
spec.json: [{"game_id","first_main","second_main","a_id","b_id","a_seat"}, ...]
This worker performs NO upload, NO submission, NO network deck copying.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def main() -> int:
    spec_path, out_path = sys.argv[1], sys.argv[2]
    budget_s, gt_s = float(sys.argv[3]), int(sys.argv[4])
    games = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    mev = _load("run_meta_pool_eval")
    mev.GAME_TIMEOUT_S = gt_s
    deadline = time.time() + budget_s
    fh = open(out_path, "a", encoding="utf-8")

    def emit(rec: dict) -> None:
        fh.write(json.dumps(rec, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    played = 0
    for g in games:
        if time.time() >= deadline:
            break
        emit({"ev": "start", "game_id": g["game_id"], "a_id": g["a_id"],
              "b_id": g["b_id"], "a_seat": g["a_seat"]})
        res = mev._run_game(g["first_main"], g["second_main"])
        a_out = mev._outcome_for_seat(res, g["a_seat"]) if res.get("ok") else None
        emit({"ev": "result", "game_id": g["game_id"], "a_id": g["a_id"],
              "b_id": g["b_id"], "a_seat": g["a_seat"], "a_outcome": a_out,
              "ok": bool(res.get("ok")), "timeout": bool(res.get("timeout")),
              "steps": res.get("steps"), "error": res.get("error")})
        played += 1
    fh.close()
    sys.stdout.write(json.dumps({"played": played}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
