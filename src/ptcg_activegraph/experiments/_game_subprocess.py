"""Child entry-point: play exactly ONE cabt game and write the result as JSON.

This module is spawned as a separate OS process by
``runner.run_one_game_subprocess`` so the parent can enforce a hard wall-clock
budget and *kill* a game that hangs inside cabt's C-level ``env.run`` (where an
in-process ``SIGALRM`` watchdog cannot interrupt). It reads a spec JSON file
(control/candidate main paths + forced deck id lists + candidate seat), plays one
game via :func:`runner.run_one_game`, and writes the result dict to an output
JSON file. cabt/OpenSpiel import chatter goes to the inherited stderr (which the
parent discards); only the output file carries the structured result.

Fast-import optimization (Pass 7B, opt-in): when ``PTCG_FAST_CABT_IMPORT_STUB=1``
is set in the environment, the litellm/heavy-env stub from
``sim.kaggle_import_optimization`` is enabled *before* cabt is imported, cutting
cold-start ~4.5x. It is reversible and self-healing: if the cabt import fails
under the stub, the child tears the stub down, purges any partial
``kaggle_environments`` modules, and retries with a normal import — recording the
fallback in the result. The stub never touches root ``main.py`` or site-packages.

Every result records ``fast_import_stub_enabled`` / ``import_optimization_mode``
/ ``import_optimization_validated`` / ``import_optimization_fallback`` so the
durable ledger and ranking can attribute outcomes to the import path used.

Run as::

    python _game_subprocess.py <spec.json> <out.json>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _import_meta_defaults() -> dict:
    return {
        "fast_import_stub_enabled": False,
        "import_optimization_mode": "normal",
        "import_optimization_validated": None,
        "import_optimization_fallback": False,
    }


def _maybe_enable_fast_stub(meta: dict):
    """Enable the cabt import stub iff requested. Returns the StubState or None.

    Stub insertion only mutates ``sys.modules`` for not-yet-imported heavy
    modules; it cannot itself break cabt. Any failure here is captured and the
    child proceeds with a normal import.
    """
    if os.environ.get("PTCG_FAST_CABT_IMPORT_STUB") != "1":
        return None
    try:
        from ptcg_activegraph.sim.kaggle_import_optimization import (
            enable_fast_cabt_import_stub,
        )

        # validate=False: skip the in-child smoke (the real game IS the check);
        # the benchmark validates the shape separately.
        state = enable_fast_cabt_import_stub(validate=False)
        meta["fast_import_stub_enabled"] = bool(state.enabled)
        meta["import_optimization_mode"] = "fast_stub" if state.enabled else "normal"
        return state
    except Exception as exc:  # noqa: BLE001 - never let opt-in stub crash the game
        meta["import_optimization_fallback"] = True
        meta["import_optimization_error"] = f"stub enable failed: {exc!r}"
        return None


def _import_failed(result: dict) -> bool:
    err = str(result.get("error") or "")
    return "kaggle_environments unavailable" in err


def _fall_back_to_normal_import(meta: dict, stub_state) -> None:
    """Undo the stub and purge any partial cabt import so a retry is clean."""
    try:
        from ptcg_activegraph.sim.kaggle_import_optimization import (
            disable_fast_cabt_import_stub,
        )

        if stub_state is not None:
            disable_fast_cabt_import_stub(stub_state)
    except Exception:  # noqa: BLE001
        pass
    for name in [
        m for m in list(sys.modules)
        if m == "kaggle_environments" or m.startswith("kaggle_environments.")
    ]:
        del sys.modules[name]
    meta["fast_import_stub_enabled"] = False
    meta["import_optimization_mode"] = "normal"
    meta["import_optimization_fallback"] = True


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
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    meta = _import_meta_defaults()
    stub_state = _maybe_enable_fast_stub(meta)

    from ptcg_activegraph.experiments.runner import run_one_game

    def _play() -> dict:
        return run_one_game(
            spec["control_main"],
            spec["control_deck"],
            spec["cand_main"],
            spec["cand_deck"],
            candidate_seat=int(spec.get("candidate_seat", 0)),
        )

    result = _play()
    # Self-heal: a cabt import failure under the stub falls back to a normal
    # import and retries exactly once.
    if meta["fast_import_stub_enabled"] and _import_failed(result):
        _fall_back_to_normal_import(meta, stub_state)
        result = _play()

    result.update(meta)
    out_path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
