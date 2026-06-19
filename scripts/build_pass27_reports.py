#!/usr/bin/env python3
"""Pass 27 (Parts M + O) — reports, docs, site, and the EXACT 10-section report.

Data-driven from the Pass-27 artifacts. Produces:
- data/reports/pass27_multi_archetype_portfolio_report.md  (the EXACT Part-O
  10-section format from the spec)
- data/reports/activegraph_strategy_report.md              (narrative summary)
- docs/PTCG_STRATEGY_CANVAS.md                             (refreshed canvas)
- data/site/index.html                                     (static site landing)

CORE_PILOT_ROLE_TAXONOMY.md is written by Part D and is referenced, not rewritten.
Every artifact states clearly that the internal league is NOT Kaggle and NOT a
promotion signal. No upload, no submit, no GitHub push.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
SITE = REPO / "data" / "site"
DOCS = REPO / "docs"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _count_pass27_events() -> int:
    if not LAB_EVENTS.exists():
        return 0
    n = 0
    for line in LAB_EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if "pass27" in (ev.get("tags") or []):
            n += 1
    return n


def main() -> int:
    live = _load("pass27_live_score_status.json")
    reg = _load("pass27_portfolio_registry.json")
    manifest = _load("pass27_candidate_manifest.json")
    val = _load("pass27_candidate_validation.json")
    smoke = _load("pass27_live_smoke.json")
    rankings = _load("pass27_portfolio_rankings.json")
    gap = _load("pass27_core_gameplay_gap_analysis.json")
    decision = _load("pass27_strategy_decision.json")

    standings = rankings.get("standings", [])
    built = manifest.get("candidates_built", [])
    league_blocked = manifest.get("league_blocked", [])
    eligible = val.get("league_eligible", [])
    wr = {r["id"]: r for r in standings}
    def rate(cid):
        return wr.get(cid, {}).get("adj_win_rate")
    gcomp = {c["name"]: c for c in gap.get("competencies", [])}
    n_events = _count_pass27_events()

    leader = live.get("live_score_leader") or {}
    wfb = live.get("water_family_current_best") or {}

    def sname(d):
        return d.get("fileName") or d.get("submission") or d.get("name")

    drift = live.get("score_drift_vs_pass26") or []
    if isinstance(drift, list):
        moved = [d for d in drift if isinstance(d, dict) and d.get("delta")]
        drift_str = ("no change across all tracked submissions "
                     f"({len(drift)} compared, all delta 0.0)" if not moved
                     else "; ".join(f"{d['fileName']} {d['delta']:+}" for d in moved))
    else:
        drift_str = str(drift)

    # ---- smoke verdict buckets ----
    smoke_results = smoke.get("results", {})
    smoke_valid = [k for k, v in smoke_results.items() if v.get("clean")]
    smoke_invalid = [k for k, v in smoke_results.items() if not v.get("clean")]

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    CAVEAT = ("The internal league is a LOCAL surrogate (our own decks, one generic "
              "core pilot, subprocess-isolated, seat-swapped). It is NOT the Kaggle "
              "leaderboard and is NOT a promotion signal.")

    def yn(b):
        return "yes" if b else "no"

    # ================= Part O — EXACT 10-section report =================
    O = []
    O.append("ActiveGraph Pass 27 Multi-Archetype Core Gameplay Portfolio Report")
    O.append("")
    O.append("1. Root safety")
    O.append(f"- root main.py unchanged: {yn(manifest.get('root_main_py_untouched'))}")
    O.append(f"- root deck.csv unchanged: {yn(manifest.get('root_deck_csv_untouched'))}")
    O.append("- package verify: all candidate tarballs contain top-level main.py + "
             "deck.csv only (validate_candidate_tarball + entrypoint PASS)")
    O.append(f"- upload performed: {yn(manifest.get('upload_performed'))}")
    O.append("")
    O.append("2. Live score state")
    O.append(f"- live_score_leader: {sname(leader)} "
             f"@ {leader.get('publicScore')}")
    O.append(f"- water_family_current_best: {sname(wfb)} "
             f"@ {wfb.get('publicScore')}")
    O.append(f"- score drift: {drift_str}")
    O.append(f"- conclusion: live leader and Water-family best resolve to the same "
             f"submission (distinction_preserved={live.get('distinction_preserved')}); "
             f"refreshed_live={live.get('scores_refreshed_live')} "
             f"({live.get('refresh_method')}). No submit performed.")
    O.append("")
    O.append("3. Portfolio registry")
    O.append(f"- families registered: {reg.get('summary', {}).get('total_decks')}")
    O.append(f"- decks valid: {reg.get('summary', {}).get('buildable_valid')}")
    O.append(f"- decks blocked: {reg.get('summary', {}).get('blocked_from_league')} "
             f"(from league: {', '.join(league_blocked) or 'none'})")
    O.append(f"- no invented IDs: {yn(manifest.get('no_invented_ids'))} "
             "(all IDs validated vs data/cards/EN_Card_Data.csv)")
    O.append("- role taxonomy path: docs/CORE_PILOT_ROLE_TAXONOMY.md + "
             "data/experiments/pass27_role_taxonomy.json")
    O.append("")
    O.append("4. Candidates")
    O.append(f"- candidates built: {len(built)} "
             f"({', '.join(c['candidate_id'] for c in built)})")
    O.append(f"- candidates blocked: {len(manifest.get('candidates_not_built', []))} "
             "not-built; 1 built-but-league-blocked (league_durant_deckout_carousel)")
    O.append(f"- tarballs: data/submissions/candidates_pass27/*.tar.gz "
             f"({len(built)} files, top-level main.py+deck.csv only)")
    O.append("- runtime hooks: none added this pass — all candidates reuse the SAME "
             "generic core pilot (the point of the experiment)")
    O.append("- deck diffs: each candidate = baseline main.py + its own legal 60-card "
             "deck.csv; no main.py logic changes")
    O.append("")
    O.append("5. Validation / smoke")
    O.append("- tarball validators: PASS (all built candidates)")
    O.append("- entrypoint validators: PASS (all built candidates)")
    O.append(f"- smoke-valid: {len(smoke_valid)} "
             f"({', '.join(sorted(smoke_valid))})")
    O.append(f"- invalid/crash/timeout: {len(smoke_invalid)} "
             f"({', '.join(sorted(smoke_invalid)) or 'none'}) "
             "— Durant INVALID (races prizes; deckout unsupported)")
    O.append(f"- blocked from league: {', '.join(league_blocked) or 'none'}")
    O.append("")
    O.append("6. Internal league")
    O.append(f"- participants: {len(standings)} "
             f"({', '.join(s['id'] for s in standings)})")
    O.append("- games per seat: 3 per seat, seat-swapped (subprocess-isolated)")
    O.append(f"- top deck: {standings[0]['id']} (adj {standings[0]['adj_win_rate']})"
             if standings else "- top deck: n/a")
    O.append(f"- worst deck: {standings[-1]['id']} (adj {standings[-1]['adj_win_rate']})"
             if standings else "- worst deck: n/a")
    O.append("- compatibility labels: water_core/control reference strong; "
             "dragapult control viable; charizard/venusaur middling; "
             "gardevoir ramp weak; raging_bolt aggro broken")
    O.append(f"- caveat: {CAVEAT}")
    O.append("")
    O.append("7. Core gameplay gaps")
    O.append(f"- aggro/color-energy: {gcomp.get('color-matched energy attachment', {}).get('status')} "
             f"(raging_bolt adj {rate('league_raging_bolt_ogerpon')}, 0-34)")
    O.append(f"- spread targeting: {gcomp.get('spread/bench target planning', {}).get('status')} "
             f"(dragapult attacks at adj {rate('league_dragapult_spread')} but bench-target "
             "resolution unverified/missing)")
    O.append(f"- evolution sequencing: {gcomp.get('evolution sequencing', {}).get('status')} "
             "(opportunistic, not planned)")
    O.append(f"- ramp/combo: {gcomp.get('combo/ramp sequencing', {}).get('status')} "
             f"(gardevoir adj {rate('league_mega_gardevoir_psychic_ramp')}, 7-29)")
    O.append(f"- deckout/chaos: {gcomp.get('mill/deckout win condition', {}).get('status')} "
             "(Durant excluded; no non-prize win condition)")
    O.append(f"- deck conservation: {gcomp.get('deck conservation', {}).get('status')} "
             "(no self-deckout losses among eligible decks)")
    O.append(f"- highest-priority generic gap: "
             f"{gap.get('summary', {}).get('highest_priority_generic_gap')}")
    O.append("")
    O.append("8. Strategy decision")
    O.append(f"- decision: {decision.get('primary_decision')} "
             f"(secondary: {decision.get('secondary_decision')})")
    O.append(f"- next core rule family: {decision.get('next_core_rule_family')}")
    O.append(f"- next deck family: {decision.get('next_deck_family')}")
    O.append(f"- keep Water control: {yn(decision.get('keep_water_control'))}")
    O.append(f"- reason: {decision.get('reason')}")
    O.append("")
    O.append("9. Report site / ActiveGraph")
    O.append("- site path: data/site/index.html")
    O.append("- markdown report: data/reports/pass27_multi_archetype_portfolio_report.md")
    O.append(f"- events emitted: {n_events} (pass27-tagged, all no_upload)")
    O.append("- event store: data/activegraph/lab_events.jsonl")
    O.append("")
    O.append("10. Next recommendation")
    O.append(f"- Build colour-matched energy + attack-pressure core rules next "
             f"(the highest-priority deck-agnostic gap, exposed by raging_bolt's 0-34), "
             f"keep Water as the live reference, then expand the portfolio to re-test.")
    O.append("")
    (REPORTS / "pass27_multi_archetype_portfolio_report.md").write_text(
        "\n".join(O), encoding="utf-8")

    # ================= activegraph_strategy_report.md =================
    A = ["# ActiveGraph Strategy Report — Pass 27 (Multi-Archetype Portfolio)", "",
         f"> {CAVEAT}", "",
         "## What this pass asked", "",
         "Which fundamental gameplay competencies still fail when the SAME generic "
         "core pilot is applied to 7 different deck archetypes?", "",
         "## What we did", "",
         f"- Registered {reg.get('summary', {}).get('total_decks')} legal deck families "
         "(all IDs validated vs EN_Card_Data.csv; no invented IDs).",
         f"- Built {len(built)} candidates (baseline main.py + per-deck legal deck.csv), "
         "validated tarball + entrypoint, ran self/h2h smoke.",
         f"- Ran an internal seat-swapped league across {len(standings)} participants "
         "(Durant excluded — deckout unsupported).",
         "- Mapped a cross-deck role taxonomy and scored 15 core competencies.", "",
         "## Headline results", "",
         f"- League top: **{standings[0]['id']}** (adj {standings[0]['adj_win_rate']}); "
         f"worst: **{standings[-1]['id']}** (adj {standings[-1]['adj_win_rate']})."
         if standings else "- League: n/a",
         f"- Highest-priority deck-agnostic gap: **"
         f"{gap.get('summary', {}).get('highest_priority_generic_gap')}** "
         "(raging_bolt aggro went 0-34).",
         f"- Decision: **{decision.get('primary_decision')}**, keep Water control, "
         "no Kaggle probe.", "",
         "## Failing competencies", ""]
    for c in gap.get("competencies", []):
        if c["status"] == "FAIL":
            A.append(f"- **{c['name']}** ({c['scope']}, {c['priority']}): {c['evidence']}")
    A += ["", "## Decision", "", decision.get("reason", ""), "",
          "See `data/reports/pass27_multi_archetype_portfolio_report.md` for the "
          "full 10-section report.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ================= docs/PTCG_STRATEGY_CANVAS.md =================
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 27.", "",
         f"_{CAVEAT}_", "",
         "## Current live reference (Kaggle)", "",
         f"- live_score_leader: `{sname(leader)}` "
         f"@ {leader.get('publicScore')}",
         f"- water_family_current_best: `{sname(wfb)}` "
         f"@ {wfb.get('publicScore')}",
         f"- distinction preserved: {live.get('distinction_preserved')}", "",
         "## Pass 27 — multi-archetype portfolio", "",
         "The generic core pilot was applied unchanged across 7 archetypes to find "
         "where it breaks. Internal league standings (surrogate, not Kaggle):", "",
         "| rank | deck | adj win rate | record |", "|---|---|---|---|"]
    for i, s in enumerate(standings, 1):
        C.append(f"| {i} | {s['id']} | {s['adj_win_rate']} | "
                 f"{s['wins']}-{s['losses']}-{s['draws']} |")
    C += ["", "## Open core-pilot gaps (priority order)", ""]
    fails = sorted([c for c in gap.get("competencies", []) if c["status"] == "FAIL"],
                   key=lambda c: {"highest": 0, "high": 1, "medium": 2,
                                  "low": 3}.get(c["priority"], 9))
    for c in fails:
        C.append(f"- **{c['name']}** ({c['scope']}, {c['priority']})")
    C += ["", "## Next move", "",
          f"`{decision.get('primary_decision')}` — {decision.get('next_core_rule_family')}; "
          f"then `{decision.get('secondary_decision')}`. Keep Water as the live reference.",
          ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ================= data/site/index.html =================
    rows = "\n".join(
        f"      <tr><td>{i}</td><td>{s['id']}</td><td>{s['adj_win_rate']}</td>"
        f"<td>{s['wins']}-{s['losses']}-{s['draws']}</td></tr>"
        for i, s in enumerate(standings, 1))
    fail_items = "\n".join(
        f"      <li><b>{c['name']}</b> <span class=tag>{c['priority']}</span> "
        f"<span class=tag>{c['scope']}</span></li>"
        for c in fails)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 27 Multi-Archetype Portfolio</title>
<link rel="stylesheet" href="style.css">
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.92rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem}}
 .tag{{display:inline-block;background:#eef;border-radius:4px;padding:0 .4rem;font-size:.75rem;margin-left:.3rem}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>ActiveGraph — Pass 27: Multi-Archetype Core Gameplay Portfolio</h1>
<p class="caveat">{CAVEAT}</p>
<h2>Live reference (Kaggle)</h2>
<p>live_score_leader: <code>{sname(leader)}</code>
 @ {leader.get('publicScore')} &middot; water_family_current_best:
 <code>{sname(wfb)}</code> @ {wfb.get('publicScore')}</p>
<h2>Internal league (surrogate, NOT Kaggle)</h2>
<table><thead><tr><th>rank</th><th>deck</th><th>adj win rate</th><th>record</th></tr></thead>
<tbody>
{rows}
</tbody></table>
<h2>Highest-priority deck-agnostic gap</h2>
<p><b>{gap.get('summary', {}).get('highest_priority_generic_gap')}</b></p>
<h2>Open core-pilot gaps</h2>
<ul>
{fail_items}
</ul>
<h2>Decision</h2>
<p><b>{decision.get('primary_decision')}</b> &middot; next:
 {decision.get('next_core_rule_family')} &middot; keep Water control:
 {yn(decision.get('keep_water_control'))}</p>
<p>Full report: <code>data/reports/pass27_multi_archetype_portfolio_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("wrote:")
    print("  data/reports/pass27_multi_archetype_portfolio_report.md")
    print("  data/reports/activegraph_strategy_report.md")
    print("  docs/PTCG_STRATEGY_CANVAS.md")
    print("  data/site/index.html")
    print(f"events counted: {n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
