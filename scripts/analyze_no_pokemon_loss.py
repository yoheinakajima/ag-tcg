#!/usr/bin/env python3
"""Pass 22 (Part C) — no-Pokémon-in-play / empty-bench loss analyzer.

Read-only forensic analysis of every replay where our Water seat (agent name
``Yohei Nakajima``) appears. For each game we read ground-truth board state from
the per-step ``observation.current`` and classify how a loss happened, with a
focus on board-collapse losses: the last Pokémon in play KO'd with an empty
bench and no benchable Basic to promote.

Key deck distinction (no invented IDs):
  * benchable Basic = Kyogre (721) or Snover (722)
  * Mega Abomasnow ex (723) is an EVOLUTION payoff (played on top of Snover) and
    is NOT benchable; it is classified as ``evolution_payoff_available``.

Anything not provable from the replay is reported as ``None`` / ``"unknown"``
rather than guessed. NO upload. NO root changes.

Outputs (data/experiments/):
  pass22_no_pokemon_loss_analysis.json
  pass22_no_pokemon_loss_analysis.md
  pass22_no_pokemon_loss_windows.jsonl
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
OUT_JSON = REPO / "data" / "experiments" / "pass22_no_pokemon_loss_analysis.json"
OUT_MD = REPO / "data" / "experiments" / "pass22_no_pokemon_loss_analysis.md"
OUT_JSONL = REPO / "data" / "experiments" / "pass22_no_pokemon_loss_windows.jsonl"

OUR_AGENT = "Yohei Nakajima"
KYOGRE, SNOVER, MEGA_ABOMASNOW = 721, 722, 723
BENCHABLE_BASICS = {KYOGRE, SNOVER}
BASIC_ENERGY = 3

# User-identified no-bench losses to verify explicitly (80594000 is absent).
REQUIRED_EPISODES = ["80592831", "80594000"]


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


def _own_player(obs):
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return None, None
    players = cur.get("players")
    idx = cur.get("yourIndex")
    if isinstance(players, list) and isinstance(idx, int) and 0 <= idx < len(players):
        p = players[idx]
        return (p if isinstance(p, dict) else None), cur.get("turn")
    return None, cur.get("turn") if isinstance(cur, dict) else None


def _opp_player(obs):
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return None
    players = cur.get("players")
    idx = cur.get("yourIndex")
    if isinstance(players, list) and isinstance(idx, int):
        for i, p in enumerate(players):
            if i != idx and isinstance(p, dict):
                return p
    return None


def _classify(reward):
    if reward is None:
        return "unknown"
    return "win" if reward > 0 else ("loss" if reward < 0 else "draw")


def _per_turn_views(replay, seat):
    """Per-turn snapshots: {turn: {bench, active_ids, hand_ids, deck}}.

    Keeps the FIRST observation seen for each turn (matches board_metrics) and
    also the LAST hand/bench seen that turn for completeness of 'had backup'.
    """
    views = {}
    for rec in replay.agent_steps(seat):
        obs = rec.get("observation")
        if not isinstance(obs, dict):
            continue
        pl, turn = _own_player(obs)
        if pl is None or not isinstance(turn, int):
            continue
        active = _ids(pl.get("active"))
        bench = _ids(pl.get("bench"))
        hand = _ids(pl.get("hand"))
        snap = {
            "turn": turn,
            "active_ids": active,
            "active_count": len(active),
            "bench_ids": bench,
            "bench_count": len(bench),
            "bench_empty": len(bench) == 0,
            "hand_ids": hand,
            "deck_count": pl.get("deckCount"),
            "benchable_in_hand": sorted(set(hand) & BENCHABLE_BASICS),
            "mega_in_hand": MEGA_ABOMASNOW in hand,
        }
        # Last snapshot of the turn wins (closest to end-of-turn board).
        views[turn] = snap
    return dict(sorted(views.items()))


def analyze_episode(ep, path, force_seat=None):
    replay = load_replay(path)
    info = replay.info
    agents = [a.get("Name") for a in info.get("Agents", []) if isinstance(a, dict)]
    our_seats = [i for i, a in enumerate(agents) if a == OUR_AGENT]
    is_mirror = len(our_seats) == 2
    if force_seat is None and not our_seats:
        return None
    seat = force_seat if force_seat is not None else our_seats[0]

    reward = replay.rewards[seat] if seat < len(replay.rewards) else None
    # When a specific seat is requested (e.g. the losing seat in a self-mirror),
    # classify by that seat's actual reward so loss-condition logic runs.
    if force_seat is not None:
        result = _classify(reward)
    else:
        result = "self_mirror" if is_mirror else _classify(reward)
    status = replay.statuses[seat] if seat < len(replay.statuses) else None

    final_obs = replay.final_observation(seat)
    me, _ = _own_player(final_obs) if final_obs else (None, None)
    opp = _opp_player(final_obs) if final_obs else None

    final_active = _ids(me.get("active")) if me else []
    final_bench = _ids(me.get("bench")) if me else []
    final_hand = _ids(me.get("hand")) if me else []
    final_discard = _ids(me.get("discard")) if me else []
    final_deck = me.get("deckCount") if me else None
    our_prize_left = len(me.get("prize")) if me and isinstance(me.get("prize"), list) else None
    opp_prize_left = len(opp.get("prize")) if opp and isinstance(opp.get("prize"), list) else None

    final_active_id = final_active[0] if final_active else None
    final_active_is = (
        "kyogre" if final_active_id == KYOGRE else
        "snover" if final_active_id == SNOVER else
        "mega_abomasnow_ex" if final_active_id == MEGA_ABOMASNOW else
        (None if final_active_id is None else "other")
    )

    # Loss-condition inference (only meaningful for losses).
    loss_condition = "unknown"
    if result == "loss":
        if final_deck == 0:
            loss_condition = "deckout"
        elif opp_prize_left == 0:
            loss_condition = "prizes"
        elif status not in (None, "DONE"):
            loss_condition = "timeout"
        elif len(final_bench) == 0 and len(final_active) <= 1:
            loss_condition = "no_pokemon_in_play"
        else:
            loss_condition = "unknown"

    # Per-turn trajectory.
    views = _per_turn_views(replay, seat)
    turns = list(views.values())
    turns_with_empty_bench = sum(1 for v in turns if v["bench_empty"])
    turns_single_in_play = sum(1 for v in turns if v["active_count"] >= 1 and v["bench_empty"])
    turns_empty_after_2 = sum(1 for v in turns if v["turn"] > 2 and v["bench_empty"])

    # Did we hold a benchable Basic while bench was empty?
    backup_in_hand_windows = [
        {"turn": v["turn"], "benchable_in_hand": v["benchable_in_hand"]}
        for v in turns if v["bench_empty"] and v["benchable_in_hand"]
    ]
    benchable_basic_in_hand_while_bench_empty = bool(backup_in_hand_windows)

    # Failed to play an available backup Basic: we held a benchable Basic while
    # bench was empty on some turn, AND a LATER our-turn still shows empty bench.
    failed_to_play_available_backup = False
    fail_evidence_turns = []
    held_turns = [w["turn"] for w in backup_in_hand_windows]
    for ht in held_turns:
        later_empty = [v["turn"] for v in turns if v["turn"] > ht and v["bench_empty"]]
        if later_empty:
            failed_to_play_available_backup = True
            fail_evidence_turns.append({"held_turn": ht, "still_empty_turns": later_empty})

    # Searchable backup: copies of benchable Basics not accounted for on board /
    # in discard / in hand could still be in deck or prizes. We can prove a basic
    # is *somewhere out of play* but NOT that it is searchable (could be prized).
    decks = replay.submitted_decks()
    our_deck = decks.get(seat, [])
    deck_counts = Counter(our_deck)
    seen = Counter(final_active + final_bench + final_hand + final_discard)
    remaining_benchable = {
        cid: deck_counts.get(cid, 0) - seen.get(cid, 0)
        for cid in BENCHABLE_BASICS
    }
    remaining_benchable = {k: max(0, v) for k, v in remaining_benchable.items()}
    searchable_basic_possible = (
        any(c > 0 for c in remaining_benchable.values())
        and (final_deck or 0) > 0
        and len(final_bench) == 0
    )

    # Discarded a backup Basic / line piece while bench thin.
    discarded_backup = sorted(set(final_discard) & BENCHABLE_BASICS)
    discarded_backup_basic = bool(discarded_backup) and turns_with_empty_bench > 0

    # Root cause synthesis.
    root_cause = "unknown"
    if result == "loss" and loss_condition == "no_pokemon_in_play":
        if final_active_is == "mega_abomasnow_ex":
            root_cause = "lone_evolution_active_ko_no_backup_basic"
        elif benchable_basic_in_hand_while_bench_empty and failed_to_play_available_backup:
            root_cause = "held_backup_basic_but_never_benched"
        elif MEGA_ABOMASNOW in final_hand and not (set(final_hand) & BENCHABLE_BASICS):
            root_cause = "only_non_benchable_mega_in_hand_when_active_ko"
        elif searchable_basic_possible:
            root_cause = "backup_basic_out_of_play_not_deployed"
        else:
            root_cause = "board_collapsed_no_available_backup"

    tags = []
    if result == "loss" and loss_condition == "no_pokemon_in_play":
        tags.append("no_pokemon_in_play_loss")
        if len(final_bench) == 0:
            tags.append("final_active_ko_empty_bench")
    if failed_to_play_available_backup:
        tags.append("failed_to_play_available_backup_basic")
    if turns_single_in_play >= 2:
        tags.append("active_alone_too_long")
    if result == "loss" and not (set(final_hand) & BENCHABLE_BASICS) and MEGA_ABOMASNOW in final_hand:
        tags.append("no_backup_plan_after_energy_denial")  # only non-benchable payoff left

    return {
        "episode": ep,
        "present": True,
        "agents": agents,
        "our_seat": seat,
        "is_self_mirror": is_mirror,
        "opponent": agents[[i for i in range(len(agents)) if i != seat][0]] if (not is_mirror and len(agents) > 1) else None,
        "result": result,
        "status": status,
        "num_steps": replay.num_steps,
        "loss_condition": loss_condition,
        "final_active_count": len(final_active),
        "final_active_ids": final_active,
        "final_active_names": [_name(c) for c in final_active],
        "final_active_is": final_active_is,
        "final_bench_count": len(final_bench),
        "final_bench_empty": len(final_bench) == 0,
        "final_hand_ids": final_hand,
        "final_deck_count": final_deck,
        "our_prize_left": our_prize_left,
        "opp_prize_left": opp_prize_left,
        "turns_with_empty_bench": turns_with_empty_bench,
        "turns_with_single_pokemon_in_play": turns_single_in_play,
        "turns_with_bench_empty_after_turn_2": turns_empty_after_2,
        "benchable_basic_in_hand_while_bench_empty": benchable_basic_in_hand_while_bench_empty,
        "backup_in_hand_windows": backup_in_hand_windows,
        "searchable_basic_available_while_bench_empty": searchable_basic_possible,
        "remaining_benchable_basics_out_of_play": remaining_benchable,
        "failed_to_play_available_backup_basic": failed_to_play_available_backup,
        "failed_to_play_evidence": fail_evidence_turns,
        "failed_to_search_backup_when_available": "unknown",  # search options not in replay obs
        "discarded_backup_basic_or_line_piece": discarded_backup_basic,
        "discarded_backup_ids": discarded_backup,
        "evolution_payoff_in_hand": MEGA_ABOMASNOW in final_hand,
        "no_pokemon_loss_root_cause": root_cause,
        "tags": tags,
        "evidence_steps": {
            "final_observation_used": True,
            "turns_observed": [v["turn"] for v in turns],
        },
    }


PASS24_EPISODES = ["80623232", "80622745", "80622626"]
P24_OUT_JSON = REPO / "data" / "experiments" / "pass24_empty_board_postmortem.json"
P24_OUT_MD = REPO / "data" / "experiments" / "pass24_empty_board_postmortem.md"
P24_OUT_JSONL = REPO / "data" / "experiments" / "pass24_empty_board_windows.jsonl"


def _mega_benched_from_hand(views):
    """True only if Mega Abomasnow ex (723) appears on the bench in a game where a
    Snover (722) was never benched first (i.e. it would have to be benched directly
    from hand — illegal for an evolution payoff). 723 on bench after a benched Snover
    is legitimate evolution and is NOT flagged."""
    snover_seen = False
    for v in views:
        if SNOVER in v.get("bench_ids", []):
            snover_seen = True
        if MEGA_ABOMASNOW in v.get("bench_ids", []) and not snover_seen:
            return True
    return False


def _pass24_extra_signals(replay, seat, base):
    """Hook-firing & midgame-collapse signals inferred from board trajectory only."""
    views = list(_per_turn_views(replay, seat).values())
    max_bench = max((v["bench_count"] for v in views), default=0)
    final_bench_empty = base.get("final_bench_empty")
    result = base.get("result")
    # Did the bench ever look healthy (>=2) after setup, then collapse to empty at loss?
    healthy_then_collapsed = (
        max_bench >= 2 and final_bench_empty and result == "loss"
    )
    # Inferred emergency-backup hook outcomes (replay shows board, not agent logic):
    #  - missed: held a benchable Basic while bench empty AND bench still empty later
    #  - success: bench was empty + benchable in hand on turn T, then a LATER turn
    #             shows a benchable Basic actually on the bench
    hook_missed = base.get("failed_to_play_available_backup_basic", False)
    hook_success = False
    held_turns = [w["turn"] for w in base.get("backup_in_hand_windows", [])]
    # success (inferred): after a turn where the bench was empty while a benchable
    # Basic was held, a LATER turn shows the bench actually populated.
    for ht in held_turns:
        for v in views:
            if v["turn"] > ht and v["bench_count"] >= 1 and not v["bench_empty"]:
                hook_success = True
                break
        if hook_success:
            break
    # turn the bench first became empty after turn 2 (collapse onset)
    collapse_turn = next((v["turn"] for v in views if v["turn"] > 2 and v["bench_empty"]), None)
    # peak bench turn
    peak_turn = None
    for v in views:
        if v["bench_count"] == max_bench:
            peak_turn = v["turn"]
            break
    extra = {
        "max_bench_count": max_bench,
        "bench_healthy_after_setup": max_bench >= 2,
        "bench_collapsed_after_initial_success": healthy_then_collapsed,
        "emergency_backup_hook_missed_inferred": hook_missed,
        "emergency_backup_hook_success_inferred": hook_success,
        "hook_fired_too_late_inferred": (hook_success and final_bench_empty and result == "loss"),
        "collapse_onset_turn": collapse_turn,
        "bench_peak_turn": peak_turn,
        # Derived (not hardcoded): 723 is benched-from-hand only if it appears on the
        # bench in a game where Snover (722) was never benched first. 723 reaching the
        # bench via evolution of a benched Snover is legitimate, not "treated benchable".
        "mega_723_treated_as_benchable_anywhere": _mega_benched_from_hand(views),
    }
    tags = list(base.get("tags", []))
    if extra["bench_collapsed_after_initial_success"]:
        tags.append("bench_collapsed_after_initial_success")
    if extra["emergency_backup_hook_missed_inferred"]:
        tags.append("emergency_backup_hook_missed")
    if extra["emergency_backup_hook_success_inferred"]:
        tags.append("emergency_backup_hook_success")
    if result == "loss" and base.get("loss_condition") == "no_pokemon_in_play":
        tags.append("board_safety_not_fixed")
    elif result == "win" or (result == "loss" and base.get("loss_condition") != "no_pokemon_in_play"):
        tags.append("board_safety_fixed")
    extra["tags"] = sorted(set(tags))
    return extra


def run_pass24():
    """Pass 24 empty-board post-mortem for the 3 newly ingested replays.

    For non-mirror games we analyze our (pivot) seat; for the self-mirror we
    analyze the LOSING seat (the empty-board question is about whoever lost).
    """
    records = []
    for ep in PASS24_EPISODES:
        path = RAW_DIR / f"{ep}.json"
        if not path.exists():
            records.append({"episode": ep, "present": False,
                            "note": "ABSENT — recorded as missing input, not fabricated"})
            continue
        replay = load_replay(path)
        agents = [a.get("Name") for a in replay.info.get("Agents", []) if isinstance(a, dict)]
        is_mirror = sum(1 for a in agents if a == OUR_AGENT) == 2
        rewards = replay.rewards
        if is_mirror:
            # analyze the losing seat
            seat = next((i for i, r in enumerate(rewards) if r is not None and r < 0), 0)
        else:
            seat = next((i for i, a in enumerate(agents) if a == OUR_AGENT), 0)
        base = analyze_episode(ep, path, force_seat=seat)
        extra = _pass24_extra_signals(replay, seat, base)
        base.update(extra)
        base["analyzed_seat"] = seat
        base["is_self_mirror"] = is_mirror
        records.append(base)

    no_pokemon = [r for r in records if r.get("loss_condition") == "no_pokemon_in_play"]
    tag_counts = Counter()
    for r in records:
        for t in r.get("tags", []):
            tag_counts[t] += 1

    out = {
        "schema": "activegraph.pass24.empty_board_postmortem/v1",
        "pass": 24, "part": "G", "no_upload": True,
        "candidate_id": "league_water_anti_disruption_pivot_v1",
        "episodes": PASS24_EPISODES,
        "no_pokemon_in_play_losses": [r["episode"] for r in no_pokemon],
        "tag_counts": dict(tag_counts.most_common()),
        "caveat": "Replay observations show board state, not agent internals; hook fired/missed is INFERRED from board trajectory.",
        "per_game": records,
    }
    P24_OUT_JSON.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    with P24_OUT_JSONL.open("w", encoding="utf-8") as f:
        for r in records:
            if not r.get("present", True):
                continue
            f.write(json.dumps({
                "episode_id": r["episode"], "analyzed_seat": r.get("analyzed_seat"),
                "result": r.get("result"), "loss_condition": r.get("loss_condition"),
                "final_active_is": r.get("final_active_is"),
                "final_bench_count": r.get("final_bench_count"),
                "final_bench_empty": r.get("final_bench_empty"),
                "max_bench_count": r.get("max_bench_count"),
                "bench_collapsed_after_initial_success": r.get("bench_collapsed_after_initial_success"),
                "emergency_backup_hook_missed_inferred": r.get("emergency_backup_hook_missed_inferred"),
                "emergency_backup_hook_success_inferred": r.get("emergency_backup_hook_success_inferred"),
                "no_pokemon_loss_root_cause": r.get("no_pokemon_loss_root_cause"),
                "tags": r.get("tags"),
            }) + "\n")
    L = ["# Pass 24 — Empty-board / no-backup post-mortem (Part G)", "",
         "> Read-only. Board state is ground truth; hook fired/missed is INFERRED from "
         "the board trajectory (replay does not expose agent internals). "
         "Benchable Basic = Kyogre 721 / Snover 722; Mega Abomasnow ex 723 is NOT benchable.", "",
         f"- candidate: `league_water_anti_disruption_pivot_v1`",
         f"- no-Pokémon-in-play losses among new replays: **{len(no_pokemon)}** "
         f"({', '.join(out['no_pokemon_in_play_losses']) or 'none'})", "",
         "## Tag counts"]
    for t, n in tag_counts.most_common():
        L.append(f"- `{t}`: {n}")
    L.append("")
    L.append("## Per-game")
    for r in records:
        if not r.get("present", True):
            L.append(f"\n### {r['episode']} — ABSENT (recorded missing, not fabricated)")
            continue
        L.append(f"\n### {r['episode']} — seat {r.get('analyzed_seat')} {str(r.get('result')).upper()} "
                 f"({r.get('loss_condition')})  {'[mirror]' if r.get('is_self_mirror') else ''}")
        L.append(f"- final active: {r.get('final_active_is')}; bench={r.get('final_bench_count')} "
                 f"(empty={r.get('final_bench_empty')}); max bench this game={r.get('max_bench_count')}")
        L.append(f"- prizes left: ours={r.get('our_prize_left')} opp={r.get('opp_prize_left')}; "
                 f"deck={r.get('final_deck_count')}; steps={r.get('num_steps')}")
        L.append(f"- bench_healthy_then_collapsed={r.get('bench_collapsed_after_initial_success')} "
                 f"(collapse onset turn {r.get('collapse_onset_turn')}, peak bench turn {r.get('bench_peak_turn')})")
        L.append(f"- emergency hook (inferred): missed={r.get('emergency_backup_hook_missed_inferred')}, "
                 f"success={r.get('emergency_backup_hook_success_inferred')}, "
                 f"too_late={r.get('hook_fired_too_late_inferred')}")
        L.append(f"- mega 723 treated as benchable anywhere: {r.get('mega_723_treated_as_benchable_anywhere')}")
        L.append(f"- **root cause: `{r.get('no_pokemon_loss_root_cause')}`** | tags: "
                 f"{', '.join(r.get('tags', [])) or 'none'}")
    P24_OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    for r in records:
        print(f"{r['episode']}: seat={r.get('analyzed_seat')} {r.get('result')} "
              f"loss_cond={r.get('loss_condition')} max_bench={r.get('max_bench_count')} "
              f"collapse={r.get('bench_collapsed_after_initial_success')}")
    return 0


def main():
    if "--pass24" in sys.argv:
        return run_pass24()
    raw_paths = sorted(RAW_DIR.glob("*.json"))
    per_game = []
    for p in raw_paths:
        ep = p.stem.split("_")[0]
        try:
            res = analyze_episode(ep, p)
        except Exception as exc:  # defensive: report, never crash the pass
            res = {"episode": ep, "present": True, "error": str(exc)}
        if res is not None:
            per_game.append(res)

    # Missing required episodes (e.g. 80594000) recorded honestly, not fabricated.
    present_eps = {g["episode"] for g in per_game}
    required_status = {}
    for ep in REQUIRED_EPISODES:
        if ep in present_eps:
            g = next(x for x in per_game if x["episode"] == ep)
            required_status[ep] = {
                "present": True,
                "loss_condition": g.get("loss_condition"),
                "final_active_is": g.get("final_active_is"),
                "final_bench_empty": g.get("final_bench_empty"),
            }
        else:
            required_status[ep] = {"present": False, "note": "ABSENT — recorded as missing input, not fabricated"}

    losses = [g for g in per_game if g.get("result") == "loss"]
    no_pokemon = [g for g in losses if g.get("loss_condition") == "no_pokemon_in_play"]
    tag_counts = Counter()
    for g in per_game:
        for t in g.get("tags", []):
            tag_counts[t] += 1

    out = {
        "schema": "activegraph.pass22.no_pokemon_loss/v1",
        "pass": 22,
        "part": "C",
        "no_upload": True,
        "agent": OUR_AGENT,
        "benchable_basics": sorted(BENCHABLE_BASICS),
        "non_benchable_evolution_payoff": MEGA_ABOMASNOW,
        "episodes_analyzed": [g["episode"] for g in per_game],
        "required_episode_status": required_status,
        "missing_inputs": [ep for ep in REQUIRED_EPISODES if ep not in present_eps],
        "loss_count": len(losses),
        "no_pokemon_in_play_losses": [g["episode"] for g in no_pokemon],
        "tag_counts": dict(tag_counts.most_common()),
        "per_game": per_game,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for g in per_game:
            if g.get("result") != "loss":
                continue
            f.write(json.dumps({
                "episode_id": g["episode"],
                "opponent": g.get("opponent"),
                "loss_condition": g.get("loss_condition"),
                "final_active_is": g.get("final_active_is"),
                "final_bench_empty": g.get("final_bench_empty"),
                "final_hand_ids": g.get("final_hand_ids"),
                "benchable_basic_in_hand_while_bench_empty": g.get("benchable_basic_in_hand_while_bench_empty"),
                "failed_to_play_available_backup_basic": g.get("failed_to_play_available_backup_basic"),
                "no_pokemon_loss_root_cause": g.get("no_pokemon_loss_root_cause"),
                "tags": g.get("tags"),
                "turns_with_empty_bench": g.get("turns_with_empty_bench"),
            }) + "\n")

    # Markdown
    L = ["# Pass 22 — No-Pokémon-in-play / empty-bench loss analysis (Part C)", ""]
    L.append("> Read-only. Benchable Basic = Kyogre (721) / Snover (722). "
             "Mega Abomasnow ex (723) is an evolution payoff, NOT benchable. "
             "Unprovable signals are reported as `unknown`. No upload.")
    L.append("")
    L.append(f"- episodes analyzed (our seat): **{len(per_game)}**")
    L.append(f"- losses: **{len(losses)}**; no-Pokémon-in-play losses: "
             f"**{len(no_pokemon)}** ({', '.join(out['no_pokemon_in_play_losses']) or 'none'})")
    L.append("")
    L.append("## Required episode status")
    for ep, st in required_status.items():
        if st.get("present"):
            L.append(f"- **{ep}**: present — loss_condition=`{st['loss_condition']}`, "
                     f"final_active=`{st['final_active_is']}`, bench_empty={st['final_bench_empty']}")
        else:
            L.append(f"- **{ep}**: {st['note']}")
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
        L.append(f"### {g['episode']} — {g['result'].upper()} vs {g.get('opponent') or '?'} "
                 f"({g.get('loss_condition')})")
        L.append(f"- final active: {g.get('final_active_names')} ({g.get('final_active_is')}); "
                 f"bench={g.get('final_bench_count')} (empty={g.get('final_bench_empty')})")
        L.append(f"- final hand ids: {g.get('final_hand_ids')}; deck={g.get('final_deck_count')}; "
                 f"our_prizes_left={g.get('our_prize_left')}; opp_prizes_left={g.get('opp_prize_left')}")
        L.append(f"- turns_empty_bench={g.get('turns_with_empty_bench')}, "
                 f"single_in_play={g.get('turns_with_single_pokemon_in_play')}, "
                 f"empty_after_t2={g.get('turns_with_bench_empty_after_turn_2')}")
        L.append(f"- benchable_in_hand_while_empty={g.get('benchable_basic_in_hand_while_bench_empty')}, "
                 f"failed_to_play_backup={g.get('failed_to_play_available_backup_basic')}, "
                 f"searchable_possible={g.get('searchable_basic_available_while_bench_empty')}")
        L.append(f"- **root cause: `{g.get('no_pokemon_loss_root_cause')}`** | tags: "
                 f"{', '.join(g.get('tags', [])) or 'none'}")
    L.append("")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"analyzed {len(per_game)} of-our-seat episodes; losses={len(losses)}; "
          f"no_pokemon_in_play={len(no_pokemon)} ({out['no_pokemon_in_play_losses']})")
    print(f"required: {required_status}")
    print(f"missing: {out['missing_inputs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
