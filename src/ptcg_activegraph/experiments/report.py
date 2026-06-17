"""Render the ActiveGraph strategy-lab report (HTML site + Markdown).

Consumes the lab's own artifacts and never fabricates data:

* ``data/activegraph/lab_events.jsonl`` — the event stream,
* ``data/experiments/latest_ranking.json`` — the ranking,
* ``experiments/runs/*/branch.yaml`` + ``metrics.json`` — candidate lineage,
* ``data/submission_queue.json`` — the (dry-run) queue,
* ``data/baselines/v1_kaggle_349_8/README.md`` — the immutable control.

Outputs ``data/site/*.html`` + ``style.css`` and
``data/reports/activegraph_strategy_report.md``. Every section degrades to a
clear empty state when its input is missing.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .branch import list_runs, load_branch_yaml
from .config import (
    BASELINE_DIR,
    LAB_EVENTS_PATH,
    RUNS_ROOT,
)

SITE_DIR = Path("data/site")
REPORT_MD = Path("data/reports/activegraph_strategy_report.md")
RANKING_JSON = Path("data/experiments/latest_ranking.json")
FOCUSED_RANKING_JSON = Path("data/experiments/focused_ranking.json")
PASS4_SCOUT_RANKING_JSON = Path("data/experiments/pass4_scout_ranking.json")
PASS4_BLOCKED_JSON = Path("data/experiments/pass4_blocked_candidates.json")
PASS4_REPLAY_ANALYSIS_JSON = Path("data/replays/80374966_analysis.json")
V2_BASELINE_DIR = Path("data/baselines/v2_kaggle_479_1_deck_energy_trim_light")
QUEUE_JSON = Path("data/submission_queue.json")

# Corrected live baseline scores (see v2 baseline README correction note: the
# v1 archive dir keeps its historical `349_8` name but live v1 is 356.9).
V1_LIVE_SCORE = 356.9
V2_LIVE_SCORE = 479.1

STYLE = """\
:root{--bg:#0f1115;--panel:#171a21;--ink:#e6e9ef;--muted:#9aa4b2;--line:#262b35;
--accent:#6ea8fe;--good:#5bd6a0;--bad:#ff7b72;--warn:#e3b341}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:28px 32px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{margin:0 0 4px;font-size:22px}header p{margin:0;color:var(--muted)}
nav{display:flex;gap:18px;padding:12px 32px;border-bottom:1px solid var(--line);
background:#12151b}nav a{color:var(--accent);text-decoration:none;font-weight:600}
nav a:hover{text-decoration:underline}
main{padding:28px 32px;max-width:1100px}
section{margin:0 0 34px}h2{font-size:18px;border-left:3px solid var(--accent);
padding-left:10px;margin:0 0 14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:22px;font-weight:700;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}
th{background:#12151b;color:var(--muted);text-transform:uppercase;font-size:11px;
letter-spacing:.05em}tr:last-child td{border-bottom:none}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.ok{color:var(--good)}.rej{color:var(--bad)}.muted{color:var(--muted)}
.empty{padding:18px;border:1px dashed var(--line);border-radius:10px;color:var(--muted)}
code{background:#12151b;padding:1px 5px;border-radius:4px}
footer{padding:18px 32px;color:var(--muted);border-top:1px solid var(--line)}
"""


def _esc(x) -> str:
    return html.escape(str(x))


def _load_json(path: Path):
    if not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_events(path: Path = LAB_EVENTS_PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def gather(runs_root=RUNS_ROOT) -> dict:
    """Collect everything the report needs into one dict (all optional)."""
    runs = []
    for run_dir in list_runs(runs_root):
        b = load_branch_yaml(run_dir)
        m = _load_json(Path(run_dir) / "metrics.json")
        if b:
            runs.append({"branch": b, "metrics": m, "run_dir": str(run_dir)})
    return {
        "events": _load_events(),
        "ranking": _load_json(RANKING_JSON) or [],
        "focused_ranking": _load_json(FOCUSED_RANKING_JSON) or [],
        "pass4_scout_ranking": _load_json(PASS4_SCOUT_RANKING_JSON) or [],
        "pass4_blocked": _load_json(PASS4_BLOCKED_JSON) or [],
        "pass4_replay": _load_json(PASS4_REPLAY_ANALYSIS_JSON) or {},
        "queue": _load_json(QUEUE_JSON) or {},
        "runs": runs,
        "baseline_readme": (BASELINE_DIR / "README.md"),
        "v2_baseline_readme": (V2_BASELINE_DIR / "README.md"),
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _page(title: str, body: str) -> str:
    nav = ('<nav><a href="index.html">Overview</a>'
           '<a href="candidates.html">Candidates</a>'
           '<a href="events.html">Event stream</a></nav>')
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)}</title><link rel=stylesheet href=style.css></head>"
            f"<body><header><h1>ActiveGraph Strategy Lab</h1>"
            f"<p>{_esc(title)} — transparent experiment factory around the v1 control"
            f" (Kaggle public 349.8)</p></header>{nav}<main>{body}</main>"
            f"<footer>Generated from lab artifacts. No values fabricated; "
            f"empty sections mean no data yet.</footer></body></html>")


def _rank_table_html(ranking: list[dict]) -> str:
    if not ranking:
        return ("<div class=empty>No ranking at this stage yet — run the batch "
                "and rank_candidates.</div>")
    rows = "".join(
        f"<tr><td>{r.get('rank')}</td><td>{_esc(r.get('branch_id'))}</td>"
        f"<td>{_esc(r.get('seam_id'))}</td><td>{_esc(r.get('kind') or '-')}</td>"
        f"<td>{_esc(r.get('games_completed') or '-')}</td>"
        f"<td>{_num(r.get('adjusted_win_rate'))}</td>"
        f"<td>{_ci_str(r.get('wilson80'))}</td>"
        f"<td>{_num(r.get('seat_balance_delta'), '{:+.3f}')}</td>"
        f"<td class={'rej' if r.get('rejected') else 'ok'}>"
        f"{_esc(r.get('label') or ('REJECTED' if r.get('rejected') else '-'))}</td></tr>"
        for r in ranking
    )
    return ("<table><tr><th>#</th><th>Branch</th><th>Seam</th><th>Kind</th>"
            "<th>Games</th><th>Adj WR</th><th>80% CI</th><th>Seat Δ</th>"
            f"<th>Label</th></tr>{rows}</table>")


def _overview_html(data: dict) -> str:
    events = data["events"]
    ranking = data["ranking"]
    focused = data.get("focused_ranking", [])
    runs = data["runs"]
    counts = Counter(e.get("event_type") for e in events)
    primary = focused or ranking
    promotable = [r for r in primary if r.get("label") == "promotable"]
    confirmation = [r for r in primary if r.get("label") == "confirmation_promising"]

    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Events", len(events)),
            ("Candidates", len(runs)),
            ("Promotable", len(promotable)),
            ("Confirmation", len(confirmation)),
            ("Rejected", sum(1 for r in primary if r.get("rejected"))),
        ]
    )

    type_rows = "".join(
        f"<tr><td>{_esc(t)}</td><td>{n}</td></tr>"
        for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ) or "<tr><td class=muted colspan=2>no events yet</td></tr>"

    body = (
        f"<section><h2>Snapshot</h2><div class=cards>{cards}</div></section>"
        f"{_pass4_html(data)}"
        f"<section><h2>Stage 1 — Broad scout ranking</h2>"
        f"{_rank_table_html(ranking)}</section>"
        f"<section><h2>Stage 2 — Focused seat-swap confirmation</h2>"
        f"{_rank_table_html(focused)}</section>"
        f"<section><h2>Event types</h2><table><tr><th>Type</th><th>Count</th></tr>"
        f"{type_rows}</table></section>"
    )
    return _page("Overview", body)


def _pass4_html(data: dict) -> str:
    scout = data.get("pass4_scout_ranking") or []
    blocked = data.get("pass4_blocked") or []
    replay = data.get("pass4_replay") or {}

    baseline_cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("v1 control (live)", V1_LIVE_SCORE),
            ("v2 control (live)", V2_LIVE_SCORE),
            ("v2 − v1 delta", f"+{round(V2_LIVE_SCORE - V1_LIVE_SCORE, 1)}"),
        ]
    )

    if replay.get("status") == "missing":
        replay_html = (
            f"<div class=empty>Replay <code>{_esc(replay.get('requested_path'))}</code> "
            f"not uploaded — analysis pending. {_esc(replay.get('note'))}</div>")
    elif replay:
        ep = replay.get("episode", {})
        replay_html = (f"<p>Episode {_esc(ep.get('episode_id'))}: "
                       f"{_esc(ep.get('num_steps'))} steps, "
                       f"result {_esc(ep.get('final_result'))}.</p>")
    else:
        replay_html = "<div class=empty>No replay analysis yet.</div>"

    if blocked:
        brows = "".join(
            f"<tr><td>{_esc(c.get('branch_id'))}</td>"
            f"<td>{_esc(c.get('seam_id'))}</td>"
            f"<td>{_esc(', '.join(str(i) for i in (c.get('core_card_ids') or [])))}</td>"
            f"<td>{_esc(c.get('reason') or c.get('blocked_reason'))}</td></tr>"
            for c in blocked
        )
        blocked_html = ("<table><tr><th>Branch</th><th>Seam</th><th>Confirmed core ids</th>"
                        f"<th>Why blocked</th></tr>{brows}</table>")
    else:
        blocked_html = "<div class=empty>No blocked chaos candidates recorded.</div>"

    return (
        "<section><h2>Pass 4 — Replay + chaos scout</h2>"
        f"<div class=cards>{baseline_cards}</div>"
        "<p class=muted>v2 (deck_energy_trim_light) is the active local control; the "
        "v1 archive dir keeps its historical <code>349_8</code> name but live v1 is "
        f"{V1_LIVE_SCORE} (see v2 baseline README correction note). "
        "No Kaggle upload / no GitHub push this pass.</p>"
        "<h3>Replay analysis</h3>"
        f"{replay_html}"
        "<h3>Scout ranking (vs v2 control)</h3>"
        f"{_rank_table_html(scout)}"
        "<h3>Blocked chaos archetypes (metadata insufficient — no invented ids)</h3>"
        f"{blocked_html}"
        "</section>"
    )


def _candidates_html(data: dict) -> str:
    runs = data["runs"]
    if not runs:
        return _page("Candidates", "<section><div class=empty>No candidates generated yet."
                     " Run generate_candidates.py.</div></section>")
    blocks = []
    for r in runs:
        b = r["branch"]
        m = r["metrics"] or {}
        diff = b.deck_diff or b.policy_diff or {}
        diff_str = _esc(json.dumps(diff)) if diff else "<span class=muted>none (control)</span>"
        gate = "ok" if (m.get("package_ok") and m.get("smoke_ok")) else "GATE-FAIL"
        rows = "".join(
            f"<tr><td>{_esc(k)}</td><td>{_esc(m.get(k))}</td></tr>"
            for k in ("games_completed", "win_rate", "attack_rate", "pass_rate",
                      "decision_entropy", "crashes", "timeouts", "avg_steps")
            if k in m
        ) or "<tr><td class=muted colspan=2>not evaluated yet</td></tr>"
        blocks.append(
            f"<section><h2>{_esc(b.branch_id)} "
            f"<span class={'ok' if gate=='ok' else 'rej'}>[{gate}]</span></h2>"
            f"<p class=muted>{_esc(b.seam_id)} · {_esc(b.kind)} · "
            f"parent {_esc(b.parent)}</p>"
            f"<p><b>Hypothesis:</b> {_esc(b.hypothesis)}</p>"
            f"<p><b>Diff:</b> <code>{diff_str}</code></p>"
            f"<table><tr><th>Metric</th><th>Value</th></tr>{rows}</table></section>"
        )
    return _page("Candidates", "".join(blocks))


def _events_html(data: dict) -> str:
    events = data["events"][-300:]
    if not events:
        return _page("Event stream", "<section><div class=empty>No events recorded yet."
                     "</div></section>")
    rows = "".join(
        f"<tr><td>{_esc(round(e.get('timestamp', 0), 2))}</td>"
        f"<td>{_esc(e.get('event_type'))}</td>"
        f"<td><code>{_esc(json.dumps(e.get('payload', {}), default=str)[:140])}</code></td></tr>"
        for e in events
    )
    body = (f"<section><h2>Event stream (latest {len(events)})</h2>"
            f"<table><tr><th>ts</th><th>type</th><th>payload</th></tr>{rows}</table>"
            f"</section>")
    return _page("Event stream", body)


def write_site(data: dict, site_dir: Path = SITE_DIR) -> list[Path]:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in [
        ("style.css", STYLE),
        ("index.html", _overview_html(data)),
        ("candidates.html", _candidates_html(data)),
        ("events.html", _events_html(data)),
    ]:
        p = site_dir / name
        p.write_text(content, encoding="utf-8")
        written.append(p)
    return written


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _ci_str(ci) -> str:
    if not ci or ci[0] is None:
        return "-"
    return f"{ci[0]:.3f}–{ci[1]:.3f}"


def _num(x, fmt="{:.3f}") -> str:
    return "-" if x is None else fmt.format(x) if isinstance(x, (int, float)) else str(x)


def _ranking_md(ranking: list[dict], title: str) -> list[str]:
    """Render a ranking table with adjusted win rate, CIs, seat split, label."""
    lines = [f"## {title}"]
    if not ranking:
        lines.append("_No ranking at this stage yet._")
        return lines
    lines.append("| # | Branch | Seam | Kind | Games | Adj WR | 80% CI | 95% CI "
                 "| Seat Δ | Label |")
    lines.append("|--:|--------|------|------|------:|-------:|--------|--------"
                 "|-------:|-------|")
    for r in ranking:
        lines.append(
            f"| {r.get('rank')} | {r.get('branch_id')} | {r.get('seam_id')} | "
            f"{r.get('kind') or '-'} | {r.get('games_completed') or '-'} | "
            f"{_num(r.get('adjusted_win_rate'))} | {_ci_str(r.get('wilson80'))} | "
            f"{_ci_str(r.get('wilson95'))} | {_num(r.get('seat_balance_delta'), '{:+.3f}')} "
            f"| {r.get('label') or ('REJECTED' if r.get('rejected') else '-')} |"
        )
    return lines


def _pass4_md(data: dict) -> list[str]:
    """Pass 4 — replay + chaos scout section (degrades to empty states)."""
    scout = data.get("pass4_scout_ranking") or []
    blocked = data.get("pass4_blocked") or []
    replay = data.get("pass4_replay") or {}
    delta = round(V2_LIVE_SCORE - V1_LIVE_SCORE, 1)

    lines = [
        "## Pass 4 — Replay + chaos scout",
        "",
        f"- v1 control (corrected live score): **{V1_LIVE_SCORE}**",
        f"- v2 control `deck_energy_trim_light` (live score): **{V2_LIVE_SCORE}** "
        f"(**+{delta}** vs corrected v1)",
        "- The v1 archive directory keeps its historical `v1_kaggle_349_8` name; "
        f"live v1 is {V1_LIVE_SCORE} (see v2 baseline README correction note). The "
        "directory is intentionally not renamed.",
        "- Scope: local research + reporting only — **no Kaggle upload, no GitHub "
        "push**; root `main.py`/`deck.csv` left immutable.",
        "",
        "### Replay analysis",
    ]
    if replay.get("status") == "missing":
        lines.append(
            f"- Replay `{replay.get('requested_path')}` is **not uploaded** — "
            f"analysis pending. {replay.get('note', '')}".rstrip())
    elif replay:
        ep = replay.get("episode", {})
        lines.append(f"- Episode {ep.get('episode_id')}: {ep.get('num_steps')} steps, "
                     f"final result {ep.get('final_result')}.")
    else:
        lines.append("- _No replay analysis artifact found._")

    lines += ["", "### Scout ranking (candidates vs v2 control)"]
    lines += _ranking_md(scout, "Pass 4 scout ranking")[1:] if scout else [
        "_No Pass 4 scout ranking yet._"]

    lines += ["", "### Blocked chaos archetypes (no invented ids)"]
    if blocked:
        for c in blocked:
            ids = ", ".join(str(i) for i in (c.get("core_card_ids") or []))
            reason = c.get("reason") or c.get("blocked_reason") or "-"
            lines.append(f"- **{c.get('branch_id')}** ({c.get('seam_id')}) — "
                         f"confirmed core ids [{ids}]. Blocked: {reason}")
    else:
        lines.append("_No blocked chaos candidates recorded._")

    return lines


def write_markdown(data: dict, path: Path = REPORT_MD) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    events, ranking, focused, runs, queue = (
        data["events"], data["ranking"], data.get("focused_ranking", []),
        data["runs"], data["queue"],
    )
    counts = Counter(e.get("event_type") for e in events)
    combos = [r for r in runs if (r["branch"].kind == "combo")]
    primary = focused or ranking
    survivors = [r for r in primary
                 if not r.get("rejected") and r.get("label") in
                 ("promotable", "confirmation_promising")]
    rejected = [r for r in primary if r.get("rejected")
                or r.get("label") in ("rejected", "inconclusive")]
    top3 = survivors[:3]

    lines = [
        "# ActiveGraph Strategy Lab — Report",
        "",
        "Transparent experiment factory around the immutable v1 control "
        "(Kaggle public score 349.8). Two-stage evaluation: a broad scout pass "
        "then a focused seat-swap confirmation pass with Wilson confidence "
        "intervals and conservative promotion labels.",
        "",
        "## Snapshot",
        f"- Events recorded: **{len(events)}**",
        f"- Candidates generated: **{len(runs)}** "
        f"({len(combos)} combination / generation-2)",
        f"- Broad-ranked: **{len(ranking)}**, Focused-ranked: **{len(focused)}**",
        f"- Survivors (promotable / confirmation): **{len(survivors)}**, "
        f"Rejected / inconclusive: **{len(rejected)}**",
        "",
    ]

    lines += _pass4_md(data)
    lines += [""]
    lines += _ranking_md(ranking, "Stage 1 — Broad scout ranking")
    lines += [""]
    lines += _ranking_md(focused, "Stage 2 — Focused seat-swap confirmation ranking")

    lines += ["", "## Top candidates (focused)"]
    if top3:
        for r in top3:
            lines.append(
                f"- **{r.get('branch_id')}** ({r.get('seam_id')}, "
                f"{r.get('kind') or 'single'}) — _{r.get('label')}_  ")
            lines.append(f"  - Hypothesis: {r.get('hypothesis') or '(n/a)'}")
            lines.append(
                f"  - Adjusted WR {_num(r.get('adjusted_win_rate'))} "
                f"(80% CI {_ci_str(r.get('wilson80'))}), seat split "
                f"p0={_num(r.get('candidate_p0_win_rate'))} / "
                f"p1={_num(r.get('candidate_p1_win_rate'))} "
                f"(Δ {_num(r.get('seat_balance_delta'), '{:+.3f}')})")
            if r.get("interpretation"):
                lines.append(f"  - {r.get('interpretation')}")
    else:
        lines.append("_No promotable or confirmation candidates at the focused "
                     "stage._")

    lines += ["", "## Combination (generation-2) candidates"]
    if combos:
        for r in combos:
            b = r["branch"]
            lines.append(f"- **{b.branch_id}** — {b.hypothesis}")
    else:
        lines.append("_No combination candidates generated._")

    lines += ["", "## Rejected & inconclusive"]
    if rejected:
        for r in rejected:
            reasons = ", ".join(r.get("reject_reasons") or []) or r.get("label") or "-"
            lines.append(f"- {r.get('branch_id')} ({r.get('seam_id')}): {reasons}")
    else:
        lines.append("_None._")

    lines += ["", "## Submission queue"]
    if queue:
        lines.append(f"- Mode: **{queue.get('mode', 'n/a')}** "
                     f"(auto_submit={queue.get('auto_submit_enabled')}, "
                     f"manual_approval={queue.get('require_manual_approval_for_submit')})")
        for c in queue.get("candidates", []):
            lines.append(f"  - {c.get('branch_id')} [{c.get('label')}] "
                         f"-> `{c.get('tarball')}` (NOT uploaded)")
        if not queue.get("candidates"):
            lines.append("  - (nothing queued)")
    else:
        lines.append("_Queue not built yet._")

    lines += ["", "## Current interpretation"]
    if top3:
        best = top3[0]
        lines.append(
            f"The strongest focused candidate is **{best.get('branch_id')}** "
            f"({best.get('seam_id')}), labelled _{best.get('label')}_ with an "
            f"adjusted win rate of {_num(best.get('adjusted_win_rate'))} "
            f"(80% CI {_ci_str(best.get('wilson80'))}). ")
        if best.get("label") == "promotable":
            lines.append(
                "Its 80% lower bound clears 0.50 and it beats the v1 control, so "
                "it is a defensible submission — but local cabt is only a proxy "
                "for the hidden Kaggle ladder, so treat it as directional.")
        else:
            lines.append(
                "No candidate has yet cleared the promotion gate (80% lower bound "
                "above 0.50 while beating the v1 control); the queue holds the "
                "best confirmation candidates for an optional, clearly-flagged "
                "submission. The v1 baseline (349.8) remains the control.")
    else:
        lines.append("No candidate currently beats the v1 control with confidence; "
                     "the immutable v1 baseline (349.8) remains the best option.")

    lines += ["", "## Event types"]
    if counts:
        for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {t}: {n}")
    else:
        lines.append("_No events yet._")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
