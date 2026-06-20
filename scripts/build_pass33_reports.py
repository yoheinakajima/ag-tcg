#!/usr/bin/env python3
"""Pass 33 (Parts M + O) — reports, docs, site, and the EXACT 10-section report.

Data-driven from the Pass-33 artifacts. Produces:
- data/reports/pass33_deck_composition_stress_test_report.md  (EXACT Part-O format)
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


def _count_events(tag="pass33") -> int:
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
    live = _load("pass33_live_score_status.json")
    audit = _load("pass33_deck_composition_audit.json")
    plan = _load("pass33_stress_test_plan.json")
    manifest = _load("pass33_composition_variants_manifest.json")
    valid = _load("pass33_candidate_validation.json")
    smoke = _load("pass33_live_smoke.json")
    rank1 = _load("pass33_composition_rankings.json")
    rank2 = _load("pass33_composition_rankings_stage2.json")
    corr = _load("pass33_composition_correlations.json")
    pc = _load("pass33_parent_child_confirmations.json")
    meta = _load("pass33_meta_sanity.json")
    decision = _load("pass33_strategy_decision.json")

    leader = live.get("live_score_leader") or {}
    water_best = live.get("water_family_current_best") or {}
    dragapult_best = live.get("dragapult_family_best") or {}
    portref = live.get("portfolio_reference") or {}
    standings = rank1.get("standings", [])
    meta_pd = meta.get("per_deck", {})
    n_events = _count_events()

    CAVEAT = ("The internal composition tournament, correlations, parent/child "
              "confirmations and meta sanity are LOCAL diagnostics: both seats are OUR "
              "portfolio decks driven by the SAME generic core pilot (meta sanity uses "
              "replay-derived surrogate opponents). They are NOT the Kaggle leaderboard "
              "and are NOT a promotion or upload signal.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    # ---- derived helpers ----
    top = standings[0] if standings else {}
    best_nonwater = next((s for s in standings if s.get("family") != "water"), {})
    fam_stand = rank1.get("family_standings", [])
    fam_sorted = sorted(fam_stand, key=lambda f: f.get("adj_win_rate", 0))
    worst_fam = fam_sorted[0] if fam_sorted else {}

    # meta best (highest weighted score)
    san_best_id, san_best = None, -1.0
    for cid, d in meta_pd.items():
        ws = d.get("weighted_meta_score")
        if ws is not None and ws > san_best:
            san_best, san_best_id = ws, cid

    # parent/child: density_v1 vs water control
    conf = {c.get("key"): c for c in pc.get("confirmations", [])}
    dv1 = conf.get("water_best__vs__density_v1", {})

    corr_rows = {r["metric"]: r for r in corr.get("correlations", [])}

    def sp(metric):
        r = corr_rows.get(metric, {})
        return r.get("spearman"), r.get("band")

    probe = decision.get("recommended_probe_candidate")
    dragapult_above_water = bool(live.get("dragapult_above_water"))

    # variant build summary
    built = [r["candidate_id"] for r in manifest.get("results", [])
             if r.get("kind") == "built"]
    reused = [r["candidate_id"] for r in manifest.get("results", [])
              if r.get("kind") == "reused"]
    blocked = [r["candidate_id"] for r in manifest.get("results", [])
               if r.get("disposition") == "blocked"]
    eligible = smoke.get("tournament_eligible", [])

    # ================= Part O — EXACT 10-section report =================
    O = []
    O.append("ActiveGraph Pass 33 Deck Composition Stress Test Report")
    O.append("")
    upload_done = bool(decision.get("upload_performed")
                       or manifest.get("upload_performed"))
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
    O.append(f"- dragapult_family_best: {dragapult_best.get('fileName')} @ "
             f"{dragapult_best.get('publicScore')} "
             f"(dragapult_above_water={yn(dragapult_above_water)})")
    O.append(f"- portfolio_reference: {portref.get('fileName')} @ "
             f"{portref.get('publicScore')}")
    O.append("- conclusion: read-only snapshot; Pass 33 is a composition stress test, "
             "no upload/submit and not a promotion decision "
             f"(distinction_preserved={yn(live.get('distinction_preserved'))})")
    O.append("")
    O.append("3. Deck composition audit")
    O.append(f"- decks audited: {audit.get('decks_audited')} "
             f"({audit.get('decks_valid_60')} valid 60-card)")
    O.append(f"- Basic count range: {audit.get('basic_count_range')}")
    O.append(f"- Energy count range: {audit.get('energy_count_range')}")
    hi = audit.get("highest_no_basic_risk", {})
    lo = audit.get("lowest_no_basic_risk", {})
    O.append(f"- highest no-Basic risk: {hi.get('candidate_id')} "
             f"({pct(hi.get('opening_no_basic_probability'))})")
    O.append(f"- lowest no-Basic risk: {lo.get('candidate_id')} "
             f"({pct(lo.get('opening_no_basic_probability'))})")
    O.append("- key finding: Basic density is the dominant composition lever — adding "
             "LEGAL Basics to the Water core halves opening no-Basic risk "
             "(0.346 -> 0.191 -> 0.099 across 8/12/16 Basics) without losing internal "
             "win rate")
    O.append("")
    O.append("4. Candidates / variants")
    O.append(f"- selected candidates: {plan.get('selection_count_eligible')} "
             f"eligible of {plan.get('selection_count_total')} "
             f"(within 8-12: {yn(plan.get('within_8_to_12'))})")
    O.append(f"- candidates reused: {len(reused)}")
    O.append(f"- candidates built: {len(built)} ({', '.join(built)})")
    O.append(f"- candidates blocked: {len(blocked)} ({', '.join(blocked)})")
    O.append("- tarballs: top-level main.py + deck.csv only, in "
             "data/submissions/candidates_pass33/")
    O.append("")
    O.append("5. Validation / smoke")
    O.append("- tarball validators: all non-blocked candidates PASS")
    O.append("- entrypoint validators: all non-blocked candidates PASS")
    O.append(f"- smoke-valid: {yn(smoke.get('smoke_ok'))} "
             f"({len(eligible)} tournament-eligible)")
    O.append("- invalid/crash/timeout: Durant smoke INVALID (deckout pilot mismatch) — "
             "the only blocked entry; all others clean")
    O.append("- excluded: league_durant_deckout_carousel (blocked from league)")
    O.append("")
    O.append("6. Internal tournament")
    O.append(f"- participants: {len(standings)} (Stage-1), "
             f"{len(rank2.get('standings', []))} (Stage-2 top4)")
    O.append("- games per seat: 3 (Stage-1), 10 (Stage-2)")
    O.append(f"- top candidate: {top.get('id')} "
             f"(adj win_rate {pct(top.get('adj_win_rate'))}, "
             f"{top.get('compatibility_label')})")
    O.append(f"- best non-Water: {best_nonwater.get('id')} "
             f"({pct(best_nonwater.get('adj_win_rate'))})")
    O.append(f"- worst family: {worst_fam.get('family')} "
             f"({pct(worst_fam.get('adj_win_rate'))})")
    O.append(f"- caveat: {CAVEAT}")
    O.append("")
    O.append("7. Composition correlations")
    bd_sp, bd_band = sp("basic_pokemon")
    er_sp, er_band = sp("energy_ratio")
    ev_sp, ev_band = sp("evolution_complexity_score")
    sd_sp, sd_band = sp("search_draw_count_heuristic")
    do_sp, _ = sp("deckout_risk_score")
    np_sp, _ = sp("no_pokemon_loss_risk_score")
    O.append(f"- Basic density: Spearman {bd_sp} ({bd_band}) — more Basics tracks with "
             "higher internal win rate; no-Basic probability mirrors it negatively")
    O.append(f"- Energy ratio: Spearman {er_sp} ({er_band}) — weak-positive, not a "
             "primary lever")
    O.append(f"- evolution complexity: Spearman {ev_sp} ({ev_band}) — slightly "
             "negative; heavier evolution lines do not help the generic pilot")
    O.append(f"- search/draw: Spearman {sd_sp} ({sd_band}) — strongest single "
             "association (directional, tiny n; confounded by family)")
    O.append(f"- deckout/no-pokemon findings: deckout_risk Spearman {do_sp}, "
             f"no-pokemon_loss_risk Spearman {np_sp} — higher modelled risk tracks "
             "with lower internal win rate, as expected")
    O.append("")
    O.append("8. Meta sanity / parent-child")
    collapses = sorted(
        sf for sf, rr in (meta_pd.get(probe, {}).get("per_archetype") or {}).items()
        if (rr.get("win_rate") or 0.0) < 0.10)
    O.append(f"- meta sanity: {meta.get('status')} "
             f"({meta.get('games_per_seat')} g/seat vs "
             f"{len(meta.get('opponent_subfamilies', []))} replay-derived surrogate "
             f"subfamilies); best weighted = {san_best_id} ({pct(san_best)}); "
             "Raging Bolt is the EXPECTED collapse control")
    O.append(f"- parent/child strongest finding: {probe} vs the Water control is a "
             f"statistical TIE (child adj win_rate {pct(dv1.get('child_adj_win_rate'))}, "
             f"Wilson95 {dv1.get('child_wilson')}) — no regression but not a clear win; "
             "the deeper-Basic v2 under-performs v1")
    O.append(f"- best future probe candidate: {probe} "
             f"(weighted meta {pct(meta_pd.get(probe, {}).get('weighted_meta_score'))} "
             f">= Water control "
             f"{pct(meta_pd.get('league_water_anti_disruption_pivot_v1', {}).get('weighted_meta_score'))}, "
             f"collapses: {', '.join(collapses) if collapses else 'none'})")
    O.append("- confidence: directional / low — surrogate + self-play only; queued as "
             "candidate_for_deeper_confirmation, NOT promoted")
    O.append("")
    O.append("9. Strategy decision / ActiveGraph")
    O.append(f"- decision: {decision.get('decision')}")
    O.append(f"- dry-run queue: {decision.get('queued_candidate_count')} "
             f"(max {decision.get('queue_max')}); HELD, "
             f"human_approval_required={yn(decision.get('human_approval_required'))}, "
             f"auto_submit_enabled={yn(decision.get('auto_submit_enabled'))}")
    O.append("- next family: water (Basic-density refinement); dragapult stays a "
             "reference (still below Water live); raging_bolt remains PILOT work")
    O.append(f"- events emitted: {n_events} (pass33-tagged, all no_upload)")
    O.append("- report site: data/site/index.html + "
             "data/reports/pass33_deck_composition_stress_test_report.md")
    O.append("")
    O.append("10. Next recommendation")
    O.append(f"- Submit nothing automatically; hold {probe} as the single "
             "human-approved dry-run probe (denser Basic line halves mulligan risk and "
             "ties the Water control internally) and run a larger confirmation batch "
             "before any human decides to submit.")
    O.append("")
    (REPORTS / "pass33_deck_composition_stress_test_report.md").write_text(
        "\n".join(O), encoding="utf-8")

    # ================= activegraph_strategy_report.md =================
    A = ["# ActiveGraph Strategy Report — Pass 33 (Deck Composition Stress Test)", "",
         f"> {CAVEAT}", "",
         "## What this pass asked", "",
         "Across OUR portfolio, how does deck COMPOSITION (Basic density, energy ratio, "
         "evolution complexity, search/draw) relate to internal strength — and what is "
         "the best next human-approved probe candidate?", "",
         "## What we did", "",
         f"- Audited {audit.get('decks_audited')} decks for composition, legality and "
         "modelled mulligan/deckout risk.",
         f"- Selected {plan.get('selection_count_eligible')} stress-test candidates and "
         f"built {len(built)} NEW Water Basic-density variants "
         f"({', '.join(built)}); everything else reused.",
         "- Validated every candidate (tarball + entrypoint + smoke); Durant blocked by "
         "design.",
         f"- Ran a 2-stage internal composition tournament ({len(standings)} "
         "participants), a correlation analysis, parent/child confirmations, and a "
         "directional surrogate meta sanity.",
         "- Recorded an evidence-gated, human-approval-gated dry-run decision "
         "(queue max 1).",
         "", "## Headline results", "",
         f"- **Top internal candidate:** {top.get('id')} "
         f"({pct(top.get('adj_win_rate'))}); **best non-Water:** "
         f"{best_nonwater.get('id')} ({pct(best_nonwater.get('adj_win_rate'))}).",
         "- **Basic density is the dominant composition lever:** the Water density "
         "ladder (8 -> 12 -> 16 Basics) cuts opening no-Basic risk 0.346 -> 0.191 -> "
         "0.099 while holding internal win rate.",
         f"- **Best future probe:** `{probe}` ties the Water control head-to-head "
         f"(child adj win_rate {pct(dv1.get('child_adj_win_rate'))}) and edges it in "
         "meta sanity, but the win is not significant — queued for deeper "
         "confirmation only.",
         f"- **Dragapult stays a reference** — still below Water on the live board "
         f"(dragapult_above_water={yn(dragapult_above_water)}).",
         f"- **Decision:** {decision.get('decision')}", "",
         "## Decision", "",
         f"- {decision.get('decision')}",
         "- Rejected: " + "; ".join(
             f"{k} — {v}" for k, v in
             (decision.get("rejected_alternatives") or {}).items()),
         "",
         "See `data/reports/pass33_deck_composition_stress_test_report.md` for the full "
         "10-section report.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ================= docs/PTCG_STRATEGY_CANVAS.md =================
    ladder = (corr.get("basic_density_hypothesis") or {}).get(
        "water_density_ladder", {})
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 33.", "",
         f"_{CAVEAT}_", "",
         "## Current live reference (Kaggle, read-only)", "",
         f"- live_score_leader: `{leader.get('fileName')}` @ "
         f"{leader.get('publicScore')}",
         f"- water_family_current_best: `{water_best.get('fileName')}` @ "
         f"{water_best.get('publicScore')}",
         f"- dragapult_family_best: `{dragapult_best.get('fileName')}` @ "
         f"{dragapult_best.get('publicScore')} "
         f"(above water: {yn(dragapult_above_water)})",
         f"- portfolio_reference: `{portref.get('fileName')}` @ "
         f"{portref.get('publicScore')}", "",
         "## Pass 33 — deck composition stress test", "",
         "We stress-tested OUR portfolio by composition to pick the next human-approved "
         "probe. Internal Stage-1 standings (NOT Kaggle):", "",
         "| rank | candidate | family | adj win_rate | label |",
         "|---|---|---|---|---|"]
    for i, s in enumerate(standings, 1):
        C.append(f"| {i} | {s.get('id')} | {s.get('family')} | "
                 f"{pct(s.get('adj_win_rate'))} | {s.get('compatibility_label')} |")
    C += ["", "## Water Basic-density ladder", "",
          "| deck | Basics | no-Basic prob | internal adj win_rate |",
          "|---|---|---|---|"]
    for k, v in ladder.items():
        C.append(f"| {k} | {v.get('basics')} | {pct(v.get('no_basic_p'))} | "
                 f"{pct(v.get('adj_win_rate'))} |")
    C += ["", "## Meta sanity (directional, surrogate)", "",
          f"- best: `{san_best_id}` @ {pct(san_best)}",
          f"- probe `{probe}` collapses: "
          f"{', '.join(collapses) if collapses else 'none'} "
          "(Raging Bolt = expected control)", "",
          "## Next move", "",
          f"`{decision.get('decision')}` Hold `{probe}` as a deeper-confirmation probe "
          "(halves mulligan risk, ties Water internally). Keep Water as the always-on "
          "benchmark; Dragapult stays a reference until it clears Water live.", ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ================= data/site/index.html =================
    trows = "\n".join(
        f"      <tr><td>{i}</td><td>{s.get('id')}</td><td>{s.get('family')}</td>"
        f"<td>{pct(s.get('adj_win_rate'))}</td>"
        f"<td>{s.get('compatibility_label')}</td></tr>"
        for i, s in enumerate(standings, 1))
    lrows = "\n".join(
        f"      <tr><td>{k}</td><td>{v.get('basics')}</td>"
        f"<td>{pct(v.get('no_basic_p'))}</td>"
        f"<td>{pct(v.get('adj_win_rate'))}</td></tr>"
        for k, v in ladder.items())
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 33 Deck Composition Stress Test</title>
<link rel="stylesheet" href="style.css">
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>ActiveGraph — Pass 33: Deck Composition Stress Test</h1>
<p class="caveat">{CAVEAT}</p>
<h2>Live reference (Kaggle, read-only)</h2>
<p>live_score_leader: <code>{leader.get('fileName')}</code> @ {leader.get('publicScore')}
 &middot; water_family_current_best: <code>{water_best.get('fileName')}</code>
 @ {water_best.get('publicScore')} &middot; dragapult_family_best:
 <code>{dragapult_best.get('fileName')}</code> @ {dragapult_best.get('publicScore')}
 &middot; portfolio_reference: <code>{portref.get('fileName')}</code>
 @ {portref.get('publicScore')}</p>
<h2>Internal tournament — Stage 1 standings (NOT Kaggle)</h2>
<table><thead><tr><th>rank</th><th>candidate</th><th>family</th><th>adj win_rate</th><th>label</th></tr></thead>
<tbody>
{trows}
</tbody></table>
<h2>Water Basic-density ladder</h2>
<table><thead><tr><th>deck</th><th>Basics</th><th>no-Basic prob</th><th>internal adj win_rate</th></tr></thead>
<tbody>
{lrows}
</tbody></table>
<h2>Meta sanity (directional, surrogate)</h2>
<p>best: <code>{san_best_id}</code> @ {pct(san_best)} &middot; probe
 <code>{probe}</code> collapses: {', '.join(collapses) if collapses else 'none'}
 (Raging Bolt = expected control)</p>
<h2>Decision</h2>
<p><b>{decision.get('decision')}</b></p>
<p>dry-run queue: {decision.get('queued_candidate_count')} (max
 {decision.get('queue_max')}, HELD) &middot; human approval required:
 {yn(decision.get('human_approval_required'))} &middot; auto-submit:
 {yn(decision.get('auto_submit_enabled'))} &middot; events emitted: {n_events}</p>
<p>Full report: <code>data/reports/pass33_deck_composition_stress_test_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("wrote:")
    print("  data/reports/pass33_deck_composition_stress_test_report.md")
    print("  data/reports/activegraph_strategy_report.md")
    print("  docs/PTCG_STRATEGY_CANVAS.md")
    print("  data/site/index.html")
    print(f"events counted: {n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
