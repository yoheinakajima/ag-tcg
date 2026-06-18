"""Child entry-point: play exactly ONE cabt game and write the result as JSON.

This module is spawned as a separate OS process by
``runner.run_one_game_subprocess`` so the parent can enforce a hard wall-clock
budget and *kill* a game that hangs inside cabt's C-level ``env.run`` (where an
in-process ``SIGALRM`` watchdog cannot interrupt). It reads a spec JSON file
(control/candidate main paths + forced deck id lists + candidate seat), plays one
game via :func:`runner.run_one_game`, and writes the result dict to an output
JSON file. cabt/OpenSpiel import chatter goes to the inherited stderr (which the
parent discards); only the output file carries the structured result.

Run as::

    python _game_subprocess.py <spec.json> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _main() -> int:
    # Running this file directly puts its own dir (.../experiments) on sys.path
    # as entry 0. That dir contains modules whose names collide with the stdlib
    # (notably ``queue.py``), so a stray ``import queue`` from deep inside cabt /
    # threading would load OUR package file as a top-level module and explode
    # with "attempted relative import with no known parent package". Strip the
    # script dir from sys.path and add the package root (.../src) instead so
    # ``ptcg_activegraph`` resolves while the stdlib stays unshadowed.
    here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if p not in ("", ".", here)]
    src_root = Path(__file__).resolve().parents[2]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    if len(sys.argv) != 3:
        sys.stderr.write("usage: _game_subprocess.py <spec.json> <out.json>\n")
        return 2
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])

    from ptcg_activegraph.experiments.runner import run_one_game

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    result = run_one_game(
        spec["control_main"],
        spec["control_deck"],
        spec["cand_main"],
        spec["cand_deck"],
        candidate_seat=int(spec.get("candidate_seat", 0)),
    )
    out_path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
