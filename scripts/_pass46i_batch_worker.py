#!/usr/bin/env python3
"""PASS 46I (Part D) — import-once, hang-safe, resumable batch game worker.

Plays a batch of pre-specified cabt confirmation games IN ONE PROCESS (kaggle_environments
imported once, native cg engine warmed once) so ~100 warm games finish per invocation
instead of paying the ~8s cold import per game. Designed to be wrapped by an orchestrator
that enforces a HARD subprocess timeout: a native cg hang (which Python SIGALRM cannot
interrupt) is killed by the parent, and every game already finished survives because each
result row is flushed + fsync'd to the JSONL ledger immediately. On the next invocation the
worker resumes — it re-reads the ledger, skips games that already have a result, and skips
"poison" games (a `start` with no `result`, i.e. the game in flight when a prior worker was
killed).

Path setup replicates the proven Pass-41 cg duel child: chdir into the OPPONENT dir and put
BOTH participant dirs on sys.path so each cg candidate's ``import cg`` resolves and any
cwd-relative opponent read works; the cg candidates are otherwise cwd-independent (their deck
is forced via ``module._DECK_IDS`` by ``_InstrumentedAgent``).

LOCAL / READ-ONLY w.r.t. production: no Object Storage, no Kaggle, no events, no tarball
writes. Reads only the extracted working dirs the orchestrator prepared.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
logging.disable(logging.WARNING)

import kaggle_environments as ke  # noqa: E402  — imported ONCE per process
from ptcg_activegraph.experiments.runner import (  # noqa: E402
    _InstrumentedAgent, _final_rewards, _load_module, _make_cabt)
from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402

# In-process SOFT watchdog: aborts a pure-Python non-terminating game. A true native-C
# hang ignores Python signals until control returns to the interpreter — that case is the
# orchestrator's HARD subprocess-timeout responsibility.
SOFT_GAME_TIMEOUT = 45
_BAD_STATUS = ("TIMEOUT", "ERROR")


class _SoftTimeout(Exception):
    pass


def _on_alarm(signum, frame):  # noqa: ANN001
    raise _SoftTimeout()


def _emit(fh, rec: dict) -> None:
    fh.write(json.dumps(rec) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def _ledger_state(jsonl: Path) -> tuple[set, set]:
    done: set[str] = set()
    started: set[str] = set()
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("type") == "result":
                done.add(r.get("game_id"))
            elif r.get("type") == "start":
                started.add(r.get("game_id"))
    return done, started


def _play(game: dict) -> dict:
    # Resolve to ABSOLUTE before any chdir — the orchestrator passes dirs relative to
    # ROOT, and chdir(opp_dir) would otherwise re-root every later relative path.
    subj_dir = (ROOT / game["subject_dir"]).resolve()
    opp_dir = (ROOT / game["opponent_dir"]).resolve()
    for d in (str(opp_dir), str(subj_dir)):
        if d not in sys.path:
            sys.path.insert(0, d)
    cwd0 = os.getcwd()
    cand_name = ctrl_name = None
    armed = False
    prev = None
    try:
        try:
            os.chdir(opp_dir)
        except Exception:  # noqa: BLE001
            pass
        subj_deck = load_deck(subj_dir / "deck.csv")
        opp_deck = load_deck(opp_dir / "deck.csv")
        cm, cand_name = _load_module(subj_dir / "main.py")
        om, ctrl_name = _load_module(opp_dir / "main.py")
        sa = _InstrumentedAgent(cm, subj_deck)
        oa = _InstrumentedAgent(om, opp_deck)
        seat = int(game["subject_seat"])
        if seat == 0:
            agents = [sa, oa]
            decks = [list(subj_deck), list(opp_deck)]
        else:
            agents = [oa, sa]
            decks = [list(opp_deck), list(subj_deck)]
        env = _make_cabt(ke, decks)
        try:
            prev = signal.signal(signal.SIGALRM, _on_alarm)
            signal.alarm(SOFT_GAME_TIMEOUT)
            armed = True
        except (ValueError, AttributeError):
            armed = False
        try:
            env.run(agents)
        finally:
            if armed:
                signal.alarm(0)
                if prev is not None:
                    signal.signal(signal.SIGALRM, prev)
        r0, r1, s0, s1 = _final_rewards(env)
        steps = len(getattr(env, "steps", []) or [])
        s_r = r0 if seat == 0 else r1
        o_r = r1 if seat == 0 else r0
        s_status = s0 if seat == 0 else s1
        o_status = s1 if seat == 0 else s0
        invalid = bool(s_status in _BAD_STATUS or o_status in _BAD_STATUS
                       or s_r is None or o_r is None)
        subject_error = bool(s_status in _BAD_STATUS)
        if invalid:
            winner, decisive = None, False
        elif s_r > o_r:
            winner, decisive = "subject", True
        elif s_r < o_r:
            winner, decisive = "opponent", True
        else:
            winner, decisive = None, False  # honest draw
        return {"winner": winner, "decisive": decisive, "invalid": invalid,
                "subject_error": subject_error, "steps": steps,
                "subject_reward": s_r, "opponent_reward": o_r,
                "subject_status": s_status, "opponent_status": o_status,
                "subject_fallbacks": sa.stats.get("fallbacks"),
                "opponent_fallbacks": oa.stats.get("fallbacks")}
    except _SoftTimeout:
        return {"winner": None, "decisive": False, "invalid": True,
                "subject_error": False, "steps": 0, "error": "soft_timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"winner": None, "decisive": False, "invalid": True,
                "subject_error": False, "steps": 0,
                "error": f"{type(exc).__name__}:{exc}"}
    finally:
        if armed:
            try:
                signal.alarm(0)
            except Exception:  # noqa: BLE001
                pass
        for nm in (cand_name, ctrl_name):
            if nm:
                sys.modules.pop(nm, None)
        try:
            os.chdir(cwd0)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--budget-seconds", type=float, default=70.0)
    a = ap.parse_args()

    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    games = spec["games"]
    jsonl = Path(a.jsonl)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    done, started = _ledger_state(jsonl)
    poison = started - done

    t0 = time.time()
    played = 0
    with jsonl.open("a", encoding="utf-8") as fh:
        for g in games:
            gid = g["game_id"]
            if gid in done or gid in poison:
                continue
            if time.time() - t0 > a.budget_seconds:
                break
            _emit(fh, {"type": "start", "game_id": gid, "panel_id": g["panel_id"],
                       "ts": time.time()})
            gt = time.time()
            res = _play(g)
            rec = {"type": "result", "game_id": gid, "panel_id": g["panel_id"],
                   "subject_id": g["subject_id"], "opponent_id": g["opponent_id"],
                   "subject_seat": g["subject_seat"],
                   "wall_s": round(time.time() - gt, 3), "ts": time.time()}
            rec.update(res)
            _emit(fh, rec)
            played += 1

    print(json.dumps({"played_this_batch": played, "already_done": len(done),
                      "poison_skipped": len(poison)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
