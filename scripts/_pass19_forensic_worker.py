#!/usr/bin/env python3
"""Batched cabt forensic worker for the Pass-19 Dragapult parent/child trace.

Plays ``count`` cabt games between two extracted agent ``main.py`` files in a
FRESH process (seat 0 = ``agent_first``) and writes a JSON list of per-game
telemetry to ``out_json``. Batching amortises the (~8s) engine import while
keeping memory isolation and a real, parent-enforced timeout (the SIGALRM
watchdog does not reliably interrupt the engine's C code).

Per game we record only what is ROBUSTLY derivable from cabt step logs:
winner/seat, step count, first attack step per seat, attack count per seat, and
first Abomasnow-line evolution step per seat. Deeper board metrics (deckout,
no-bench loss, spread targeting) are NOT decoded from the opaque encoded board
blob; they are intentionally omitted rather than guessed.

Usage: ``python _pass19_forensic_worker.py <main_first> <main_second> <count> <out_json>``
LOCAL ONLY -- no upload.
"""
from __future__ import annotations

import json
import sys

ATTACK_LOG_TYPE = 15  # log entries carrying an attackId are attacks (unambiguous)
EVOLUTION_CARD_IDS = {722, 723}  # confirmed Abomasnow-line evolutions (proxy only)


def _extract_metrics(env) -> dict:
    first_attack = {0: None, 1: None}
    attacks = {0: 0, 1: 0}
    first_evo = {0: None, 1: None}
    seen: set[str] = set()
    for idx, st in enumerate(env.steps):
        for seat in st:
            obs = seat.get("observation") if isinstance(seat, dict) else None
            logs = obs.get("logs") if isinstance(obs, dict) else None
            if not logs:
                continue
            for l in logs:
                key = json.dumps(l, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                if not isinstance(l, dict):
                    continue
                pi = l.get("playerIndex")
                if l.get("type") == ATTACK_LOG_TYPE and l.get("attackId") is not None:
                    if pi in attacks:
                        attacks[pi] += 1
                        if first_attack[pi] is None:
                            first_attack[pi] = idx
                if (l.get("type") == 6 and l.get("cardId") in EVOLUTION_CARD_IDS
                        and pi in first_evo and first_evo[pi] is None):
                    first_evo[pi] = idx
    return {
        "first_attack_step": {str(k): v for k, v in first_attack.items()},
        "attack_count": {str(k): v for k, v in attacks.items()},
        "first_evolution_step": {str(k): v for k, v in first_evo.items()},
    }


def _play_one(make, agent_first: str, agent_second: str) -> dict:
    env = make("cabt")
    env.run([agent_first, agent_second])
    last = env.steps[-1]
    rewards = [s.get("reward") for s in last]
    statuses = [s.get("status") for s in env.state]
    legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
    winner = None
    if rewards and rewards[0] is not None and rewards[1] is not None:
        if rewards[0] > rewards[1]:
            winner = 0
        elif rewards[1] > rewards[0]:
            winner = 1
    out = {"ok": legal, "steps": len(env.steps), "rewards": rewards,
           "statuses": statuses, "timeout": False, "invalid": not legal,
           "winner_seat": winner}
    out.update(_extract_metrics(env))
    return out


def main() -> int:
    agent_first, agent_second = sys.argv[1], sys.argv[2]
    count, out_path = int(sys.argv[3]), sys.argv[4]
    from kaggle_environments import make
    results = []
    for _ in range(count):
        try:
            results.append(_play_one(make, agent_first, agent_second))
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "timeout": False, "error": repr(exc)})
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
