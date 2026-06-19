#!/usr/bin/env python3
"""Pass 25 (Part C) — replay-window diagnostics for the two remaining Water seams.

Read-only forensic analysis of the three Pass-24 replays, grounding the Pass-25
hardening sprint in proven board/select/prize state (never fabricated effects):

  * 80623232 — Fighting / Mega-Lucario tempo / prize-liability LOSS
  * 80622626 — mirror / grind DECKOUT LOSS
  * 80622745 — Psychic WIN (positive control)

Everything is derived from ground truth in each step's ``observation.current``
(board, deckCount, prize, hand, discard) and ``observation.select`` (decision
context). Card *names* come from the official card DB; card *effects* are NOT
inferred. Any value not provable from replay state is reported as ``None`` /
``"unknown"``.

Key proven facts encoded here (see report):
  * ``prize`` is the face-down REMAINING prize list (you win at 0).
  * ctx7 search at low deck is FORCED: minCount==maxCount==1, so there is NO
    legal "decline" — the only conservation lever is at the Main phase (ctx0),
    declining to PLAY an optional draw/search trainer when the deck is low.
  * ctx38 (DrawCount) barely appears (~1 occurrence across all 3 games): a
    ctx38 draw-count clamp has essentially no replay grounding this pass.

Outputs (data/experiments/):
  pass25_loss_seam_analysis.json
  pass25_loss_seam_analysis.md
  pass25_loss_windows.jsonl

NO upload. NO root changes.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import tarfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

RAW_DIR = REPO / "data" / "meta_replays" / "raw"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
CAND_TARBALL = REPO / "data" / "submissions" / "candidates_pass22" / "league_water_anti_disruption_pivot_v1.tar.gz"

OUT_JSON = REPO / "data" / "experiments" / "pass25_loss_seam_analysis.json"
OUT_MD = REPO / "data" / "experiments" / "pass25_loss_seam_analysis.md"
OUT_JSONL = REPO / "data" / "experiments" / "pass25_loss_windows.jsonl"

OUR_AGENT = "Yohei Nakajima"
KYOGRE, SNOVER, MEGA = 721, 722, 723
BENCHABLE_BASICS = {KYOGRE, SNOVER}
# Optional deck-thinning draw/search TRAINERS in the pivot deck (names from the
# official card DB; we do NOT model their effects, only that they are the
# candidate conservation targets at low deck).
DRAW_SEARCH_TRAINERS = {1092, 1121, 1227}  # Secret Box, Ultra Ball, Lillie's Determination

# Reporting band for "low deck" search/draw decisions (the candidate guard uses
# its own, stricter threshold; this is purely diagnostic).
LOW_DECK_BAND = 12

CTX_MAIN, CTX_SEARCH, CTX_DRAWCOUNT = 0, 7, 38

EPISODES = {
    "80623232": "fighting_mega_lucario_tempo_prize_liability",
    "80622626": "mirror_grind_deckout",
    "80622745": "psychic_win_positive_control",
}


def _card_names() -> dict[int, str]:
    out: dict[int, str] = {}
    if not CARD_DB.exists():
        return out
    for row in csv.DictReader(open(CARD_DB, encoding="utf-8")):
        cid = (row.get("Card ID") or "").strip()
        if cid.isdigit():
            out[int(cid)] = (row.get("Card Name") or "").strip()
    return out


NAMES = _card_names()


def _name(cid):
    return None if cid is None else NAMES.get(cid, f"card {cid}")


def _candidate_fingerprint() -> dict:
    if not CAND_TARBALL.exists():
        return {}
    with tarfile.open(CAND_TARBALL) as t:
        m = [x for x in t.getmembers() if x.name.endswith("deck.csv")][0]
        data = t.extractfile(m).read().decode()
    ids = [int(r[0]) for r in csv.reader(io.StringIO(data)) if r and r[0].strip().isdigit()]
    return dict(Counter(ids))


def _ids(zone):
    out = []
    if isinstance(zone, list):
        for c in zone:
            if isinstance(c, dict):
                cid = c.get("id")
                if isinstance(cid, int) and not isinstance(cid, bool):
                    out.append(cid)
    return out


def _prize_remaining(player) -> int | None:
    pr = player.get("prize") if isinstance(player, dict) else None
    return len(pr) if isinstance(pr, list) else None


def analyze(ep: str, seam: str) -> dict:
    path = RAW_DIR / f"{ep}.json"
    if not path.exists():
        return {"episode": ep, "seam": seam, "present": False,
                "note": "ABSENT — recorded as missing input, not fabricated"}
    replay = load_replay(path)
    agents = [a.get("Name") for a in replay.info.get("Agents", []) if isinstance(a, dict)]
    rewards = replay.rewards
    statuses = replay.statuses
    our_name_seats = [i for i, a in enumerate(agents) if a == OUR_AGENT]
    is_mirror = len(our_name_seats) == 2

    # Attribution by exact deck fingerprint (a seat is the pivot only if its
    # submitted 60-card multiset matches the candidate deck exactly).
    cand_fp = _candidate_fingerprint()
    decks = replay.submitted_decks()
    pivot_seats = [s for s, d in decks.items() if dict(Counter(d)) == cand_fp]

    # Choose the analyzed seat: for losses, the seat that lost; otherwise our seat.
    if is_mirror:
        seat = next((i for i, r in enumerate(rewards) if isinstance(r, (int, float)) and r < 0), 0)
    elif pivot_seats:
        seat = pivot_seats[0]
    elif our_name_seats:
        seat = our_name_seats[0]
    else:
        seat = 0
    opp_seat = 1 - seat if len(agents) == 2 else None

    reward = rewards[seat] if seat < len(rewards) else None
    status = statuses[seat] if seat < len(statuses) else None
    result = "win" if (reward or 0) > 0 else ("loss" if (reward or 0) < 0 else "draw")

    attribution = (
        "pivot_self_mirror" if (is_mirror and len(pivot_seats) == 2)
        else "pivot_vs_external" if (seat in pivot_seats)
        else "our_name_only" if seat in our_name_seats
        else "unknown"
    )
    confidence = "high" if seat in pivot_seats else ("medium" if seat in our_name_seats else "low")

    # ---- per-turn trajectory (first snapshot per turn) -------------------
    deck_by_turn: list[dict] = []
    our_prize_by_turn: list[dict] = []
    opp_prize_by_turn: list[dict] = []
    bench_by_turn: list[dict] = []
    seen = set()
    mega_active_ever = mega_bench_ever = snover_bench_ever = False
    search_decisions: list[dict] = []   # ctx7 resolutions
    drawcount_decisions: list[dict] = []  # ctx38
    draw_search_trainer_in_hand_low: list[dict] = []

    for rec in replay.agent_steps(seat):
        obs = rec.get("observation")
        if not isinstance(obs, dict):
            continue
        cur = obs.get("current")
        if not isinstance(cur, dict):
            continue
        turn = cur.get("turn")
        yi = cur.get("yourIndex")
        pls = cur.get("players")
        if not (isinstance(pls, list) and isinstance(yi, int) and 0 <= yi < len(pls)):
            continue
        me = pls[yi]
        opp = pls[1 - yi] if len(pls) == 2 else None
        dc = me.get("deckCount")
        active = _ids(me.get("active"))
        bench = _ids(me.get("bench"))
        hand = _ids(me.get("hand"))
        if MEGA in active:
            mega_active_ever = True
        if MEGA in bench:
            mega_bench_ever = True
        if SNOVER in bench:
            snover_bench_ever = True
        if isinstance(turn, int) and turn not in seen and isinstance(dc, int):
            seen.add(turn)
            deck_by_turn.append({"turn": turn, "deck": dc})
            our_prize_by_turn.append({"turn": turn, "remaining": _prize_remaining(me)})
            if opp is not None:
                opp_prize_by_turn.append({"turn": turn, "remaining": _prize_remaining(opp)})
            bench_by_turn.append({"turn": turn, "bench": len(bench), "active": len(active)})

        sel = obs.get("select")
        if isinstance(sel, dict):
            ctx = sel.get("context")
            if ctx == CTX_SEARCH and isinstance(dc, int):
                search_decisions.append({
                    "turn": turn, "deck": dc,
                    "minCount": sel.get("minCount"), "maxCount": sel.get("maxCount"),
                    "forced": sel.get("minCount") not in (0, None),
                    "low_deck": dc <= LOW_DECK_BAND,
                })
            if ctx == CTX_DRAWCOUNT and isinstance(dc, int):
                drawcount_decisions.append({
                    "turn": turn, "deck": dc,
                    "minCount": sel.get("minCount"), "maxCount": sel.get("maxCount"),
                    "low_deck": dc <= LOW_DECK_BAND,
                })
            if ctx == CTX_MAIN and isinstance(dc, int) and dc <= LOW_DECK_BAND:
                held = sorted(set(hand) & DRAW_SEARCH_TRAINERS)
                if held:
                    draw_search_trainer_in_hand_low.append({
                        "turn": turn, "deck": dc,
                        "trainers": [{"id": c, "name": _name(c)} for c in held],
                    })

    # ---- final state ----------------------------------------------------
    fo = replay.final_observation(seat)
    me_f = fo["current"]["players"][fo["current"]["yourIndex"]] if fo else {}
    fa = _ids(me_f.get("active"))
    fb = _ids(me_f.get("bench"))
    fh = _ids(me_f.get("hand"))
    fd = _ids(me_f.get("discard"))
    fdeck = me_f.get("deckCount")
    our_prize_left = _prize_remaining(me_f)
    opp_f = None
    if opp_seat is not None:
        ofo = replay.final_observation(opp_seat)
        if ofo:
            opp_f = ofo["current"]["players"][ofo["current"]["yourIndex"]]
    opp_prize_left = _prize_remaining(opp_f) if opp_f else (
        opp_prize_by_turn[-1]["remaining"] if opp_prize_by_turn else None)
    opp_deck = opp_f.get("deckCount") if isinstance(opp_f, dict) else None
    opp_board = (_ids(opp_f.get("active")) + _ids(opp_f.get("bench"))) if isinstance(opp_f, dict) else []

    board_healthy_at_end = len(fa) >= 1 and len(fb) >= 1
    mega_ko_inferred = mega_active_ever and (MEGA in fd)

    # prize swing for/against us (remaining drops from 6).
    opp_remaining_vals = [p["remaining"] for p in opp_prize_by_turn if isinstance(p.get("remaining"), int) and p["remaining"] > 0]
    our_remaining_vals = [p["remaining"] for p in our_prize_by_turn if isinstance(p.get("remaining"), int) and p["remaining"] > 0]
    opp_prizes_taken_observed = (6 - min(opp_remaining_vals)) if opp_remaining_vals else None  # WE took
    our_prizes_taken_observed = (6 - min(our_remaining_vals)) if our_remaining_vals else None  # ... this is OUR remaining (= they took from us is wrong)
    # NOTE on semantics: a player's own ``prize`` remaining decreases as THAT
    # player takes prizes. So OUR remaining shrinking == WE took; OPP remaining
    # shrinking == OPP took.
    we_took = (6 - min(our_remaining_vals)) if our_remaining_vals else None
    opp_took = (6 - min(opp_remaining_vals)) if opp_remaining_vals else None

    # ---- loss / win condition ------------------------------------------
    loss_condition = None
    if result == "loss":
        if fdeck == 0:
            loss_condition = "deckout"
        elif len(fa) == 0 and len(fb) == 0:
            loss_condition = "no_pokemon_in_play"
        elif status in (None, "DONE"):
            # board present + deck > 0 + game DONE => opponent closed on prizes
            loss_condition = "prize_loss"
        else:
            loss_condition = "timeout" if status not in (None, "DONE") else "unknown"

    # positive-control honesty: was the WIN an aggression/prize win or did the
    # opponent run out of deck?
    win_via_opponent_deckout = None
    win_via_prizes = None
    if result == "win":
        win_via_prizes = (our_prize_left == 0)
        win_via_opponent_deckout = bool(
            our_prize_left and our_prize_left > 0 and isinstance(opp_deck, int) and opp_deck <= 3)

    # ---- seam-specific signals -----------------------------------------
    # prize-liability (Fighting/Mega-Lucario tempo)
    backup_attacker_available = (KYOGRE in (fa + fb)) or (KYOGRE in fh)
    could_avoid_mega_exposure = backup_attacker_available  # had a non-Mega attacker option
    opp_has_ex_or_mega_on_board = any(c in opp_board for c in (678,)) or len(opp_board) >= 4

    # deckout
    forced_search_low_deck = [s for s in search_decisions if s["low_deck"] and s["forced"]]
    min_deck = min((d["deck"] for d in deck_by_turn), default=None)

    rec_out = {
        "episode": ep,
        "seam": seam,
        "present": True,
        "agents": agents,
        "rewards": rewards,
        "analyzed_seat": seat,
        "is_self_mirror": is_mirror,
        "attribution": attribution,
        "attribution_confidence": confidence,
        "candidate_id": "league_water_anti_disruption_pivot_v1" if seat in pivot_seats else None,
        "opponent": agents[opp_seat] if (opp_seat is not None and not is_mirror) else ("self_mirror" if is_mirror else None),
        "opponent_board_ids": opp_board,
        "opponent_board_names": [_name(c) for c in opp_board],
        "opponent_deck_count": opp_deck,
        "result": result,
        "status": status,
        "num_steps": replay.num_steps,
        "turns_observed": max((d["turn"] for d in deck_by_turn), default=None),
        "loss_condition": loss_condition,
        # final board
        "final_active_ids": fa, "final_active_names": [_name(c) for c in fa],
        "final_bench_ids": fb, "final_bench_count": len(fb),
        "final_hand_ids": fh, "final_discard_has_mega": MEGA in fd,
        "final_deck_count": fdeck,
        "board_healthy_at_end": board_healthy_at_end,
        # prize state (remaining; you win at 0)
        "our_prize_remaining": our_prize_left,
        "opp_prize_remaining": opp_prize_left,
        "we_took_prizes_observed": we_took,
        "opp_took_prizes_observed": opp_took,
        # mega exposure / KO
        "mega_active_ever": mega_active_ever,
        "mega_bench_ever": mega_bench_ever,
        "snover_bench_ever": snover_bench_ever,
        "mega_ko_inferred": mega_ko_inferred,
        "mega_multi_prize_swing_inferred": bool(mega_ko_inferred and (opp_took or 0) >= 2),
        "backup_attacker_available": backup_attacker_available,
        "could_avoid_mega_exposure_inferred": could_avoid_mega_exposure,
        "opp_high_damage_threat_on_board_inferred": opp_has_ex_or_mega_on_board,
        # deckout trajectory
        "min_deck_count": min_deck,
        "deck_by_turn": deck_by_turn,
        "search_decisions_total": len(search_decisions),
        "search_decisions_low_deck": len(forced_search_low_deck),
        "search_decisions_low_deck_decks": [s["deck"] for s in forced_search_low_deck],
        "ctx7_forced_no_decline": all(s["forced"] for s in search_decisions) if search_decisions else None,
        "drawcount_decisions_total": len(drawcount_decisions),
        "drawcount_decisions_low_deck": len([d for d in drawcount_decisions if d["low_deck"]]),
        "draw_search_trainer_in_hand_at_low_deck": draw_search_trainer_in_hand_low,
        # positive control
        "win_via_prizes": win_via_prizes,
        "win_via_opponent_deckout_inferred": win_via_opponent_deckout,
    }
    return rec_out


def build_windows(records: list[dict]) -> list[dict]:
    """Decision windows for Part H decision-replay, grounded per seam."""
    windows = []
    for r in records:
        if not r.get("present"):
            continue
        ep = r["episode"]
        seat = r["analyzed_seat"]
        if r["seam"].startswith("fighting"):
            windows.append({
                "episode_id": ep, "analyzed_seat": seat, "seam": "prize_liability",
                "window": "mega_exposure_tempo",
                "description": "Mega Abomasnow ex active/exposed while opponent ran a "
                               "Mega-Lucario ex line; opp took a multi-prize swing.",
                "evidence": {
                    "mega_ko_inferred": r["mega_ko_inferred"],
                    "opp_took_prizes_observed": r["opp_took_prizes_observed"],
                    "we_took_prizes_observed": r["we_took_prizes_observed"],
                    "backup_attacker_available": r["backup_attacker_available"],
                    "board_healthy_at_end": r["board_healthy_at_end"],
                    "loss_condition": r["loss_condition"],
                },
                "expected_behavior": "Prefer the backup Basic (Kyogre) attacker / avoid "
                                     "exposing Mega ex when behind on prizes and a high-damage "
                                     "threat is online; do not orphan Mega without Snover.",
            })
        if r["seam"].startswith("mirror"):
            windows.append({
                "episode_id": ep, "analyzed_seat": seat, "seam": "deckout",
                "window": "low_deck_optional_search",
                "description": "Repeated forced searches at low deck during a grind; we "
                               "decked out with a full healthy board while ahead on prizes.",
                "evidence": {
                    "min_deck_count": r["min_deck_count"],
                    "search_decisions_total": r["search_decisions_total"],
                    "search_decisions_low_deck_decks": r["search_decisions_low_deck_decks"],
                    "ctx7_forced_no_decline": r["ctx7_forced_no_decline"],
                    "draw_search_trainer_in_hand_at_low_deck": r["draw_search_trainer_in_hand_at_low_deck"],
                    "loss_condition": r["loss_condition"],
                },
                "expected_behavior": "At LOW deck, decline to PLAY optional draw/search "
                                     "trainers at the Main phase (ctx0) — the ctx7 resolution "
                                     "itself is forced (minCount=1) and cannot be declined.",
            })
        if r["seam"].startswith("psychic"):
            windows.append({
                "episode_id": ep, "analyzed_seat": seat, "seam": "positive_control",
                "window": "healthy_deck_pressure",
                "description": "WIN, but via opponent deckout while we were prize-behind "
                               "(6 remaining) with a HEALTHY deck and Kyogre active.",
                "evidence": {
                    "win_via_prizes": r["win_via_prizes"],
                    "win_via_opponent_deckout_inferred": r["win_via_opponent_deckout_inferred"],
                    "our_prize_remaining": r["our_prize_remaining"],
                    "opp_prize_remaining": r["opp_prize_remaining"],
                    "final_deck_count": r["final_deck_count"],
                    "opponent_deck_count": r["opponent_deck_count"],
                },
                "expected_behavior": "Deck was HEALTHY (no low-deck state) — a deckout guard "
                                     "must NOT clamp draw/search here. Maintain normal play.",
            })
    return windows


def main() -> int:
    records = [analyze(ep, seam) for ep, seam in EPISODES.items()]
    windows = build_windows(records)

    summary = {
        "schema": "activegraph.pass25.loss_seam_analysis/v1",
        "pass": 25, "part": "C", "no_upload": True,
        "candidate_under_hardening": "league_water_anti_disruption_pivot_v1",
        "episodes": list(EPISODES.keys()),
        "proven_constraints": {
            "prize_field": "face-down REMAINING prizes; a player wins when their own remaining hits 0",
            "ctx7_search_low_deck_forced": "minCount==maxCount==1 at low deck -> NO legal decline; "
                                           "the only conservation lever is declining the optional "
                                           "Main-phase (ctx0) play of a draw/search trainer",
            "ctx38_drawcount_grounding": "ctx38 appears ~1x across all 3 games -> a draw-count clamp "
                                         "has essentially no replay grounding this pass",
        },
        "seam_findings": {
            "fighting_mega_lucario_prize_liability": {
                "episode": "80623232",
                "loss_condition": records[0].get("loss_condition"),
                "mega_ko_inferred": records[0].get("mega_ko_inferred"),
                "we_took_prizes_observed": records[0].get("we_took_prizes_observed"),
                "opp_took_prizes_observed": records[0].get("opp_took_prizes_observed"),
                "note": "0-prize blowout: we KO'd nothing while Mega ex was KO'd into a "
                        "multi-prize swing vs a Mega-Lucario ex line.",
            },
            "mirror_grind_deckout": {
                "episode": "80622626",
                "loss_condition": records[2].get("loss_condition"),
                "min_deck_count": records[2].get("min_deck_count"),
                "search_decisions_low_deck_decks": records[2].get("search_decisions_low_deck_decks"),
                "note": "Decked out with a full healthy bench while ahead on prizes; "
                        "forced searches kept firing at very low deck.",
            },
            "psychic_positive_control": {
                "episode": "80622745",
                "result": records[1].get("result"),
                "win_via_opponent_deckout_inferred": records[1].get("win_via_opponent_deckout_inferred"),
                "note": "HONEST REFRAME: this WIN was an opponent deckout while we were "
                        "prize-behind (6 remaining) with a healthy deck — NOT a clean "
                        "aggression win. Reinforces: a deckout guard must fire only at LOW deck.",
            },
        },
        "per_game": records,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for w in windows:
            f.write(json.dumps(w) + "\n")

    # markdown
    L = ["# Pass 25 — Loss-seam diagnostics (Part C)", "",
         "> Read-only. Board / select / prize state is ground truth; card *effects* are "
         "not inferred. `prize` = face-down REMAINING prizes (win at 0).", "",
         "## Proven constraints", ""]
    for k, v in summary["proven_constraints"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    L.append("## Per-game")
    for r in records:
        if not r.get("present"):
            L.append(f"\n### {r['episode']} — ABSENT")
            continue
        L += [
            f"\n### {r['episode']} — {r['seam']} — seat {r['analyzed_seat']} "
            f"**{r['result'].upper()}** ({r.get('loss_condition') or 'n/a'})",
            f"- attribution: `{r['attribution']}` ({r['attribution_confidence']}); "
            f"opponent: {r['opponent']}",
            f"- opp board: {r['opponent_board_names']}",
            f"- final: active={r['final_active_names']} bench={r['final_bench_count']} "
            f"deck={r['final_deck_count']} (healthy_at_end={r['board_healthy_at_end']})",
            f"- prizes remaining: ours={r['our_prize_remaining']} opp={r['opp_prize_remaining']} "
            f"(we_took≈{r['we_took_prizes_observed']}, opp_took≈{r['opp_took_prizes_observed']})",
            f"- Mega: active_ever={r['mega_active_ever']} ko_inferred={r['mega_ko_inferred']} "
            f"multi_prize_swing={r['mega_multi_prize_swing_inferred']} "
            f"backup_attacker={r['backup_attacker_available']}",
            f"- deck: min={r['min_deck_count']} searches={r['search_decisions_total']} "
            f"(low-deck forced at decks {r['search_decisions_low_deck_decks']}) "
            f"ctx7_forced_no_decline={r['ctx7_forced_no_decline']} "
            f"ctx38_total={r['drawcount_decisions_total']}",
            f"- positive-control: win_via_prizes={r['win_via_prizes']} "
            f"win_via_opp_deckout={r['win_via_opponent_deckout_inferred']}",
        ]
    L.append("")
    L.append(f"## Decision windows: {len(windows)} (see pass25_loss_windows.jsonl)")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    for r in records:
        if r.get("present"):
            print(f"{r['episode']}: {r['result']} {r.get('loss_condition')} "
                  f"min_deck={r['min_deck_count']} mega_ko={r['mega_ko_inferred']} "
                  f"low_deck_searches={r['search_decisions_low_deck_decks']}")
    print(f"windows={len(windows)} -> {OUT_JSONL.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
