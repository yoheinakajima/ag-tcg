#!/usr/bin/env python3
"""Pass 35 — decision-replay worker. LOCAL. Runs ALL of one typed child's replay
games in a SINGLE process (kaggle_environments is imported once, not per game)
and streams one JSON line per game to an output file, flushed+fsync'd after each
game so partial results survive even if the parent kills this process for a hang
(native open_spiel can wedge in C; the in-process SIGALRM below is best-effort and
the parent enforces the real wall-clock cap via subprocess timeout).

For each game it instruments the child's embedded strategy layer to record, per
gameplay decision, what the BASE policy chose vs what the TYPED layer chose (the
parent's decision == the child's own base before refinement, since child = parent
base + typed override) plus whether the typed choice is LEGAL.

Usage:
  _pass35_replay_worker.py <child_main.py> <jsonl_out> <opp_main|seat|timeout> ...
Each spec runs one game. Prints "DONE <n>" on stdout when finished.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys

BAD = {"INVALID", "ERROR", "TIMEOUT"}


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _load_child(child_main: str):
    d = os.path.dirname(os.path.abspath(child_main))
    os.chdir(d)
    spec = importlib.util.spec_from_file_location("p35_child", child_main)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _legal(refined, n_opts, mn, mx) -> bool:
    if not isinstance(refined, list):
        return False
    if any((not isinstance(i, int)) or isinstance(i, bool)
           or i < 0 or i >= n_opts for i in refined):
        return False
    if len(set(refined)) != len(refined):
        return False
    return mn <= len(refined) <= mx


def _run_one(make, mod, opp_main, seat, timeout_s, decisions):
    base_fn = mod._TP_ORIG_EMBEDDED
    refined_fn = mod._embedded_agent if mod._embedded_agent.__name__ != "recorder" \
        else mod._TP_TYPED_EMBEDDED
    get_select = mod._get_select
    get_options = mod._get_options
    get_min_max = mod._get_min_max_count

    def recorder(obs):
        refined = refined_fn(obs)
        try:
            base = base_fn(obs)
        except Exception:  # noqa: BLE001
            base = None
        try:
            sel = get_select(obs)
            if isinstance(sel, dict):
                opts = get_options(sel) or []
                mn, mx = get_min_max(sel, len(opts))
                changed = (isinstance(base, list) and isinstance(refined, list)
                           and base != refined)
                decisions.append({
                    "ctx": sel.get("context"), "n_options": len(opts),
                    "changed": bool(changed),
                    "legal": _legal(refined, len(opts), mn, mx),
                })
        except Exception:  # noqa: BLE001
            pass
        return refined

    mod._TP_TYPED_EMBEDDED = refined_fn
    recorder.__name__ = "recorder"
    mod._embedded_agent = recorder
    entry = mod.typed_pilot_agent

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    rec = {"opponent": os.path.basename(os.path.dirname(opp_main)),
           "seat": seat, "ok": False, "timeout": False}
    try:
        env = make("cabt")
        pair = [entry, opp_main] if seat == 0 else [opp_main, entry]
        env.run(pair)
        last = env.steps[-1]
        statuses = [s.get("status") for s in last]
        rec.update({"ok": True, "statuses": statuses,
                    "invalid": any(s in BAD for s in statuses)})
    except _Timeout:
        rec.update({"timeout": True, "error": "watchdog"})
    except Exception as exc:  # noqa: BLE001
        rec.update({"error": repr(exc)})
    finally:
        signal.alarm(0)
    return rec


def main() -> int:
    child_main, jsonl_out = sys.argv[1], sys.argv[2]
    specs = sys.argv[3:]
    mod = _load_child(child_main)
    if not all(hasattr(mod, a) for a in
               ("_TP_ORIG_EMBEDDED", "_embedded_agent", "_get_select",
                "_get_options", "_get_min_max_count", "typed_pilot_agent")):
        sys.stdout.write("ERR missing typed hooks\n")
        return 0

    from kaggle_environments import make  # noqa: E402

    n = 0
    with open(jsonl_out, "a", encoding="utf-8") as fh:
        for spec in specs:
            opp_main, seat_s, to_s = spec.split("|")
            decisions: list = []
            rec = _run_one(make, mod, opp_main, int(seat_s), int(to_s), decisions)
            rec["decisions"] = decisions
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            n += 1
    sys.stdout.write(f"DONE {n}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
