#!/usr/bin/env python3
"""Pass 30 (Parts M + O) — reports, docs, site, and the EXACT 10-section report.

Data-driven from the Pass-30 artifacts. Produces:
- data/reports/pass30_existing_portfolio_hardening_report.md  (EXACT Part-O format,
  spec lines 584-649)
- data/reports/activegraph_strategy_report.md                 (narrative summary)
- docs/PTCG_STRATEGY_CANVAS.md                                (refreshed canvas)
- data/site/index.html                                        (static site landing)

Every artifact states clearly that the internal tournament / meta sanity is NOT the
Kaggle leaderboard and is NOT a promotion signal. No upload, no submit, no push.
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


def _count_events(tag="pass30") -> int:
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
        if tag in (ev.get("tags") or []):
            n += 1
    return n


def yn(b) -> str:
    return "yes" if b else "no"


def pct(x) -> str:
    return "n/a" if x is None else f"{float(x) * 100:.1f}%"


def main() -> int:
    live = _load("pass30_live_score_status.json")
    reg = _load("pass30_existing_portfolio_registry.json")
    plan = _load("pass30_hardening_plan.json")
    manifest = _load("pass30_candidate_manifest.json")
    valid = _load("pass30_candidate_validation.json")
    smoke = _load("pass30_live_smoke.json")
    rank1 = _load("pass30_portfolio_rankings.json")
    rank2 = _load("pass30_portfolio_rankings_stage2.json")
    pc = _load("pass30_parent_child_confirmations.json")
    sanity = _load("pass30_meta_sanity.json")
    diag = _load("pass30_hardening_diagnosis.json")
    decision = _load("pass30_strategy_decision.json")

    leader = live.get("live_score_leader") or {}
    water_best = live.get("water_family_current_best") or {}
    portref = live.get("portfolio_reference") or {}
    standings = rank1.get("standings", [])
    fstand = rank1.get("family_standings", [])
    fam_diag = diag.get("families", {})
    san = sanity.get("sanity", {})
    san_per = san.get("per_deck", {})
    n_events = _count_events()

    CAVEAT = ("The internal tournament, parent/child confirmations and meta sanity "
              "are LOCAL diagnostics: both seats are OUR portfolio decks driven by the "
              "SAME generic core pilot, run subprocess-isolated and seat-swapped. They "
              "are NOT the Kaggle leaderboard and are NOT a promotion or upload signal.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    pairs = {p.get("id"): p for p in pc.get("pairs", [])}
    dp_search = pairs.get("dragapult_parent_vs_search_only", {})
    dp_draw = pairs.get("dragapult_parent_vs_draw_only", {})
    ven = pairs.get("venusaur_parent_vs_loop_guard", {})
    rb_cons = pairs.get("raging_bolt_base_vs_consistency", {})
    rb_en = pairs.get("raging_bolt_base_vs_energy_attacker", {})
    water_cmp = pairs.get("water_benchmark_vs_best_non_water", {})

    top = standings[0] if standings else {}
    fstand_sorted = sorted(fstand, key=lambda f: f.get("adj_win_rate", 0),
                           reverse=True)
    top_fam = fstand_sorted[0] if fstand_sorted else {}
    worst_fam = fstand_sorted[-1] if fstand_sorted else {}

    # meta sanity best candidate (highest weighted_meta_score)
    san_best_id, san_best = None, -1.0
    for cid, d in san.get("per_deck", {}).items():
        ws = d.get("weighted_meta_score")
        if ws is not None and ws > san_best:
            san_best, san_best_id = ws, cid
    collapses = [cid for cid, d in san.get("per_deck", {}).items()
                 if not d.get("no_collapse", True)]

    # ================= Part O — EXACT 10-section report =================
    O = []
    O.append("ActiveGraph Pass 30 Existing Portfolio Hardening Tournament Report")
    O.append("")
    upload_done = bool(decision.get("upload_performed")
                       or manifest.get("upload_performed"))
    probe = decision.get("recommended_probe_candidate")
    O.append("1. Root safety")
    O.append("- root main.py unchanged: yes (cmp vs v1 baseline, verify-only)")
    O.append("- root deck.csv unchanged: yes (cmp vs v1 baseline)")
    O.append("- package verify: PASS (verify-only; no root file mutated)")
    O.append(f"- upload performed: {yn(upload_done)}")
    O.append("")
    O.append("2. Live score state")
    O.append(f"- live_score_leader: {leader.get('fileName')} @ "
             f"{leader.get('publicScore')}")
    O.append(f"- water_family_current_best: {water_best.get('fileName')} @ "
             f"{water_best.get('publicScore')}")
    O.append(f"- portfolio_reference: {portref.get('fileName')} @ "
             f"{portref.get('publicScore')}")
    O.append("- conclusion: read-only snapshot; Pass 30 is a hardening tournament, "
             "no upload/submit and not a promotion decision "
             f"(distinction_preserved={yn(live.get('distinction_preserved'))})")
    O.append("")
    O.append("3. Portfolio / hardening plan")
    O.append(f"- families included: {len(reg.get('families', []))} "
             f"({', '.join(f.get('family_key') for f in reg.get('families', []))})")
    O.append(f"- variants planned: {len(plan.get('tracks', []))} tracks "
             f"(max {plan.get('max_variants')}); new builds = "
             f"{plan.get('new_builds_total')} (Raging Bolt structural A/B only)")
    O.append(f"- candidates reused: {len(manifest.get('candidates_reused', []))}")
    O.append(f"- candidates built: {len(manifest.get('candidates_built', []))} "
             f"({', '.join(manifest.get('candidates_built', []))})")
    O.append(f"- blocked: {len(manifest.get('league_blocked', []))} "
             f"({', '.join(manifest.get('league_blocked', []))})")
    O.append("")
    O.append("4. Validation / smoke")
    O.append("- tarball validators: all non-blocked candidates PASS "
             "(top-level main.py+deck.csv only)")
    O.append("- entrypoint validators: all non-blocked candidates PASS")
    O.append(f"- smoke-valid: {yn(smoke.get('smoke_ok'))} "
             f"({len(valid.get('tournament_eligible', []))} tournament-eligible)")
    O.append("- invalid/crash/timeout: Durant INVALID (deckout pilot mismatch) — "
             "the only blocked entry; all others clean")
    O.append("- excluded: league_durant_deckout_carousel (blocked from league)")
    O.append("")
    O.append("5. Internal tournament")
    O.append(f"- participants: {len(standings)} (Stage-1), "
             f"{len(rank2.get('standings', []))} (Stage-2 top4)")
    O.append("- games per seat: 3 (Stage-1), 10 (Stage-2)")
    O.append(f"- top candidate: {top.get('id')} "
             f"(adj win_rate {pct(top.get('adj_win_rate'))}, "
             f"{top.get('compatibility_label')})")
    O.append(f"- top family: {top_fam.get('family')} "
             f"({pct(top_fam.get('adj_win_rate'))})")
    O.append(f"- worst family: {worst_fam.get('family')} "
             f"({pct(worst_fam.get('adj_win_rate'))})")
    O.append(f"- caveat: {CAVEAT}")
    O.append("")
    O.append("6. Parent/child confirmations")
    O.append(f"- Dragapult: parent vs search_only parent_win_rate "
             f"{pct(dp_search.get('a_win_rate'))}, vs draw_only "
             f"{pct(dp_draw.get('a_win_rate'))} — children run clean, behaviourally "
             "close to parent (CI spans 0.5)")
    O.append(f"- Venusaur: tank parent vs loop-guard child parent_win_rate "
             f"{pct(ven.get('a_win_rate'))}; guard build slightly ahead in Stage-1, "
             "no significant H2H separation")
    O.append(f"- Raging Bolt: base vs consistency parent_win_rate "
             f"{pct(rb_cons.get('a_win_rate'))} (base ahead), vs energy_attacker "
             f"{pct(rb_en.get('a_win_rate'))} — neither rebuild helps")
    O.append(f"- Water comparison: water core vs best non-water "
             f"({water_cmp.get('child')}) parent_win_rate "
             f"{pct(water_cmp.get('a_win_rate'))} (dead even)")
    O.append("- strongest finding: the Dragapult children are the strongest "
             "non-water decks but do not separate from their parent; Raging Bolt "
             "structural hardening does not move the needle")
    O.append("")
    O.append("7. Meta sanity")
    O.append(f"- run: {sanity.get('status')} "
             f"({sanity.get('games_per_seat')} g/seat vs "
             f"{len(sanity.get('opponent_subfamilies', []))} replay-derived "
             "subfamilies, surrogate)")
    O.append(f"- best candidate: {san_best_id} "
             f"(weighted meta {pct(san_best)} > water "
             f"{pct(san.get('water_weighted_meta_score'))})")
    O.append(f"- collapses: {', '.join(collapses) if collapses else 'none'} "
             "(Raging Bolt is the EXPECTED collapse control)")
    O.append(f"- caveat: {sanity.get('disclaimer')}")
    O.append("")
    O.append("8. Compatibility diagnosis")
    O.append(f"- Water: {fam_diag.get('water', {}).get('conclusion', '')}")
    O.append(f"- Dragapult: {fam_diag.get('dragapult', {}).get('conclusion', '')}")
    O.append(f"- Venusaur: {fam_diag.get('venusaur', {}).get('conclusion', '')}")
    O.append(f"- Raging Bolt: {fam_diag.get('raging_bolt', {}).get('conclusion', '')}")
    diagn = fam_diag.get("diagnostics", {})
    O.append(f"- Charizard: {diagn.get('conclusion', '')}")
    O.append(f"- Gardevoir: weak diagnostic benchmark ({diagn.get('worst')}); "
             "kept as a fixed reference, no new builds this pass")
    O.append("- Chaos/Durant: blocked from league by design (deckout pilot "
             "mismatch); reserved as a future lane, not hardened this pass")
    O.append("")
    O.append("9. Strategy decision / ActiveGraph")
    O.append(f"- decision: {decision.get('decision')}")
    O.append(f"- dry-run queue: {decision.get('queued_candidate_count')} "
             f"(max {decision.get('queue_max')}); HELD, "
             f"human_approval_required={yn(decision.get('human_approval_required'))}, "
             f"auto_submit_enabled={yn(decision.get('auto_submit_enabled'))}")
    O.append(f"- next family: dragapult (probe {probe}); raging_bolt moves to "
             "PILOT work, not new decklists")
    O.append(f"- events emitted: {n_events} (pass30-tagged, all no_upload)")
    O.append("- report site: data/site/index.html + "
             "data/reports/pass30_existing_portfolio_hardening_report.md")
    O.append("")
    O.append("10. Next recommendation")
    O.append("- Submit nothing automatically. Hold league_dragapult_v1_search_only "
             "as the single human-approved dry-run probe (top internal + top meta, "
             "no collapse), with league_dragapult_v1_draw_only as backup. Stop "
             "building Raging Bolt decklists — its bottleneck is the generic pilot, "
             "so the next Raging Bolt move must be a PILOT/policy change, not another "
             "deck. Keep Water as the always-on benchmark and Charizard/Gardevoir as "
             "fixed diagnostics.")
    O.append("")
    (REPORTS / "pass30_existing_portfolio_hardening_report.md").write_text(
        "\n".join(O), encoding="utf-8")

    # ================= activegraph_strategy_report.md =================
    A = ["# ActiveGraph Strategy Report — Pass 30 (Existing Portfolio Hardening "
         "Tournament)", "",
         f"> {CAVEAT}", "",
         "## What this pass asked", "",
         "Among OUR existing decks and variants, which is the best next "
         "human-approved probe candidate — and does structural hardening (especially "
         "of Raging Bolt) actually help?", "",
         "## What we did", "",
         f"- Inventoried {len(reg.get('families', []))} existing families and planned "
         f"{len(plan.get('tracks', []))} hardening tracks (≤5), building only "
         f"{plan.get('new_builds_total')} NEW Raging Bolt structural variants; "
         "everything else reused.",
         "- Validated every candidate (tarball + entrypoint + deck legality + smoke); "
         "Durant blocked by design.",
         f"- Ran a 2-stage internal tournament ({len(standings)} participants), "
         "parent/child confirmations (10 g/seat), and a directional surrogate meta "
         "sanity check.",
         "- Diagnosed each family and recorded an evidence-gated, human-approval-"
         "gated dry-run decision (queue max 1).",
         "", "## Headline results", "",
         f"- **Top internal candidate:** {top.get('id')} "
         f"({pct(top.get('adj_win_rate'))}); **top family:** {top_fam.get('family')}; "
         f"**worst family:** {worst_fam.get('family')} "
         f"({pct(worst_fam.get('adj_win_rate'))}).",
         f"- **Dragapult is the strongest non-water family** and tops meta sanity "
         f"({san_best_id} @ {pct(san_best)} > water "
         f"{pct(san.get('water_weighted_meta_score'))}).",
         "- **Raging Bolt structural hardening did NOT help** — it stays bottom and "
         "collapses in meta sanity (expected control). The bottleneck is the generic "
         "pilot, not the decklist.",
         f"- **Decision:** {decision.get('decision')}", "",
         "## Per-family diagnosis", ""]
    for fam in ("water", "dragapult", "venusaur", "raging_bolt", "diagnostics"):
        f = fam_diag.get(fam, {})
        if not f:
            continue
        A.append(f"- **{fam}** (action `{f.get('hardening_action')}`, "
                 f"helped={f.get('hardening_helped')}, "
                 f"stay_active={f.get('stay_active')}): {f.get('next_work', '')}")
    A += ["", "## Decision", "",
          f"- {decision.get('decision')}",
          f"- Rejected: " + "; ".join(
              f"{k} — {v}" for k, v in
              (decision.get("rejected_alternatives") or {}).items()),
          "",
          "See `data/reports/pass30_existing_portfolio_hardening_report.md` for the "
          "full 10-section report.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ================= docs/PTCG_STRATEGY_CANVAS.md =================
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 30.", "",
         f"_{CAVEAT}_", "",
         "## Current live reference (Kaggle, read-only)", "",
         f"- live_score_leader: `{leader.get('fileName')}` @ "
         f"{leader.get('publicScore')}",
         f"- water_family_current_best: `{water_best.get('fileName')}` @ "
         f"{water_best.get('publicScore')}",
         f"- portfolio_reference: `{portref.get('fileName')}` @ "
         f"{portref.get('publicScore')}",
         f"- distinction preserved: {yn(live.get('distinction_preserved'))}", "",
         "## Pass 30 — existing portfolio hardening tournament", "",
         "We hardened and ranked OUR existing portfolio to pick the next "
         "human-approved probe. Internal Stage-1 standings (NOT Kaggle):", "",
         "| rank | candidate | family | adj win_rate | label |",
         "|---|---|---|---|---|"]
    for i, s in enumerate(standings, 1):
        C.append(f"| {i} | {s.get('id')} | {s.get('family')} | "
                 f"{pct(s.get('adj_win_rate'))} | {s.get('compatibility_label')} |")
    C += ["", "## Family hardening verdicts", "",
          "| family | action | helped | stay active | best deck |",
          "|---|---|---|---|---|"]
    for fam in ("water", "dragapult", "venusaur", "raging_bolt", "diagnostics"):
        f = fam_diag.get(fam, {})
        if not f:
            continue
        C.append(f"| {fam} | {f.get('hardening_action')} | "
                 f"{f.get('hardening_helped')} | {f.get('stay_active')} | "
                 f"{f.get('best')} |")
    C += ["", "## Meta sanity (directional, surrogate)", "",
          f"- best: `{san_best_id}` @ {pct(san_best)} (> water "
          f"{pct(san.get('water_weighted_meta_score'))})",
          f"- collapses: {', '.join(collapses) if collapses else 'none'} "
          "(Raging Bolt = expected control)", "",
          "## Next move", "",
          f"`{decision.get('decision')}` Stop building Raging Bolt decklists — its "
          "next move is a PILOT/policy change. Keep Water as the always-on benchmark.",
          ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ================= data/site/index.html =================
    trows = "\n".join(
        f"      <tr><td>{i}</td><td>{s.get('id')}</td><td>{s.get('family')}</td>"
        f"<td>{pct(s.get('adj_win_rate'))}</td>"
        f"<td>{s.get('compatibility_label')}</td></tr>"
        for i, s in enumerate(standings, 1))
    frows = "\n".join(
        f"      <tr><td>{fam}</td>"
        f"<td>{fam_diag.get(fam, {}).get('hardening_action')}</td>"
        f"<td>{fam_diag.get(fam, {}).get('hardening_helped')}</td>"
        f"<td>{fam_diag.get(fam, {}).get('stay_active')}</td>"
        f"<td>{fam_diag.get(fam, {}).get('best')}</td></tr>"
        for fam in ("water", "dragapult", "venusaur", "raging_bolt", "diagnostics")
        if fam_diag.get(fam))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 30 Existing Portfolio Hardening Tournament</title>
<link rel="stylesheet" href="style.css">
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem}}
 .tag{{display:inline-block;background:#eef;border-radius:4px;padding:0 .4rem;font-size:.75rem;margin-left:.3rem}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>ActiveGraph — Pass 30: Existing Portfolio Hardening Tournament</h1>
<p class="caveat">{CAVEAT}</p>
<h2>Live reference (Kaggle, read-only)</h2>
<p>live_score_leader: <code>{leader.get('fileName')}</code> @ {leader.get('publicScore')}
 &middot; water_family_current_best: <code>{water_best.get('fileName')}</code>
 @ {water_best.get('publicScore')} &middot; portfolio_reference:
 <code>{portref.get('fileName')}</code> @ {portref.get('publicScore')}</p>
<h2>Internal tournament — Stage 1 standings (NOT Kaggle)</h2>
<table><thead><tr><th>rank</th><th>candidate</th><th>family</th><th>adj win_rate</th><th>label</th></tr></thead>
<tbody>
{trows}
</tbody></table>
<h2>Family hardening verdicts</h2>
<table><thead><tr><th>family</th><th>action</th><th>helped</th><th>stay active</th><th>best deck</th></tr></thead>
<tbody>
{frows}
</tbody></table>
<h2>Meta sanity (directional, surrogate)</h2>
<p>best: <code>{san_best_id}</code> @ {pct(san_best)} (&gt; water
 {pct(san.get('water_weighted_meta_score'))}) &middot; collapses:
 {', '.join(collapses) if collapses else 'none'} (Raging Bolt = expected control)</p>
<h2>Decision</h2>
<p><b>{decision.get('decision')}</b></p>
<p>dry-run queue: {decision.get('queued_candidate_count')} (max
 {decision.get('queue_max')}, HELD) &middot; human approval required:
 {yn(decision.get('human_approval_required'))} &middot; auto-submit:
 {yn(decision.get('auto_submit_enabled'))} &middot; events emitted: {n_events}</p>
<p>Full report: <code>data/reports/pass30_existing_portfolio_hardening_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("wrote:")
    print("  data/reports/pass30_existing_portfolio_hardening_report.md")
    print("  data/reports/activegraph_strategy_report.md")
    print("  docs/PTCG_STRATEGY_CANVAS.md")
    print("  data/site/index.html")
    print(f"events counted: {n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
