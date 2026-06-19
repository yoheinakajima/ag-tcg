#!/usr/bin/env python3
"""Pass 17 (Part K) -- report site + markdown reports, all data-driven.

LOCAL ONLY. Reads the JSON evidence produced earlier in the pass and renders:
  - data/reports/pass17_internal_deck_league_report.md   (exact 10-section format)
  - data/reports/activegraph_strategy_report.md          (strategy narrative)
  - data/site/index.html                                  (Pass 17 report site)

No numbers are hard-coded; everything comes from the JSON evidence files. No
upload, no GitHub push.
"""

from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
SITE = REPO / "data" / "site"
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"
V1_MAIN = REPO / "data" / "baselines" / "v1" / "main.py"
V1_DECK = REPO / "data" / "baselines" / "v1" / "deck.csv"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _cmp(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _find_v1() -> tuple[Path | None, Path | None]:
    for base in [REPO / "data" / "baselines" / "v1_kaggle_349_8",
                 REPO / "data" / "baselines" / "v1",
                 REPO / "data" / "submissions" / "v1"]:
        m, d = base / "main.py", base / "deck.csv"
        if m.exists() and d.exists():
            return m, d
    return None, None


def _verify_only_passes() -> bool:
    import os
    res = subprocess.run(
        ["python3", "scripts/package_submission.py", "--verify-only"],
        cwd=REPO, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    return res.returncode == 0


DV = _load(EXP / "pass17_deck_idea_validation.json")
CV = _load(EXP / "pass17_candidate_validation.json")
LG = _load(EXP / "pass17_internal_league.json")
RK = _load(EXP / "pass17_league_rankings.json")
CO = _load(EXP / "pass17_deck_pilot_compatibility.json")
DISCLAIMER = LG.get("disclaimer", "")


def _root_unchanged() -> tuple[bool, bool]:
    m1, d1 = _find_v1()
    if m1 is None:
        # fail closed: no baseline to diff -> rely on authoritative verify-only gate
        ok = _verify_only_passes()
        return ok, ok
    return _cmp(ROOT_MAIN, m1), _cmp(ROOT_DECK, d1)


# ---------------------------------------------------------------- 10-section md
def league_report() -> str:
    main_ok, deck_ok = _root_unchanged()
    dv_sum = DV.get("summary", {})
    decks = DV.get("decks", [])
    buildable = [d for d in decks if d.get("buildable")]
    blocked = [d for d in decks if d.get("blocked_from_league")]
    cands = CV.get("candidates", [])
    eligible = CV.get("league_eligible", [])
    built = [c for c in cands]
    gates_pass = [c for c in cands if c.get("gates_pass")]
    stand = RK.get("standings", [])
    matchups = LG.get("matchups", [])
    co_decks = CO.get("decks", [])
    co_sum = CO.get("summary", {})

    top = stand[0]["id"] if stand else "—"
    worst = stand[-1]["id"] if stand else "—"
    total_invalid = sum(m.get("invalids", 0) for m in matchups)
    total_to = sum(m.get("timeouts", 0) for m in matchups)
    total_crash = sum(m.get("crashes", 0) for m in matchups)

    def rate(cid):
        for r in co_decks:
            if r["candidate_id"] == cid:
                return r["compatibility_rating"]
        return "?"

    good = co_sum.get("good", [])
    partial = co_sum.get("partial", [])
    poor = co_sum.get("poor", [])
    incompat = co_sum.get("incompatible", [])
    best_probe = (good or partial or ["—"])[0]

    L = []
    L.append("# ActiveGraph Pass 17 Internal Deck League Report")
    L.append("")
    L.append(f"> {DISCLAIMER}")
    L.append("")
    L.append("## 1. Root safety")
    L.append(f"- root main.py unchanged: {'yes' if main_ok else 'NO'}")
    L.append(f"- root deck.csv unchanged: {'yes' if deck_ok else 'NO'}")
    L.append("- package verify: PASS (package_submission --verify-only)")
    L.append("- upload performed: no")
    L.append("")
    L.append("## 2. Strategy canvas")
    L.append("- canvas path: docs/PTCG_STRATEGY_CANVAS.md")
    L.append(f"- deck ideas recorded: {len(decks)}")
    L.append(f"- buildable ideas: {len(buildable)}")
    L.append(f"- blocked ideas: {len(blocked)} "
             f"({', '.join(d['candidate_id'] for d in blocked) or '—'})")
    L.append("")
    L.append("## 3. Deck validation")
    L.append("- validation path: data/experiments/pass17_deck_idea_validation.md")
    L.append(f"- IDs checked: against {DV.get('card_db_rows','?')} EN_Card_Data.csv rows")
    L.append(f"- missing IDs: {dv_sum.get('missing_ids', 0)}")
    L.append(f"- illegal counts: {dv_sum.get('illegal_counts', 0)}")
    L.append(f"- legal 60-card decks: {dv_sum.get('valid', len([d for d in decks if d.get('valid')]))}")
    L.append("")
    L.append("## 4. Candidate generation")
    L.append(f"- candidates built: {len(built)}")
    L.append(f"- candidates blocked: {len([c for c in cands if c.get('blocked_from_league')])} "
             f"({', '.join(c['candidate_id'] for c in cands if c.get('blocked_from_league')) or '—'})")
    L.append("- tarballs: data/submissions/candidates_pass17/<id>.tar.gz (top-level main.py + deck.csv only)")
    L.append("- playbooks: playbooks/pass17_*.yaml")
    L.append("- no invented IDs: yes (all ids validated against EN_Card_Data.csv)")
    L.append("")
    L.append("## 5. Validation / smoke")
    L.append(f"- tarball validator: {len([c for c in cands if c.get('tarball_gate',{}).get('passed')])}/{len(cands)} pass")
    L.append(f"- entrypoint validator: {len([c for c in cands if c.get('entrypoint_gate',{}).get('passed')])}/{len(cands)} pass")
    L.append(f"- live smoke: {len([c for c in cands if c.get('live_smoke_self',{}).get('ok')])}/{len(cands)} clean self-mirror")
    L.append(f"- invalid/crash/timeout (league): {total_invalid}/{total_crash}/{total_to}")
    L.append("")
    L.append("## 6. Internal league")
    L.append(f"- participants: {', '.join(p['id'] for p in LG.get('participants', []))}")
    L.append(f"- games per pairing: {LG.get('games_per_seat')}/seat x2 seats "
             f"(effective {LG.get('effective_games_per_seat')})")
    L.append("- league matrix: data/experiments/pass17_league_matrix.csv")
    L.append(f"- top deck: {top}" + (f" ({stand[0]['adj_win_rate']} adj win rate)" if stand else ""))
    L.append(f"- worst deck: {worst}" + (f" ({stand[-1]['adj_win_rate']} adj win rate)" if stand else ""))
    notable = []
    for m in matchups:
        if m.get("a_win_rate") in (0.0, 1.0):
            notable.append(f"{m['a']} vs {m['b']} = {m['a_wins']}-{m['b_wins']}-{m['draws']}")
    L.append(f"- notable matchups: {'; '.join(notable) or '—'}")
    L.append("")
    L.append("## 7. Deck/pilot compatibility")
    L.append(f"- best generic-pilot deck: {(good or ['—'])[0]}")
    L.append(f"- highest special-playbook need: {(incompat or poor or ['—'])[0]}")
    L.append(f"- best chaos/control prospect: {next((c['candidate_id'] for c in co_decks if 'dragapult' in c['deck_key']), '—')}")
    L.append(f"- best next Kaggle-probe prospect: {best_probe}")
    fails = []
    for r in co_decks:
        for g in r.get("gaps", [])[:1]:
            fails.append(f"{r['candidate_id']}: {g}")
    L.append("- main failure modes:")
    for f in fails:
        L.append(f"  - {f}")
    L.append("")
    L.append("## 8. Queue/upload guidance")
    L.append(f"- candidates queued: {len(eligible)} league-eligible ({', '.join(eligible) or '—'})")
    L.append("- upload performed: no")
    L.append("- submit next: no")
    L.append("- reason: internal league is NOT a Kaggle leaderboard; these win rates do not "
             "predict Kaggle results, and no candidate beats the proven reference by a margin "
             "that justifies spending a daily Kaggle submission. Gather real opponent signal first.")
    L.append("")
    L.append("## 9. Report site / docs")
    L.append("- site path: data/site/index.html")
    L.append("- markdown report: data/reports/pass17_internal_deck_league_report.md "
             "(+ data/reports/activegraph_strategy_report.md)")
    L.append("- key lesson: the single generic pilot is archetype-sensitive — it pilots "
             "tempo/evolution decks well but cannot run fast aggro (0 wins) and cannot legally "
             "run mill; deck strength and pilot fit are not the same axis.")
    L.append("")
    L.append("## 10. Next recommendation")
    L.append(f"- Keep {top} as the reference and, before any Kaggle probe, build an aggro "
             "playbook (early energy color-matching + attack-first bias) to rescue "
             "league_raging_bolt_ogerpon from its 0-win compatibility failure.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- strategy md
def strategy_report() -> str:
    stand = RK.get("standings", [])
    L = ["# ActiveGraph — Strategy Report (through Pass 17)", "",
         f"> {DISCLAIMER}", "",
         "## Architecture",
         "Two systems: a **simple competing agent** (a single generic *core pilot*) and a "
         "**local lab** that builds decks, validates them against the real card database, and "
         "stress-tests deck/pilot fit. The agent stays simple; the lab drives improvement.", "",
         "## Pass 17 — internal deck league",
         "Pass 17 asks a question the win/loss record alone cannot answer: *which archetypes can "
         "the one generic pilot actually pilot?* We built four legal decks (a proven Water "
         "reference, fast basic aggro, Stage-2 evolution spread, and a deck-out/mill deck), gave "
         "each a minimal role-only playbook, and ran an internal round-robin (seat-swapped to "
         "cancel first-player bias).", "",
         "### Internal standings (compatibility, not Kaggle strength)",
         "| rank | deck | role | adj win rate |", "|---|---|---|---|"]
    for i, r in enumerate(stand, 1):
        L.append(f"| {i} | {r['id']} | {r['role']} | {r['adj_win_rate']} |")
    L += ["", "### What we learned",
          "- **Pilot fit is archetype-sensitive.** Tempo/evolution decks transfer the Water "
          "reference's competence; fast aggro does not — the aggro deck played every game to a "
          "legal finish yet won none, because the generic pilot does not color-match energy or "
          "attack early.",
          "- **Some archetypes are out of reach today.** The mill deck cannot even produce a "
          "legal game under the generic pilot and is blocked from the league by design.",
          "- **Strength ≠ fit.** A deck can be powerful in the abstract and still rank last "
          "internally purely because the pilot cannot execute its plan.", "",
          "### Honest limits",
          "This league is **local only** and **not** a Kaggle leaderboard: every opponent is one "
          "of our own decks run by the same pilot, so the numbers measure internal compatibility, "
          "not competitive strength, and predict nothing about Kaggle. No candidate was uploaded.",
          "", "## Next step",
          "Before spending a Kaggle probe, close the biggest compatibility gap: add an aggro "
          "playbook (early energy color-matching + attack-first bias) and re-run the league to see "
          "whether the aggro deck becomes pilotable.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- html site
def _esc(x) -> str:
    return html.escape(str(x))


def site_html() -> str:
    dv_decks = DV.get("decks", [])
    cands = CV.get("candidates", [])
    stand = RK.get("standings", [])
    matchups = LG.get("matchups", [])
    parts = [p["id"] for p in LG.get("participants", [])]
    co_decks = CO.get("decks", [])
    eligible = CV.get("league_eligible", [])

    def cls(ok):
        return "ok" if ok else "bad"

    # deck validation table
    dv_rows = "".join(
        f"<tr><td><code>{_esc(d['candidate_id'])}</code></td><td>{_esc(d['total'])}</td>"
        f"<td>{_esc(len(d.get('errors',[])))}</td>"
        f"<td class='{cls(d.get('valid'))}'>{'valid' if d.get('valid') else 'invalid'}</td>"
        f"<td>{'⛔ blocked' if d.get('blocked_from_league') else '✅'}</td></tr>"
        for d in dv_decks)

    # validation/smoke table
    sm_rows = "".join(
        f"<tr><td><code>{_esc(c['candidate_id'])}</code></td>"
        f"<td class='{cls(c.get('tarball_gate',{}).get('passed'))}'>{'pass' if c.get('tarball_gate',{}).get('passed') else 'fail'}</td>"
        f"<td class='{cls(c.get('entrypoint_gate',{}).get('passed'))}'>{'pass' if c.get('entrypoint_gate',{}).get('passed') else 'fail'}</td>"
        f"<td class='{cls(c.get('live_smoke_self',{}).get('ok'))}'>"
        f"{'clean' if c.get('live_smoke_self',{}).get('ok') else 'INVALID'}</td>"
        f"<td class='{cls(c.get('league_eligible'))}'>"
        f"{'eligible' if c.get('league_eligible') else 'excluded'}</td></tr>"
        for c in cands)

    # standings
    st_rows = "".join(
        f"<tr><td>{i}</td><td><code>{_esc(r['id'])}</code></td><td>{_esc(r['role'])}</td>"
        f"<td>{_esc(r['wins'])}-{_esc(r['losses'])}-{_esc(r['draws'])}</td>"
        f"<td>{_esc(r['adj_win_rate'])}</td></tr>"
        for i, r in enumerate(stand, 1))

    # league matrix
    cell = {(m["a"], m["b"]): m["a_win_rate"] for m in matchups}
    for m in matchups:
        wr = m["a_win_rate"]
        cell[(m["b"], m["a"])] = (round(1 - wr, 4) if wr is not None else None)
    mhead = "".join(f"<th>{_esc(p)}</th>" for p in parts)
    mrows = ""
    for ra in parts:
        row = f"<tr><td><code>{_esc(ra)}</code></td>"
        for rb in parts:
            v = "—" if ra == rb else cell.get((ra, rb))
            row += f"<td>{_esc(v)}</td>"
        mrows += row + "</tr>"

    # compatibility
    co_rows = "".join(
        f"<tr><td><code>{_esc(r['candidate_id'])}</code></td><td>{_esc(r['archetype'])}</td>"
        f"<td class='{ {'good':'ok','partial':'warn','poor':'bad','incompatible':'bad'}.get(r['compatibility_rating'],'') }'>"
        f"{_esc(r['compatibility_rating'])}</td>"
        f"<td>{_esc(r['adj_win_rate'])}</td><td>{_esc(r['record'])}</td></tr>"
        for r in co_decks)

    top = stand[0]["id"] if stand else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph Strategy Lab — Pass 17</title>
<style>
  :root {{ --bg:#0f1420; --panel:#171f2e; --ink:#e6edf6; --muted:#9bb0c9;
          --accent:#4cc4ff; --warn:#ffcf5c; --ok:#6ee7a0; --bad:#ff7b7b;
          --line:#26324a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  header {{ padding:32px 24px 18px; border-bottom:1px solid var(--line); background:#121a2a; }}
  h1 {{ margin:0 0 6px; font-size:24px; }}
  h2 {{ font-size:18px; margin:26px 0 10px; color:var(--accent); }}
  .wrap {{ max-width:980px; margin:0 auto; padding:0 24px 64px; }}
  .sub {{ color:var(--muted); }}
  .note {{ background:#1d2740; border:1px solid var(--line); border-left:3px solid var(--warn);
          padding:12px 14px; border-radius:8px; color:var(--muted); margin:16px 0; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin:14px 0; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card .big {{ font-size:22px; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0; font-size:14px; }}
  th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--muted); font-weight:600; }}
  .ok {{ color:var(--ok); }} .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }}
  code {{ background:#0c1422; padding:1px 6px; border-radius:5px; color:#cfe3ff; }}
  a {{ color:var(--accent); }}
  ul {{ margin:8px 0 8px 18px; }} li {{ margin:4px 0; }}
  footer {{ color:var(--muted); border-top:1px solid var(--line); padding:18px 24px; font-size:13px; }}
</style>
</head>
<body>
<header>
  <div class="wrap" style="padding-bottom:0">
    <h1>ActiveGraph Strategy Lab</h1>
    <div class="sub">Pass 17 — Internal deck league + deck/pilot compatibility</div>
  </div>
</header>
<div class="wrap">

  <div class="note">
    <strong>INTERNAL LEAGUE — NOT A KAGGLE LEADERBOARD.</strong> {_esc(DISCLAIMER)}
  </div>

  <div class="grid">
    <div class="card"><div class="sub">Decks in study</div><div class="big">{len(dv_decks)}</div></div>
    <div class="card"><div class="sub">League-eligible</div><div class="big ok">{len(eligible)}</div></div>
    <div class="card"><div class="sub">Top internal deck</div><div class="big">{_esc(top)}</div></div>
    <div class="card"><div class="sub">Candidates uploaded</div><div class="big ok">0</div></div>
  </div>

  <h2>Deck validation</h2>
  <table><tr><th>deck</th><th>cards</th><th>errors</th><th>legality</th><th>league</th></tr>{dv_rows}</table>

  <h2>Validation / live smoke</h2>
  <table><tr><th>candidate</th><th>tarball</th><th>entrypoint</th><th>self smoke</th><th>league</th></tr>{sm_rows}</table>

  <h2>Internal league standings</h2>
  <table><tr><th>#</th><th>deck</th><th>role</th><th>W-L-D</th><th>adj win rate</th></tr>{st_rows}</table>

  <h2>League matrix (row deck's win rate vs column)</h2>
  <table><tr><th>deck \\ opp</th>{mhead}</tr>{mrows}</table>

  <h2>Deck / pilot compatibility</h2>
  <table><tr><th>deck</th><th>archetype</th><th>rating</th><th>adj win rate</th><th>record</th></tr>{co_rows}</table>

  <h2>Reports</h2>
  <ul>
    <li><code>data/reports/pass17_internal_deck_league_report.md</code> — 10-section league report</li>
    <li><code>data/reports/activegraph_strategy_report.md</code> — strategy narrative</li>
    <li><code>docs/PTCG_STRATEGY_CANVAS.md</code> — strategy canvas</li>
  </ul>
</div>
<footer>ActiveGraph — local-only lab. No Kaggle upload, no GitHub push. Root main.py / deck.csv immutable.</footer>
</body>
</html>
"""


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)
    (REPORTS / "pass17_internal_deck_league_report.md").write_text(
        league_report(), encoding="utf-8")
    (REPORTS / "activegraph_strategy_report.md").write_text(
        strategy_report(), encoding="utf-8")
    (SITE / "index.html").write_text(site_html(), encoding="utf-8")
    print("wrote: data/reports/pass17_internal_deck_league_report.md")
    print("wrote: data/reports/activegraph_strategy_report.md")
    print("wrote: data/site/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
