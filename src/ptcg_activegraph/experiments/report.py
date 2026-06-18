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
PASS5_SCOUT_RANKING_JSON = Path("data/experiments/pass5_scout_ranking.json")
PASS5_FOCUSED_RANKING_JSON = Path("data/experiments/pass5_focused_ranking.json")
PASS5_REPLAY_ANALYSIS_JSON = Path("data/replays/80374966_analysis.json")
CHAOS_TELEMETRY_CONTRACT_JSON = Path("data/experiments/chaos_telemetry_contract.json")
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


def _load_run_ledger() -> list[dict]:
    """Summaries of every durable ActiveGraph run ledger (Pass 7A, Part E).

    The ledger — not the HTML — is the source of truth for run/candidate/game
    state. This reads it through the same adapter the runner writes with, so the
    report can never drift from the recorded events. Degrades to ``[]`` when no
    runs exist (or the ledger is unavailable).
    """
    try:
        from ..ag import ActiveGraphLedger

        ledger = ActiveGraphLedger(warn=False)
        out = []
        for run in ledger.list_runs():
            run_id = run.get("run_id")
            if not run_id:
                continue
            out.append(ledger.inspect_run(run_id))
        return out
    except Exception:
        return []


def gather(runs_root=RUNS_ROOT) -> dict:
    """Collect everything the report needs into one dict (all optional)."""
    runs = []
    for run_dir in list_runs(runs_root):
        b = load_branch_yaml(run_dir)
        m = _load_json(Path(run_dir) / "metrics.json")
        if b:
            runs.append({"branch": b, "metrics": m, "run_dir": str(run_dir)})
    return {
        "run_ledger": _load_run_ledger(),
        "events": _load_events(),
        "ranking": _load_json(RANKING_JSON) or [],
        "focused_ranking": _load_json(FOCUSED_RANKING_JSON) or [],
        "pass4_scout_ranking": _load_json(PASS4_SCOUT_RANKING_JSON) or [],
        "pass4_blocked": _load_json(PASS4_BLOCKED_JSON) or [],
        "pass4_replay": _load_json(PASS4_REPLAY_ANALYSIS_JSON) or {},
        "pass5_scout_ranking": _load_json(PASS5_SCOUT_RANKING_JSON) or [],
        "pass5_focused_ranking": _load_json(PASS5_FOCUSED_RANKING_JSON) or [],
        "pass5_replay": _load_json(PASS5_REPLAY_ANALYSIS_JSON) or {},
        "chaos_contract": _load_json(CHAOS_TELEMETRY_CONTRACT_JSON) or {},
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


def _run_ledger_html(data: dict) -> str:
    """Render durable run-ledger summaries (Pass 7A source of truth)."""
    ledger = data.get("run_ledger") or []
    if not ledger:
        return ("<section><h2>Durable run ledger</h2><div class=empty>No durable "
                "runs recorded yet — created by <code>scripts/run_durable_eval.py"
                "</code>.</div></section>")
    rows = ""
    details = ""
    for s in ledger:
        gs = s.get("game_status_counts") or s.get("games_by_status") or {}
        gs_str = ", ".join(f"{k}:{v}" for k, v in sorted(gs.items())) or "-"
        artifacts = s.get("artifact_paths") or []
        rows += (
            f"<tr><td><code>{_esc(s.get('run_id'))}</code></td>"
            f"<td>{_esc(s.get('status') or '-')}</td>"
            f"<td>{_esc(s.get('candidate_count', '-'))}</td>"
            f"<td>{_esc(s.get('game_count', '-'))}</td>"
            f"<td>{_esc(gs_str)}</td>"
            f"<td>{_esc(s.get('event_count', 0))}</td>"
            f"<td>{_esc(len(artifacts))}</td>"
            f"</tr>"
        )
        # Event-type timeline + cited artifact paths for this run.
        ebt = s.get("events_by_type") or {}
        tl = ", ".join(f"{k}×{v}" for k, v in sorted(ebt.items())) or "no events"
        art_html = "".join(
            f"<li><code>{_esc(p)}</code></li>" for p in artifacts[:20]
        ) or "<li class=muted>none cited</li>"
        details += (
            f"<details><summary><code>{_esc(s.get('run_id'))}</code> — "
            f"{_esc(s.get('status') or '-')}</summary>"
            f"<p class=muted>Timeline: {_esc(tl)}</p>"
            f"<p class=muted>Artifacts cited (first 20):</p>"
            f"<ul>{art_html}</ul></details>"
        )
    return ("<section><h2>Durable run ledger</h2>"
            "<p class=muted>Source of truth: <code>data/activegraph/"
            "ptcg_ledger_events.jsonl</code>. The HTML is a projection of these "
            "events, never the other way round. Status values: "
            "completed / partial / stale / failed / created.</p>"
            "<table><tr><th>Run</th><th>Status</th><th>Candidates</th>"
            "<th>Games</th><th>Game status</th><th>Events</th><th>Artifacts</th></tr>"
            f"{rows}</table>{details}</section>")


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
        f"{_run_ledger_html(data)}"
        f"{_pass4_html(data)}"
        f"{_pass5_html(data)}"
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


def _pass5_findings(replay: dict) -> dict:
    """Extract Pass-5 replay findings from the real analysis (honest fallbacks)."""
    ep = replay.get("episode") or {}
    fr = ep.get("final_result") or {}
    fs = replay.get("final_state") or {}
    et = replay.get("effect_traces") or {}
    f: dict = {
        "episode_id": ep.get("episode_id", "uncertain"),
        "total_steps": ep.get("total_steps", "uncertain"),
        "winner_seat": fr.get("winner_seat", "uncertain"),
        "loser_seat": fs.get("loser_seat", "uncertain"),
        "loss_reason": fs.get("apparent_loss_reason", "uncertain"),
        "strongest_tag": replay.get("strongest_failure_tag", "uncertain"),
        "trace_count": et.get("trace_count", "uncertain"),
        "traces_by_card": et.get("traces_by_effect_card") or {},
        "per_seat": fs.get("per_seat") or [],
        "failure_tags": [t for t in (replay.get("failure_tags") or []) if t.get("present")],
    }
    return f


def _ev_str(ev) -> str:
    if isinstance(ev, list):
        return "; ".join(str(x) for x in ev)
    return str(ev)


def _chaos_summary(chaos: dict) -> str:
    """Honest readiness sentence derived from the loaded contract (no fabrication).

    Returns plain text (no markup) so HTML and Markdown renderers can apply their
    own emphasis. Degrades to an explicit 'uncertain' statement when no contract
    is loaded rather than asserting a fabricated 'all blocked' conclusion.
    """
    seams = (chaos or {}).get("seams") or []
    if not seams:
        return ("Chaos telemetry contract not loaded — readiness is uncertain. "
                "No card ids invented; no conclusions fabricated.")
    blocked = [s for s in seams if s.get("telemetry_availability") == "blocked"]
    if len(blocked) == len(seams):
        return (f"All {len(seams)} chaos seams remain blocked: their decisive "
                "signals are opponent-hidden, so own-seat telemetry cannot supply "
                "them. No card ids invented; no conclusions fabricated.")
    return (f"{len(blocked)} of {len(seams)} chaos seams are blocked "
            "(opponent-hidden signals); the remainder are uncertain — see the "
            "table below. No card ids invented; no conclusions fabricated.")


def _pass5_html(data: dict) -> str:
    replay = data.get("pass5_replay") or {}
    scout = data.get("pass5_scout_ranking") or []
    focused = data.get("pass5_focused_ranking") or []
    chaos = data.get("chaos_contract") or {}

    if not replay:
        return ("<section><h2>Pass 5 — Replay-informed effect resolution &amp; "
                "deck-out awareness</h2><div class=empty>No replay analysis artifact "
                "found yet.</div></section>")

    f = _pass5_findings(replay)

    # Effect-resolution failure chain (strongest tag + present tags w/ evidence).
    tag_rows = "".join(
        f"<tr><td>{_esc(t.get('tag'))}</td><td>{_esc(t.get('confidence'))}</td>"
        f"<td>{_esc(_ev_str(t.get('evidence')))}</td></tr>"
        for t in f["failure_tags"]
    ) or "<tr><td class=muted colspan=3>no failure tags present</td></tr>"

    card_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in f["traces_by_card"].items()
    ) or "<tr><td class=muted colspan=2>no effect traces</td></tr>"

    seat_rows = "".join(
        f"<tr><td>{_esc(s.get('seat'))}</td><td>{_esc(s.get('deck_count'))}</td>"
        f"<td>{_esc(s.get('hand_count'))}</td><td>{_esc(s.get('discard_count'))}</td></tr>"
        for s in f["per_seat"]
    ) or "<tr><td class=muted colspan=4>no final-state per-seat data</td></tr>"

    # Chaos telemetry readiness — all seams blocked (decisive signals opponent-hidden).
    seams = chaos.get("seams") or []
    chaos_rows = "".join(
        f"<tr><td>{_esc(s.get('seam_id'))}</td>"
        f"<td>{_esc(s.get('telemetry_availability'))}</td>"
        f"<td>{_esc(', '.join(str(i) for i in (s.get('confirmed_card_ids') or [])) or '-')}</td>"
        f"<td>{_esc(_ev_str(s.get('blockers')))}</td></tr>"
        for s in seams
    ) or "<tr><td class=muted colspan=4>no chaos contract loaded</td></tr>"

    return (
        "<section><h2>Pass 5 — Replay-informed effect resolution &amp; "
        "deck-out awareness</h2>"
        "<p class=muted>Local research only — <b>no Kaggle upload, no GitHub push</b>; "
        f"root <code>main.py</code>/<code>deck.csv</code> immutable. Controls: v1 live "
        f"<b>{V1_LIVE_SCORE}</b>, v2 <code>deck_energy_trim_light</code> live "
        f"<b>{V2_LIVE_SCORE}</b>.</p>"
        f"<h3>Replay findings (episode {_esc(f['episode_id'])})</h3>"
        f"<p>{_esc(f['total_steps'])} steps; winner seat {_esc(f['winner_seat'])}, "
        f"loser seat {_esc(f['loser_seat'])}. Apparent loss reason: "
        f"<b>{_esc(f['loss_reason'])}</b>.</p>"
        "<h3>Effect-resolution failure chain</h3>"
        f"<p>Strongest failure tag: <b>{_esc(f['strongest_tag'])}</b> "
        f"({_esc(f['trace_count'])} effect traces examined).</p>"
        "<table><tr><th>Failure tag</th><th>Confidence</th><th>Evidence</th></tr>"
        f"{tag_rows}</table>"
        "<h4>Effect traces by card</h4>"
        "<table><tr><th>Effect card</th><th>Traces</th></tr>"
        f"{card_rows}</table>"
        "<h3>Deck-out evidence (final state)</h3>"
        "<table><tr><th>Seat</th><th>Deck</th><th>Hand</th><th>Discard</th></tr>"
        f"{seat_rows}</table>"
        "<h3>Candidate results (vs v2 control)</h3>"
        "<h4>Scout ranking</h4>"
        f"{_rank_table_html(scout)}"
        "<h4>Focused ranking</h4>"
        f"{_rank_table_html(focused)}"
        "<h3>Chaos telemetry readiness</h3>"
        f"<p class=muted>{_esc(_chaos_summary(chaos))}</p>"
        "<table><tr><th>Seam</th><th>Telemetry</th><th>Confirmed ids</th>"
        f"<th>Blockers</th></tr>{chaos_rows}</table>"
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


def _run_ledger_md(data: dict) -> list[str]:
    """Render durable run-ledger summaries as Markdown (Pass 7A source of truth)."""
    ledger = data.get("run_ledger") or []
    lines = ["## Durable run ledger",
             "_Source of truth: `data/activegraph/ptcg_ledger_events.jsonl`. "
             "This table is a projection of those events._"]
    if not ledger:
        lines.append("")
        lines.append("_No durable runs recorded yet._")
        return lines
    lines.append("")
    lines.append("Status values: completed / partial / stale / failed / created.")
    lines.append("")
    lines.append("| Run | Status | Candidates | Games | Game status | Events | Artifacts |")
    lines.append("|-----|--------|-----------:|------:|-------------|-------:|----------:|")
    for s in ledger:
        gs = s.get("game_status_counts") or s.get("games_by_status") or {}
        gs_str = ", ".join(f"{k}:{v}" for k, v in sorted(gs.items())) or "-"
        ev = s.get("event_count", 0)
        n_art = len(s.get("artifact_paths") or [])
        lines.append(
            f"| `{s.get('run_id')}` | {s.get('status') or '-'} | "
            f"{s.get('candidate_count', '-')} | "
            f"{s.get('game_count', '-')} | {gs_str} | {ev} | {n_art} |"
        )
    # Per-run event-type timeline + cited artifact paths.
    for s in ledger:
        ebt = s.get("events_by_type") or {}
        tl = ", ".join(f"{k}×{v}" for k, v in sorted(ebt.items())) or "no events"
        lines.append("")
        lines.append(f"### `{s.get('run_id')}` — {s.get('status') or '-'}")
        lines.append(f"- Timeline: {tl}")
        artifacts = s.get("artifact_paths") or []
        if artifacts:
            lines.append("- Artifacts cited:")
            for p in artifacts[:20]:
                lines.append(f"  - `{p}`")
        else:
            lines.append("- Artifacts cited: _none_")
    return lines


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


def _pass5_md(data: dict) -> list[str]:
    """Pass 5 — replay-informed effect resolution + deck-out awareness."""
    replay = data.get("pass5_replay") or {}
    scout = data.get("pass5_scout_ranking") or []
    focused = data.get("pass5_focused_ranking") or []
    chaos = data.get("chaos_contract") or {}

    lines = ["## Pass 5 — Replay-informed effect resolution & deck-out awareness", ""]
    if not replay:
        lines.append("_No replay analysis artifact found yet._")
        return lines

    f = _pass5_findings(replay)
    lines += [
        f"- Controls: v1 live **{V1_LIVE_SCORE}**, v2 `deck_energy_trim_light` live "
        f"**{V2_LIVE_SCORE}**.",
        "- Scope: local research only — **no Kaggle upload, no GitHub push**; root "
        "`main.py`/`deck.csv` immutable.",
        "",
        f"### Replay findings (episode {f['episode_id']})",
        f"- {f['total_steps']} steps; winner seat {f['winner_seat']}, loser seat "
        f"{f['loser_seat']}.",
        f"- Apparent loss reason: **{f['loss_reason']}**.",
        "",
        "### Effect-resolution failure chain",
        f"- Strongest failure tag: **{f['strongest_tag']}** ({f['trace_count']} "
        "effect traces examined).",
    ]
    if f["failure_tags"]:
        lines.append("")
        lines.append("| Failure tag | Confidence | Evidence |")
        lines.append("|-------------|------------|----------|")
        for t in f["failure_tags"]:
            lines.append(f"| {t.get('tag')} | {t.get('confidence')} | "
                         f"{_ev_str(t.get('evidence'))} |")
    if f["traces_by_card"]:
        lines += ["", "**Effect traces by card:**"]
        for k, v in f["traces_by_card"].items():
            lines.append(f"- {k}: {v}")

    lines += ["", "### Deck-out evidence (final state)"]
    if f["per_seat"]:
        lines.append("| Seat | Deck | Hand | Discard |")
        lines.append("|-----:|-----:|-----:|--------:|")
        for s in f["per_seat"]:
            lines.append(f"| {s.get('seat')} | {s.get('deck_count')} | "
                         f"{s.get('hand_count')} | {s.get('discard_count')} |")
    else:
        lines.append("_No final-state per-seat data._")

    lines += ["", "### Candidate results (vs v2 control)"]
    lines += _ranking_md(scout, "Pass 5 scout ranking")
    lines += [""]
    lines += _ranking_md(focused, "Pass 5 focused ranking")

    lines += ["", "### Chaos telemetry readiness"]
    lines.append(_chaos_summary(chaos))
    seams = chaos.get("seams") or []
    if seams:
        lines += ["", "| Seam | Telemetry | Confirmed ids | Blockers |",
                  "|------|-----------|---------------|----------|"]
        for s in seams:
            ids = ", ".join(str(i) for i in (s.get("confirmed_card_ids") or [])) or "-"
            lines.append(f"| {s.get('seam_id')} | {s.get('telemetry_availability')} | "
                         f"{ids} | {_ev_str(s.get('blockers'))} |")
    else:
        lines.append("_No chaos contract loaded._")

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

    lines += _run_ledger_md(data)
    lines += [""]
    lines += _pass4_md(data)
    lines += [""]
    lines += _pass5_md(data)
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
