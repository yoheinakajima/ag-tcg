#!/usr/bin/env python3
"""Pass 27 (Part J) — core gameplay gap analysis across the portfolio. LOCAL.

Cross-references the 15 fundamental gameplay competencies against the portfolio
evidence (Part-I league standings, Part-G smoke, Part-D role taxonomy, Part-H
fixtures) to answer the pass's core question: which competencies still fail when
the SAME generic core pilot drives different archetypes.

For each competency it records: which deck exposed it, the concrete evidence,
whether the pilot/taxonomy/runtime-hook support it, an implementation priority,
and whether the gap is deck-agnostic or deck-specific.

Data-driven where possible (league win rates / smoke verdicts are read from the
artifacts); the support/priority judgements are the curated analysis. No upload.
Writes data/experiments/pass27_core_gameplay_gap_analysis.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
FIXDIR = REPO / "data" / "fixtures" / "pass27_portfolio_core"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s.lower()).strip("_")


def _load_fixture_coverage() -> dict:
    """Read the Part-H fixtures and build {competency_slug: [coverage...]}.

    Cross-references the fixture suites mechanically so the gap analysis is
    genuinely tied to the fixtures rather than just citing them.
    """
    coverage: dict[str, list] = {}
    try:
        import yaml  # noqa: PLC0415
        idx = yaml.safe_load((FIXDIR / "index.yaml").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return coverage
    for fam in idx.get("families", []):
        # family-level competency tags
        for comp in fam.get("competencies", []):
            coverage.setdefault(_slug(comp), []).append(
                {"fixture_family": fam["id"], "level": "family"})
        # per-assertion detail from the family plan file
        try:
            data = json.loads((FIXDIR / fam["file"]).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for a in data.get("assertions", []):
            for comp in fam.get("competencies", []):
                coverage.setdefault(_slug(comp), []).append(
                    {"fixture_family": fam["id"], "assertion": a["id"],
                     "executable": a.get("executable", False),
                     "status": a.get("status")})
    return coverage


def main() -> int:
    rankings = _load("pass27_portfolio_rankings.json")
    smoke = _load("pass27_live_smoke.json")
    taxonomy = _load("pass27_role_taxonomy.json")

    wr = {r["id"]: r for r in rankings.get("standings", [])}
    def rate(cid):
        return wr.get(cid, {}).get("adj_win_rate")
    durant_invalid = not smoke.get("results", {}).get(
        "league_durant_deckout_carousel", {}).get("clean", True)

    # 15 competencies (spec Part J order). support flags: pilot / taxonomy / hook.
    comps = [
        {"n": 1, "name": "setup active choice", "deck": "all",
         "evidence": "All league-eligible decks place a legal active and complete games (smoke clean).",
         "pilot": True, "taxonomy": True, "hook": True,
         "priority": "none", "scope": "deck-agnostic", "status": "supported"},
        {"n": 2, "name": "bench development", "deck": "all evolution decks",
         "evidence": f"Evolution decks set up benches and run clean, but ramp/tank lines underperform "
                     f"(gardevoir {rate('league_mega_gardevoir_psychic_ramp')}, venusaur "
                     f"{rate('league_mega_venusaur_tank')}); bench is placed but not role-prioritised.",
         "pilot": "partial", "taxonomy": True, "hook": False,
         "priority": "medium", "scope": "deck-agnostic", "status": "partial"},
        {"n": 3, "name": "color-matched energy attachment", "deck": "league_raging_bolt_ogerpon",
         "evidence": f"Raging Bolt aggro went 0-34 (adj {rate('league_raging_bolt_ogerpon')}); "
                     f"multi-colour F/L/G costs are not matched — attaches off-colour.",
         "pilot": False, "taxonomy": True, "hook": False,
         "priority": "highest", "scope": "deck-agnostic", "status": "FAIL"},
        {"n": 4, "name": "attack pressure / avoid passivity", "deck": "league_mega_venusaur_tank",
         "evidence": f"Venusaur drew 10/36 games (adj {rate('league_mega_venusaur_tank')}): survives "
                     "but never closes — passivity / no pressure objective.",
         "pilot": "partial", "taxonomy": True, "hook": False,
         "priority": "high", "scope": "deck-agnostic", "status": "partial"},
        {"n": 5, "name": "evolution sequencing", "deck": "dragapult / gardevoir / charizard / venusaur",
         "evidence": f"Dragapult control reaches {rate('league_dragapult_spread')} (good), but Mega "
                     "Stage-2 ramp/tank lines lag — evolution happens opportunistically, not planned.",
         "pilot": "partial", "taxonomy": True, "hook": False,
         "priority": "medium", "scope": "deck-agnostic", "status": "partial"},
        {"n": 6, "name": "search target planning", "deck": "all",
         "evidence": "Search cards are played but targets are generic (no role-aware fetch priorities).",
         "pilot": "partial", "taxonomy": True, "hook": False,
         "priority": "medium", "scope": "deck-agnostic", "status": "partial"},
        {"n": 7, "name": "discard safety", "deck": "all",
         "evidence": "Decks run clean (no INVALID from illegal discards), but discard is not line/payoff-aware.",
         "pilot": "partial", "taxonomy": True, "hook": "partial",
         "priority": "low", "scope": "deck-agnostic", "status": "partial"},
        {"n": 8, "name": "deck conservation", "deck": "all",
         "evidence": "No self-deckout losses observed among eligible decks; draw engines are not over-thinned.",
         "pilot": True, "taxonomy": True, "hook": True,
         "priority": "low", "scope": "deck-agnostic", "status": "supported"},
        {"n": 9, "name": "prize-race awareness", "deck": "league_durant_deckout_carousel",
         "evidence": "Durant races prizes instead of milling (smoke INVALID); pilot has no prize-vs-mill model.",
         "pilot": False, "taxonomy": "partial", "hook": False,
         "priority": "medium", "scope": "deck-specific", "status": "FAIL"},
        {"n": 10, "name": "retreat/switch awareness", "deck": "all",
         "evidence": "Switching happens legally but is not optimised (no retreat value model).",
         "pilot": "partial", "taxonomy": "partial", "hook": False,
         "priority": "low", "scope": "deck-agnostic", "status": "partial"},
        {"n": 11, "name": "recovery/recursion", "deck": "league_durant_deckout_carousel",
         "evidence": "Recovery cards play, but recursion LOOPS (mill engine) are not planned.",
         "pilot": False, "taxonomy": "partial", "hook": False,
         "priority": "low", "scope": "deck-specific", "status": "FAIL"},
        {"n": 12, "name": "spread/bench target planning", "deck": "league_dragapult_spread",
         "evidence": f"Dragapult performs ({rate('league_dragapult_spread')}) but spread DAMAGE TARGETING "
                     "is unverified — no bench-damage target resolution hook.",
         "pilot": False, "taxonomy": True, "hook": False,
         "priority": "high", "scope": "deck-specific", "status": "FAIL"},
        {"n": 13, "name": "mill/deckout win condition", "deck": "league_durant_deckout_carousel",
         "evidence": f"Durant excluded; smoke INVALID={durant_invalid}. No non-prize win condition exists.",
         "pilot": False, "taxonomy": "partial", "hook": False,
         "priority": "medium", "scope": "deck-specific", "status": "FAIL"},
        {"n": 14, "name": "combo/ramp sequencing", "deck": "league_mega_gardevoir_psychic_ramp",
         "evidence": f"Gardevoir ramp 7-29 (adj {rate('league_mega_gardevoir_psychic_ramp')}): energy-ramp "
                     "accumulation toward a scaling attack is not sequenced.",
         "pilot": False, "taxonomy": True, "hook": False,
         "priority": "high", "scope": "deck-agnostic", "status": "FAIL"},
        {"n": 15, "name": "lethal counting / all-in attack timing", "deck": "league_mega_charizard_x_burst",
         "evidence": f"Charizard burst middling ({rate('league_mega_charizard_x_burst')}); all-in/lethal "
                     "timing unverified — no lethal-counting hook.",
         "pilot": False, "taxonomy": True, "hook": False,
         "priority": "high", "scope": "deck-agnostic", "status": "FAIL"},
    ]

    # Mechanically cross-reference each competency with the Part-H fixtures.
    fixture_coverage = _load_fixture_coverage()
    for c in comps:
        c["fixture_coverage"] = fixture_coverage.get(_slug(c["name"]), [])

    fails = [c for c in comps if c["status"] == "FAIL"]
    agnostic_fails = [c for c in fails if c["scope"] == "deck-agnostic"]
    # Highest-priority deck-AGNOSTIC gap = the one to fix first for the whole portfolio.
    prio_rank = {"highest": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    top = sorted(agnostic_fails, key=lambda c: prio_rank[c["priority"]])[0]

    report = {
        "pass": "27", "part": "J", "local_only": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "core_question": ("Which fundamental gameplay competencies still fail when "
                          "the same generic core pilot is applied to different deck "
                          "archetypes?"),
        "evidence_sources": ["pass27_portfolio_rankings.json (internal league)",
                             "pass27_live_smoke.json", "pass27_role_taxonomy.json",
                             "data/fixtures/pass27_portfolio_core/*"],
        "caveat": ("All evidence is from an INTERNAL surrogate league (our decks, "
                   "one generic pilot) — NOT Kaggle and NOT a promotion signal."),
        "competencies": comps,
        "summary": {
            "supported": [c["name"] for c in comps if c["status"] == "supported"],
            "partial": [c["name"] for c in comps if c["status"] == "partial"],
            "failing": [c["name"] for c in fails],
            "deck_agnostic_failures": [c["name"] for c in agnostic_fails],
            "highest_priority_generic_gap": top["name"],
            "highest_priority_reason": top["evidence"],
            "competencies_with_fixture_coverage": sum(
                1 for c in comps if c["fixture_coverage"]),
            "fixture_assertions_cross_referenced": sum(
                len([x for x in c["fixture_coverage"] if "assertion" in x])
                for c in comps),
        },
        "unsupported_runtime_roles": taxonomy.get("unsupported_runtime_roles", {}),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass27_core_gameplay_gap_analysis.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    L = ["# Pass 27 — Core Gameplay Gap Analysis (Part J)", "",
         f"> {report['caveat']}", "",
         f"**Core question:** {report['core_question']}", "",
         f"**Highest-priority deck-agnostic gap:** `{top['name']}` — {top['evidence']}",
         "", "## Competency matrix", "",
         "| # | competency | exposed by | pilot | taxonomy | hook | status | priority | scope |",
         "|---|---|---|---|---|---|---|---|---|"]
    for c in comps:
        L.append(f"| {c['n']} | {c['name']} | {c['deck']} | {c['pilot']} | "
                 f"{c['taxonomy']} | {c['hook']} | **{c['status']}** | {c['priority']} "
                 f"| {c['scope']} |")
    L += ["", "## Evidence detail", ""]
    for c in comps:
        L.append(f"- **{c['name']}** ({c['status']}, {c['priority']}, {c['scope']}): "
                 f"{c['evidence']}")
    L += ["", "## Summary", "",
          f"- supported: {len(report['summary']['supported'])}",
          f"- partial: {len(report['summary']['partial'])}",
          f"- failing: {len(report['summary']['failing'])} "
          f"({', '.join(report['summary']['failing'])})",
          f"- deck-agnostic failures (fix these for the whole portfolio): "
          f"{', '.join(report['summary']['deck_agnostic_failures'])}",
          f"- **highest-priority generic gap: {top['name']}**", ""]
    (EXP / "pass27_core_gameplay_gap_analysis.md").write_text(
        "\n".join(L), encoding="utf-8")

    print(f"competencies: {len(comps)}  failing: {len(fails)}  "
          f"agnostic-failing: {len(agnostic_fails)}")
    print(f"highest-priority generic gap: {top['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
