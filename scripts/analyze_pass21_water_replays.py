#!/usr/bin/env python3
"""Pass 21 — Water reference post-mortem over the newly ingested replays.

Read-only forensic analysis of the league_water_core_reference seat ("our" seat,
agent name 'Yohei Nakajima') in the five replays ingested this pass. Every signal
is read from ground-truth replay state via ``KaggleReplay.board_metrics`` /
``final_result``; anything not provable from the replay is reported as ``None`` /
``"unknown"`` rather than guessed. No Grok summary is trusted over replay evidence.

Outputs (under data/experiments/):
  pass21_water_postmortem.json
  pass21_water_postmortem.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402
from ptcg_activegraph.playbooks.schema import CARD_NAMES  # noqa: E402

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
OUT_JSON = REPO / "data" / "experiments" / "pass21_water_replay_analysis.json"
OUT_MD = REPO / "data" / "experiments" / "pass21_water_replay_analysis.md"
OUT_JSONL = REPO / "data" / "experiments" / "pass21_water_game_summaries.jsonl"

# Our submitted agent name across the corpus.
OUR_AGENT = "Yohei Nakajima"

# Confirmed water-line cards of interest (same constants the meta layer uses).
KYOGRE, SNOVER, MEGA_ABOMASNOW = 721, 722, 723

# Episodes ingested in Pass 21 (5 new replays; 80590776 is a self-mirror).
NEW_EPISODES = ["80590776", "80591511", "80592173", "80592831", "80593320"]

FAST_LOSS_STEPS = 60
LONG_GAME_STEPS = 140


def _name(cid: int) -> str:
    return CARD_NAMES.get(cid, f"card {cid}")


def _our_seats(agents: list[str]) -> list[int]:
    return [i for i, a in enumerate(agents) if a == OUR_AGENT]


def _classify_result(reward) -> str:
    if reward is None:
        return "unknown"
    if reward > 0:
        return "win"
    if reward < 0:
        return "loss"
    return "draw"


def _failure_modes(seat_view: dict, num_steps: int, result: str,
                   is_mirror: bool) -> list[str]:
    """Evidence-grounded failure tags for a single (losing) seat view."""
    tags: list[str] = []
    if is_mirror:
        return tags
    if result == "loss" and num_steps <= FAST_LOSS_STEPS:
        tags.append("fast_loss")
    if seat_view.get("stuck_on_basic_snover"):
        tags.append("stuck_on_basic_snover")
    if seat_view.get("decked_out"):
        tags.append("decked_out_over_thinning")
    fat = seat_view.get("first_attack_turn")
    if result == "loss" and (fat is None or (isinstance(fat, int) and fat >= 4)):
        tags.append("slow_or_no_attack")
    if result == "loss" and num_steps >= LONG_GAME_STEPS:
        tags.append("long_passive_game")
    if not tags and result == "loss":
        tags.append("loss_no_specific_tempo_tag")
    return tags


def analyze_episode(ep: str) -> dict:
    path = RAW_DIR / f"{ep}.json"
    # The self-mirror raw file carries a suffix.
    if not path.exists():
        cand = list(RAW_DIR.glob(f"{ep}*.json"))
        if cand:
            path = cand[0]
    replay = load_replay(path)
    info = replay.info
    agents = [a.get("Name") for a in info.get("Agents", []) if isinstance(a, dict)]
    rewards = replay.rewards
    decks = replay.submitted_decks()
    our_seats = _our_seats(agents)
    is_mirror = len(our_seats) == 2

    seat_views: dict[str, dict] = {}
    for seat in sorted(decks):
        m = replay.board_metrics(seat)
        board = set(m["board_card_ids"])
        ids = decks[seat]
        active_by_turn = m["active_ids_by_turn"]
        first_turn = min((int(t) for t in active_by_turn), default=None)
        opening_active = active_by_turn.get(str(first_turn), []) if first_turn is not None else []
        seat_views[str(seat)] = {
            "agent": agents[seat] if seat < len(agents) else None,
            "is_ours": seat in our_seats,
            "final_reward": m["final_reward"],
            "result": _classify_result(m["final_reward"]),
            "opening_active_ids": opening_active,
            "opening_active_names": [_name(c) for c in opening_active],
            "kyogre_became_active": any(
                KYOGRE in v for v in active_by_turn.values()),
            "snover_became_active": any(
                SNOVER in v for v in active_by_turn.values()),
            "first_attack_turn": m["first_attack_turn"],
            "turns_observed": m["turns_observed"],
            "max_bench_size": max((v for v in m["bench_size_by_turn"].values()), default=0),
            "no_bench_developed": max((v for v in m["bench_size_by_turn"].values()), default=0) == 0,
            "min_deck_count": m["min_deck_count"],
            "decked_out": m["min_deck_count"] == 0,
            "used_kyogre": KYOGRE in board,
            "used_snover": SNOVER in board,
            "evolved_mega_abomasnow": MEGA_ABOMASNOW in board,
            "stuck_on_basic_snover": (SNOVER in board and MEGA_ABOMASNOW not in board),
            "deck_unique": len(set(ids)),
            "deck_fingerprint": {str(k): v for k, v in sorted(Counter(ids).items())},
            "deckcount_trajectory": m["deckcount_trajectory"],
        }

    # Primary "our" view (first our-seat; mirror reports both).
    primary_seat = our_seats[0] if our_seats else (sorted(decks)[0] if decks else None)
    our_view = seat_views.get(str(primary_seat), {}) if primary_seat is not None else {}
    result = "self_mirror" if is_mirror else our_view.get("result", "unknown")
    opp_seats = [] if is_mirror else [s for s in sorted(decks) if s not in our_seats]
    opponent = (agents[opp_seats[0]] if opp_seats and opp_seats[0] < len(agents)
                else None)

    failure_modes = _failure_modes(our_view, replay.num_steps, result, is_mirror)
    opp_fp = (seat_views.get(str(opp_seats[0]), {}).get("deck_fingerprint")
              if opp_seats else None)

    return {
        "episode": ep,
        "agents": agents,
        "rewards": rewards,
        "statuses": replay.statuses,
        "our_seats": our_seats,
        "is_self_mirror": is_mirror,
        "opponent": opponent,
        "opponent_deck_fingerprint": opp_fp,
        "num_steps": replay.num_steps,
        "result_for_us": result,
        "our_seat_view": our_view,
        "failure_modes": failure_modes,
        "seat_views": seat_views,
    }


def build_postmortem() -> dict:
    per_game = [analyze_episode(ep) for ep in NEW_EPISODES]

    non_mirror = [g for g in per_game if not g["is_self_mirror"]]
    wins = sum(1 for g in non_mirror if g["result_for_us"] == "win")
    losses = sum(1 for g in non_mirror if g["result_for_us"] == "loss")
    draws = sum(1 for g in non_mirror if g["result_for_us"] == "draw")

    tag_counts: Counter = Counter()
    for g in non_mirror:
        for t in g["failure_modes"]:
            tag_counts[t] += 1

    # Snover-stuck rate across our non-mirror seat views.
    snover_games = [g for g in non_mirror if g["our_seat_view"].get("used_snover")]
    stuck_games = [g for g in non_mirror
                   if g["our_seat_view"].get("stuck_on_basic_snover")]

    return {
        "schema": "activegraph.pass21.water_postmortem/v1",
        "pass": 21,
        "agent": OUR_AGENT,
        "active_control": "league_water_core_reference",
        "active_control_public_score": 420.8,
        "new_episodes": NEW_EPISODES,
        "record_excluding_mirror": {"wins": wins, "losses": losses, "draws": draws},
        "self_mirrors": [g["episode"] for g in per_game if g["is_self_mirror"]],
        "failure_mode_counts": dict(tag_counts.most_common()),
        "snover_played_games": [g["episode"] for g in snover_games],
        "stuck_on_basic_snover_games": [g["episode"] for g in stuck_games],
        "mega_abomasnow_evolution_observed": any(
            g["our_seat_view"].get("evolved_mega_abomasnow") for g in non_mirror
        ),
        "per_game": per_game,
    }


def to_markdown(pm: dict) -> str:
    rec = pm["record_excluding_mirror"]
    L = ["# Pass 21 — Water reference post-mortem (Part E)", ""]
    L.append(f"> Active control **{pm['active_control']}** @ public **{pm['active_control_public_score']}**. "
             f"All signals read from ground-truth replay state; unprovable signals are `None`.")
    L.append("")
    L.append(f"- new episodes: **{len(pm['new_episodes'])}** "
             f"(self-mirror: {', '.join(pm['self_mirrors']) or 'none'})")
    L.append(f"- record (excluding mirror): **{rec['wins']}W / {rec['losses']}L / {rec['draws']}D**")
    L.append(f"- Mega Abomasnow ex evolution observed in any game: "
             f"**{pm['mega_abomasnow_evolution_observed']}**")
    L.append(f"- games where Snover was played but never evolved: "
             f"**{len(pm['stuck_on_basic_snover_games'])}** "
             f"({', '.join(pm['stuck_on_basic_snover_games']) or 'none'})")
    L.append("")
    L.append("## Failure-mode tally (our seat, losses)")
    if pm["failure_mode_counts"]:
        for tag, n in pm["failure_mode_counts"].items():
            L.append(f"- `{tag}`: {n}")
    else:
        L.append("- none")
    L.append("")
    L.append("## Per-game post-mortem")
    for g in pm["per_game"]:
        ov = g["our_seat_view"]
        L.append("")
        L.append(f"### Episode {g['episode']} — {g['result_for_us'].upper()}"
                 f"{' (self-mirror)' if g['is_self_mirror'] else ''}")
        L.append(f"- opponent: **{g['opponent'] or '(self)'}** | steps: {g['num_steps']} "
                 f"| rewards: {g['rewards']}")
        if not g["is_self_mirror"]:
            L.append(f"- our seat {g['our_seats']}: opening_active="
                     f"{ov.get('opening_active_names') or 'unknown'}, first_attack_turn="
                     f"{ov.get('first_attack_turn')}, turns_observed={ov.get('turns_observed')}, "
                     f"max_bench={ov.get('max_bench_size')}, min_deck_count={ov.get('min_deck_count')}")
            L.append(f"- water line: kyogre_active={ov.get('kyogre_became_active')}, "
                     f"snover_active={ov.get('snover_became_active')}, "
                     f"used_kyogre={ov.get('used_kyogre')}, used_snover={ov.get('used_snover')}, "
                     f"evolved_mega_abomasnow={ov.get('evolved_mega_abomasnow')}, "
                     f"stuck_on_basic_snover={ov.get('stuck_on_basic_snover')}, "
                     f"no_bench={ov.get('no_bench_developed')}")
            L.append(f"- failure modes: {', '.join(g['failure_modes']) or 'none'}")
        else:
            L.append("- self-mirror (Yohei vs Yohei): excluded from win/loss record; "
                     "tempo signals retained for reference only.")
    L.append("")
    return "\n".join(L)


def main() -> int:
    pm = build_postmortem()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(pm, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(to_markdown(pm), encoding="utf-8")
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for g in pm["per_game"]:
            ov = g["our_seat_view"]
            row = {
                "episode_id": g["episode"],
                "opponent": g["opponent"],
                "our_seats": g["our_seats"],
                "result": g["result_for_us"],
                "rewards": g["rewards"],
                "statuses": g["statuses"],
                "num_steps": g["num_steps"],
                "is_self_mirror": g["is_self_mirror"],
                "opponent_deck_fingerprint": g["opponent_deck_fingerprint"],
                "opening_active_ids": ov.get("opening_active_ids"),
                "kyogre_became_active": ov.get("kyogre_became_active"),
                "snover_became_active": ov.get("snover_became_active"),
                "evolved_mega_abomasnow": ov.get("evolved_mega_abomasnow"),
                "stuck_on_basic_snover": ov.get("stuck_on_basic_snover"),
                "first_attack_turn": ov.get("first_attack_turn"),
                "no_bench_developed": ov.get("no_bench_developed"),
                "min_deck_count": ov.get("min_deck_count"),
                "failure_modes": g["failure_modes"],
            }
            f.write(json.dumps(row) + "\n")
    rec = pm["record_excluding_mirror"]
    print(f"water post-mortem: {rec['wins']}W/{rec['losses']}L/{rec['draws']}D "
          f"(excl. mirror); stuck_on_basic_snover in "
          f"{len(pm['stuck_on_basic_snover_games'])} game(s)")
    print(f"  mega_abomasnow_evolution_observed={pm['mega_abomasnow_evolution_observed']}")
    print(f"  -> {OUT_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
