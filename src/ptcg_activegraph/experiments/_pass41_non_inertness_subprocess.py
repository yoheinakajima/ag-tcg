"""Child entry-point: ONE live cabt game that traces candidate-vs-parent decisions.

Seats OUR Pass-41 cg_typed candidate (subject) against its stdlib parent, and at
EVERY decision the candidate makes it also computes what the PARENT would have
chosen on the *identical* observation (a shadow call). For each decision it records:

  * the SelectContext, option count, min/max selection bounds
  * the candidate's chosen indices and the parent's shadow choice
  * ``changed``      — candidate disagrees with the parent (non-inertness signal)
  * ``cand_legal``   — candidate's indices are in-range and respect min/max
  * ``fallback_used``— the candidate's typed ``_decide`` deferred to its generic
                       legal fallback (detected by monkeypatching the module-global
                       ``_decide``, which ``agent()`` resolves at call time)
  * ``cand_exc`` / ``par_exc`` — an exception escaped that agent's top-level call

A candidate illegal action or an UNCAUGHT candidate exception is a hard failure
(surfaced as counts the parent runner gates on). The parent's robustness is not
under test — its exceptions are recorded for context only.

chdirs into the OPPONENT (parent) dir; the candidate is cwd-independent (deck via
``__file__``, cg via ``__file__`` fallback). Benchmark-only: no upload/submit/mutate.

Run as: ``python _pass41_non_inertness_subprocess.py <spec.json> <out.json>``
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

_MAX_EXAMPLES = 8


class _Holder:
    typed = None  # set by the patched _decide each call; None/empty => fallback


def _legal(out, n, mn, mx) -> bool:
    if not isinstance(out, (list, tuple)):
        return False
    seen = set()
    for idx in out:
        if not isinstance(idx, int) or isinstance(idx, bool):
            return False
        if not (0 <= idx < n) or idx in seen:
            return False
        seen.add(idx)
    return mn <= len(out) <= mx if mx >= 0 else False


class _TracerAgent:
    """Callable INSTANCE (deliberately not a bare function) for the candidate seat.

    kaggle_environments' ``Agent.act`` slices call args by the callable's
    ``__code__.co_argcount``; a plain ``def f(*args)`` reports co_argcount 0 and is
    therefore invoked with NO arguments (observation becomes None), which silently
    aborts the game after the deck-submission step. A callable *instance* has no
    ``__code__`` attribute, so both ``(observation, configuration)`` are forwarded
    — exactly how the proven ``_InstrumentedAgent`` is invoked.
    """

    def __init__(self, cand_mod, par_mod, par_deck, trace):
        self.cand_mod = cand_mod
        self.par_mod = par_mod
        self.trace = trace
        self._g = cand_mod._g
        self._as_int = cand_mod._as_int
        orig_decide = cand_mod._decide

        def _patched_decide(root, raw_obs):
            res = orig_decide(root, raw_obs)
            _Holder.typed = res
            return res

        cand_mod._decide = _patched_decide  # module-global; agent() resolves at call
        try:
            par_mod._DECK_IDS = list(par_deck)
        except Exception:
            pass

    def __call__(self, *args, **kwargs):
        obs = args[0] if args else kwargs.get("observation")
        cand_mod, par_mod, trace = self.cand_mod, self.par_mod, self.trace
        g, as_int = self._g, self._as_int
        _Holder.typed = None
        cand_exc = False
        try:
            out = cand_mod.agent(obs)
        except Exception:  # candidate must never raise -> hard-fail signal
            out = []
            cand_exc = True

        # Only count genuine decision points (skip deck-submission / empty selects).
        try:
            select = cand_mod._get_select(obs)
            options = cand_mod._get_options(select)
            n = len(options)
            mn, mx = cand_mod._min_max(select, n)
            ctx = as_int(g(select, "context")) if select is not None else None
        except Exception:
            n, mn, mx, ctx = 0, 0, 0, None
        if n == 0 or mx <= 0:
            return out  # not a tracked decision

        # Shadow: what would the parent pick on this exact observation?
        par_exc = False
        try:
            par_out = par_mod.agent(obs)
            if not isinstance(par_out, (list, tuple)):
                par_out = []
            par_out = [int(x) for x in par_out
                       if isinstance(x, int) and not isinstance(x, bool)]
        except Exception:
            par_out, par_exc = [], True

        cand_legal = (not cand_exc) and _legal(out, n, mn, mx)
        fallback_used = _Holder.typed is None or (
            isinstance(_Holder.typed, (list, tuple)) and len(_Holder.typed) == 0)
        changed = set(out) != set(par_out)
        ckey = str(ctx)

        trace["total_decisions"] += 1
        trace["context_total"][ckey] = trace["context_total"].get(ckey, 0) + 1
        if changed:
            trace["changed"] += 1
            trace["context_changed"][ckey] = trace["context_changed"].get(ckey, 0) + 1
        if not cand_legal:
            trace["illegal"] += 1
        if fallback_used:
            trace["fallback"] += 1
        if cand_exc:
            trace["cand_exceptions"] += 1
        if par_exc:
            trace["par_exceptions"] += 1
        if changed and len(trace["examples"]) < _MAX_EXAMPLES:
            trace["examples"].append({
                "ctx": ctx, "n": n, "minCount": mn, "maxCount": mx,
                "candidate": list(out), "parent": list(par_out),
                "fallback_used": fallback_used, "cand_legal": cand_legal,
            })
        return out


def _play(spec: dict) -> dict:
    from ptcg_activegraph.experiments.runner import (
        _InstrumentedAgent, _final_rewards, _load_module, _make_cabt,
    )

    seat = int(spec.get("candidate_seat", 0))
    cand_deck = list(spec["cand_deck"])
    par_deck = list(spec["control_deck"])  # opponent == parent
    trace = {"total_decisions": 0, "changed": 0, "illegal": 0, "fallback": 0,
             "cand_exceptions": 0, "par_exceptions": 0,
             "context_total": {}, "context_changed": {}, "examples": []}
    result = {"candidate_seat": seat, "completed": False, "candidate_won": None,
              "draw": False, "steps": 0, "error": None, "timeout": False,
              "subprocess": True, "pass41_non_inertness": True, "trace": trace}
    try:
        import kaggle_environments as ke
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"kaggle_environments unavailable: {exc!r}"
        return result
    try:
        cand_mod, cand_name = _load_module(spec["cand_main"])
        par_mod, par_name = _load_module(spec["control_main"])
        cand_agent = _TracerAgent(cand_mod, par_mod, par_deck, trace)
        try:
            cand_mod._DECK_IDS = list(cand_deck)
        except Exception:
            pass
        par_agent = _InstrumentedAgent(par_mod, par_deck)

        if seat == 0:
            agents, decks = [cand_agent, par_agent], [cand_deck, par_deck]
        else:
            agents, decks = [par_agent, cand_agent], [par_deck, cand_deck]

        env = _make_cabt(ke, decks)
        env.run(agents)
        r0, r1, s0, s1 = _final_rewards(env)
        result["steps"] = len(getattr(env, "steps", []) or [])
        result["status"] = [s0, s1]
        cand_reward = r0 if seat == 0 else r1
        opp_reward = r1 if seat == 0 else r0
        if any(s in ("TIMEOUT", "ERROR") for s in (s0, s1) if s):
            result["error"] = f"non-DONE status: {[s0, s1]}"
            result["timeout"] = any(s == "TIMEOUT" for s in (s0, s1) if s)
        else:
            result["completed"] = True
            if cand_reward is None or opp_reward is None:
                result["candidate_won"] = None
            elif cand_reward > opp_reward:
                result["candidate_won"] = True
            elif cand_reward < opp_reward:
                result["candidate_won"] = False
            else:
                result["candidate_won"], result["draw"] = None, True
        sys.modules.pop(cand_name, None)
        sys.modules.pop(par_name, None)
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        result["trace_error"] = traceback.format_exc()
    return result


def _main() -> int:
    here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if p not in ("", ".", here)]
    src_root = Path(__file__).resolve().parents[2]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    if len(sys.argv) != 3:
        sys.stderr.write("usage: _pass41_non_inertness_subprocess.py <spec> <out>\n")
        return 2
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    cand_dir = Path(spec["cand_main"]).resolve().parent
    ctrl_dir = Path(spec["control_main"]).resolve().parent
    try:
        os.chdir(ctrl_dir)
    except Exception:  # noqa: BLE001
        pass
    for d in (str(ctrl_dir), str(cand_dir)):
        if d not in sys.path:
            sys.path.insert(0, d)

    result = _play(spec)
    Path(sys.argv[2]).write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
