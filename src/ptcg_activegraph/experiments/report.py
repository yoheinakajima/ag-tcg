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
QUEUE_JSON = Path("data/submission_queue.json")

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
        "queue": _load_json(QUEUE_JSON) or {},
        "runs": runs,
        "baseline_readme": (BASELINE_DIR / "README.md"),
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


def _overview_html(data: dict) -> str:
    events = data["events"]
    ranking = data["ranking"]
    runs = data["runs"]
    counts = Counter(e.get("event_type") for e in events)
    promotable = [r for r in ranking if not r.get("rejected") and r.get("score") is not None]

    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Events", len(events)),
            ("Candidates", len(runs)),
            ("Promotable", len(promotable)),
            ("Rejected", sum(1 for r in ranking if r.get("rejected"))),
        ]
    )

    if ranking:
        rows = "".join(
            f"<tr><td>{r.get('rank')}</td><td>{_esc(r.get('branch_id'))}</td>"
            f"<td>{_esc(r.get('seam_id'))}</td>"
            f"<td>{'-' if r.get('score') is None else _esc(r.get('score'))}</td>"
            f"<td>{'-' if r.get('win_rate') is None else _esc(r.get('win_rate'))}</td>"
            f"<td class={'rej' if r.get('rejected') else 'ok'}>"
            f"{'REJECTED' if r.get('rejected') else 'ok'}</td></tr>"
            for r in ranking
        )
        rank_tbl = ("<table><tr><th>#</th><th>Branch</th><th>Seam</th><th>Score</th>"
                    f"<th>Win rate</th><th>Status</th></tr>{rows}</table>")
    else:
        rank_tbl = "<div class=empty>No ranking yet — run the batch and rank_candidates.</div>"

    type_rows = "".join(
        f"<tr><td>{_esc(t)}</td><td>{n}</td></tr>"
        for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ) or "<tr><td class=muted colspan=2>no events yet</td></tr>"

    body = (
        f"<section><h2>Snapshot</h2><div class=cards>{cards}</div></section>"
        f"<section><h2>Latest ranking</h2>{rank_tbl}</section>"
        f"<section><h2>Event types</h2><table><tr><th>Type</th><th>Count</th></tr>"
        f"{type_rows}</table></section>"
    )
    return _page("Overview", body)


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

def write_markdown(data: dict, path: Path = REPORT_MD) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    events, ranking, runs, queue = (
        data["events"], data["ranking"], data["runs"], data["queue"],
    )
    counts = Counter(e.get("event_type") for e in events)
    lines = [
        "# ActiveGraph Strategy Lab — Report",
        "",
        "Transparent experiment factory around the immutable v1 control "
        "(Kaggle public score 349.8).",
        "",
        "## Snapshot",
        f"- Events recorded: **{len(events)}**",
        f"- Candidates generated: **{len(runs)}**",
        f"- Ranked: **{len(ranking)}** "
        f"({sum(1 for r in ranking if r.get('rejected'))} rejected)",
        "",
        "## Ranking",
    ]
    if ranking:
        lines.append("| # | Branch | Seam | Score | Win rate | Status |")
        lines.append("|--:|--------|------|------:|---------:|--------|")
        for r in ranking:
            status = "REJECTED" if r.get("rejected") else "ok"
            sc = "-" if r.get("score") is None else f"{r.get('score')}"
            wr = "-" if r.get("win_rate") is None else f"{r.get('win_rate')}"
            lines.append(f"| {r.get('rank')} | {r.get('branch_id')} | "
                         f"{r.get('seam_id')} | {sc} | {wr} | {status} |")
    else:
        lines.append("_No ranking yet._")
    lines += ["", "## Candidate lineage"]
    if runs:
        for r in runs:
            b = r["branch"]
            lines.append(f"- **{b.branch_id}** ({b.seam_id}, {b.kind}) — {b.hypothesis}")
    else:
        lines.append("_No candidates generated yet._")
    lines += ["", "## Submission queue"]
    if queue:
        lines.append(f"- Mode: **{queue.get('mode', 'n/a')}** "
                     f"(auto_submit={queue.get('auto_submit_enabled')}, "
                     f"manual_approval={queue.get('require_manual_approval_for_submit')})")
        for c in queue.get("candidates", []):
            lines.append(f"  - {c.get('branch_id')} -> `{c.get('kaggle_command')}`")
        if not queue.get("candidates"):
            lines.append("  - (nothing queued)")
    else:
        lines.append("_Queue not built yet._")
    lines += ["", "## Event types"]
    if counts:
        for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {t}: {n}")
    else:
        lines.append("_No events yet._")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
