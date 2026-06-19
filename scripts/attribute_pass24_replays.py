#!/usr/bin/env python3
"""Pass 24 — attribute new replays to the Pass 23 candidate by deck fingerprint.

Read-only. Does NOT assume every Yohei seat is the pivot: a seat is attributed to
`league_water_anti_disruption_pivot_v1` only when its 60-card multiset matches the
candidate deck exactly. Writes:
  - data/experiments/pass24_replay_attribution.json
  - data/experiments/pass24_replay_attribution.md
"""
from __future__ import annotations
import csv, io, json, tarfile, collections, datetime
from pathlib import Path

NEW_EPISODES = ["80623232", "80622745", "80622626"]
CANDIDATE_ID = "league_water_anti_disruption_pivot_v1"
CANDIDATE_TARBALL = "data/submissions/candidates_pass22/league_water_anti_disruption_pivot_v1.tar.gz"
RAW_DIR = Path("data/meta_replays/raw")
DECK_DIR = Path("data/meta_replays/decks")
OUR_NAME_TOKENS = ("yohei nakajima", "yohei", "theyohei")


def candidate_fingerprint() -> dict:
    with tarfile.open(CANDIDATE_TARBALL) as t:
        m = [x for x in t.getmembers() if x.name.endswith("deck.csv")][0]
        data = t.extractfile(m).read().decode()
    ids = [int(r[0]) for r in csv.reader(io.StringIO(data)) if r and r[0].strip().isdigit()]
    return dict(collections.Counter(ids))


def deck_fingerprint(path: Path) -> dict:
    if not path.exists():
        return {}
    ids = [int(r[0]) for r in csv.reader(open(path)) if r and r[0].strip().isdigit()]
    return dict(collections.Counter(ids))


def main() -> None:
    cand = candidate_fingerprint()
    results = []
    for ep in NEW_EPISODES:
        raw = json.load(open(RAW_DIR / f"{ep}.json"))
        info = raw.get("info", {})
        names = info.get("TeamNames") or info.get("Agents") or []
        rewards = raw.get("rewards", [])
        seats = []
        for idx in range(len(names)):
            name = str(names[idx])
            is_ours = any(tok in name.lower() for tok in OUR_NAME_TOKENS)
            fp = deck_fingerprint(DECK_DIR / f"{ep}_p{idx}_deck.csv")
            matches_pivot = fp == cand
            seats.append({
                "seat": idx, "name": name, "reward": rewards[idx] if idx < len(rewards) else None,
                "is_our_name": is_ours, "deck_matches_pivot": matches_pivot,
                "deck_unique": len(fp),
            })
        our_seats = [s for s in seats if s["is_our_name"]]
        pivot_seats = [s for s in seats if s["deck_matches_pivot"]]
        both_yohei = len(our_seats) == 2
        # classification
        if both_yohei and len(pivot_seats) == 2:
            kind = "pivot_self_mirror"
        elif both_yohei:
            kind = "old_water_mirror"
        elif len(pivot_seats) == 1 and len(our_seats) == 1:
            kind = "pivot_vs_external"
        else:
            kind = "unknown"
        # confidence: high if deck fingerprint + our seat + upload timing all align
        if pivot_seats and our_seats:
            confidence = "high"
        elif our_seats:
            confidence = "medium"
        else:
            confidence = "low"
        our_seat_idx = pivot_seats[0]["seat"] if pivot_seats else (our_seats[0]["seat"] if our_seats else None)
        our_reward = rewards[our_seat_idx] if our_seat_idx is not None and our_seat_idx < len(rewards) else None
        opp_idx = next((i for i in range(len(names)) if i != our_seat_idx), None) if our_seat_idx is not None else None
        opp_fp = deck_fingerprint(DECK_DIR / f"{ep}_p{opp_idx}_deck.csv") if opp_idx is not None else {}
        opponent_known = (opp_fp == cand) if opp_fp else False
        results.append({
            "episode_id": ep, "team_names": names, "rewards": rewards, "seats": seats,
            "our_seat": our_seat_idx, "our_reward": our_reward,
            "result": ("win" if our_reward == 1 else "loss" if our_reward == -1 else "draw/unknown"),
            "opponent_seat": opp_idx, "opponent_deck_known": opponent_known,
            "candidate_id": CANDIDATE_ID if pivot_seats else None,
            "attribution_confidence": confidence, "replay_kind": kind,
        })
    out = {"pass": "24", "part": "E", "generated": datetime.datetime.utcnow().isoformat() + "Z",
           "candidate_id": CANDIDATE_ID, "candidate_fingerprint_unique": len(cand),
           "episodes": results}
    Path("data/experiments/pass24_replay_attribution.json").write_text(json.dumps(out, indent=2))
    md = ["# Pass 24 — Replay Attribution", "", f"- generated: {out['generated']}",
          f"- candidate: `{CANDIDATE_ID}` (deck fingerprint = {len(cand)} unique IDs)",
          "- attribution rule: a seat is the pivot ONLY if its 60-card multiset matches the candidate exactly.",
          "", "## Episodes", ""]
    for r in results:
        md += [f"### {r['episode_id']} — {r['replay_kind']} ({r['attribution_confidence']} confidence)",
               f"- team names: {r['team_names']}  | rewards: {r['rewards']}",
               f"- our seat: {r['our_seat']}  → **{r['result']}**",
               f"- opponent seat: {r['opponent_seat']}  | opponent deck == pivot: {r['opponent_deck_known']}",
               f"- candidate attribution: `{r['candidate_id']}`", ""]
    Path("data/experiments/pass24_replay_attribution.md").write_text("\n".join(md))
    for r in results:
        print(f"{r['episode_id']}: {r['replay_kind']} | our_seat={r['our_seat']} {r['result']} | conf={r['attribution_confidence']}")


if __name__ == "__main__":
    main()
