"""Child entry-point: play ONE cabt game with OUR cg_typed candidate as subject.

Spawned by ``runner.run_one_game_subprocess`` (via ``child_script``) so the parent
can enforce a hard wall-clock budget and KILL a wedged native game. Unlike
``_cg_reference_game_subprocess.py`` (which seats a *reference* as the subprocess
'candidate' and chdirs into the reference dir), this child seats OUR Pass-41
cg_typed candidate as the 'cand' and chdirs into the OPPONENT'S dir.

Why chdir into the opponent dir: our cg_typed candidate is deliberately
cwd-independent — it resolves its own ``deck.csv`` via ``__file__`` and imports the
bundled ``cg`` SDK via a ``__file__``-relative ``sys.path`` fallback. A cg_typed
*reference* opponent, by contrast, reads a cwd-relative ``deck.csv`` and ``import
cg`` at module import. So we point cwd at the opponent (correct for the reference)
and put BOTH agent dirs on ``sys.path`` (so both ``import cg`` calls resolve; the
bundled SDKs are byte-identical). For non-cg opponents (our parent / anchor, no
``cg/``) the candidate's own dir on ``sys.path`` supplies ``cg`` and both decks are
force-injected by ``_InstrumentedAgent`` anyway.

Benchmark-only: never uploads, submits, promotes, or mutates anything. The
candidate is OUR owned agent; opponents (references) are benchmark-only and NEVER
treated as our candidate/parent/queue/promote.

Run as::

    python _pass41_cg_duel_subprocess.py <spec.json> <out.json>
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
        "pass41_cg_duel": True,
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
            "usage: _pass41_cg_duel_subprocess.py <spec.json> <out.json>\n")
        return 2
    spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    cand_dir = Path(spec["cand_main"]).resolve().parent
    ctrl_dir = Path(spec["control_main"]).resolve().parent
    # Run from the OPPONENT dir so a cg_typed reference reads its own cwd deck.csv +
    # imports its own cg/. Put BOTH agent dirs on sys.path so every ``import cg``
    # resolves (bundled SDKs are identical); our candidate stays cwd-independent.
    try:
        os.chdir(ctrl_dir)
    except Exception:  # noqa: BLE001
        pass
    for d in (str(ctrl_dir), str(cand_dir)):
        if d not in sys.path:
            sys.path.insert(0, d)

    result = _play(spec)
    out_path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
