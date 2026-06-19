#!/usr/bin/env python3
"""Pass 24 — verify Grok's replay summaries against replay ground truth.

Read-only. Grok is NOT trusted; every claim is checked against the replay's
``rewards`` and ``observation.current`` board state. Writes:
  - data/experiments/pass24_grok_claim_verification.json
  - data/experiments/pass24_grok_claim_verification.md
"""
from __future__ import annotations
import csv, collections, datetime, json, os, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ptcg_activegraph.replays.kaggle_replay import load_replay  # noqa: E402

RAW = REPO / "data" / "meta_replays" / "raw"
DECKS = REPO / "data" / "meta_replays" / "decks"
OUR = "Yohei Nakajima"

# Grok's claims (to be checked, NOT trusted).
GROK = {
    "80623232": {"result": "loss", "turn": 11, "loss_type": "empty-board/no-Pokémon",
                 "opponent": "Fighting ex / Mega Lucario-Hariyama"},
    "80622745": {"result": "win", "turn": 11, "loss_type": "opponent empty-board",
                 "opponent": "Psychic Alakazam/Dudunsparce"},
    "80622626": {"result": "mirror", "turn": 43, "loss_type": "loser empty-board",
                 "opponent": "mirror"},
}


def card_names():
    names = {}
    p = REPO / "data" / "cards" / "EN_Card_Data.csv"
    if p.exists():
        for row in csv.DictReader(open(p)):
            cid = row.get("Card ID")
            if cid and str(cid).strip().isdigit():
                names[int(cid)] = row.get("Card Name")
    return names


def deck_ids(ep, seat):
    p = DECKS / f"{ep}_p{seat}_deck.csv"
    if not p.exists():
        return collections.Counter()
    return collections.Counter(int(r[0]) for r in csv.reader(open(p)) if r and r[0].strip().isdigit())


def lenz(z):
    return len(z) if isinstance(z, list) else 0


def classify_opp(ids, names):
    s = set(ids)
    if {743, 741, 742} & s:  # Alakazam line
        return "psychic_alakazam_dudunsparce" if (66 in s or 305 in s) else "psychic_alakazam"
    if 678 in s:  # Mega Lucario ex
        return "fighting_mega_lucario_ex_hariyama" if (674 in s) else "fighting_mega_lucario_ex"
    return "unknown"


def main():
    names = card_names()
    out = []
    for ep, claim in GROK.items():
        r = load_replay(RAW / f"{ep}.json")
        agents = [a.get("Name") for a in r.info.get("Agents", []) if isinstance(a, dict)]
        rewards = r.rewards
        is_mirror = sum(1 for a in agents if a == OUR) == 2
        our_seat = next((i for i, a in enumerate(agents) if a == OUR), 1)
        opp_seat = 1 - our_seat
        our_reward = rewards[our_seat] if our_seat < len(rewards) else None
        replay_result = "mirror" if is_mirror else ("win" if our_reward == 1 else "loss" if our_reward == -1 else "draw")
        # loser board state (for empty-board claim)
        loser_seat = next((i for i, x in enumerate(rewards) if x is not None and x < 0), None)
        fo = r.final_observation(loser_seat) if loser_seat is not None else None
        cur = fo.get("current") if fo else {}
        replay_turn = cur.get("turn")
        pl = cur.get("players", [])
        loser = pl[loser_seat] if (loser_seat is not None and loser_seat < len(pl)) else {}
        loser_active = lenz(loser.get("active"))
        loser_bench = lenz(loser.get("bench"))
        loser_deck = loser.get("deckCount")
        empty_board = (loser_active <= 1 and loser_bench == 0)
        # actual loss mechanism
        if loser_deck == 0:
            mechanism = "deckout"
        elif empty_board:
            mechanism = "no_pokemon_in_play"
        else:
            mechanism = "prizes_or_tempo_with_board_present"
        opp_ids = deck_ids(ep, opp_seat) if not is_mirror else collections.Counter()
        opp_arch = "mirror" if is_mirror else classify_opp(opp_ids, names)

        result_match = (claim["result"] == replay_result)
        # turn within +/-1 counts as a match (Grok rounds)
        turn_match = (isinstance(replay_turn, int) and abs(replay_turn - claim["turn"]) <= 1)
        empty_claim = "empty" in claim["loss_type"].lower()
        loss_type_match = (empty_claim == empty_board)
        opp_match = (is_mirror and claim["opponent"] == "mirror") or (
            not is_mirror and (
                ("alakazam" in claim["opponent"].lower() and "alakazam" in opp_arch) or
                ("lucario" in claim["opponent"].lower() and "lucario" in opp_arch)
            ))
        disagreements = []
        if not result_match:
            disagreements.append(f"result: grok={claim['result']} replay={replay_result}")
        if not turn_match:
            disagreements.append(f"turn: grok={claim['turn']} replay={replay_turn}")
        if not loss_type_match:
            disagreements.append(f"loss_type: grok claims {'empty-board' if empty_claim else 'non-empty'} but replay shows {'empty-board' if empty_board else f'{mechanism} (active={loser_active}, bench={loser_bench})'}")
        if not opp_match:
            disagreements.append(f"opponent: grok={claim['opponent']} replay_arch={opp_arch}")
        out.append({
            "episode_id": ep,
            "grok": claim,
            "replay": {"result": replay_result, "turn": replay_turn,
                       "loser_seat": loser_seat, "loser_active": loser_active,
                       "loser_bench": loser_bench, "loser_deck": loser_deck,
                       "empty_board": empty_board, "loss_mechanism": mechanism,
                       "opponent_archetype": opp_arch},
            "matched": {"result": result_match, "turn": turn_match,
                        "loss_type": loss_type_match, "opponent": opp_match},
            "disagreements": disagreements,
        })
    doc = {"pass": "24", "part": "F", "generated": datetime.datetime.utcnow().isoformat() + "Z",
           "trust": "replay state is ground truth; Grok is unverified summary",
           "episodes": out}
    (REPO / "data/experiments/pass24_grok_claim_verification.json").write_text(json.dumps(doc, indent=2))
    L = ["# Pass 24 — Grok Claim Verification", "",
         f"- generated: {doc['generated']}",
         "- **Replay state is ground truth. Grok is NOT trusted.**", ""]
    for e in out:
        L += [f"## {e['episode_id']}",
              f"- result: grok=`{e['grok']['result']}` | replay=`{e['replay']['result']}` → {'MATCH' if e['matched']['result'] else 'MISMATCH'}",
              f"- turn: grok=`{e['grok']['turn']}` | replay=`{e['replay']['turn']}` → {'MATCH' if e['matched']['turn'] else 'MISMATCH'}",
              f"- loss type: grok=`{e['grok']['loss_type']}` | replay loser active={e['replay']['loser_active']} bench={e['replay']['loser_bench']} deck={e['replay']['loser_deck']} → mechanism=`{e['replay']['loss_mechanism']}` → {'MATCH' if e['matched']['loss_type'] else 'MISMATCH'}",
              f"- opponent: grok=`{e['grok']['opponent']}` | replay arch=`{e['replay']['opponent_archetype']}` → {'MATCH' if e['matched']['opponent'] else 'MISMATCH'}",
              f"- disagreements: {e['disagreements'] or 'none'}", ""]
    (REPO / "data/experiments/pass24_grok_claim_verification.md").write_text("\n".join(L))
    for e in out:
        print(f"{e['episode_id']}: matched={e['matched']} disagreements={len(e['disagreements'])}")


if __name__ == "__main__":
    main()
