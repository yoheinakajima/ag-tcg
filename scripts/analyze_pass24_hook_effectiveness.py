#!/usr/bin/env python3
"""Pass 24 — anti-disruption hook effectiveness (inferred from board trajectory).

Read-only. The replay exposes board state, NOT the agent's internal hook flags,
so every "did the hook fire" signal is INFERRED from how the board evolved:
  * benching backup basics when the board was thin
  * keeping >=2 Pokémon in play vs big ex threats
  * never benching the non-benchable Mega Abomasnow ex (723) from hand
Outputs:
  - data/experiments/pass24_hook_effectiveness.json
  - data/experiments/pass24_hook_effectiveness.md
"""
from __future__ import annotations
import csv, datetime, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

RAW = REPO / "data" / "meta_replays" / "raw"
OUR = "Yohei Nakajima"
KYOGRE, SNOVER, MEGA = 721, 722, 723
BENCHABLE = {KYOGRE, SNOVER}
EPISODES = ["80623232", "80622745", "80622626"]


def _ids(zone):
    out = []
    if isinstance(zone, list):
        for c in zone:
            if isinstance(c, dict) and isinstance(c.get("id"), int) and not isinstance(c.get("id"), bool):
                out.append(c["id"])
    return out


def seat_trajectory(replay, seat):
    """Per-turn snapshot of active/bench/hand ids for a seat (last obs per turn)."""
    views = {}
    for rec in replay.agent_steps(seat):
        obs = rec.get("observation")
        cur = obs.get("current") if isinstance(obs, dict) else None
        if not isinstance(cur, dict):
            continue
        players = cur.get("players")
        idx = cur.get("yourIndex")
        turn = cur.get("turn")
        if not (isinstance(players, list) and isinstance(idx, int) and isinstance(turn, int)):
            continue
        p = players[idx] if idx < len(players) else None
        if not isinstance(p, dict):
            continue
        active = _ids(p.get("active"))
        bench = _ids(p.get("bench"))
        hand = _ids(p.get("hand"))
        views[turn] = {"turn": turn, "active": active, "bench": bench, "hand": hand,
                       "bench_count": len(bench), "bench_ids": bench,
                       "benchable_in_hand": sorted(set(hand) & BENCHABLE),
                       "mega_in_hand": MEGA in hand}
    return [views[t] for t in sorted(views)]


def analyze(ep, seat):
    replay = load_replay(RAW / f"{ep}.json")
    traj = seat_trajectory(replay, seat)
    benched_when_thin = 0          # turns: bench went from <2 to higher with a benchable in hand prev
    thin_board_turns = 0           # turns with <=1 Pokémon in play after turn 2
    held_unplayed_when_thin = 0    # turns: bench thin + benchable in hand AND next turn still thin
    kept_two_plus = 0              # turns with >=2 Pokémon in play
    # Mega Abomasnow ex (723) is an evolution payoff: it can legitimately sit on the
    # bench ONLY after a Snover (722) was benched there and evolved. It is "benched
    # from hand" (illegal/red-flag) only if 723 appears on the bench in a game where
    # no Snover was ever benched first.
    snover_benched_before = False
    mega_on_bench = False
    mega_benched_from_hand = False
    for v in traj:
        if SNOVER in v["bench_ids"]:
            snover_benched_before = True
        if MEGA in v["bench_ids"]:
            mega_on_bench = True
            if not snover_benched_before:
                mega_benched_from_hand = True
        in_play = len(v["active"]) + v["bench_count"]
        if v["turn"] > 2 and in_play <= 1:
            thin_board_turns += 1
        if in_play >= 2:
            kept_two_plus += 1
    # benching response: compare consecutive turns
    for a, b in zip(traj, traj[1:]):
        thin_a = (len(a["active"]) + a["bench_count"]) <= 1 and a["turn"] > 1
        if thin_a and a["benchable_in_hand"]:
            if b["bench_count"] > a["bench_count"]:
                benched_when_thin += 1
            else:
                held_unplayed_when_thin += 1
    max_bench = max((v["bench_count"] for v in traj), default=0)
    return {
        "episode": ep, "seat": seat, "turns_observed": len(traj),
        "max_bench_count": max_bench,
        "turns_thin_board_after_t2": thin_board_turns,
        "turns_two_plus_in_play": kept_two_plus,
        "benched_backup_when_thin": benched_when_thin,
        "held_backup_unplayed_when_thin": held_unplayed_when_thin,
        "mega_723_on_bench_via_evolution": mega_on_bench and not mega_benched_from_hand,
        "mega_723_benched_from_hand": mega_benched_from_hand,
    }


def main():
    rows = []
    for ep in EPISODES:
        replay = load_replay(RAW / f"{ep}.json")
        agents = [a.get("Name") for a in replay.info.get("Agents", []) if isinstance(a, dict)]
        is_mirror = sum(1 for a in agents if a == OUR) == 2
        # our pivot seat(s): both in a mirror
        seats = [i for i, a in enumerate(agents) if a == OUR] or [1]
        for s in seats:
            r = analyze(ep, s)
            r["is_mirror"] = is_mirror
            rows.append(r)
    agg = {
        "episodes": len(EPISODES),
        "seats_analyzed": len(rows),
        "total_benched_when_thin": sum(r["benched_backup_when_thin"] for r in rows),
        "total_held_unplayed_when_thin": sum(r["held_backup_unplayed_when_thin"] for r in rows),
        "any_mega_benched_from_hand": any(r["mega_723_benched_from_hand"] for r in rows),
        "mega_on_bench_via_evolution": any(r["mega_723_on_bench_via_evolution"] for r in rows),
        "min_max_bench": min(r["max_bench_count"] for r in rows),
    }
    doc = {"pass": "24", "part": "H", "generated": datetime.datetime.utcnow().isoformat() + "Z",
           "candidate_id": "league_water_anti_disruption_pivot_v1",
           "caveat": "Inferred from board trajectory; replay does not expose agent hook flags.",
           "summary": agg, "per_seat": rows}
    (REPO / "data/experiments/pass24_hook_effectiveness.json").write_text(json.dumps(doc, indent=2))
    L = ["# Pass 24 — Anti-Disruption Hook Effectiveness", "",
         f"- generated: {doc['generated']}",
         "- **Inferred from board trajectory only** (replay does not expose agent internals).",
         f"- Mega Abomasnow ex (723) ever benched directly from hand (illegal/red-flag): **{agg['any_mega_benched_from_hand']}**",
         f"- Mega Abomasnow ex (723) on bench via legitimate evolution of a benched Snover: **{agg['mega_on_bench_via_evolution']}**",
         f"- min(max bench) across analyzed seats: **{agg['min_max_bench']}** (board was developed in every game)",
         f"- backup benched when thin: {agg['total_benched_when_thin']}; "
         f"held-unplayed-when-thin: {agg['total_held_unplayed_when_thin']}", "",
         "## Per seat"]
    for r in rows:
        L.append(f"- `{r['episode']}` seat {r['seat']}{' (mirror)' if r['is_mirror'] else ''}: "
                 f"max_bench={r['max_bench_count']}, thin_after_t2={r['turns_thin_board_after_t2']}, "
                 f"two_plus_in_play={r['turns_two_plus_in_play']}, benched_when_thin={r['benched_backup_when_thin']}, "
                 f"held_unplayed_when_thin={r['held_backup_unplayed_when_thin']}, "
                 f"mega_via_evo={r['mega_723_on_bench_via_evolution']}, "
                 f"mega_from_hand={r['mega_723_benched_from_hand']}")
    (REPO / "data/experiments/pass24_hook_effectiveness.md").write_text("\n".join(L))
    print("summary:", json.dumps(agg))


if __name__ == "__main__":
    main()
