#!/usr/bin/env python3
"""Pass 22 (Part D) — Water anti-disruption / energy-denial analyzer.

Read-only forensic analysis of our Water seat (agent ``Yohei Nakajima``) focused
on energy / resource denial and self-inflicted disruption: how often the active
was under-energized, how many turns we could not attack, and whether we discarded
or buried our own backup Basics / line pieces (which compounds the no-backup
collapse studied in Part C).

All signals are read from ground-truth ``observation.current`` state. Anything
not provable is reported as ``None`` / ``"unknown"``. NO upload. NO root changes.

Benchable Basic = Kyogre (721) / Snover (722). Mega Abomasnow ex (723) is a
non-benchable evolution payoff. Basic Water Energy id = 3.

Outputs (data/experiments/):
  pass22_energy_denial_analysis.json
  pass22_energy_denial_analysis.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

try:
    from ptcg_activegraph.playbooks.schema import CARD_NAMES  # noqa: E402
except Exception:  # pragma: no cover
    CARD_NAMES = {}

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
OUT_JSON = REPO / "data" / "experiments" / "pass22_energy_denial_analysis.json"
OUT_MD = REPO / "data" / "experiments" / "pass22_energy_denial_analysis.md"

OUR_AGENT = "Yohei Nakajima"
KYOGRE, SNOVER, MEGA_ABOMASNOW = 721, 722, 723
BENCHABLE_BASICS = {KYOGRE, SNOVER}
WATER_ENERGY = 3
LINE_PIECES = {KYOGRE, SNOVER, MEGA_ABOMASNOW}


def _name(cid):
    if cid is None:
        return None
    return CARD_NAMES.get(cid, f"card {cid}")


def _ids(zone):
    out = []
    if isinstance(zone, list):
        for c in zone:
            if isinstance(c, dict):
                cid = c.get("id")
                if isinstance(cid, int) and not isinstance(cid, bool):
                    out.append(cid)
    return out


def _own(obs):
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return None, None
    players = cur.get("players")
    idx = cur.get("yourIndex")
    if isinstance(players, list) and isinstance(idx, int) and 0 <= idx < len(players):
        p = players[idx]
        return (p if isinstance(p, dict) else None), cur.get("turn")
    return None, None


def _active_energy_count(player):
    act = player.get("active") if player else None
    if isinstance(act, list) and act and isinstance(act[0], dict):
        cards = act[0].get("energyCards")
        if isinstance(cards, list):
            return len(cards)
    return 0


def analyze_episode(ep, path):
    replay = load_replay(path)
    agents = [a.get("Name") for a in replay.info.get("Agents", []) if isinstance(a, dict)]
    our_seats = [i for i, a in enumerate(agents) if a == OUR_AGENT]
    if not our_seats:
        return None
    is_mirror = len(our_seats) == 2
    seat = our_seats[0]
    reward = replay.rewards[seat] if seat < len(replay.rewards) else None
    result = "self_mirror" if is_mirror else (
        "win" if (reward or 0) > 0 else "loss" if (reward or 0) < 0 else "draw")

    m = replay.board_metrics(seat)
    first_attack = m["first_attack_turn"]
    turns_observed = m["turns_observed"]

    # Per-turn energy on active (first snapshot per turn).
    energy_by_turn = {}
    seen = set()
    for rec in replay.agent_steps(seat):
        obs = rec.get("observation")
        if not isinstance(obs, dict):
            continue
        pl, turn = _own(obs)
        if pl is None or not isinstance(turn, int):
            continue
        if turn not in seen:
            energy_by_turn[turn] = _active_energy_count(pl)
            seen.add(turn)
    energy_by_turn = dict(sorted(energy_by_turn.items()))
    max_energy_on_active = max(energy_by_turn.values(), default=0)
    turns_zero_energy = sum(1 for v in energy_by_turn.values() if v == 0)

    # Final discard (self-inflicted resource loss).
    final_obs = replay.final_observation(seat)
    me, _ = _own(final_obs) if final_obs else (None, None)
    discard = _ids(me.get("discard")) if me else []
    discard_counts = Counter(discard)
    energy_in_discard = discard_counts.get(WATER_ENERGY, 0)
    benchable_basics_in_discard = {c: discard_counts.get(c, 0) for c in BENCHABLE_BASICS}
    line_pieces_in_discard = {c: discard_counts.get(c, 0) for c in LINE_PIECES}
    discarded_own_backup_basic = any(v > 0 for v in benchable_basics_in_discard.values())

    # Tempo: turns we never attacked.
    no_attack_whole_game = first_attack is None
    slow_attack = (first_attack is not None and first_attack >= 4)

    # Energy denial signal: chronic under-energization on a non-mirror loss.
    energy_starved = (result == "loss" and max_energy_on_active <= 1
                      and (turns_observed or 0) >= 3)

    tags = []
    if result == "loss" and not is_mirror:
        if no_attack_whole_game:
            tags.append("never_attacked")
        elif slow_attack:
            tags.append("slow_first_attack")
        if energy_starved:
            tags.append("energy_starved_active")
        if discarded_own_backup_basic:
            tags.append("self_discarded_backup_basic")

    return {
        "episode": ep,
        "agents": agents,
        "our_seat": seat,
        "is_self_mirror": is_mirror,
        "opponent": (agents[[i for i in range(len(agents)) if i != seat][0]]
                     if (not is_mirror and len(agents) > 1) else None),
        "result": result,
        "first_attack_turn": first_attack,
        "turns_observed": turns_observed,
        "never_attacked": no_attack_whole_game,
        "slow_first_attack": slow_attack,
        "energy_by_turn": {str(k): v for k, v in energy_by_turn.items()},
        "max_energy_on_active": max_energy_on_active,
        "turns_zero_energy_on_active": turns_zero_energy,
        "energy_starved_active": energy_starved,
        "energy_in_discard": energy_in_discard,
        "benchable_basics_in_discard": {str(k): v for k, v in benchable_basics_in_discard.items()},
        "line_pieces_in_discard": {str(k): v for k, v in line_pieces_in_discard.items()},
        "self_discarded_backup_basic": discarded_own_backup_basic,
        "min_deck_count": m["min_deck_count"],
        "tags": tags,
    }


def main():
    per_game = []
    for p in sorted(RAW_DIR.glob("*.json")):
        ep = p.stem.split("_")[0]
        try:
            res = analyze_episode(ep, p)
        except Exception as exc:
            res = {"episode": ep, "error": str(exc)}
        if res is not None:
            per_game.append(res)

    losses = [g for g in per_game if g.get("result") == "loss"]
    tag_counts = Counter()
    for g in per_game:
        for t in g.get("tags", []):
            tag_counts[t] += 1

    out = {
        "schema": "activegraph.pass22.energy_denial/v1",
        "pass": 22,
        "part": "D",
        "no_upload": True,
        "agent": OUR_AGENT,
        "water_energy_id": WATER_ENERGY,
        "benchable_basics": sorted(BENCHABLE_BASICS),
        "episodes_analyzed": [g["episode"] for g in per_game],
        "loss_count": len(losses),
        "tag_counts": dict(tag_counts.most_common()),
        "energy_starved_losses": [g["episode"] for g in losses if g.get("energy_starved_active")],
        "self_discard_backup_losses": [g["episode"] for g in losses if g.get("self_discarded_backup_basic")],
        "per_game": per_game,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    L = ["# Pass 22 — Water anti-disruption / energy-denial analysis (Part D)", ""]
    L.append("> Read-only. Basic Water Energy id=3. Benchable Basic = Kyogre (721) / "
             "Snover (722). Unprovable signals reported as `None`/`unknown`. No upload.")
    L.append("")
    L.append(f"- episodes analyzed: **{len(per_game)}**; losses: **{len(losses)}**")
    L.append(f"- energy-starved losses: **{len(out['energy_starved_losses'])}** "
             f"({', '.join(out['energy_starved_losses']) or 'none'})")
    L.append(f"- self-discarded-backup losses: **{len(out['self_discard_backup_losses'])}** "
             f"({', '.join(out['self_discard_backup_losses']) or 'none'})")
    L.append("")
    L.append("## Tag counts")
    if tag_counts:
        for t, n in tag_counts.most_common():
            L.append(f"- `{t}`: {n}")
    else:
        L.append("- none")
    L.append("")
    L.append("## Per-loss detail")
    for g in losses:
        L.append("")
        L.append(f"### {g['episode']} — LOSS vs {g.get('opponent') or '?'}")
        L.append(f"- first_attack_turn={g.get('first_attack_turn')}, "
                 f"turns_observed={g.get('turns_observed')}, never_attacked={g.get('never_attacked')}")
        L.append(f"- max_energy_on_active={g.get('max_energy_on_active')}, "
                 f"turns_zero_energy={g.get('turns_zero_energy_on_active')}, "
                 f"energy_starved={g.get('energy_starved_active')}")
        L.append(f"- energy_in_discard={g.get('energy_in_discard')}, "
                 f"self_discarded_backup_basic={g.get('self_discarded_backup_basic')} "
                 f"({g.get('benchable_basics_in_discard')})")
        L.append(f"- tags: {', '.join(g.get('tags', [])) or 'none'}")
    L.append("")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"energy-denial: {len(per_game)} episodes, {len(losses)} losses; "
          f"energy_starved={out['energy_starved_losses']}; "
          f"self_discard_backup={out['self_discard_backup_losses']}")
    print(f"tag_counts={dict(tag_counts.most_common())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
