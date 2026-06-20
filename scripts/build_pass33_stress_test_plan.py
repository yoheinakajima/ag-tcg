#!/usr/bin/env python3
"""Pass 33 (Part D) — stress-test deck set selection. LOCAL / no upload.

Selects the 8-12 candidate decks that enter the Pass 33 composition stress test
and records, per candidate, whether it is reused as-is (`existing_reuse`), built
as a new composition variant (`build_variant`), or excluded/blocked. Rationale is
grounded in the Part C composition audit (Basic density / opening no-Basic
probability) and the Part B fresh live read (read-only Kaggle scores).

No deck is built here; this only writes the plan that Part E consumes. Durant is
listed but stays blocked_from_league (it needs a special pilot; reused decks run
the generic core pilot) — it is smoke-tested for honesty in Part F, never league
eligible unless that smoke is clean.

Writes data/experiments/pass33_stress_test_plan.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
AUDIT = EXP / "pass33_deck_composition_audit.json"
LIVE = EXP / "pass33_live_score_status.json"
SUB = REPO / "data" / "submissions"

OUT_JSON = EXP / "pass33_stress_test_plan.json"
OUT_MD = EXP / "pass33_stress_test_plan.md"

# Reused decks (run the generic core pilot, deck unchanged). Each must be a
# valid 60-card deck already in the portfolio.
REUSE = [
    ("league_water_anti_disruption_pivot_v1", "water",
     "Current Water family best (fresh live 340.0); composition baseline whose "
     "8-Basic / 34.6% opening no-Basic risk this stress test probes."),
    ("league_water_core_reference", "water",
     "Water portfolio reference (live 219.5); low ceiling but a stable control "
     "for composition-vs-result correlation."),
    ("core_pilot_water_v2_runtime", "water",
     "Water core-pilot runtime sibling; same Basic-light shell, isolates pilot "
     "vs deck composition."),
    ("league_dragapult_v1_search_only", "dragapult",
     "Dragapult family best (fresh live 306.7, BELOW Water 340 — contradicts the "
     "prior claimed 357.3); 6-Basic / 45.9% no-Basic, a key fragility data point."),
    ("league_dragapult_spread", "dragapult",
     "Dragapult spread parent; parent/child confirmation anchor and high "
     "evolution-complexity (Stage 2 line) composition sample."),
    ("league_mega_charizard_x_burst", "charizard",
     "High-ceiling Mega burst archetype; 6-Basic / 45.9% no-Basic + heavy "
     "energy, a deckout-leaning composition sample."),
    ("league_mega_venusaur_tank", "venusaur",
     "Mega tank; worst-tier Basic density (4 Basics / 60.1% no-Basic) — the "
     "extreme fragility end of the stress test."),
    ("effect_loop_exit_guard_v1", "venusaur",
     "Venusaur-family loop/exit-guard reuse; same 4-Basic shell, tests whether "
     "the guard changes composition fragility outcomes."),
    ("league_mega_gardevoir_psychic_ramp", "gardevoir",
     "Psychic ramp; 4-Basic / 60.1% no-Basic, high evolution complexity — "
     "fragility + pilot-complexity sample."),
    ("league_raging_bolt_ogerpon", "raging_bolt",
     "Raging Bolt control; all-Basic-attacker (no evolution) 8-Basic shell, a "
     "structurally different composition for correlation contrast."),
]

# New composition variants built in Part E. Only buildable because verified
# cabt-legal, Water-compatible Basic Pokémon exist (Mantine #720 searches out
# Basics; Alomomola #505 consistency wall) — confirmed by a real cabt game.
BUILD = [
    ("water_basic_density_v1", "water", "league_water_anti_disruption_pivot_v1",
     {"remove": {3: 4}, "add": {720: 4}},
     "Moderate Basic-density bump: -4 Basic {W} Energy, +4 Mantine (#720, Water "
     "Basic, ability fetches 2 Basics). Basics 8->12, opening no-Basic "
     "0.346->~0.191. Core (Kyogre 721, Snover 722, Mega Abomasnow ex 723, Ultra "
     "Ball 1121) untouched."),
    ("water_basic_density_v2", "water", "league_water_anti_disruption_pivot_v1",
     {"remove": {3: 8}, "add": {720: 4, 505: 4}},
     "Aggressive Basic-density bump: -8 Basic {W} Energy, +4 Mantine (#720), +4 "
     "Alomomola (#505, Water Basic consistency). Basics 8->16, opening no-Basic "
     "0.346->~0.099. Core untouched; tests whether density gains trade off "
     "attacker energy."),
]

# Listed for honesty but never league-eligible from a reused tarball.
BLOCKED = [
    ("league_durant_deckout_carousel", "durant",
     "Durant deck-out carousel needs a special pilot; reused decks run the "
     "generic core pilot, under which Durant has historically smoked INVALID. "
     "Smoke-tested in Part F for honesty; stays blocked_from_league unless that "
     "smoke is clean."),
]


def _canonical(cid: str):
    found = sorted(SUB.glob(f"candidates_pass*/{cid}.tar.gz"))
    return found[-1] if found else None


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    by_id = {d["candidate_id"]: d for d in audit["decks"]}
    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}

    def audit_slice(cid):
        d = by_id.get(cid, {})
        return {k: d.get(k) for k in (
            "valid_60", "basic_pokemon", "non_basic_pokemon", "evolution_count",
            "energy_total", "opening_no_basic_probability",
            "evolution_complexity_score", "pilot_complexity_score",
            "no_pokemon_loss_risk", "deckout_risk", "previous_kaggle_score")}

    selected = []
    for cid, fam, why in REUSE:
        src = _canonical(cid)
        a = by_id.get(cid, {})
        selected.append({
            "candidate_id": cid, "family": fam, "disposition": "existing_reuse",
            "source_tarball": str(src.relative_to(REPO)) if src else None,
            "available": bool(src) and a.get("valid_60", False),
            "rationale": why, "audit": audit_slice(cid),
            "blocked_from_league": False,
        })
    for cid, fam, parent, delta, why in BUILD:
        psrc = _canonical(parent)
        pa = by_id.get(parent, {})
        base = pa.get("basic_pokemon")
        added = sum(delta["add"].values())
        selected.append({
            "candidate_id": cid, "family": fam, "disposition": "build_variant",
            "parent_id": parent,
            "parent_tarball": str(psrc.relative_to(REPO)) if psrc else None,
            "available": bool(psrc) and pa.get("valid_60", False),
            "deck_delta": {"remove": delta["remove"], "add": delta["add"]},
            "projected_basic_pokemon": (base + added) if base is not None else None,
            "rationale": why, "parent_audit": audit_slice(parent),
            "blocked_from_league": False,
        })
    for cid, fam, why in BLOCKED:
        src = _canonical(cid)
        selected.append({
            "candidate_id": cid, "family": fam, "disposition": "blocked",
            "source_tarball": str(src.relative_to(REPO)) if src else None,
            "available": bool(src), "rationale": why,
            "audit": audit_slice(cid), "blocked_from_league": True,
        })

    eligible = [s for s in selected if s["disposition"] in
                ("existing_reuse", "build_variant")]
    out = {
        "pass": "33", "part": "D", "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "selection_count_eligible": len(eligible),
        "selection_count_total": len(selected),
        "within_8_to_12": 8 <= len(eligible) <= 12,
        "live_read_summary": {
            "leader": live.get("leader"),
            "water_family_current_best": live.get("water_family_current_best"),
            "dragapult_family_best": live.get("dragapult_family_best"),
            "dragapult_above_water": live.get("dragapult_above_water"),
        },
        "selection_rules": [
            "Include each family's current best plus a structural-contrast deck.",
            "Span the full Basic-density spectrum found in Part C (4..16 Basics).",
            "Build composition variants only where a verified, cabt-legal, "
            "Water-compatible Basic exists (Mantine #720, Alomomola #505).",
            "Exclude invalid decks and opponent clones (none present).",
            "Durant stays blocked_from_league; smoke-tested for honesty only.",
        ],
        "candidates": selected,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 33 — Stress-Test Deck Set Selection (Part D)", "",
         "> LOCAL / no upload. Not a leaderboard. Rationale grounded in the Part C "
         "composition audit and the Part B fresh read-only live read.", "",
         f"- eligible candidates: **{len(eligible)}** "
         f"(within 8-12: **{out['within_8_to_12']}**); total listed "
         f"{len(selected)}",
         f"- live read: leader **{(live.get('leader') or {}).get('publicScore')}**, "
         f"Water best **{(live.get('water_family_current_best') or {}).get('publicScore')}**, "
         f"Dragapult best **{(live.get('dragapult_family_best') or {}).get('publicScore')}**, "
         f"dragapult_above_water **{live.get('dragapult_above_water')}**", "",
         "| candidate | family | disposition | Basics | no-Basic P | NPL | "
         "Kaggle | note |", "|---|---|---|---|---|---|---|---|"]
    for s in selected:
        a = s.get("audit") or s.get("parent_audit") or {}
        basics = (s.get("projected_basic_pokemon")
                  if s["disposition"] == "build_variant" else a.get("basic_pokemon"))
        nb = a.get("opening_no_basic_probability")
        L.append(f"| {s['candidate_id']} | {s['family']} | {s['disposition']} | "
                 f"{basics} | {nb} | {a.get('no_pokemon_loss_risk')} | "
                 f"{a.get('previous_kaggle_score')} | "
                 f"{s['rationale'][:80].replace(chr(10),' ')}… |")
    L += ["", "## Selection rules"] + [f"- {r}" for r in out["selection_rules"]]
    L += ["", "## Build variants (Part E)"]
    for cid, fam, parent, delta, why in BUILD:
        L.append(f"- **{cid}** (parent {parent}): remove {delta['remove']}, add "
                 f"{delta['add']} — {why}")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"selected {len(eligible)} eligible (+{len(BLOCKED)} blocked); "
          f"within 8-12: {out['within_8_to_12']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
