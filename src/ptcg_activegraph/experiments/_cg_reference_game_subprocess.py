"""Child entry-point: play ONE cabt game involving a cg_typed reference agent.

Spawned by ``runner.run_one_game_subprocess`` (via its ``child_script`` hook) so the
parent can enforce a hard wall-clock budget and KILL a game that hangs inside cabt's
or cg's native C. Reads the standard spec JSON
(``control_main``/``control_deck``/``cand_main``/``cand_deck``/``candidate_seat``).

cg_typed reference agents ``import cg`` and read a *cwd-relative* ``deck.csv`` at
module import. This child therefore ``chdir``s into the candidate (reference) agent's
own run directory — where ``cg/`` ships alongside ``main.py`` + ``deck.csv`` (the
Part F immutable tarball layout) — and puts that directory on ``sys.path`` so both
``import cg`` and the deck read resolve. It deliberately does NOT use the in-process
SIGALRM watchdog (which is too tight for a cold cabt + native-cg game); the parent's
process-group SIGTERM→SIGKILL is the sole hard bound.

Benchmark-only: this never uploads, submits, promotes, or mutates anything.

Run as::

    python _cg_reference_game_subprocess.py <spec.json> <out.json>
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def _play(spec: dict) -> dict:
    from ptcg_activegraph.experiments.runner import (
        _InstrumentedAgent, _final_rewards, _load_module, _make_cabt,
    )

    result = {
        "candidate_seat": int(spec.get("candidate_seat", 0)),
        "completed": False, "candidate_won": None, "draw": False, "steps": 0,
        "error": None, "timeout": False, "cg_typed_game": True, "subprocess": True,
    }
    try:
        import kaggle_environments as ke
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"kaggle_environments unavailable: {exc!r}"
        return result

    seat = int(spec.get("candidate_seat", 0))
    cand_deck = list(spec["cand_deck"])
    ctrl_deck = list(spec["control_deck"])
    try:
        cand_mod, cand_name = _load_module(spec["cand_main"])
        ctrl_mod, ctrl_name = _load_module(spec["control_main"])
        cand_agent = _InstrumentedAgent(cand_mod, cand_deck)
        ctrl_agent = _InstrumentedAgent(ctrl_mod, ctrl_deck)

        if seat == 0:
            agents = [cand_agent, ctrl_agent]
            decks = [cand_deck, ctrl_deck]
        else:
            agents = [ctrl_agent, cand_agent]
            decks = [ctrl_deck, cand_deck]

        env = _make_cabt(ke, decks)
        env.run(agents)

        r0, r1, s0, s1 = _final_rewards(env)
        result["steps"] = len(getattr(env, "steps", []) or [])
        result["status"] = [s0, s1]
        cand_reward = r0 if seat == 0 else r1
        opp_reward = r1 if seat == 0 else r0
        statuses = [s0, s1]
        if any(s in ("TIMEOUT", "ERROR") for s in statuses if s):
            result["timeout"] = any(s == "TIMEOUT" for s in statuses if s)
            result["error"] = f"non-DONE status: {statuses}"
        else:
            result["completed"] = True
            if cand_reward is None or opp_reward is None:
                result["candidate_won"] = None
            elif cand_reward > opp_reward:
                result["candidate_won"] = True
            elif cand_reward < opp_reward:
                result["candidate_won"] = False
            else:
                result["candidate_won"] = None
                result["draw"] = True
        for k, v in cand_agent.stats.items():
            result[k] = v
        sys.modules.pop(cand_name, None)
        sys.modules.pop(ctrl_name, None)
    except Exception as exc:  # noqa: BLE001 - one bad game must not crash silently
        result["error"] = repr(exc)
        result["trace"] = traceback.format_exc()
    return result


def _main() -> int:
    # Strip the script's own dir (collides with stdlib names like queue.py) and add
    # the package root so ``ptcg_activegraph`` resolves while stdlib stays unshadowed.
    here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if p not in ("", ".", here)]
    src_root = Path(__file__).resolve().parents[2]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    if len(sys.argv) != 3:
        sys.stderr.write(
            "usage: _cg_reference_game_subprocess.py <spec.json> <out.json>\n")
        return 2
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    # Run from the reference agent's own dir: cg/ alongside main.py + deck.csv.
    cand_dir = Path(spec["cand_main"]).resolve().parent
    try:
        os.chdir(cand_dir)
    except Exception:  # noqa: BLE001
        pass
    if str(cand_dir) not in sys.path:
        sys.path.insert(0, str(cand_dir))

    result = _play(spec)
    out_path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
