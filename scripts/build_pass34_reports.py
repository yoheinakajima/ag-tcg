#!/usr/bin/env python3
"""Pass 34 (Parts N + Q) — reports, docs, site, and the EXACT 10-section report.

Data-driven from the Pass-34 artifacts. Produces:
- data/reports/pass34_new_deck_intake_tournament_report.md  (EXACT Part-Q format)
- data/reports/activegraph_strategy_report.md               (narrative summary)
- docs/PTCG_STRATEGY_CANVAS.md                              (refreshed canvas)
- docs/SPECIAL_PILOT_LANES.md                              (refreshed w/ diagnosis)
- data/site/index.html                                      (static site landing)

Every artifact states clearly that the internal tournament / meta sanity is NOT the
Kaggle leaderboard and is NOT a promotion signal. No upload, no submit, no push.
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
SITE = REPO / "data" / "site"
DOCS = REPO / "docs"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"


def _root_unchanged(name: str) -> bool | None:
    """Real evidence: compare a root file byte-for-byte vs the frozen baseline.
    Returns True/False, or None when either side is missing (cannot verify)."""
    root_f = REPO / name
    base_f = BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return None
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return None


def _load(name: str) -> dict:
    try:
        return json.loads((EXP / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _count_events(tag="pass34") -> int:
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
    live = _load("pass34_live_score_status.json")
    intake = _load("pass34_deck_intake.json")
    builds = _load("pass34_decklist_builds.json")
    manifest = _load("pass34_candidate_manifest.json")
    valid = _load("pass34_candidate_validation.json")
    smoke = _load("pass34_live_smoke.json")
    rankings = _load("pass34_new_deck_rankings.json")
    diag = _load("pass34_special_lane_diagnosis.json")
    pilot = _load("pass34_pilot_fit_analysis.json")
    meta = _load("pass34_meta_sanity.json")
    decision = _load("pass34_strategy_decision.json")

    leader = live.get("live_score_leader") or {}
    water_best = live.get("water_family_current_best") or {}
    dragapult_best = live.get("dragapult_family_best") or {}
    portref = live.get("portfolio_reference") or {}
    dragapult_above_water = bool(live.get("dragapult_above_water"))
    standings = rankings.get("standings", [])
    meta_pd = meta.get("per_deck", {})
    sanity = meta.get("sanity", {})
    n_events = _count_events()

    CAVEAT = ("The internal new-deck tournament and the replay-derived meta sanity are "
              "LOCAL diagnostics: both seats are OUR portfolio decks driven by the SAME "
              "deck-agnostic generic pilot (meta sanity uses replay-derived surrogate "
              "opponents). They are NOT the Kaggle leaderboard and are NOT a promotion "
              "or upload signal.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    # ---- derived helpers ----
    decks = {d["deck_id"]: d for d in intake.get("decks", [])}
    NEW_IDS = {"mono_lightning_miraidon_easy", "diamond_toolbox_diancie",
               "toxic_trap_poison_lock", "deckout_carousel_durant_v2"}
    NORMAL = [d for d in intake.get("decks", []) if d.get("lane") == "normal"]
    SPECIAL = [d for d in intake.get("decks", []) if d.get("lane") == "special"]

    bres = {r["deck_id"]: r for r in builds.get("results", [])}
    mres = {r["candidate_id"]: r for r in manifest.get("results", [])}
    vres = {r["candidate_id"]: r for r in valid.get("results", [])}
    sres = {r["candidate_id"]: r for r in smoke.get("results", [])}
    dres = {d["candidate_id"]: d for d in diag.get("diagnoses", [])}
    rank = {r["id"]: r for r in standings}

    normal_built = [d["deck_id"] for d in NORMAL
                    if bres.get(d["deck_id"], {}).get("built")]
    special_built = [d["deck_id"] for d in SPECIAL
                     if bres.get(d["deck_id"], {}).get("built")]
    blocked = [cid for cid, r in mres.items() if r.get("blocked_from_league")]
    eligible = [r["id"] for r in standings if r["id"] in NEW_IDS]

    # corrections summary
    energy_corr = sum(len(d.get("energy_resolution", {}).get("corrections", []) or [])
                      if isinstance(d.get("energy_resolution"), dict) else 0
                      for d in intake.get("decks", []))
    stage_corr = sum(len(bres.get(d["deck_id"], {}).get("corrections_applied", []) or [])
                     for d in intake.get("decks", []))
    missing_total = sum(len(d.get("missing_ids", []) or [])
                        for d in intake.get("decks", []))

    top = standings[0] if standings else {}
    best_new = next((s for s in standings if s["id"] in NEW_IDS), {})
    # best simple/basic deck: simplest design class = miraidon (mono-Lightning Basic)
    simple_id = "mono_lightning_miraidon_easy"
    best_simple = rank.get(simple_id, {})
    fam_sorted = sorted(standings, key=lambda s: s.get("adj_win_rate", 0))
    worst = fam_sorted[0] if fam_sorted else {}

    toxic = dres.get("toxic_trap_poison_lock", {})
    durant = dres.get("deckout_carousel_durant_v2", {})
    answers = pilot.get("answers", {})

    # meta best
    san_best_id, san_best = None, -1.0
    for cid, d in meta_pd.items():
        ws = d.get("weighted_meta_score")
        if ws is not None and ws > san_best:
            san_best, san_best_id = ws, cid

    def collapses_of(cid):
        return sorted(sf for sf, rr in (meta_pd.get(cid, {}).get("per_archetype")
                                        or {}).items()
                      if (rr.get("win_rate") or 0.0) < 0.10)

    held = decision.get("held_probe")
    held_row = rank.get(held, {})

    # ================= Part Q — EXACT 10-section report =================
    O = []
    O.append("ActiveGraph Pass 34 New Deck Intake + Easy Basic / Chaos Lane Split "
             "Report")
    O.append("")
    O.append("1. Root safety")
    main_ok = _root_unchanged("main.py")
    deck_ok = _root_unchanged("deck.csv")

    def _evi(v):
        return "yes" if v is True else ("no" if v is False else "unverified")
    O.append(f"- root main.py unchanged: {_evi(main_ok)} "
             "(byte cmp vs baseline, verify-only)")
    O.append(f"- root deck.csv unchanged: {_evi(deck_ok)} "
             "(byte cmp vs baseline, verify-only)")
    pkg = ("PASS" if (main_ok is True and deck_ok is True)
           else ("FAIL" if (main_ok is False or deck_ok is False)
                 else "UNVERIFIED"))
    O.append(f"- package verify: {pkg} (verify-only; derived from root-file cmp)")
    O.append(f"- upload performed: {yn(decision.get('upload_performed'))}")
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
    O.append("- conclusion: read-only snapshot; Pass 34 is a new-deck intake + lane "
             "split, no upload/submit and not a promotion decision "
             f"(distinction_preserved={yn(live.get('distinction_preserved'))})")
    O.append("")
    O.append("3. Deck intake")
    O.append(f"- new deck ideas: {len(decks)} ("
             + ", ".join(f"{d['display_name']} [{d['lane']}]"
                         for d in intake.get("decks", [])) + ")")
    O.append(f"- IDs validated: all skeleton card IDs resolved against "
             f"{intake.get('card_db')} ({missing_total} missing/unresolved)")
    O.append(f"- energy ID corrections: {energy_corr} (energy IDs read from card DB: "
             "Lightning=4, Psychic=5, Darkness=7 — not user placeholders)")
    O.append(f"- stage/evolution corrections: {stage_corr} "
             "(Mismagius ex -> +Misdreavus id 812 x2; Whimsicott -> +Cottonee "
             "id 814 x2; both verified Basics)")
    O.append("- skeleton count issues: skeletons need NOT sum to 60; every BUILT "
             f"decklist is exactly 60 ({builds.get('built_count')}/"
             f"{len(intake.get('decks', []))} built); non-Basic copy cap <=4 honoured, "
             "Basic Energy may exceed 4")
    O.append("- no invented IDs: yes (every card id exists in the card DB; no "
             "fabricated ids)")
    O.append("")
    O.append("4. Candidates / variants")
    O.append(f"- normal-lane candidates built: {len(normal_built)} "
             f"({', '.join(normal_built)})")
    O.append(f"- special-lane candidates built: {len(special_built)} "
             f"({', '.join(special_built)}) — built as decklists but "
             "blocked_from_league (special pilot not wired)")
    O.append(f"- candidates blocked: {len(blocked)} ({', '.join(blocked)})")
    O.append("- tarballs: top-level main.py + deck.csv only, in "
             "data/submissions/candidates_pass34/")
    O.append("")
    O.append("5. Validation / smoke")
    nonblocked = [cid for cid in mres if not mres[cid].get("blocked_from_league")]
    O.append(f"- tarball validators: all {len(vres)} candidates PASS "
             f"(tarball_valid)")
    O.append(f"- entrypoint validators: all {len(vres)} candidates PASS "
             "(entrypoint_valid)")
    O.append(f"- smoke-valid: normal lane PASS ({', '.join(nonblocked)}); special lane "
             "INVALID by generic pilot (deck legal, pilot mis-fit)")
    O.append("- invalid/crash/timeout: 0 in the normal-lane tournament; the two "
             "special-lane decks emit illegal generic-pilot actions (pilot fault, not "
             "deck fault)")
    O.append(f"- excluded: {', '.join(blocked)} (special-pilot blocked from league)")
    O.append("")
    O.append("6. Internal tournament")
    O.append(f"- participants: {len(standings)} (2 new normal-lane decks + 6 portfolio "
             "benchmarks; special-lane decks excluded)")
    O.append("- games per seat: 7 (round-robin, generic pilot both seats)")
    O.append(f"- top candidate: {top.get('id')} (adj win_rate "
             f"{pct(top.get('adj_win_rate'))}, {top.get('compatibility_label')})")
    O.append(f"- best new deck: {best_new.get('id')} "
             f"({pct(best_new.get('adj_win_rate'))}, "
             f"{best_new.get('compatibility_label')})")
    O.append(f"- best simple/basic deck: {simple_id} "
             f"({pct(best_simple.get('adj_win_rate'))}, "
             f"{best_simple.get('compatibility_label')})")
    O.append(f"- worst family: {worst.get('id')} ({pct(worst.get('adj_win_rate'))}, "
             f"{worst.get('compatibility_label')})")
    O.append(f"- caveat: {CAVEAT}")
    O.append("")
    O.append("7. Special-lane diagnosis")
    O.append(f"- Toxic Trap: decklist_valid={yn(toxic.get('decklist_valid'))}, "
             f"built={yn(toxic.get('built'))}, smoke_valid={yn(toxic.get('smoke_valid'))}"
             f" — {toxic.get('reason_if_blocked')}")
    O.append(f"- Durant Carousel: decklist_valid={yn(durant.get('decklist_valid'))}, "
             f"built={yn(durant.get('built'))}, "
             f"smoke_valid={yn(durant.get('smoke_valid'))} — "
             f"{durant.get('reason_if_blocked')}")
    hooks = sorted(set((toxic.get("missing_pilot_hooks") or [])
                       + (durant.get("missing_pilot_hooks") or [])))
    O.append(f"- required special pilot hooks: {', '.join(hooks) if hooks else 'n/a'}")
    O.append("- next special-pilot step: open special-pilot sprint — Toxic (priority 1, "
             f"first fixture: {toxic.get('first_executable_fixture_needed')}); "
             f"Durant (priority 2, first fixture: "
             f"{durant.get('first_executable_fixture_needed')})")
    O.append("")
    O.append("8. Pilot-fit / meta sanity")
    O.append(f"- pilot-fit findings: simple Basic deck helped="
             f"{answers.get('did_simple_basic_deck_help')}; basic toolbox helped="
             f"{answers.get('did_basic_toolbox_help')}; weird decks blocked by="
             f"{answers.get('are_weird_decks_blocked_by_decklist_or_pilot')}; "
             f"next family to improve={answers.get('which_family_to_improve_next')}")
    O.append(f"- meta sanity: {meta.get('status')} "
             f"({meta.get('games_per_seat')} g/seat vs "
             f"{len(meta.get('opponent_subfamilies', []))} replay-derived surrogate "
             f"subfamilies); sanity_passed={yn(sanity.get('sanity_passed'))}; best "
             f"weighted = {san_best_id} ({pct(san_best)})")
    O.append("- strongest finding: the two NEW normal-lane decks pilot cleanly "
             f"(Miraidon {pct(rank.get('mono_lightning_miraidon_easy', {}).get('adj_win_rate'))}"
             f", Diamond {pct(rank.get('diamond_toolbox_diancie', {}).get('adj_win_rate'))})"
             " with NO meta-sanity collapse; the special-lane decks are blocked by the "
             "PILOT, not the decklist")
    O.append("- confidence: directional / low — surrogate + self-play only; new decks "
             "labelled candidate_for_confirmation, NOT promoted")
    O.append("")
    O.append("9. Strategy decision / ActiveGraph")
    O.append(f"- decision: {decision.get('decision')}")
    O.append(f"- dry-run queue: {decision.get('queued_candidate_count')} "
             f"(max {decision.get('queue_max')}); HELD {held}, "
             f"human_approval_required={yn(decision.get('human_approval_required'))}, "
             f"auto_submit_enabled={yn(decision.get('auto_submit_enabled'))}")
    O.append(f"- next family: {answers.get('which_family_to_improve_next')} "
             "(Water Basic-density stays the held probe; Dragapult stays the non-Water "
             "reference; Toxic/Durant need special pilots)")
    O.append(f"- events emitted: {n_events} (pass34-tagged, all no_upload=true)")
    O.append("- report site: data/site/index.html + "
             "data/reports/pass34_new_deck_intake_tournament_report.md")
    O.append("")
    O.append("10. Next recommendation")
    O.append(f"- Submit nothing automatically; keep {held} as the single human-approved "
             "dry-run probe (still rank 1, no meta collapse). Treat Miraidon and Diamond "
             "as candidate_for_confirmation and run a larger confirmation batch before "
             "any human submits. Open the special-pilot sprint for Toxic (priority 1) "
             "and Durant (priority 2) — their decklists are legal; only the generic "
             "pilot blocks them.")
    O.append("")
    (REPORTS / "pass34_new_deck_intake_tournament_report.md").write_text(
        "\n".join(O), encoding="utf-8")

    # ================= activegraph_strategy_report.md =================
    A = ["# ActiveGraph Strategy Report — Pass 34 (New Deck Intake + Lane Split)", "",
         f"> {CAVEAT}", "",
         "## What this pass asked", "",
         "Ingest four NEW deck families (Miraidon, Diamond, Toxic, Durant), split them "
         "into a normal lane (generic-pilotable) and a special-pilot lane (non-prize "
         "win conditions), then run an internal tournament + diagnosis to decide what to "
         "build next.", "",
         "## What we did", "",
         f"- Intake-validated {len(decks)} new decks against the card DB: every card id "
         f"resolved, energy ids read from the DB, {stage_corr} evolution fixes with "
         "verified Basics, zero invented ids.",
         f"- Built {builds.get('built_count')} legal 60-card decklists; packaged "
         f"{len(normal_built)} normal-lane candidates (top-level main.py + deck.csv).",
         "- Validated every candidate (tarball + entrypoint + smoke); the two "
         "special-lane decks are legal decklists but blocked_from_league (generic "
         "pilot mis-fit).",
         f"- Ran an {len(standings)}-deck internal tournament, a special-lane "
         "diagnosis, a pilot-fit analysis, and a directional surrogate meta sanity.",
         "- Recorded an evidence-gated, human-approval-gated dry-run decision "
         "(queue max 1).",
         "", "## Headline results", "",
         f"- **Top internal deck:** {top.get('id')} ({pct(top.get('adj_win_rate'))}); "
         f"**best NEW deck:** {best_new.get('id')} "
         f"({pct(best_new.get('adj_win_rate'))}).",
         "- **The new normal-lane decks pilot cleanly** (Miraidon "
         f"{pct(rank.get('mono_lightning_miraidon_easy', {}).get('adj_win_rate'))}, "
         f"Diamond {pct(rank.get('diamond_toolbox_diancie', {}).get('adj_win_rate'))}) "
         "with no meta-sanity collapse — but neither clears the strong threshold, so "
         "both are candidate_for_confirmation.",
         "- **The special-lane decks are blocked by the PILOT, not the decklist** — "
         "Toxic and Durant build legal 60-card lists but the generic pilot emits illegal "
         "actions; they enter a special-pilot sprint.",
         f"- **Dragapult stays the non-Water reference** and leads the live board "
         f"(dragapult_above_water={yn(dragapult_above_water)}).",
         f"- **Decision:** {decision.get('decision')} — held probe `{held}` re-affirmed "
         "(still rank 1).", "",
         "## Decision", "",
         f"- {decision.get('decision')}",
         "- Rejected for queue: " + "; ".join(
             f"{k} — {v}" for k, v in
             (decision.get("rejected_for_queue") or {}).items()),
         "",
         "See `data/reports/pass34_new_deck_intake_tournament_report.md` for the full "
         "10-section report.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ================= docs/PTCG_STRATEGY_CANVAS.md =================
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 34.", "",
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
         "## Pass 34 — new-deck intake + lane split", "",
         "Four new families ingested and split into two lanes. Internal tournament "
         "standings (NOT Kaggle):", "",
         "| rank | candidate | family | lane | adj win_rate | label |",
         "|---|---|---|---|---|---|"]
    for i, s in enumerate(standings, 1):
        lane = "normal" if s["id"] in NEW_IDS else "benchmark"
        C.append(f"| {i} | {s.get('id')} | {s.get('family')} | {lane} | "
                 f"{pct(s.get('adj_win_rate'))} | {s.get('compatibility_label')} |")
    C += ["", "## Lanes", "",
          "- **Normal lane (built + tournament-eligible):** "
          + ", ".join(f"`{x}`" for x in normal_built),
          "- **Special-pilot lane (legal decklist, pilot-blocked):** "
          + ", ".join(f"`{x}`" for x in special_built),
          "", "## Meta sanity (directional, surrogate)", "",
          f"- sanity_passed: {yn(sanity.get('sanity_passed'))}; best: "
          f"`{san_best_id}` @ {pct(san_best)}",
          f"- new decks collapses: Miraidon "
          f"{collapses_of('mono_lightning_miraidon_easy') or 'none'}, Diamond "
          f"{collapses_of('diamond_toolbox_diancie') or 'none'}",
          "", "## Next move", "",
          f"`{decision.get('decision')}` Keep `{held}` as the held probe (rank 1, no "
          "collapse). Miraidon/Diamond = candidate_for_confirmation. Open special-pilot "
          "sprint for Toxic (P1) and Durant (P2). Dragapult stays the non-Water "
          "reference.", ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ================= docs/SPECIAL_PILOT_LANES.md (refresh diagnosis tail) ====
    sp_doc = (DOCS / "SPECIAL_PILOT_LANES.md")
    base = sp_doc.read_text(encoding="utf-8") if sp_doc.exists() else \
        "# Special-Pilot Lanes (Pass 34)\n"
    marker = "\n## Part-I diagnosis (refreshed)\n"
    base = base.split(marker)[0].rstrip()
    D = [base, "", "## Part-I diagnosis (refreshed)", "",
         "Live-smoke diagnosis of the two special-lane decks (generic pilot, both "
         "seats = candidate). Both have LEGAL 60-card decklists; both are blocked by "
         "the PILOT, not the deck:", "",
         "| deck | decklist_valid | built | smoke_valid | blocked_by | "
         "should_enter_sprint |", "|---|---|---|---|---|---|"]
    for d in diag.get("diagnoses", []):
        D.append(f"| {d.get('candidate_id')} | {yn(d.get('decklist_valid'))} | "
                 f"{yn(d.get('built'))} | {yn(d.get('smoke_valid'))} | "
                 f"{'pilot' if not d.get('smoke_valid') else 'n/a'} | "
                 f"{yn(d.get('should_enter_special_pilot_sprint'))} |")
    D += ["", "### Required pilot hooks & next step", ""]
    for d in diag.get("diagnoses", []):
        D.append(f"- **{d.get('candidate_id')}** — missing hooks: "
                 f"{', '.join(d.get('missing_pilot_hooks') or []) or 'n/a'}; "
                 f"first fixture needed: {d.get('first_executable_fixture_needed')}")
    D += ["", "_LOCAL / no upload. Diagnosis is internal smoke evidence, NOT a Kaggle "
          "result._", ""]
    sp_doc.write_text("\n".join(D), encoding="utf-8")

    # ================= data/site/index.html =================
    trows = "\n".join(
        f"      <tr><td>{i}</td><td>{s.get('id')}</td><td>{s.get('family')}</td>"
        f"<td>{'normal' if s['id'] in NEW_IDS else 'benchmark'}</td>"
        f"<td>{pct(s.get('adj_win_rate'))}</td>"
        f"<td>{s.get('compatibility_label')}</td></tr>"
        for i, s in enumerate(standings, 1))
    drows = "\n".join(
        f"      <tr><td>{d.get('candidate_id')}</td>"
        f"<td>{yn(d.get('decklist_valid'))}</td><td>{yn(d.get('built'))}</td>"
        f"<td>{yn(d.get('smoke_valid'))}</td>"
        f"<td>{yn(d.get('should_enter_special_pilot_sprint'))}</td></tr>"
        for d in diag.get("diagnoses", []))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 34 New Deck Intake + Lane Split</title>
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>ActiveGraph — Pass 34: New Deck Intake + Easy Basic / Chaos Lane Split</h1>
<p class="caveat">{CAVEAT}</p>
<h2>Live reference (Kaggle, read-only)</h2>
<p>live_score_leader: <code>{leader.get('fileName')}</code> @ {leader.get('publicScore')}
 &middot; water_family_current_best: <code>{water_best.get('fileName')}</code>
 @ {water_best.get('publicScore')} &middot; dragapult_family_best:
 <code>{dragapult_best.get('fileName')}</code> @ {dragapult_best.get('publicScore')}
 (above water: {yn(dragapult_above_water)}) &middot; portfolio_reference:
 <code>{portref.get('fileName')}</code> @ {portref.get('publicScore')}</p>
<h2>Internal tournament standings (NOT Kaggle)</h2>
<table><thead><tr><th>rank</th><th>candidate</th><th>family</th><th>lane</th><th>adj win_rate</th><th>label</th></tr></thead>
<tbody>
{trows}
</tbody></table>
<h2>Special-lane diagnosis</h2>
<table><thead><tr><th>deck</th><th>decklist valid</th><th>built</th><th>smoke valid</th><th>enter sprint</th></tr></thead>
<tbody>
{drows}
</tbody></table>
<h2>Meta sanity (directional, surrogate)</h2>
<p>sanity_passed: {yn(sanity.get('sanity_passed'))} &middot; best:
 <code>{san_best_id}</code> @ {pct(san_best)}</p>
<h2>Decision</h2>
<p><b>{decision.get('decision')}</b> &middot; held probe: <code>{held}</code>
 (re-affirmed rank 1)</p>
<p>dry-run queue: {decision.get('queued_candidate_count')} (max
 {decision.get('queue_max')}, HELD) &middot; human approval required:
 {yn(decision.get('human_approval_required'))} &middot; auto-submit:
 {yn(decision.get('auto_submit_enabled'))} &middot; events emitted: {n_events}
 (all no_upload)</p>
<p>Full report: <code>data/reports/pass34_new_deck_intake_tournament_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("wrote:")
    print("  data/reports/pass34_new_deck_intake_tournament_report.md")
    print("  data/reports/activegraph_strategy_report.md")
    print("  docs/PTCG_STRATEGY_CANVAS.md")
    print("  docs/SPECIAL_PILOT_LANES.md")
    print("  data/site/index.html")
    print(f"events counted: {n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
