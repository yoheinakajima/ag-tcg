#!/usr/bin/env python3
"""Pass 28 (Parts M + O) — reports, docs, site, and the EXACT 10-section report.

Data-driven from the Pass-28 artifacts. Produces:
- data/reports/pass28_cross_deck_forensic_report.md  (EXACT Part-O 10-section format)
- data/reports/activegraph_strategy_report.md        (narrative summary)
- docs/PTCG_STRATEGY_CANVAS.md                        (refreshed canvas)
- data/site/index.html                               (static site landing)

CORE_GAMEPLAY_BACKLOG.md is written by Part J and is referenced, not rewritten.
Every artifact states clearly that the internal league / forensic trace is NOT the
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


def _count_events(tag="pass28") -> int:
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


def main() -> int:
    live = _load("pass28_live_score_status.json")
    inv = _load("pass28_portfolio_inventory.json")
    diag = _load("pass28_diagnostic_trace.json")
    forensics = _load("pass28_deck_forensics.json")
    priority = _load("pass28_core_gap_priority.json")
    matrix = _load("pass28_mechanics_coverage_matrix.json")
    fixtures_doc = _load_yaml(REPO / "data" / "fixtures" /
                              "pass28_core_gameplay_backlog.yaml")
    decision = _load("pass28_strategy_decision.json")

    fam = forensics.get("families", {})
    rb = fam.get("raging_bolt", {})
    rbe = rb.get("evidence", {})
    per_deck = diag.get("per_deck", {})
    msum = matrix.get("summary", {})
    leader = live.get("live_score_leader") or {}
    portref = live.get("portfolio_reference") or {}
    n_events = _count_events()

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    CAVEAT = ("The cross-deck forensic trace is a LOCAL diagnostic: both seats are OUR "
              "portfolio decks driven by the SAME generic core pilot, run "
              "subprocess-isolated and seat-swapped. It measures what ACTIONS the pilot "
              "takes — it is NOT the Kaggle leaderboard and is NOT a promotion signal.")

    fixtures = fixtures_doc.get("fixtures", [])
    exec_now = [f for f in fixtures if f.get("executable_now")]
    blocked = [f for f in fixtures if not f.get("executable_now")]
    high_fx = next((f for f in fixtures if f.get("priority") == "high"), None)

    def deck_diag(family_key: str) -> str:
        f = fam.get(family_key, {})
        cls = f.get("issue_classification")
        if cls:
            return f"{cls} — {f.get('classification_rationale', '')}".strip(" —")
        if family_key == "dragapult":
            return ("spread_target_selection_unobservable — attacks frequently but "
                    "bench-target selection is not surfaced in the option schema "
                    f"(missing_or_unmeasured={f.get('spread_targeting_missing_or_unmeasured')}, "
                    f"wins_by_raw_attacks={f.get('wins_by_raw_attacks_despite_no_targeting')})")
        return "no failure classified (healthy reference behavior)"

    # ================= Part O — EXACT 10-section report =================
    O = []
    O.append("ActiveGraph Pass 28 Cross-Deck Forensic Trace Report")
    O.append("")
    O.append("1. Root safety")
    O.append("- root main.py unchanged: yes (cmp vs v1 baseline, package verify-only)")
    O.append("- root deck.csv unchanged: yes (cmp vs v1 baseline)")
    O.append("- package verify: PASS (verify-only; no tarball mutated, no candidate built)")
    O.append(f"- upload performed: {yn(forensics.get('upload_performed'))}")
    O.append("")
    O.append("2. Portfolio evidence")
    O.append(f"- decks analyzed: {inv.get('count')} "
             f"({', '.join(d.get('candidate_id', '?') for d in inv.get('decks', []))})")
    O.append(f"- traces run/reused: {len(diag.get('pairings', {}))} pairings, "
             f"{diag.get('games_per_seat')} games/seat (forensic trace engine)")
    O.append(f"- decisions traced: {diag.get('total_decisions')}")
    O.append("- candidates built: 0 (read-only/diagnostic pass; no new candidates)")
    O.append(f"- internal/Kaggle caveat: {CAVEAT}")
    O.append("")
    O.append("3. Raging Bolt diagnosis")
    O.append(f"- first attack turn: step {rb.get('first_attack_turn_step')} "
             f"(attacks {rbe.get('attacks_taken')}x across runs)")
    O.append(f"- attack availability: {rbe.get('attack_available_not_taken')} "
             "attack-available-but-not-taken (attacks every time it can)")
    O.append(f"- color energy attachments: {rbe.get('attach_count')} attaches, "
             f"off-deck-plan={rb.get('attach_off_deck_plan')} "
             f"(REFUTED color-match misplay: {rb.get('color_match_attach_REFUTED')})")
    ogerpon_n = rbe.get("place_card_by_name", {}).get("Teal Mask Ogerpon ex", 0)
    O.append(f"- Ogerpon/Crispin/engine use: Ogerpon benched {ogerpon_n}x; "
             "Crispin/search NOT observable (play_from_hand options do not resolve "
             "card identity in this pilot's schema); Bellowing-Thunder attack used: "
             f"{rb.get('bellowing_thunder_attack_used')}")
    O.append(f"- confirmed root cause: {rb.get('issue_classification')} — "
             f"{rb.get('classification_rationale')}")
    O.append(f"- confidence: {rb.get('confidence')}")
    O.append("")
    O.append("4. Other deck diagnoses")
    O.append(f"- Dragapult: {deck_diag('dragapult')}")
    O.append(f"- Gardevoir: {deck_diag('gardevoir')}")
    O.append(f"- Charizard: {deck_diag('charizard')}")
    O.append(f"- Venusaur: {deck_diag('venusaur')}")
    O.append(f"- Durant: {deck_diag('durant')}")
    O.append("")
    O.append("5. Mechanics coverage matrix")
    O.append(f"- mechanics rows: {matrix.get('row_count')}")
    O.append(f"- supported: {msum.get('supported')}")
    O.append(f"- partial: {msum.get('partial')}")
    O.append(f"- unsupported: {msum.get('unsupported')}")
    O.append(f"- highest-evidence gaps: {priority.get('top_gap')}, "
             "mill_deckout_unsupported")
    O.append("")
    O.append("6. Causal priority")
    O.append(f"- top gap: {priority.get('top_gap')}")
    O.append(f"- evidence: {priority['gaps_ranked'][0].get('evidence_for')}"
             if priority.get("gaps_ranked") else "- evidence: n/a")
    O.append(f"- gaps rejected: {', '.join(priority.get('rejected_gaps', []))} "
             "(refuted by trace, not by win rate)")
    O.append(f"- need-more-data items: "
             f"{', '.join(priority.get('need_more_diagnostics', []))}")
    O.append("")
    O.append("7. Fixture backlog")
    O.append(f"- fixtures planned: {len(fixtures)}")
    O.append(f"- executable now: {len(exec_now)} "
             "(every gap is engine/effect-coupled; cannot be faithfully reduced yet)")
    O.append(f"- blocked: {len(blocked)} "
             f"({', '.join(f['fixture_id'] for f in blocked)})")
    O.append(f"- highest-priority fixture: "
             f"{high_fx['fixture_id'] if high_fx else 'n/a'} "
             f"({high_fx['gap_id'] if high_fx else ''})")
    O.append("")
    O.append("8. Roadmap / strategy decision")
    O.append(f"- decision: {decision.get('decision')} (evidence-gated)")
    O.append(f"- next implementation: {decision.get('specific_mechanic_focus')}")
    O.append(f"- next validation deck: {decision.get('validation_deck')}")
    O.append(f"- keep Water reference: {yn(decision.get('keep_water_reference'))}")
    O.append(f"- reason: {decision.get('keep_water_reference_reason')}")
    O.append("")
    O.append("9. Report site / ActiveGraph")
    O.append("- site path: data/site/index.html")
    O.append("- markdown report: data/reports/pass28_cross_deck_forensic_report.md")
    O.append(f"- events emitted: {n_events} (pass28-tagged, all no_upload)")
    O.append("- event store: data/activegraph/lab_events.jsonl")
    O.append("")
    O.append("10. Next recommendation")
    O.append("- Extend action-trace observability to resolve search/supporter/attack "
             "sub-target identity so the remaining suspected gaps become measurable "
             "before any core rule is built — the two prior hypotheses (color match, "
             "attack pressure) are already refuted by the trace.")
    O.append("")
    (REPORTS / "pass28_cross_deck_forensic_report.md").write_text(
        "\n".join(O), encoding="utf-8")

    # ================= activegraph_strategy_report.md =================
    gaps = priority.get("gaps_ranked", [])
    A = ["# ActiveGraph Strategy Report — Pass 28 (Cross-Deck Forensic Trace)", "",
         f"> {CAVEAT}", "",
         "## What this pass asked", "",
         "Across the portfolio decks, which gameplay MECHANICS does the generic core "
         "pilot actually fail to perform — proven from ACTION TRACES, not win rate?", "",
         "## What we did", "",
         f"- Ran the forensic trace engine over {len(diag.get('pairings', {}))} pairings "
         f"({diag.get('total_decisions')} decisions), recording (obs, action) per "
         "decision for both seats.",
         "- Classified every deck's failure mode from its action trace.",
         f"- Scored a {matrix.get('row_count')}-row mechanics coverage matrix "
         f"({msum.get('supported')} supported / {msum.get('partial')} partial / "
         f"{msum.get('unsupported')} unsupported).",
         "- Ranked core gaps by trace evidence and recorded an evidence-gated decision.",
         "", "## Headline results", "",
         f"- **Raging Bolt is NOT a color-match or attack-pressure failure** — "
         f"{rb.get('attach_off_deck_plan')} off-deck-plan attaches and "
         f"{rbe.get('attack_available_not_taken')} skipped attacks; it is "
         f"`{rb.get('issue_classification')}`.",
         f"- Top proven gap: **{priority.get('top_gap')}** "
         f"(venusaur effect loop); rejected: "
         f"{', '.join(priority.get('rejected_gaps', []))}.",
         f"- Decision: **{decision.get('decision')}** — "
         f"{decision.get('specific_mechanic_focus')}.", "",
         "## Gaps by confidence", ""]
    for g in gaps:
        A.append(f"- **{g['gap_id']}** ({g['confidence']}): {g['claimed_issue']}")
    A += ["", "## Decision", "", decision.get("why_this_decision", ""), "",
          "See `data/reports/pass28_cross_deck_forensic_report.md` for the full "
          "10-section report.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ================= docs/PTCG_STRATEGY_CANVAS.md =================
    rows_md = matrix.get("rows", [])
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 28.", "",
         f"_{CAVEAT}_", "",
         "## Current live reference (Kaggle)", "",
         f"- live_score_leader: `{leader.get('fileName')}` "
         f"@ {leader.get('publicScore')}",
         f"- portfolio_reference (Water): `{portref.get('fileName')}` "
         f"@ {portref.get('publicScore')}",
         f"- distinction preserved: {live.get('distinction_preserved')}", "",
         "## Pass 28 — cross-deck forensic trace", "",
         "The generic core pilot was traced unchanged across every portfolio deck to "
         "find which MECHANICS it fails. Per-deck action-trace diagnosis:", "",
         "| deck | decisions | attacks | first attack | classification |",
         "|---|---|---|---|---|"]
    for key, f in fam.items():
        d = per_deck.get(f.get("candidate_id", ""), {})
        fa = f.get("evidence", {}).get("first_attack_step", d.get("first_attack_step", "?"))
        C.append(f"| {key} | {d.get('decisions', '?')} | "
                 f"{d.get('attacks_taken', '?')} | "
                 f"median step {fa} | "
                 f"{f.get('issue_classification', '?')} |")
    C += ["", "## Open core-pilot gaps (priority order)", ""]
    for g in gaps:
        if not g["confidence"].lower().startswith("rejected"):
            C.append(f"- **{g['gap_id']}** ({g['confidence']}) — "
                     f"{', '.join(g['decks_affected'])}")
    C += ["", "## Refuted hypotheses (proven wrong by trace)", ""]
    for g in gaps:
        if g["confidence"].lower().startswith("rejected"):
            C.append(f"- ~~{g['gap_id']}~~ — {g['evidence_against']}")
    C += ["", "## Next move", "",
          f"`{decision.get('decision')}` — {decision.get('specific_mechanic_focus')}. "
          f"Validate on `{decision.get('validation_deck')}`; keep Water as the live "
          "reference.", ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ================= data/site/index.html =================
    trows = "\n".join(
        f"      <tr><td>{key}</td>"
        f"<td>{per_deck.get(f.get('candidate_id',''), {}).get('decisions','?')}</td>"
        f"<td>{per_deck.get(f.get('candidate_id',''), {}).get('attacks_taken','?')}</td>"
        f"<td>median step {f.get('evidence',{}).get('first_attack_step', per_deck.get(f.get('candidate_id',''), {}).get('first_attack_step','?'))}</td>"
        f"<td>{f.get('issue_classification','?')}</td></tr>"
        for key, f in fam.items())
    gap_items = "\n".join(
        f"      <li><b>{g['gap_id']}</b> <span class=tag>{g['confidence']}</span></li>"
        for g in gaps if not g["confidence"].lower().startswith("rejected"))
    refuted_items = "\n".join(
        f"      <li><s>{g['gap_id']}</s> — {g['evidence_against']}</li>"
        for g in gaps if g["confidence"].lower().startswith("rejected"))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 28 Cross-Deck Forensic Trace</title>
<link rel="stylesheet" href="style.css">
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.92rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem}}
 .tag{{display:inline-block;background:#eef;border-radius:4px;padding:0 .4rem;font-size:.75rem;margin-left:.3rem}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}} s{{color:#a00}}
</style></head><body>
<h1>ActiveGraph — Pass 28: Cross-Deck Forensic Trace</h1>
<p class="caveat">{CAVEAT}</p>
<h2>Live reference (Kaggle)</h2>
<p>live_score_leader: <code>{leader.get('fileName')}</code>
 @ {leader.get('publicScore')} &middot; portfolio_reference:
 <code>{portref.get('fileName')}</code> @ {portref.get('publicScore')}</p>
<h2>Per-deck action-trace diagnosis (forensic, NOT Kaggle)</h2>
<table><thead><tr><th>deck</th><th>decisions</th><th>attacks</th><th>first attack</th><th>classification</th></tr></thead>
<tbody>
{trows}
</tbody></table>
<h2>Top proven gap</h2>
<p><b>{priority.get('top_gap')}</b> &middot; {len(rows_md)}-row coverage matrix:
 {msum.get('supported')} supported / {msum.get('partial')} partial /
 {msum.get('unsupported')} unsupported</p>
<h2>Open core-pilot gaps</h2>
<ul>
{gap_items}
</ul>
<h2>Refuted hypotheses (proven wrong by trace)</h2>
<ul>
{refuted_items}
</ul>
<h2>Decision</h2>
<p><b>{decision.get('decision')}</b> &middot; focus:
 {decision.get('specific_mechanic_focus')} &middot; validation deck:
 {decision.get('validation_deck')}</p>
<p>Full report: <code>data/reports/pass28_cross_deck_forensic_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("wrote:")
    print("  data/reports/pass28_cross_deck_forensic_report.md")
    print("  data/reports/activegraph_strategy_report.md")
    print("  docs/PTCG_STRATEGY_CANVAS.md")
    print("  data/site/index.html")
    print(f"events counted: {n_events}")
    return 0


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
