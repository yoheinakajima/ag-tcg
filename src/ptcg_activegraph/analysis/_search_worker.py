#!/usr/bin/env python3
"""PASS 46E — cg Search subprocess worker (NOT imported by search_oracle).

Invoked ONLY as a child process by ``search_oracle._run_worker``:

    python3 _search_worker.py <worklist.json> <out.jsonl>

It is the *only* place ``cg`` / ``libcg.so`` is imported, isolating native
hangs/crashes from the parent. For each task it:

* writes a ``{"kind":"start","id":...}`` marker BEFORE the risky native call (so a
  parent that loses the whole process to a native hang can still tell which task
  was in flight and mark the rest timed_out),
* runs ``search_begin`` + ``search_step(selected)`` under an in-process
  ``SIGALRM`` per-task budget,
* computes an objective post-state signature,
* always attempts ``search_release`` + ``search_end`` cleanup,
* writes a ``{"kind":"result",...}`` line and flushes.

Hidden-zone card IDs (opponent deck/hand/prize, your prize) are filled here with
valid basic-Pokémon IDs — a clearly-labeled assumption, never a claim of the real
hidden state. Reads opponent hand *count* only; never opponent hand contents.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[3]
_SDK = _REPO / "data" / "reference_agents" / "_sdk"
for _p in (str(_SDK), str(_REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Timeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise _Timeout()


def _zone_sig_for_player(player) -> dict:
    actives = getattr(player, "active", None) or []
    active_ids, active_hp, energy_total = [], [], 0
    for p in actives:
        if p is not None:
            active_ids.append(getattr(p, "id", None))
            active_hp.append(getattr(p, "hp", None))
            energy_total += len(getattr(p, "energies", None) or [])
    bench = getattr(player, "bench", None) or []
    for p in bench:
        if p is not None:
            energy_total += len(getattr(p, "energies", None) or [])
    discard = getattr(player, "discard", None) or []
    prize = getattr(player, "prize", None) or []
    return {
        "active_ids": active_ids, "active_hp": active_hp,
        "bench_count": len(bench), "hand_count": getattr(player, "handCount", None),
        "deck_count": getattr(player, "deckCount", None),
        "discard_count": len(discard), "prize_count": len(prize),
        "energy_total": energy_total,
    }


def _signature_from_state(state, your_index) -> dict | None:
    if state is None:
        return None
    players = getattr(state, "players", None)
    if not players or len(players) != 2:
        return None
    stadium = getattr(state, "stadium", None) or []
    yi = getattr(state, "yourIndex", your_index)
    return {
        "turn": getattr(state, "turn", None),
        "result": getattr(state, "result", None),
        "stadium_count": len(stadium), "your_index": yi,
        "players": [_zone_sig_for_player(players[0]), _zone_sig_for_player(players[1])],
    }


def _basic_pokemon_id(api) -> int:
    for c in api.all_card_data():
        try:
            if getattr(c, "basic", False) and int(getattr(c, "cardType", -1)) == 0:
                return int(c.cardId)
        except Exception:  # noqa: BLE001
            continue
    return 1


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    wl_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    out = open(out_path, "w", encoding="utf-8")

    def _emit(rec: dict) -> None:
        out.write(json.dumps(rec) + "\n")
        out.flush()
        os.fsync(out.fileno())

    try:
        spec = json.loads(wl_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _emit({"kind": "fatal", "error": f"bad_worklist:{type(exc).__name__}"})
        out.close()
        return 2

    per = float(spec.get("per_task_timeout_s", 8.0))
    tasks = spec.get("tasks", [])

    try:
        from cg import api  # noqa: WPS433  (native import isolated to this process)
    except Exception as exc:  # noqa: BLE001
        for t in tasks:
            _emit({"kind": "result", "id": t.get("id"), "ok": False,
                   "error": f"cg_import_failed:{type(exc).__name__}",
                   "timed_out": False})
        out.close()
        return 1

    signal.signal(signal.SIGALRM, _alarm)
    try:
        basic = _basic_pokemon_id(api)
    except Exception:  # noqa: BLE001
        basic = 1

    for t in tasks:
        tid = t.get("id")
        _emit({"kind": "start", "id": tid})
        rec = {"kind": "result", "id": tid, "ok": False, "legal": None,
               "error": None, "timed_out": False, "elapsed_s": None,
               "post_signature": None}
        sid = None
        t0 = time.time()
        try:
            obs = t["observation"]
            yi = int(t["your_index"])
            your_deck = [] if t.get("deck_needs_fill") is False else \
                [basic] * int(t.get("your_deck_count") or 0)
            your_prize = [basic] * int(t.get("your_prize_count") or 0)
            opp_deck = [basic] * int(t.get("opponent_deck_count") or 0)
            opp_prize = [basic] * int(t.get("opponent_prize_count") or 0)
            opp_hand = [basic] * int(t.get("opponent_hand_count") or 0)
            opp_active = [basic] if t.get("opponent_active_facedown") else []
            selected = [int(i) for i in t.get("selected", [])]

            signal.setitimer(signal.ITIMER_REAL, max(0.5, per))
            obs_cls = api.to_observation_class(obs)
            ss = api.search_begin(obs_cls, your_deck, your_prize, opp_deck,
                                  opp_prize, opp_hand, opp_active)
            sid = ss.searchId
            ss2 = api.search_step(sid, selected)
            signal.setitimer(signal.ITIMER_REAL, 0)
            post = ss2.observation.current if ss2 and ss2.observation else None
            rec["post_signature"] = _signature_from_state(post, yi)
            rec["legal"] = True
            rec["ok"] = rec["post_signature"] is not None
            rec["elapsed_s"] = round(time.time() - t0, 4)
        except _Timeout:
            signal.setitimer(signal.ITIMER_REAL, 0)
            rec["timed_out"] = True
            rec["error"] = "timeout"
            rec["elapsed_s"] = round(time.time() - t0, 4)
        except Exception as exc:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            name = type(exc).__name__
            msg = str(exc)[:120]
            rec["error"] = f"{name}:{msg}"
            # ValueError on illegal select indices => legal False
            if "minCount" in msg or "len(Observation.select.option)" in msg \
                    or "Duplicate" in msg:
                rec["legal"] = False
            rec["elapsed_s"] = round(time.time() - t0, 4)
        finally:
            try:
                if sid is not None:
                    api.search_release(sid)
                api.search_end()
            except Exception:  # noqa: BLE001
                pass
        _emit(rec)

    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
