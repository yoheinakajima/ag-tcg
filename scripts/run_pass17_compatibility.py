#!/usr/bin/env python3
"""Pass 17 (Part H) -- deck / pilot compatibility analysis.

LOCAL ONLY. Combines the internal-league outcomes (Part G), the candidate
validation/smoke results (Part F), and the documented per-deck gaps (the
playbooks' unsafe_or_deferred / special-trigger sections) into one honest
deck/pilot compatibility report: for each deck, does the SINGLE generic core
pilot fit it, partly fit it, or fail to pilot it, and WHY.

Ratings (data-driven, then annotated with documented gaps):
  good          -- runs clean AND adj win rate >= 0.55
  partial       -- runs clean AND 0.20 <= adj win rate < 0.55
  poor          -- runs clean (legal) but adj win rate < 0.20
  incompatible  -- cannot even play a legal game (live smoke INVALID) / blocked

Writes data/experiments/pass17_deck_pilot_compatibility.{json,md}. No upload.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
LEAGUE = EXP / "pass17_internal_league.json"
RANKINGS = EXP / "pass17_league_rankings.json"
VALIDATION = EXP / "pass17_candidate_validation.json"
DECK_IDEAS = REPO / "experiments" / "deck_ideas.yaml"

# Qualitative pilot-fit notes per deck archetype. These are interpretations of
# the data + the documented playbook gaps -- never invented metrics.
FINDINGS = {
    "league_water_core_reference": {
        "archetype": "tempo + evolution payoff",
        "pilot_fit": [
            "The generic pilot was tuned around this line, so it sets up Snover, "
            "evolves Mega Abomasnow ex, and pressures with Kyogre coherently.",
            "Strongest internal win rate; the reference the others are measured against.",
        ],
        "gaps": [],
    },
    "league_dragapult_spread": {
        "archetype": "Stage-2 evolution control",
        "pilot_fit": [
            "The pilot builds the Dreepy->Drakloak->Dragapult ex line well enough "
            "to win the majority of games -- evolution sequencing transfers from "
            "the Water reference's evolution handling.",
            "Competitive vs the Water reference and beats the historical anchor.",
        ],
        "gaps": [
            "Spread-damage placement (Phantom Dive distribution) is NOT modeled; "
            "the pilot attacks but does not optimize bench damage spreading.",
            "Rare Candy / Dusknoir timing is left to the base policy.",
        ],
    },
    "league_raging_bolt_ogerpon": {
        "archetype": "fast basic aggro",
        "pilot_fit": [
            "Plays every game to a legal finish (no invalids/timeouts) but wins "
            "ZERO games -- the generic pilot cannot execute the aggro plan.",
            "Likely causes: it does not color-match energy onto the intended "
            "attacker and does not prioritize early attach+attack, so Raging Bolt "
            "ex's discard-scaling attack never comes online before it is out-raced.",
        ],
        "gaps": [
            "No energy color matching (generic attach).",
            "No 'attack as early as possible' aggression bias.",
            "Raging Bolt ex's discard-Basic-Energy damage scaling is not exploited.",
        ],
    },
    "league_durant_deckout_carousel": {
        "archetype": "deck-out / mill chaos",
        "pilot_fit": [
            "Blocked from the league by design AND empirically fails a live "
            "self-mirror smoke (one seat INVALID): the generic pilot produces an "
            "illegal play sequence with this deck and has no mill win condition.",
        ],
        "gaps": [
            "Entire deckout/mill win condition is unimplemented in the generic pilot.",
            "Would race prizes with Durant ex instead of keeping it back to mill.",
        ],
    },
}


def _rate(ran_clean: bool, blocked: bool, awr) -> str:
    if blocked or not ran_clean:
        return "incompatible"
    if awr is None:
        return "unknown"
    if awr >= 0.55:
        return "good"
    if awr >= 0.20:
        return "partial"
    return "poor"


def build() -> dict:
    league = json.loads(LEAGUE.read_text(encoding="utf-8")) if LEAGUE.exists() else {}
    rankings = json.loads(RANKINGS.read_text(encoding="utf-8")) if RANKINGS.exists() else {}
    validation = json.loads(VALIDATION.read_text(encoding="utf-8")) if VALIDATION.exists() else {}
    ideas = yaml.safe_load(DECK_IDEAS.read_text(encoding="utf-8")) or {}

    stand = {r["id"]: r for r in rankings.get("standings", [])}
    valid = {r["candidate_id"]: r for r in validation.get("candidates", [])}

    # aggregate per-deck legality across league matchups
    legal_agg: dict[str, dict] = {}
    for m in league.get("matchups", []):
        for who in (m["a"], m["b"]):
            d = legal_agg.setdefault(who, {"invalids": 0, "timeouts": 0,
                                           "crashes": 0, "steps": [], "n": 0})
            d["invalids"] += m["invalids"]; d["timeouts"] += m["timeouts"]
            d["crashes"] += m["crashes"]; d["n"] += m["n_games"]
            if m.get("avg_steps") is not None:
                d["steps"].append(m["avg_steps"])

    decks = ideas.get("decks") or {}
    results = []
    for key, spec in decks.items():
        cid = spec["candidate_id"]
        blocked = bool(spec.get("blocked_from_league"))
        v = valid.get(cid, {})
        s = stand.get(cid, {})
        la = legal_agg.get(cid, {})
        ran_in_league = cid in stand
        smoke_self = v.get("live_smoke_self", {})
        ran_clean = (
            not blocked
            and bool(smoke_self.get("ok"))
            and la.get("invalids", 0) == 0
            and la.get("timeouts", 0) == 0
            and la.get("crashes", 0) == 0
        )
        awr = s.get("adj_win_rate")
        rating = _rate(ran_clean, blocked, awr if ran_in_league else None)
        f = FINDINGS.get(cid, {})
        avg_steps = (round(sum(la["steps"]) / len(la["steps"]), 1)
                     if la.get("steps") else None)
        results.append({
            "deck_key": key,
            "candidate_id": cid,
            "archetype": f.get("archetype"),
            "in_league": ran_in_league,
            "blocked_from_league": blocked,
            "block_reason": spec.get("block_reason"),
            "adj_win_rate": awr,
            "wilson": s.get("wilson"),
            "record": (f"{s.get('wins')}-{s.get('losses')}-{s.get('draws')}"
                       if ran_in_league else None),
            "ran_clean": ran_clean,
            "invalids": la.get("invalids"),
            "timeouts": la.get("timeouts"),
            "crashes": la.get("crashes"),
            "avg_game_steps": avg_steps,
            "live_smoke_self_ok": smoke_self.get("ok"),
            "compatibility_rating": rating,
            "pilot_fit": f.get("pilot_fit", []),
            "gaps": f.get("gaps", []),
        })

    order = {"good": 0, "partial": 1, "poor": 2, "incompatible": 3, "unknown": 4}
    results.sort(key=lambda r: (order.get(r["compatibility_rating"], 9),
                                -(r["adj_win_rate"] or 0)))
    return {
        "pass": "17", "part": "H", "local_only": True,
        "disclaimer": league.get("disclaimer"),
        "decks": results,
        "summary": {
            "good": [r["candidate_id"] for r in results if r["compatibility_rating"] == "good"],
            "partial": [r["candidate_id"] for r in results if r["compatibility_rating"] == "partial"],
            "poor": [r["candidate_id"] for r in results if r["compatibility_rating"] == "poor"],
            "incompatible": [r["candidate_id"] for r in results if r["compatibility_rating"] == "incompatible"],
        },
    }


def md(rep: dict) -> str:
    L = ["# Pass 17 — deck / pilot compatibility analysis (Part H)", "",
         f"> {rep.get('disclaimer','')}", "",
         "How well does the single generic core pilot fit each deck?", "",
         "| deck | archetype | rating | adj win_rate | record | clean run | avg steps |",
         "|---|---|---|---|---|---|---|"]
    for r in rep["decks"]:
        L.append(f"| {r['candidate_id']} | {r['archetype']} | "
                 f"**{r['compatibility_rating']}** | {r['adj_win_rate']} | "
                 f"{r['record']} | {'✅' if r['ran_clean'] else '❌'} | "
                 f"{r['avg_game_steps']} |")
    for r in rep["decks"]:
        L += ["", f"## {r['candidate_id']} — {r['compatibility_rating']}",
              f"- archetype: {r['archetype']}",
              f"- in league: {r['in_league']}  blocked: {r['blocked_from_league']}",
              f"- adj win rate: {r['adj_win_rate']}  record: {r['record']}  "
              f"95% CI: {r['wilson']}",
              f"- legality: invalids={r['invalids']} timeouts={r['timeouts']} "
              f"crashes={r['crashes']} live-smoke-self ok={r['live_smoke_self_ok']}"]
        if r["block_reason"]:
            L.append(f"- block reason: {r['block_reason'].strip()}")
        if r["pilot_fit"]:
            L += ["- pilot fit:"] + [f"  - {x}" for x in r["pilot_fit"]]
        if r["gaps"]:
            L += ["- compatibility gaps:"] + [f"  - {x}" for x in r["gaps"]]
    s = rep["summary"]
    L += ["", "## Verdict",
          f"- good: {s['good'] or '—'}",
          f"- partial: {s['partial'] or '—'}",
          f"- poor: {s['poor'] or '—'}",
          f"- incompatible: {s['incompatible'] or '—'}", ""]
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    rep = build()
    (EXP / "pass17_deck_pilot_compatibility.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass17_deck_pilot_compatibility.md").write_text(md(rep), encoding="utf-8")
    print("compatibility analysis:")
    for r in rep["decks"]:
        print(f"  {r['candidate_id']}: {r['compatibility_rating']} "
              f"(awr={r['adj_win_rate']} clean={r['ran_clean']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
