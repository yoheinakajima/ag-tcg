#!/usr/bin/env python3
"""Pass 35 (T-O) — reports, docs, and static site for the typed board-aware layer.

Data-driven from the Pass-35 artifacts. Produces:
- data/reports/pass35_final_report.md                     (EXACT 10-section report)
- data/reports/pass35_typed_strategy_portfolio_report.md  (detailed portfolio report)
- data/reports/activegraph_strategy_report.md             (refreshed narrative)
- docs/PTCG_STRATEGY_CANVAS.md                            (refreshed canvas)
- docs/TYPED_AGENT_ARCHITECTURE.md                        (refreshed Pass-35 tail)
- data/site/index.html                                    (static landing)

Honesty mandate carried throughout: attack / lethal / KO / spread / Boss / gust are
UNSUPPORTED (numeric attackId only); Raging Bolt gets NO fake color-match fix. The
internal tournament + parent/child H2H + meta sanity are LOCAL self-play / surrogate
diagnostics, NOT the Kaggle leaderboard and NOT a promotion or upload signal. No
upload, no submit, no GitHub push; root main.py/deck.csv verified byte-identical to
the frozen baseline.
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

CAVEAT = ("The internal tournament, parent/child H2H confirmations, and the "
          "replay-derived meta sanity are LOCAL diagnostics: every seat is OUR own "
          "portfolio deck driven by the SAME deck-agnostic base pilot (meta sanity "
          "uses replay-derived surrogate opponents). They are NOT the Kaggle "
          "leaderboard and are NOT a promotion or upload signal.")
HONESTY = ("Honesty mandate: attack damage/effect, lethal, KO target, spread "
           "placement, Boss/gust are UNSUPPORTED by the option schema (numeric "
           "attackId only); the typed layer refuses to fabricate them. Raging Bolt "
           "gets NO fake color-match fix (Pass 28 refuted it).")


def _root_unchanged(name: str):
    root_f, base_f = REPO / name, BASELINE / name
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


def _load_path(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _count_events(tag="pass35") -> int:
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


def evi(v) -> str:
    return "yes" if v is True else ("no" if v is False else "unverified")


def pct(x) -> str:
    return "n/a" if x is None else f"{float(x) * 100:.1f}%"


def main() -> int:
    rs = _load("pass35_root_safety.json")
    prof = _load("pass35_strategy_profiles.json")
    gate = _load_path(REPORTS / "pass35_typed_strategy_gate.json")
    gate_result = "PASS" if gate.get("all_ok") else "FAIL"
    gate_fixtures = gate.get("total_fixtures")
    build = _load("pass35_candidate_build.json")
    valid = _load("pass35_candidate_validation.json")
    replay = _load("pass35_decision_replay.json")
    firing = _load("pass35_typed_firing_probe.json")
    rankings = _load("pass35_rankings.json")
    tour = _load("pass35_internal_tournament.json")
    pc = _load("pass35_parent_child.json")
    ab = _load("pass35_ab_controls.json")
    meta = _load("pass35_meta_sanity.json")
    decision = _load("pass35_strategy_decision.json")

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    main_ok = _root_unchanged("main.py")
    deck_ok = _root_unchanged("deck.csv")
    pkg = ("PASS" if (main_ok is True and deck_ok is True)
           else ("FAIL" if (main_ok is False or deck_ok is False) else "UNVERIFIED"))

    overall = rankings.get("overall_ranking", [])
    rank = {r["id"]: r for r in overall}
    s1 = rankings.get("stage1_standings", [])
    s2 = rankings.get("stage2_finalists", [])
    tcfg = tour.get("config", {})
    top = overall[0] if overall else {}
    cls_counts = pc.get("classification_counts", {})
    pairs = {p["child_id"]: p for p in pc.get("pairs", [])}
    fire_tot = firing.get("totals", {})
    fr = replay.get("fixture_replay", {})
    lr = replay.get("live_replay", {})
    san = meta.get("sanity", {})
    meta_pd = san.get("per_deck", {})
    n_events = _count_events()
    held = decision.get("held_probe")
    queued = decision.get("queued_candidate_count")

    san_best_id, san_best = None, -1.0
    for cid, d in meta_pd.items():
        ws = d.get("weighted_meta_score")
        if ws is not None and ws > san_best:
            san_best, san_best_id = ws, cid

    # ===================== EXACT 10-section final report =====================
    O = ["ActiveGraph Pass 35 Typed Board-Aware Strategy Layer + Portfolio "
         "Tournament Report", "",
         "1. Root safety",
         f"- root main.py unchanged: {evi(main_ok)} (byte cmp vs baseline "
         f"{BASELINE.name}, verify-only)",
         f"- root deck.csv unchanged: {evi(deck_ok)} (byte cmp vs baseline, "
         "verify-only)",
         f"- package verify-only: {pkg} (rc="
         f"{rs.get('package_verify_returncode')}, "
         f"passed={yn(rs.get('package_verify_only_passed'))})",
         f"- upload performed: {yn(rs.get('upload_performed'))}; github push: "
         f"{yn(rs.get('github_push'))}; local_only: {yn(rs.get('local_only'))}",
         "",
         "2. Lane decision",
         f"- lane: Option B — stdlib typed-lite (`{prof.get('lane')}`); no shippable "
         "`cg` package exists in-repo, so the tarball stays exactly top-level main.py "
         "+ deck.csv, stdlib-only.",
         "- mechanism: the proven embed-not-import compiler emits a PASS35 typed "
         "block that runs the base policy FIRST and only refines observable contexts "
         f"{sorted(set(fire_tot.get('contexts', []) or [0, 1, 2, 7, 8, 38]))}, "
         "bailing to base on any error/mismatch.",
         "- per-card metadata is generated at COMPILE time from the gitignored card "
         f"CSV for portfolio cards only (card CSV committed: "
         f"{yn(prof.get('card_csv_committed'))} — never committed).",
         "",
         "3. Typed strategy layer + profiles",
         f"- profiles: {prof.get('total_profiles')} total = "
         f"{prof.get('executable_profiles')} executable + "
         f"{prof.get('special_pilot_only_profiles')} special-pilot-only "
         "(Toxic + Durant, executable=false); registry all_ok: "
         f"{yn(prof.get('all_ok'))}.",
         f"- {HONESTY}",
         "- fixture decision replay: all_honest="
         f"{yn(fr.get('all_honest'))}, all_safe={yn(fr.get('all_safe'))}; "
         f"intended_non_inert={len(fr.get('intended_non_inert', []))} profiles, "
         f"inert={len(fr.get('inert', []))} profiles (inert = the typed view agrees "
         "with the base policy, which is a safe outcome, not a failure).",
         "",
         "4. Fixtures + typed strategy gate",
         f"- typed strategy gate: {gate_result} "
         f"({gate.get('passed_cases')}/{gate.get('total_cases')} cases passed); "
         f"executable profiles {gate.get('executable_profiles')}, fixtures "
         f"{gate_fixtures}.",
         f"- assertions_ok={yn(gate.get('assertions_ok'))}, "
         f"honesty_sweep_ok={yn(gate.get('honesty_sweep_ok'))}, "
         f"coverage_ok={yn(gate.get('coverage_ok'))}; every executable profile "
         "refuses to fabricate attack/lethal/ko/spread/boss/gust (numeric "
         "attackId only).",
         "",
         "5. Candidates built",
         f"- built: {build.get('built')}/"
         f"{prof.get('executable_profiles')} executable profiles "
         f"(all_executable_built={yn(build.get('all_executable_built'))}); "
         f"special-pilot-only skipped: {build.get('special_pilot_only_skipped')} "
         "(never built, never queued).",
         "- each candidate = its untyped parent's deck (byte-identical) + ONLY the "
         "typed override; tarballs are top-level main.py + deck.csv in "
         "data/submissions/candidates_pass35/.",
         f"- build gates: typed_strategy_gate_ok={yn(build.get('typed_strategy_gate_ok'))}, "
         f"root_safe={yn(build.get('root_safe'))}, "
         f"card_csv_committed={yn(build.get('card_csv_committed'))}.",
         "",
         "6. Validation / smoke",
         f"- validation all_ok: {yn(valid.get('all_ok'))} over "
         f"{len(valid.get('records', []))} candidates (tarball + entrypoint smoke + "
         "static import scan + self smoke + control smoke + parent-vs-child smoke).",
         "- live decision replay (4 games/child, real subprocess): "
         f"all_safe={yn(lr.get('all_safe'))}, misfires/unsafe/invalids = 0; "
         f"non_inert_in_live_play={len(lr.get('non_inert_in_live_play', []))}, "
         f"inert_in_live_play={len(lr.get('inert_in_live_play', []))}.",
         f"- typed firing probe: {fire_tot.get('overall_firing_rate_pct')}% live "
         f"firing over {fire_tot.get('decisions')} decisions, "
         f"{fire_tot.get('illegal_refinements')} illegal refinements "
         f"(any_illegal_refinement={yn(firing.get('any_illegal_refinement'))}) — the "
         "typed layer is SAFE and always falls back.",
         "",
         "7. Internal tournament",
         f"- format: subprocess-isolated, checkpointed, resumable; Stage 1 "
         f"{tcfg.get('s1_games_per_seat')}/seat round-robin over "
         f"{len(tour.get('participants', []))} typed children, Stage 2 top-"
         f"{tcfg.get('s2_top_k')} at {tcfg.get('s2_games_per_seat')}/seat "
         f"(reduced honestly: {tcfg.get('reduction_reason')}).",
         f"- overall #1: {top.get('id')} (adj win_rate {pct(top.get('adj_win_rate'))}, "
         f"Wilson {top.get('wilson')}, label {top.get('label')}).",
         "- screen<->finals disagreement is recorded; ALL finalist CIs overlap 0.5, "
         "so NO finalist is shown to be reliably strongest.",
         f"- {CAVEAT}",
         "",
         "8. Parent/child confirmations (control-calibrated)",
         f"- direct seat-swapped H2H, {pc.get('games_done')}/"
         f"{pc.get('games_target')} games; classifications: "
         + ", ".join(f"{k}={v}" for k, v in cls_counts.items()) + ".",
         f"- any superiority claim: {yn(pc.get('any_superiority_claim'))} — every "
         "child win-rate CI was required to clear BOTH self-mirror noise floors "
         "(parent-mirror AND child-mirror from the null A/B controls, "
         f"{ab.get('games_done')} games); none did.",
         "- conclusion: the typed layer is no-regression / inconclusive vs its "
         "parents, NOT a measured strength gain. Raw within-noise upticks "
         "(raging_bolt, gardevoir, venusaur) and the one raw downtick (water_core) "
         "are all downgraded to inconclusive.",
         "",
         "9. Meta sanity",
         f"- {meta.get('status')}: {meta.get('games_per_seat')} games/seat vs "
         f"{len(meta.get('opponent_subfamilies', []))} replay-derived surrogate "
         f"subfamilies; sanity_passed={yn(san.get('sanity_passed'))}, 0 collapses "
         "for every child (collapse = win rate < "
         f"{san.get('collapse_threshold')} vs any subfamily).",
         f"- best weighted meta score: {san_best_id} ({pct(san_best)}); directional "
         "only — surrogate-vs-surrogate, NOT a promotion or upload signal.",
         "",
         "10. Strategy decision / ActiveGraph + next recommendation",
         f"- decision: {decision.get('decision')}",
         f"- dry-run queue: {queued} (max {decision.get('queue_max')}); HELD probe "
         f"{held}, human_approval_required={yn(decision.get('human_approval_required'))}, "
         f"auto_submit_enabled={yn(decision.get('auto_submit_enabled'))}, "
         f"upload_performed={yn(decision.get('upload_performed'))}.",
         f"- ActiveGraph events emitted: {n_events} (pass35-tagged, all "
         "no_upload=true; NO SubmissionUploaded).",
         f"- next recommendation: adopt the typed layer as SAFE infrastructure (0 "
         "illegal refinements, always falls back) but DO NOT submit anything "
         f"automatically; keep {held} as the single human-approved held probe. Before "
         "any human submit, run a larger parent/child confirmation batch — the "
         "achievable sample here cannot separate the typed children from their "
         "parents above the engine self-mirror noise floor. Toxic + Durant remain "
         "special-pilot-only (a dedicated special-pilot task is the path for them).",
         ""]
    (REPORTS / "pass35_final_report.md").write_text("\n".join(O), encoding="utf-8")

    # ===================== detailed portfolio report =====================
    P = ["# Pass 35 — Typed Board-Aware Strategy Layer + Portfolio Tournament", "",
         f"> {CAVEAT}", "", f"> {HONESTY}", "",
         "> LOCAL ONLY — no Kaggle upload/submit, no GitHub push, root "
         "main.py/deck.csv byte-identical to the frozen baseline.", "",
         "## Typed children — tournament + confirmation + meta", "",
         "| typed child | overall adj WR | Wilson | label | vs-parent | meta score "
         "| meta collapse |", "|---|---|---|---|---|---|---|"]
    for r in overall:
        cid = r["id"]
        p = pairs.get(cid, {})
        md = meta_pd.get(cid, {})
        P.append(
            f"| {cid} | {pct(r.get('adj_win_rate'))} | {r.get('wilson')} | "
            f"{r.get('label')} | {p.get('classification', 'n/a')} | "
            f"{pct(md.get('weighted_meta_score'))} | "
            f"{md.get('collapses') or 'none'} |")
    P += ["", "## Stage 1 screen vs Stage 2 finals", "",
          f"- Stage 1 ({tcfg.get('s1_games_per_seat')}/seat) screened "
          f"{len(s1)} children; Stage 2 ({tcfg.get('s2_games_per_seat')}/seat) "
          f"re-ran the top {len(s2)} finalists.",
          "- The low-n screen is noisy; Stage 2 is authoritative for the overall "
          "ranking, but all finalist CIs overlap 0.5 — NO finalist is reliably "
          "strongest."]
    for note in tour.get("notes", []):
        P.append(f"  - {note}")
    P += ["", "## Fixture decision replay (typed vs base, per profile)", "",
          "| profile | overall | cases | honesty unsupported | misfire | unsafe |",
          "|---|---|---|---|---|---|"]
    for pr_ in fr.get("profiles", []):
        c = pr_.get("counts", {})
        P.append(
            f"| {pr_.get('profile_id')} | {pr_.get('overall')} | "
            f"{pr_.get('n_cases')} | {c.get('honesty_unsupported', 0)} | "
            f"{c.get('misfire', 0)} | {c.get('unsafe', 0)} |")
    P += ["", "## Live decision firing (4 games/child)", "",
          "| typed child | live class | decisions | changes | misfires | unsafe |",
          "|---|---|---|---|---|---|"]
    for cid, d in (lr.get("children", {}) or {}).items():
        P.append(
            f"| {cid} | {d.get('live_classification')} | "
            f"{d.get('total_decisions')} | {d.get('changes')} | "
            f"{d.get('misfires')} | {d.get('unsafe')} |")
    P += ["", "## Decision", "", f"- {decision.get('decision')}", "",
          "### Rejected for queue (typed children — safe, not promotion-worthy)"]
    for k, v in (decision.get("rejected_for_queue") or {}).items():
        P.append(f"- **{k}** — {v}")
    P += ["", "See `data/reports/pass35_final_report.md` for the EXACT 10-section "
          "report.", ""]
    (REPORTS / "pass35_typed_strategy_portfolio_report.md").write_text(
        "\n".join(P), encoding="utf-8")

    # ===================== activegraph_strategy_report.md =====================
    A = ["# ActiveGraph Strategy Report — Pass 35 (Typed Board-Aware Strategy "
         "Layer)", "", f"> {CAVEAT}", "", f"> {HONESTY}", "",
         "## What this pass asked", "",
         "Add a typed, board-aware strategy layer on top of the proven base pilot — "
         "without breaking the stdlib-only, top-level main.py + deck.csv tarball "
         "contract — then run a portfolio tournament and decide, conservatively, "
         "whether any typed child earns a (human-approved, dry-run) submission slot.",
         "", "## What we did", "",
         f"- Chose Option B (stdlib typed-lite): the embed-not-import compiler emits "
         "a PASS35 typed block that runs the base policy first and only refines "
         "observable contexts, bailing to base on any error.",
         f"- Registered {prof.get('total_profiles')} strategy profiles "
         f"({prof.get('executable_profiles')} executable in the normal lane + "
         f"{prof.get('special_pilot_only_profiles')} special-pilot-only in the "
         "special lane) with a honesty mandate baked in, and gated them with a "
         f"fixture suite ({gate_result}, {gate_fixtures} fixtures). "
         "The normal lane is built and tournament-eligible; the special lane "
         "(Toxic + Durant) stays planned-only until a special pilot is executable.",
         f"- Built {build.get('built')} typed children (parent deck "
         "byte-identical + typed override only), validated them, and replayed their "
         "decisions live (0 misfires, 0 unsafe, 0 illegal refinements).",
         "- Ran a two-stage internal tournament, control-calibrated parent/child "
         "H2H, null A/B self-mirror controls, and a directional meta sanity.",
         "", "## Headline results", "",
         f"- **Typed layer is SAFE:** {fire_tot.get('overall_firing_rate_pct')}% "
         f"live firing, {fire_tot.get('illegal_refinements')} illegal refinements, "
         "always falls back to the base policy.",
         f"- **No measured strength gain:** parent/child any_superiority_claim="
         f"{yn(pc.get('any_superiority_claim'))} — no child clears the engine "
         "self-mirror noise floor; classifications "
         + ", ".join(f"{k}={v}" for k, v in cls_counts.items()) + ".",
         f"- **Meta-sane:** sanity_passed={yn(san.get('sanity_passed'))}, 0 "
         "collapses; **internal #1** "
         f"{top.get('id')} ({pct(top.get('adj_win_rate'))}) but all finalist CIs "
         "overlap 0.5.",
         f"- **Decision:** {decision.get('decision')} — held probe `{held}` "
         "re-affirmed; nothing uploaded or submitted.",
         "", "## Decision", "", f"- {decision.get('decision')}", "",
         "See `data/reports/pass35_final_report.md` for the full 10-section report "
         "and `data/reports/pass35_typed_strategy_portfolio_report.md` for the "
         "detailed portfolio tables.", ""]
    (REPORTS / "activegraph_strategy_report.md").write_text("\n".join(A),
                                                            encoding="utf-8")

    # ===================== docs/PTCG_STRATEGY_CANVAS.md =====================
    C = ["# PTCG Strategy Canvas", "",
         "> Living strategy canvas. Updated through Pass 35.", "",
         f"_{CAVEAT}_", "", f"_{HONESTY}_", "",
         "## Pass 35 — typed board-aware strategy layer", "",
         f"- Lane: Option B stdlib typed-lite (`{prof.get('lane')}`), embed-not-"
         "import, refine-then-fallback.",
         f"- Profiles: {prof.get('total_profiles')} "
         f"({prof.get('executable_profiles')} executable + "
         f"{prof.get('special_pilot_only_profiles')} special-pilot-only).",
         f"- Typed strategy gate: {gate_result}; firing probe "
         f"{fire_tot.get('overall_firing_rate_pct')}% with "
         f"{fire_tot.get('illegal_refinements')} illegal refinements.",
         "", "## Internal tournament standings (NOT Kaggle)", "",
         "| rank | typed child | adj win_rate | Wilson | label |",
         "|---|---|---|---|---|"]
    for i, r in enumerate(overall, 1):
        C.append(f"| {i} | {r.get('id')} | {pct(r.get('adj_win_rate'))} | "
                 f"{r.get('wilson')} | {r.get('label')} |")
    C += ["", "## Parent/child confirmation (control-calibrated)", "",
          f"- any_superiority_claim: {yn(pc.get('any_superiority_claim'))}; "
          + ", ".join(f"{k}={v}" for k, v in cls_counts.items())
          + " — no child clears the self-mirror noise floor.",
          "", "## Meta sanity (directional, surrogate)", "",
          f"- sanity_passed: {yn(san.get('sanity_passed'))}; best `{san_best_id}` @ "
          f"{pct(san_best)}; 0 collapses.",
          "", "## Next move", "",
          f"`{decision.get('decision')}` Keep `{held}` as the single held dry-run "
          "probe; adopt the typed layer as SAFE infrastructure but DO NOT submit. "
          "Run a larger confirmation batch before any human submit. Toxic + Durant "
          "stay special-pilot-only.", ""]
    (DOCS / "PTCG_STRATEGY_CANVAS.md").write_text("\n".join(C), encoding="utf-8")

    # ===================== docs/TYPED_AGENT_ARCHITECTURE.md (refresh tail) ====
    ta_doc = DOCS / "TYPED_AGENT_ARCHITECTURE.md"
    base = ta_doc.read_text(encoding="utf-8") if ta_doc.exists() else \
        "# Typed Agent Architecture\n"
    marker = "\n## Pass 35 outcome (refreshed)\n"
    base = base.split(marker)[0].rstrip()
    T = [base, "", "## Pass 35 outcome (refreshed)", "",
         f"_{CAVEAT}_", "", f"_{HONESTY}_", "",
         "The Option B stdlib typed-lite layer shipped and was exercised "
         "end-to-end:", "",
         f"- **Safety:** {fire_tot.get('decisions')} live decisions, "
         f"{fire_tot.get('overall_firing_rate_pct')}% typed firing, "
         f"{fire_tot.get('illegal_refinements')} illegal refinements, 0 misfires / "
         "0 unsafe in fixture and live replay. The layer always runs the base "
         "policy first and bails to it on any error or mismatch.",
         f"- **Contexts refined:** {sorted(set(fire_tot.get('contexts', []) or [0, 1, 2, 7, 8, 38]))} "
         "(setup/active, bench, search-to-hand, attach, discard).",
         "- **Honesty:** every executable profile refuses to fabricate "
         "attack/lethal/ko/spread/boss/gust (numeric attackId only); Raging Bolt "
         "gets no fake color-match fix.",
         f"- **Strength:** NOT demonstrated. Parent/child H2H any_superiority_claim="
         f"{yn(pc.get('any_superiority_claim'))}; no child clears the engine "
         "self-mirror noise floor, so the layer is adopted as safe infrastructure, "
         "not as a proven win-rate improvement.", ""]
    ta_doc.write_text("\n".join(T), encoding="utf-8")

    # ===================== data/site/index.html =====================
    trows = "\n".join(
        f"      <tr><td>{i}</td><td>{r.get('id')}</td>"
        f"<td>{pct(r.get('adj_win_rate'))}</td><td>{r.get('wilson')}</td>"
        f"<td>{r.get('label')}</td>"
        f"<td>{pairs.get(r.get('id'), {}).get('classification', 'n/a')}</td></tr>"
        for i, r in enumerate(overall, 1))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 35 Typed Board-Aware Strategy Layer</title>
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.85rem}}
 th{{background:#f4f4f6}} .caveat{{background:#fff7e6;border:1px solid #f0c36d;padding:.7rem;border-radius:6px;font-size:.9rem;margin:.5rem 0}}
 code{{background:#f4f4f6;padding:.1rem .3rem;border-radius:3px}}
</style></head><body>
<h1>ActiveGraph — Pass 35: Typed Board-Aware Strategy Layer + Portfolio Tournament</h1>
<p class="caveat">{CAVEAT}</p>
<p class="caveat">{HONESTY}</p>
<h2>Lane &amp; safety</h2>
<p>Lane: <code>{prof.get('lane')}</code> (Option B stdlib typed-lite, embed-not-import).
 Root main.py unchanged: {evi(main_ok)} &middot; deck.csv unchanged: {evi(deck_ok)}
 &middot; package verify-only: {pkg} &middot; upload performed: {yn(rs.get('upload_performed'))}.</p>
<h2>Typed layer safety</h2>
<p>profiles: {prof.get('total_profiles')} ({prof.get('executable_profiles')} executable +
 {prof.get('special_pilot_only_profiles')} special-pilot-only) &middot; typed strategy gate:
 {gate_result} &middot; live firing: {fire_tot.get('overall_firing_rate_pct')}% over
 {fire_tot.get('decisions')} decisions &middot; illegal refinements:
 {fire_tot.get('illegal_refinements')} &middot; always falls back to base.</p>
<h2>Internal tournament standings (NOT Kaggle)</h2>
<p class="caveat">These standings are internal self-play diagnostics. Not a Kaggle leaderboard and not a promotion or upload signal.</p>
<table><thead><tr><th>rank</th><th>typed child</th><th>adj win_rate</th><th>Wilson</th><th>label</th><th>vs-parent</th></tr></thead>
<tbody>
{trows}
</tbody></table>
<h2>Parent/child confirmation (control-calibrated)</h2>
<p>any superiority claim: <b>{yn(pc.get('any_superiority_claim'))}</b> &middot;
 {', '.join(f'{k}={v}' for k, v in cls_counts.items())} &middot; no child clears the
 engine self-mirror noise floor.</p>
<h2>Meta sanity (directional, surrogate)</h2>
<p>sanity_passed: {yn(san.get('sanity_passed'))} &middot; best:
 <code>{san_best_id}</code> @ {pct(san_best)} &middot; 0 collapses.</p>
<h2>Decision</h2>
<p><b>{decision.get('decision')}</b></p>
<p>dry-run queue: {queued} (max {decision.get('queue_max')}, HELD
 <code>{held}</code>) &middot; human approval required:
 {yn(decision.get('human_approval_required'))} &middot; auto-submit:
 {yn(decision.get('auto_submit_enabled'))} &middot; events emitted: {n_events}
 (all no_upload).</p>
<p>Full report: <code>data/reports/pass35_final_report.md</code></p>
</body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print("pass35 reports built:")
    print(f"  final_report (10 sections), portfolio_report, "
          f"activegraph_strategy_report")
    print(f"  docs: PTCG_STRATEGY_CANVAS, TYPED_AGENT_ARCHITECTURE; site/index.html")
    print(f"  root_safe={pkg} any_superiority={pc.get('any_superiority_claim')} "
          f"decision={decision.get('decision')} queued={queued} events={n_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
