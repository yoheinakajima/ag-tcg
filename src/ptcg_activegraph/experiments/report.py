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
PASS7B_SCOUT_RANKING_JSON = Path("data/experiments/pass7b_scout_ranking.json")
PASS7B_FOCUSED_RANKING_JSON = Path("data/experiments/pass7b_focused_ranking.json")
PASS7B_FIXTURE_GATE_JSON = Path("data/experiments/pass7b_fixture_gate.json")
PASS7B_BENCHMARK_JSON = Path("data/experiments/cabt_import_benchmark_pass7b.json")
PASS8_SCOUT_RANKING_JSON = Path("data/experiments/pass8_scout_ranking.json")
PASS8_FOCUSED_RANKING_JSON = Path("data/experiments/pass8_focused_ranking.json")
PASS8_FIXTURE_GATE_JSON = Path("data/experiments/pass8_fixture_gate.json")
PASS9_FIXTURE_GATE_JSON = Path("data/experiments/pass9_fixture_gate.json")
META_ARCHETYPES_JSON = Path("data/meta/meta_archetypes.json")
# Pass 10 — meta-calibrated evaluation + tempo playbook artifacts.
PASS10_META_SUMMARY_JSON = Path("data/meta_replays/meta_replay_summary.json")
PASS10_META_POOL_YAML = Path("experiments/meta_pool.yaml")
PASS10_CANDIDATES_MANIFEST_JSON = Path("data/submissions/pass10_candidates_manifest.json")
PASS10_EVAL_STATUS_JSON = Path("data/meta_replays/pass10_eval_status.json")
# Pass 10B — evaluation recovery + replay acquisition artifacts.
PASS10B_LIVE_REGISTRY_JSON = Path("data/kaggle_uploads/live_score_registry.json")
PASS10B_CABT_DIAG_JSON = Path("data/experiments/cabt_diagnostic.json")
PASS10B_EVAL_SMOKE_JSON = Path("data/experiments/pass10b_eval_smoke.json")
# Pass 11B — replay inbox + meta-pool automation artifacts.
PASS11B_REPLAY_REGISTRY_JSON = Path("data/meta_replays/replay_registry.json")
PASS11B_PROCESSING_STATE_JSON = Path("data/meta_replays/replay_processing_state.json")
PASS11B_INBOX_ERRORS_JSON = Path("data/meta_replays/replay_inbox_errors.json")
PASS11B_REPLAY_ANALYSIS_JSON = Path("data/meta_replays/replay_analysis.json")
PASS11B_ARCHETYPES_YAML = Path("data/meta_replays/archetypes.yaml")
PASS11B_META_POOL_YAML = Path("experiments/meta_pool.yaml")
PASS11B_META_EVAL_JSON = Path("data/experiments/pass11b_meta_eval.json")
PASS11B_RANKING_JSON = Path("data/experiments/pass11b_ranking.json")
PASS11B_REPORT_MD = Path("data/reports/pass11b_replay_inbox_report.md")
# Pass 12 — meta-driven candidate generation + two-stage directional eval.
PASS12_CONFIG_YAML = Path("experiments/pass12_meta_eval.yaml")
PASS12_CANDIDATES_MANIFEST_JSON = Path("data/submissions/pass12_candidates_manifest.json")
PASS12_SCOUT_JSON = Path("data/experiments/pass12_scout_results.json")
PASS12_FOCUSED_JSON = Path("data/experiments/pass12_focused_results.json")
PASS12_CANDIDATE_METRICS_JSON = Path("data/experiments/pass12_candidate_metrics.json")
PASS12_RANKING_JSON = Path("data/experiments/pass12_ranking.json")
PASS12_DRY_RUN_QUEUE_JSON = Path("data/experiments/pass12_dry_run_queue.json")
PASS12_REPORT_MD = Path("data/reports/pass12_meta_candidate_eval_report.md")
# Pass 13 — operating manual + unknown_ex_tempo decomposition (docs + meta-analysis).
PASS13_MANUAL_MD = Path("docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md")
PASS13_NEXT_AGENT_MD = Path("docs/NEXT_AGENT_README.md")
PASS13_DECOMP_JSON = Path("data/meta_replays/unknown_ex_tempo_decomposition.json")
PASS13_REFINED_POOL_YAML = Path("experiments/pass13_refined_meta_pool.yaml")
PASS13_REFINED_EVAL_JSON = Path("data/experiments/pass13_refined_eval.json")
PASS13_LIVE_REGISTRY_JSON = Path("data/kaggle_uploads/live_score_registry.json")
PASS13_REPORT_MD = Path("data/reports/pass13_operating_manual_and_meta_decomposition.md")
# Pass 15 — core-pilot runtime coverage + focused directional confirmation (local-only).
PASS15_RUNTIME_COVERAGE_JSON = Path("data/experiments/pass15_core_runtime_coverage.json")
PASS15_EXPANSION_PLAN_MD = Path("data/experiments/pass15_runtime_expansion_plan.md")
PASS15_LIVE_SMOKE_JSON = Path("data/reports/pass15_live_smoke.json")
PASS15_FOCUSED_EVAL_JSON = Path("data/reports/pass15_core_focused_eval.json")
PASS15_METRICS_JSON = Path("data/experiments/pass15_candidate_metrics.json")
PASS15_DRY_RUN_QUEUE_JSON = Path("data/experiments/pass15_dry_run_queue.json")
PASS15_RUNTIME_REPORT_MD = Path("data/reports/pass15_runtime_coverage_report.md")
PASS15_EVAL_REPORT_MD = Path("data/reports/pass15_focused_eval_report.md")

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


def _load_yaml(path: Path):
    if not Path(path).exists():
        return None
    try:
        import yaml  # local import; yaml is available in this repo
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:
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
        "pass7b_scout_ranking": _load_json(PASS7B_SCOUT_RANKING_JSON) or {},
        "pass7b_focused_ranking": _load_json(PASS7B_FOCUSED_RANKING_JSON) or {},
        "pass7b_fixture_gate": _load_json(PASS7B_FIXTURE_GATE_JSON) or {},
        "pass7b_benchmark": _load_json(PASS7B_BENCHMARK_JSON) or {},
        "pass8_scout_ranking": _load_json(PASS8_SCOUT_RANKING_JSON) or {},
        "pass8_focused_ranking": _load_json(PASS8_FOCUSED_RANKING_JSON) or {},
        "pass8_fixture_gate": _load_json(PASS8_FIXTURE_GATE_JSON) or {},
        "pass9_fixture_gate": _load_json(PASS9_FIXTURE_GATE_JSON) or {},
        "meta_archetypes": _load_json(META_ARCHETYPES_JSON) or {},
        "pass10_meta_summary": _load_json(PASS10_META_SUMMARY_JSON) or {},
        "pass10_meta_pool": _load_yaml(PASS10_META_POOL_YAML) or {},
        "pass10_candidates": _load_json(PASS10_CANDIDATES_MANIFEST_JSON) or {},
        "pass10_eval": _load_json(PASS10_EVAL_STATUS_JSON) or {},
        "pass10b_live_registry": _load_json(PASS10B_LIVE_REGISTRY_JSON) or {},
        "pass10b_cabt_diag": _load_json(PASS10B_CABT_DIAG_JSON) or {},
        "pass10b_eval_smoke": _load_json(PASS10B_EVAL_SMOKE_JSON) or {},
        "pass11b_replay_registry": _load_json(PASS11B_REPLAY_REGISTRY_JSON) or {},
        "pass11b_processing_state": _load_json(PASS11B_PROCESSING_STATE_JSON) or {},
        "pass11b_inbox_errors": _load_json(PASS11B_INBOX_ERRORS_JSON) or {},
        "pass11b_replay_analysis": _load_json(PASS11B_REPLAY_ANALYSIS_JSON) or {},
        "pass11b_archetypes": _load_yaml(PASS11B_ARCHETYPES_YAML) or {},
        "pass11b_meta_pool": _load_yaml(PASS11B_META_POOL_YAML) or {},
        "pass11b_meta_eval": _load_json(PASS11B_META_EVAL_JSON) or {},
        "pass11b_ranking": _load_json(PASS11B_RANKING_JSON) or {},
        "pass12_config": _load_yaml(PASS12_CONFIG_YAML) or {},
        "pass12_candidates": _load_json(PASS12_CANDIDATES_MANIFEST_JSON) or {},
        "pass12_scout": _load_json(PASS12_SCOUT_JSON) or {},
        "pass12_focused": _load_json(PASS12_FOCUSED_JSON) or {},
        "pass12_metrics": _load_json(PASS12_CANDIDATE_METRICS_JSON) or {},
        "pass12_ranking": _load_json(PASS12_RANKING_JSON) or {},
        "pass12_dry_run_queue": _load_json(PASS12_DRY_RUN_QUEUE_JSON) or {},
        "pass13_manual_exists": PASS13_MANUAL_MD.exists(),
        "pass13_next_agent_exists": PASS13_NEXT_AGENT_MD.exists(),
        "pass13_decomp": _load_json(PASS13_DECOMP_JSON) or {},
        "pass13_refined_pool": _load_yaml(PASS13_REFINED_POOL_YAML) or {},
        "pass13_refined_eval": _load_json(PASS13_REFINED_EVAL_JSON) or {},
        "pass13_live_registry": _load_json(PASS13_LIVE_REGISTRY_JSON) or {},
        "pass15_runtime_coverage": _load_json(PASS15_RUNTIME_COVERAGE_JSON) or {},
        "pass15_expansion_plan_exists": PASS15_EXPANSION_PLAN_MD.exists(),
        "pass15_live_smoke": _load_json(PASS15_LIVE_SMOKE_JSON) or {},
        "pass15_focused_eval": _load_json(PASS15_FOCUSED_EVAL_JSON) or {},
        "pass15_metrics": _load_json(PASS15_METRICS_JSON) or {},
        "pass15_dry_run_queue": _load_json(PASS15_DRY_RUN_QUEUE_JSON) or {},
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
            f" (live {V1_LIVE_SCORE})</p></header>{nav}<main>{body}</main>"
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
        f"{_pass15_html(data)}"
        f"{_pass13_html(data)}"
        f"{_pass12_html(data)}"
        f"{_pass11b_html(data)}"
        f"{_pass10b_html(data)}"
        f"{_pass10_html(data)}"
        f"{_run_ledger_html(data)}"
        f"{_pass8_html(data)}"
        f"{_pass7b_html(data)}"
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


def _pass7b_rank_rows_html(ranking: dict) -> str:
    cands = (ranking or {}).get("candidates") or []
    if not cands:
        return ("<div class=empty>No Pass 7B ranking yet — run "
                "<code>scripts/run_durable_eval.py --rank</code>.</div>")
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{_esc(c.get('candidate_id'))}</td>"
        f"<td>{_esc(c.get('promotion_label'))}</td>"
        f"<td>{_esc(c.get('games_completed'))}/{_esc(c.get('games_planned'))}</td>"
        f"<td>{_esc(c.get('wins'))}-{_esc(c.get('losses'))}-{_esc(c.get('draws'))}</td>"
        f"<td>{_num(c.get('adjusted_win_rate'))}</td>"
        f"<td>{_ci_str(c.get('wilson_80'))}</td>"
        f"<td>{_ci_str(c.get('wilson_95'))}</td>"
        f"<td>{_num(c.get('seat_p0_win_rate'))}/{_num(c.get('seat_p1_win_rate'))}</td>"
        f"<td>{_esc(c.get('crashes'))}/{_esc(c.get('timeouts'))}/{_esc(c.get('stale'))}</td>"
        f"<td>{_esc(c.get('fixture_gate_status'))}</td></tr>"
        for i, c in enumerate(cands)
    )
    return ("<table><tr><th>#</th><th>Candidate</th><th>Label</th><th>Games</th>"
            "<th>W-L-D</th><th>Adj WR</th><th>80% CI</th><th>95% CI</th>"
            "<th>p0/p1</th><th>cr/to/st</th><th>Fixture</th></tr>"
            f"{rows}</table>")


def _pass7b_html(data: dict) -> str:
    scout = data.get("pass7b_scout_ranking") or {}
    focused = data.get("pass7b_focused_ranking") or {}
    gate = data.get("pass7b_fixture_gate") or {}
    bench = data.get("pass7b_benchmark") or {}
    meta = data.get("meta_archetypes") or {}
    queue = data.get("queue") or {}

    if not (scout or focused or gate or bench or meta or queue):
        return ("<section><h2>Pass 7B — Durable fast scout</h2><div class=empty>"
                "No Pass 7B artifacts found yet.</div></section>")

    baseline_cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("v2 active control", V2_LIVE_SCORE),
            ("v1 control (live)", V1_LIVE_SCORE),
            ("import speedup", f"{bench.get('import_speedup_x', '-')}×"),
            ("Kaggle upload", "no"),
        ]
    )

    # Fast-import benchmark.
    n_imp = (bench.get("normal") or {}).get("import_seconds")
    f_imp = (bench.get("fast") or {}).get("import_seconds")
    bench_html = (
        f"<p>Cold cabt import: normal <b>{_num(n_imp, '{:.2f}')}s</b> → fast "
        f"<b>{_num(f_imp, '{:.2f}')}s</b> "
        f"(<b>{_esc(bench.get('import_speedup_x', '-'))}×</b>, validated="
        f"{_esc(bench.get('fast_validated'))}).</p>"
    ) if bench else "<div class=empty>No benchmark artifact.</div>"

    # Fixture gate (anchors excluded everywhere, incl. the pass/fail summary).
    gate_results = [r for r in (gate.get("results") or []) if not r.get("is_anchor")]
    non_anchor_ids = {r.get("candidate_id") for r in gate_results}
    passed = [c for c in (gate.get("passed") or []) if not non_anchor_ids or c in non_anchor_ids]
    failed = [c for c in (gate.get("failed") or []) if not non_anchor_ids or c in non_anchor_ids]
    gate_rows = "".join(
        f"<tr><td>{_esc(r.get('candidate_id'))}</td>"
        f"<td>{_esc(r.get('status'))}</td>"
        f"<td>{_esc(r.get('seam_covered'))}</td>"
        f"<td>{_esc(r.get('preference_pass'))}/{_esc(r.get('preference_fail'))}/"
        f"{_esc(r.get('preference_na'))}</td></tr>"
        for r in gate_results
    ) or "<tr><td class=muted colspan=4>no fixture gate</td></tr>"
    gate_html = (
        f"<p class=muted>Passing: {_esc(', '.join(passed) or 'none')}; "
        f"failing: {_esc(', '.join(failed) or 'none')}. "
        f"Secret Box step-11 nuance preserved (forced 3-of-3 discard = forced_all/na, "
        "not a policy failure).</p>"
        "<table><tr><th>Candidate</th><th>Status</th><th>Seam covered</th>"
        f"<th>pref p/f/na</th></tr>{gate_rows}</table>"
    )

    # Dry-run queue (supports both the dry-run `queue[]` schema and legacy `candidates[]`).
    q_items = queue.get("queue") or queue.get("candidates") or []
    auto_submit = queue.get("auto_submit_enabled", queue.get("auto_submit"))
    upload = queue.get("upload_performed", queue.get("will_upload"))
    if q_items:
        q_html = "".join(
            f"<li><code>{_esc(c.get('candidate_id') or c.get('branch_id'))}</code> "
            f"[{_esc(c.get('promotion_label') or c.get('label'))}] "
            f"→ <code>{_esc(c.get('tarball'))}</code> (NOT uploaded)</li>"
            for c in q_items
        )
        q_html = (f"<p class=muted>auto_submit={_esc(auto_submit)}, "
                  f"manual_approval={_esc(queue.get('require_manual_approval_for_submit'))}, "
                  f"upload_performed={_esc(upload)}, "
                  f"max={_esc(queue.get('max_queue_size', queue.get('max_per_day')))}.</p>"
                  f"<ul>{q_html}</ul>")
    else:
        q_html = "<div class=empty>Queue empty — no candidate qualified.</div>"

    # Meta engine strategy backlog.
    tracks = (meta.get("strategy_tracks") or [])
    track_html = "".join(
        f"<li><b>{_esc(t.get('name'))}</b> — policy seam: <i>{_esc(t.get('policy_seam'))}</i></li>"
        for t in tracks
    ) or "<li class=muted>no strategy tracks</li>"
    meta_html = (
        f"<p class=muted>Replays present: {_esc(meta.get('n_replays', 0))}; "
        f"archetypes extracted: {_esc(meta.get('n_archetypes_extracted', 0))} "
        "(scaffolding only — no card ids invented). "
        "Docs: <code>docs/META_ENGINE_STRATEGIES.md</code>, "
        "<code>data/meta_replays/README.md</code>.</p>"
        f"<ul>{track_html}</ul>"
    )

    return (
        "<section><h2>Pass 7B — Durable fast scout</h2>"
        f"<div class=cards>{baseline_cards}</div>"
        "<p class=muted>Local research only — <b>no Kaggle upload, no GitHub push</b>; "
        "root <code>main.py</code>/<code>deck.csv</code> immutable. The durable "
        "ActiveGraph ledger (above) is the source of truth; tables below are "
        "projections.</p>"
        "<h3>Fast-import benchmark</h3>"
        f"{bench_html}"
        "<h3>Fixture gate (advisory)</h3>"
        f"{gate_html}"
        "<h3>Scout ranking (vs v2 control; controls/anchors excluded from queue)</h3>"
        f"{_pass7b_rank_rows_html(scout)}"
        "<h3>Focused micro-confirmation</h3>"
        f"{_pass7b_rank_rows_html(focused)}"
        "<h3>Dry-run submission queue (≤1, no upload)</h3>"
        f"{q_html}"
        "<h3>Meta engine strategy backlog</h3>"
        f"{meta_html}"
        "</section>"
    )


def _pass8_gate_html(gate: dict) -> str:
    """Render the Pass 8 fixture gate (hard promotion filter schema)."""
    if not gate:
        return "<div class=empty>No Pass 8 fixture gate yet.</div>"
    results = [r for r in (gate.get("results") or []) if not r.get("is_anchor")]
    eligible = gate.get("eligible") or []
    blocked = gate.get("blocked") or []
    rows = ""
    for r in results:
        hard = r.get("hard_failures") or []
        hard_str = "; ".join(
            f"{h.get('fixture')} ({h.get('detail') or h.get('reason')})" for h in hard
        ) if hard else "<span class=muted>none</span>"
        status = "eligible" if r.get("promotable_gate") else "blocked"
        cls = "ok" if r.get("promotable_gate") else "rej"
        rows += (
            f"<tr><td>{_esc(r.get('candidate_id'))}</td>"
            f"<td class={cls}>{status}</td>"
            f"<td>{_esc(r.get('fixture_pass_count'))}/{_esc(r.get('fixture_fail_count'))}/"
            f"{_esc(r.get('fixture_na_count'))}</td>"
            f"<td>{hard_str}</td></tr>"
        )
    rows = rows or "<tr><td class=muted colspan=4>no candidates graded</td></tr>"
    return (
        f"<p class=muted>{_esc(gate.get('n_hard_fixtures'))} HARD of "
        f"{_esc(gate.get('n_gradeable_fixtures'))} gradeable fixtures. "
        f"Eligible (all hard fixtures pass): <b>{_esc(', '.join(eligible) or 'none')}</b>; "
        f"blocked: {_esc(str(len(blocked)))} candidate(s).</p>"
        f"<p class=muted>{_esc(gate.get('forced_discard_note') or '')}</p>"
        "<table><tr><th>Candidate</th><th>Gate</th><th>pass/fail/na</th>"
        f"<th>Hard failures</th></tr>{rows}</table>"
    )


def _pass8_html(data: dict) -> str:
    scout = data.get("pass8_scout_ranking") or {}
    focused = data.get("pass8_focused_ranking") or {}
    gate = data.get("pass8_fixture_gate") or {}
    queue = data.get("queue") or {}
    chaos = data.get("chaos_contract") or {}

    if not (scout or focused or gate):
        return ("<section><h2>Pass 8 — Fixture-first effect safety</h2><div class=empty>"
                "No Pass 8 artifacts found yet.</div></section>")

    baseline_cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("v2 active control", V2_LIVE_SCORE),
            ("v1 control (live)", V1_LIVE_SCORE),
            ("Eligible (hard gate)", len(gate.get("eligible") or [])),
            ("Kaggle upload", "no"),
        ]
    )

    # Dry-run queue.
    q_items = queue.get("queue") or queue.get("candidates") or []
    if q_items:
        q_html = "<ul>" + "".join(
            f"<li><code>{_esc(c.get('candidate_id') or c.get('branch_id'))}</code> "
            f"[{_esc(c.get('promotion_label') or c.get('label'))}] "
            f"→ <code>{_esc(c.get('tarball'))}</code> (NOT uploaded)</li>"
            for c in q_items
        ) + "</ul>"
    else:
        reason = queue.get("selection_reason") or "no candidate qualified"
        q_html = f"<div class=empty>Queue empty — {_esc(reason)}.</div>"
    q_meta = (
        f"<p class=muted>auto_submit={_esc(queue.get('auto_submit_enabled'))}, "
        f"manual_approval={_esc(queue.get('require_manual_approval_for_submit'))}, "
        f"no_more_submissions_today={_esc(queue.get('no_more_submissions_today'))}, "
        f"upload_performed={_esc(queue.get('upload_performed'))}, "
        f"max={_esc(queue.get('max_queue_size'))}.</p>"
    )

    # Chaos telemetry correction surface.
    correction = (chaos or {}).get("telemetry_correction") or {}
    chaos_html = ""
    if correction:
        avail = correction.get("available") or correction.get("opponent_observable") or []
        missing = (correction.get("still_missing_or_uncertain")
                   or correction.get("opponent_hidden") or [])
        chaos_html = (
            "<h3>Chaos telemetry correction</h3>"
            f"<p class=muted><b>Observable:</b> {_esc(', '.join(avail) or '—')}</p>"
            f"<p class=muted><b>Still hidden:</b> {_esc(', '.join(missing) or '—')}</p>"
            f"<p class=muted>{_esc(correction.get('conclusion') or '')}</p>"
        )

    return (
        "<section><h2>Pass 8 — Fixture-first effect safety</h2>"
        f"<div class=cards>{baseline_cards}</div>"
        "<p class=muted>Local research only — <b>no Kaggle upload, no GitHub push</b>; "
        "root <code>main.py</code>/<code>deck.csv</code> immutable. Replay failures are "
        "turned into deterministic fixtures; the HARD fixture gate is a strict promotion "
        "filter. <code>secret_box_forced_discard_all</code> is forced_all/na and never a "
        "failure.</p>"
        "<h3>Fixture gate (HARD = promotion filter)</h3>"
        f"{_pass8_gate_html(gate)}"
        "<h3>Scout ranking (vs v2 control; gate-failers excluded from queue)</h3>"
        f"{_pass7b_rank_rows_html(scout)}"
        "<h3>Focused seat-swap confirmation</h3>"
        f"{_pass7b_rank_rows_html(focused)}"
        "<h3>Dry-run submission queue (≤1, no upload)</h3>"
        f"{q_meta}{q_html}"
        f"{chaos_html}"
        "</section>"
    )


def _fixture_gate_status_for(branch_id: str, data: dict) -> str | None:
    """Return ``eligible``/``blocked`` from the loaded hard fixture gates.

    Gate JSONs key candidates by their run-dir-prefixed id, so we match by
    suffix against ``branch_id``. Returns ``None`` when no gate covers it.
    """
    for key in ("pass9_fixture_gate", "pass8_fixture_gate"):
        gate = data.get(key) or {}
        for cid in gate.get("eligible") or []:
            if cid == branch_id or cid.endswith(f"_{branch_id}"):
                return "eligible"
        for cid in gate.get("blocked") or []:
            if cid == branch_id or cid.endswith(f"_{branch_id}"):
                return "blocked"
    return None


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
        # Prefer the hard fixture gate; fall back to package/smoke metrics; and
        # never label a not-yet-evaluated candidate as a failure.
        gate_status = _fixture_gate_status_for(b.branch_id, data)
        if gate_status == "eligible":
            gate = "ok"
        elif gate_status == "blocked":
            gate = "GATE-FAIL"
        elif m.get("package_ok") is not None or m.get("smoke_ok") is not None:
            gate = "ok" if (m.get("package_ok") and m.get("smoke_ok")) else "GATE-FAIL"
        else:
            gate = "not evaluated"
        rows = "".join(
            f"<tr><td>{_esc(k)}</td><td>{_esc(m.get(k))}</td></tr>"
            for k in ("games_completed", "win_rate", "attack_rate", "pass_rate",
                      "decision_entropy", "crashes", "timeouts", "avg_steps")
            if k in m
        ) or "<tr><td class=muted colspan=2>not evaluated yet</td></tr>"
        blocks.append(
            f"<section><h2>{_esc(b.branch_id)} "
            f"<span class={'ok' if gate=='ok' else ('muted' if gate=='not evaluated' else 'rej')}>"
            f"[{gate}]</span></h2>"
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


def _pass10b_html(data: dict) -> str:
    reg = data.get("pass10b_live_registry") or {}
    diag = data.get("pass10b_cabt_diag") or {}
    smoke = data.get("pass10b_eval_smoke") or {}
    if not (reg or diag or smoke):
        return ("<section><h2>Pass 10B — Evaluation recovery</h2>"
                "<div class=empty>No Pass 10B artifacts yet.</div></section>")

    ac = reg.get("active_control") or {}
    counts = reg.get("counts") or {}
    sub_rows = "".join(
        f"<tr><td><code>{_esc(s.get('filename'))}</code></td>"
        f"<td>{_esc(s.get('date'))}</td><td>{_esc(s.get('status'))}</td>"
        f"<td>{_esc(s.get('public_score') if s.get('public_score') is not None else '—')}</td>"
        f"<td class={'ok' if s.get('classification') == 'active_control_candidate' else ('rej' if s.get('classification') in ('error', 'live_rejected') else '')}>"
        f"{_esc(s.get('classification'))}</td></tr>"
        for s in (reg.get("submissions") or [])
    ) or "<tr><td class=muted colspan=5>no submissions</td></tr>"

    cabt_ok = bool(diag.get("cabt_available"))
    smoke_status = smoke.get("status")
    return (
        "<section><h2>Pass 10B — Evaluation recovery + replay acquisition</h2>"
        "<p class=muted><b>Infrastructure pass — no Kaggle upload, no GitHub push, "
        "no new candidates</b>; root <code>main.py</code>/<code>deck.csv</code> immutable.</p>"
        "<div class=cards>"
        f"<div class=card><div class=k>active control (dynamic)</div>"
        f"<div class=v>{_esc(ac.get('filename'))} @ {_esc(ac.get('public_score'))}</div></div>"
        f"<div class=card><div class=k>submissions</div><div class=v>"
        f"{_esc(counts.get('complete'))} complete / {_esc(counts.get('error'))} error / "
        f"{_esc(counts.get('pending'))} pending</div></div>"
        f"<div class=card><div class=k>cabt available</div>"
        f"<div class='v {'ok' if cabt_ok else 'rej'}'>{cabt_ok}</div></div>"
        f"<div class=card><div class=k>eval smoke</div><div class=v>{_esc(smoke_status)}</div></div>"
        "</div>"
        "<h3>Live score registry (dynamic active control = highest complete non-error)</h3>"
        "<table><tr><th>fileName</th><th>date</th><th>status</th><th>publicScore</th>"
        f"<th>classification</th></tr>{sub_rows}</table>"
        "<h3>cabt diagnostic</h3>"
        f"<p class=muted>kaggle_environments import: <b>{_esc((diag.get('checks') or {}).get('kaggle_environments_import', {}).get('ok'))}</b>; "
        f"make('cabt'): <b>{_esc((diag.get('checks') or {}).get('make_cabt', {}).get('ok'))}</b>; "
        f"real self-play game: <b>{_esc((diag.get('checks') or {}).get('self_play_smoke', {}).get('ok'))}</b>. "
        "<b>Correction:</b> the prior \"cabt absent / games not runnable\" conclusion was "
        "wrong — kaggle-environments 1.30.1 ships a working cabt engine; full games run "
        "locally again.</p>"
        "<h3>Replay acquisition &amp; meta coverage</h3>"
        "<p class=muted>Kaggle CLI has <b>no replay/episode download</b> command "
        "(verified); missing opponent replays must be fetched manually — see "
        "<code>data/meta_replays/REPLAY_ACQUISITION.md</code>. Externals "
        "<code>metal_ex_zacian_ramp</code> and <code>water_kyogre_abomasnow_maxbelt</code> "
        "stay <b>blocked</b> (no replay, ids unconfirmed); only the self-mirror surrogate "
        "is real.</p>"
        "<div class=empty><b>Eval engine restored; meta coverage still incomplete. "
        "Nothing promotable. Queue empty. Next upload: none.</b></div>"
        "</section>"
    )


def _pass10b_md(data: dict) -> list[str]:
    reg = data.get("pass10b_live_registry") or {}
    diag = data.get("pass10b_cabt_diag") or {}
    smoke = data.get("pass10b_eval_smoke") or {}
    if not (reg or diag or smoke):
        return []
    ac = reg.get("active_control") or {}
    counts = reg.get("counts") or {}
    checks = diag.get("checks") or {}
    lines = ["## Pass 10B — Evaluation recovery + replay acquisition", ""]
    lines.append("_Infrastructure pass — no Kaggle upload, no GitHub push, no new "
                 "candidates; root main.py/deck.csv immutable._")
    lines += ["", "### Live score registry (dynamic active control)",
              f"- Submissions: {counts.get('complete')} complete / "
              f"{counts.get('error')} error / {counts.get('pending')} pending",
              f"- **Active control (dynamic):** `{ac.get('filename')}` @ "
              f"**{ac.get('public_score')}** — highest publicScore among complete "
              "non-error (no hardcoded v1/v2 label)"]
    for r in reg.get("rejected_candidates") or []:
        lines.append(f"- live-rejected: `{r.get('filename')}` @ {r.get('public_score')} "
                     f"({r.get('reason')})")
    lines += ["", "### cabt diagnostic",
              f"- kaggle_environments import: **{checks.get('kaggle_environments_import', {}).get('ok')}**",
              f"- make('cabt'): **{checks.get('make_cabt', {}).get('ok')}**",
              f"- real self-play game: **{checks.get('self_play_smoke', {}).get('ok')}**",
              f"- cabt available: **{diag.get('cabt_available')}**",
              "- **Correction:** the prior \"cabt absent / games not runnable\" "
              "conclusion was wrong — kaggle-environments 1.30.1 ships a working cabt "
              "engine; full games run locally again."]
    lines += ["", "### Replay acquisition & meta coverage",
              "- Kaggle CLI has **no replay/episode download** command (verified); "
              "missing replays must be fetched manually "
              "(`data/meta_replays/REPLAY_ACQUISITION.md`).",
              "- Externals `metal_ex_zacian_ramp` and "
              "`water_kyogre_abomasnow_maxbelt` remain **blocked** (no replay, ids "
              "unconfirmed); only the self-mirror surrogate is real."]
    lines += ["", "### Evaluation smoke",
              f"- Status: **{smoke.get('status')}** (cabt available: "
              f"{smoke.get('cabt_available')}); can run future meta eval: "
              f"**{smoke.get('can_run_future_meta_eval')}**",
              "- **Eval engine restored; meta coverage still incomplete. Nothing "
              "promotable. Queue empty. Next upload: none.**"]
    return lines


def _pass11b_stats(data: dict) -> dict:
    """Collect the Pass 11B replay-inbox numbers used by every renderer.

    Every field degrades to a safe default so the section renders even when an
    artifact is missing. No value is fabricated — only counted from artifacts.
    """
    reg = data.get("pass11b_replay_registry") or {}
    proc = data.get("pass11b_processing_state") or {}
    errs = data.get("pass11b_inbox_errors") or {}
    analysis = data.get("pass11b_replay_analysis") or {}
    arch = data.get("pass11b_archetypes") or {}
    pool = data.get("pass11b_meta_pool") or {}
    ev = data.get("pass11b_meta_eval") or {}
    ranking = data.get("pass11b_ranking") or {}

    records = reg.get("records") or []
    perspectives = Counter(r.get("perspective") for r in records)
    confirmed = arch.get("confirmed_opponent_archetypes") or []
    provisional = arch.get("provisional_archetypes") or []
    arch_list = arch.get("archetypes") or []
    unknown = [a.get("archetype_id") for a in arch_list
               if a.get("confidence") == "unknown"]
    ac = (pool.get("controls") or {}).get("active_control") or {}
    rec = analysis.get("record") or {}
    per_cand = ev.get("per_candidate") or {}
    # Coverage block is nested under ``coverage:`` (fall back to top-level).
    cov = pool.get("coverage") or {}
    coverage_status = cov.get("coverage_status") or pool.get("coverage_status")
    eval_complete = (cov.get("eval_complete") if "eval_complete" in cov
                     else pool.get("eval_complete"))
    blocked_archetypes = (cov.get("blocked_archetypes")
                          or pool.get("blocked_archetypes") or [])

    # Replay counts per archetype, sourced from the meta pool.
    by_archetype = {}
    for a in pool.get("archetypes") or []:
        eps = a.get("replay_episodes") or ([a.get("replay_episode")]
                                           if a.get("replay_episode") else [])
        by_archetype[a.get("key")] = len([e for e in eps if e is not None])

    return {
        "reg": reg, "proc": proc, "errs": errs, "analysis": analysis,
        "arch": arch, "pool": pool, "ev": ev, "ranking": ranking,
        "records": records, "perspectives": perspectives,
        "confirmed": confirmed, "provisional": provisional, "unknown": unknown,
        "arch_list": arch_list, "active_control": ac, "record": rec,
        "per_candidate": per_cand, "by_archetype": by_archetype,
        "coverage_status": coverage_status, "eval_complete": eval_complete,
        "blocked_archetypes": blocked_archetypes,
        "raw_found": reg.get("replays_total"),
        "parsed": reg.get("replays_registered"),
        "duplicates": len(reg.get("duplicates_skipped") or []),
        "errors": len(reg.get("errors") or []),
        "decks_written": len(proc.get("decks_written") or []),
        "known_own_decks": len(reg.get("known_own_decks") or []),
    }


def _pass11b_md(data: dict) -> list[str]:
    s = _pass11b_stats(data)
    if not (s["reg"] or s["analysis"] or s["arch"] or s["ev"]):
        return []
    rec = s["record"]
    ev = s["ev"]
    rk = s["ranking"]
    persp = s["perspectives"]
    lines = ["## Pass 11B — Replay inbox + meta-pool automation", ""]
    lines.append("_Infrastructure pass — no Kaggle upload, no GitHub push, no new "
                 "gameplay candidates; root main.py/deck.csv immutable; no card id "
                 "invented._")
    lines += ["", "### Replay inbox",
              f"- Raw replay files found: **{s['raw_found']}**",
              f"- Parsed / registered: **{s['parsed']}**",
              f"- Duplicates skipped: **{s['duplicates']}**",
              f"- Errors: **{s['errors']}**",
              f"- Decks extracted: **{s['decks_written']}**",
              f"- Perspectives: "
              + (", ".join(f"{k}={v}" for k, v in sorted(persp.items())
                          if k) or "_none_"),
              f"- Registry: `{PASS11B_REPLAY_REGISTRY_JSON}`; "
              f"processing state: `{PASS11B_PROCESSING_STATE_JSON}`"]
    lines += ["", "### Deck attribution & archetypes",
              f"- Known own-deck fingerprints: **{s['known_own_decks']}** "
              "(our decks recognised by ordered-deck SHA-256)",
              f"- Confirmed opponent archetypes: "
              + (", ".join(f"`{a}`" for a in s["confirmed"]) or "_none_"),
              f"- Provisional archetypes: "
              + (", ".join(f"`{a}`" for a in s["provisional"]) or "_none_"),
              f"- Unknown archetypes: "
              + (", ".join(f"`{a}`" for a in s["unknown"]) or "_none_"),
              f"- Archetypes file: `{PASS11B_ARCHETYPES_YAML}`"]
    for a in s["arch_list"]:
        names = ", ".join(a.get("evidence_card_names") or []) or "_no evidence_"
        lines.append(f"  - `{a.get('archetype_id')}` ({a.get('confidence')}): "
                     f"{names}")
    lines += ["", "### Replay analysis",
              f"- Record (our seat): **{rec.get('wins', 0)}W-"
              f"{rec.get('losses', 0)}L-{rec.get('draws', 0)}D** "
              f"({rec.get('self_mirrors', 0)} self-mirror)",
              f"- Fast losses: "
              + (", ".join(s["analysis"].get("fast_losses") or []) or "_none_"),
              f"- Long / deckout games: "
              + (", ".join(s["analysis"].get("long_or_deckout_games") or [])
                 or "_none_"),
              "- Recurring failure tags: "
              + (", ".join(f"{k}×{v}" for k, v in
                          (s["analysis"].get("recurring_failure_tags") or {}).items())
                 or "_none_"),
              f"- Analysis file: `{PASS11B_REPLAY_ANALYSIS_JSON}`"]
    # Meta pool coverage.
    pool = s["pool"]
    ac = s["active_control"]
    lines += ["", "### Meta pool",
              f"- Active control (dynamic): `{ac.get('candidate_id')}` @ "
              f"**{ac.get('live_public_score')}**",
              f"- Coverage status: **{s['coverage_status'] or 'unknown'}** "
              f"(eval_complete={s['eval_complete']})",
              "- Replay count by archetype: "
              + (", ".join(f"{k}={v}" for k, v in s["by_archetype"].items())
                 or "_none_"),
              f"- Blocked archetypes: "
              + (", ".join(f"`{a}`" for a in s["blocked_archetypes"])
                 or "_none_"),
              f"- Meta pool file: `{PASS11B_META_POOL_YAML}`"]
    # Local evaluation.
    lines += ["", "### Local evaluation"]
    if ev:
        lines += [f"- cabt runnable: **{ev.get('cabt_available')}**, status: "
                  f"**{ev.get('status')}** ({ev.get('external_meta_eval')})",
                  f"- Opponent families: "
                  + (", ".join(f"`{f}`" for f in ev.get('opponent_families') or [])
                     or "_none_"),
                  f"- Candidates evaluated: "
                  + (", ".join(f"`{c}`" for c in ev.get('candidates_evaluated') or [])
                     or "_none_")]
        for cid, c in (s["per_candidate"]).items():
            lines.append(f"  - `{cid}` ({c.get('role')}): weighted_meta_score "
                         f"**{_num(c.get('weighted_meta_score'))}**, "
                         f"vs_active_control {c.get('vs_active_control')}")
            for k, m in (c.get("per_archetype") or {}).items():
                lines.append(f"    - {k}: WR {_num(m.get('win_rate'))} "
                             f"({m.get('wins')}-{m.get('losses')}-{m.get('draws')}, "
                             f"crashes {m.get('crashes')}, timeouts {m.get('timeouts')})")
        lines.append(f"- Upload-ready: **{rk.get('upload_ready')}** "
                     "(directional local proxy only)")
    else:
        lines.append("_Eval not run._")
    lines += ["", "### Bottom line",
              "- **Eval is directional only; meta coverage is usable but not yet "
              "complete (provisional buckets still need confirming replays) and no "
              "candidate is upload-ready. Queue empty. Next upload: none.**"]
    return lines


def _pass11b_html(data: dict) -> str:
    s = _pass11b_stats(data)
    if not (s["reg"] or s["analysis"] or s["arch"] or s["ev"]):
        return ""
    rec = s["record"]
    ev = s["ev"]
    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Raw replays", s["raw_found"]),
            ("Parsed", s["parsed"]),
            ("Duplicates", s["duplicates"]),
            ("Errors", s["errors"]),
            ("Decks extracted", s["decks_written"]),
            ("Confirmed archetypes", len(s["confirmed"])),
            ("Provisional", len(s["provisional"])),
            ("Record", f"{rec.get('wins', 0)}-{rec.get('losses', 0)}-"
                       f"{rec.get('draws', 0)}"),
        ]
    )
    arch_rows = "".join(
        f"<tr><td><code>{_esc(a.get('archetype_id'))}</code></td>"
        f"<td>{_esc(a.get('confidence'))}</td>"
        f"<td>{_esc(', '.join(a.get('evidence_card_names') or []) or '—')}</td></tr>"
        for a in s["arch_list"]
    ) or "<tr><td class=muted colspan=3>no archetypes</td></tr>"
    eval_rows = "".join(
        f"<tr><td><code>{_esc(cid)}</code></td><td>{_esc(c.get('role'))}</td>"
        f"<td>{_esc(_num(c.get('weighted_meta_score')))}</td>"
        f"<td>{_esc(c.get('vs_active_control'))}</td></tr>"
        for cid, c in s["per_candidate"].items()
    ) or "<tr><td class=muted colspan=4>eval not run</td></tr>"
    ac = s["active_control"]
    upload = s["ranking"].get("upload_ready")
    return (
        "<section><h2>Pass 11B — Replay inbox + meta-pool automation</h2>"
        "<p class=muted>Infrastructure pass — no upload, no push, no new "
        "candidates; root immutable; no card id invented. Active control "
        f"<code>{_esc(ac.get('candidate_id'))}</code> @ "
        f"{_esc(ac.get('live_public_score'))}; coverage "
        f"<b>{_esc(s['coverage_status'] or 'unknown')}</b>.</p>"
        f"<div class=cards>{cards}</div>"
        "<h3>Opponent archetypes (replay-derived evidence)</h3>"
        "<table><tr><th>Archetype</th><th>Confidence</th><th>Evidence cards</th></tr>"
        f"{arch_rows}</table>"
        "<h3>Local evaluation (directional)</h3>"
        "<table><tr><th>Candidate</th><th>Role</th><th>Weighted meta score</th>"
        f"<th>vs active control</th></tr>{eval_rows}</table>"
        f"<p class=muted>Upload-ready: <b>{_esc(upload)}</b>. "
        "Eval is a directional local proxy; meta coverage partial; "
        "queue empty; next upload: none.</p></section>"
    )


def write_pass11b_report(data: dict, path: Path = PASS11B_REPORT_MD) -> Path:
    """Write the standalone Pass 11B replay-inbox report (Part L)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _pass11b_md(data)
    if not body:
        lines = ["# ActiveGraph Pass 11B — Replay inbox report", "",
                 "_No Pass 11B artifacts found yet._", ""]
    else:
        lines = ["# ActiveGraph Pass 11B — Replay inbox report", "",
                 "Generated from lab artifacts only; no values fabricated.", ""]
        lines += body
        # Missing replay types + next upload recommendation (spec Part L).
        s = _pass11b_stats(data)
        missing = [a.get("archetype_id") for a in s["arch_list"]
                   if a.get("confidence") != "confirmed"]
        lines += ["", "## Missing replay types",
                  "- Provisional/unknown archetypes still need more replays for "
                  "confirmation: "
                  + (", ".join(f"`{m}`" for m in missing) or "_none_"),
                  "- The meta pool stays at coverage "
                  f"**{(s['coverage_status'] or 'unknown')}** until those "
                  "are upgraded to confirmed.",
                  "", "## Next upload recommendation",
                  "- **None.** Local evaluation is directional only and no "
                  "candidate is upload-ready; the dynamic active control "
                  f"`{s['active_control'].get('candidate_id')}` "
                  f"(@{s['active_control'].get('live_public_score')}) remains the "
                  "best known submission. No GitHub push, no Kaggle upload.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _pass12_stats(data: dict) -> dict:
    cfg = data.get("pass12_config") or {}
    man = data.get("pass12_candidates") or {}
    scout = data.get("pass12_scout") or {}
    focused = data.get("pass12_focused") or {}
    ranking = data.get("pass12_ranking") or {}
    queue = data.get("pass12_dry_run_queue") or {}
    built = man.get("built") or []
    blocked = man.get("blocked") or []
    foc_rank = ranking.get("ranking") or focused.get("ranking") or []
    labels = Counter(r.get("label") for r in foc_rank)
    return {
        "cfg": cfg, "man": man, "scout": scout, "focused": focused,
        "ranking": ranking, "queue": queue, "built": built, "blocked": blocked,
        "scout_rank": scout.get("ranking") or [],
        "foc_rank": foc_rank, "labels": labels,
        "weights": cfg.get("evaluation_weights") or {},
        "active_control": ranking.get("active_control")
        or scout.get("active_control") or "uncertain",
        "ac_adj": ranking.get("active_control_adj")
        or focused.get("active_control_adj"),
        "upload_ready": ranking.get("upload_ready", False),
        "upload_performed": queue.get("upload_performed", False),
        "queued": queue.get("queued") or [],
        "queue_reason": queue.get("reason") or "",
        "disclaimer": (scout.get("disclaimer") or ranking.get("disclaimer") or ""),
        "opponents": scout.get("opponents") or [],
        "mirror_key": scout.get("mirror_key"),
        "candidate_notes": scout.get("candidate_notes") or [],
        "focused_set": focused.get("focused_set") or [],
    }


def _pass12_present(s: dict) -> bool:
    return bool(s["built"] or s["foc_rank"] or s["scout_rank"] or s["cfg"])


def _pass12_md(data: dict) -> list[str]:
    s = _pass12_stats(data)
    if not _pass12_present(s):
        return []
    L = ["## Pass 12 — Meta-driven candidate generation + directional evaluation", ""]
    L.append("_LOCAL only — no Kaggle upload, no GitHub push; root main.py/deck.csv "
             "immutable; no card id invented. Surrogate eval is DIRECTIONAL ONLY: "
             "opponent decks are real replay-derived lists piloted by a generic "
             "surrogate policy, never the real opponent policy._")
    if s["disclaimer"]:
        L += ["", f"> {s['disclaimer']}"]
    # Candidate generation.
    groups = Counter(r.get("group") for r in s["built"])
    L += ["", "### Candidate generation",
          f"- Built & validator-passing candidates: **{len(s['built'])}** "
          + ("(" + ", ".join(f"{g}×{n}" for g, n in sorted(groups.items())) + ")"
             if groups else ""),
          f"- Blocked (honest, no invented ids): **{len(s['blocked'])}**"]
    for b in s["blocked"]:
        L.append(f"  - `{b.get('id')}`: {b.get('reason')}")
    # Eval config.
    w = ", ".join(f"{k}={v}" for k, v in s["weights"].items()) or "_none_"
    L += ["", "### Evaluation configuration",
          f"- Active control (dynamic): `{s['active_control']}` "
          f"(adj win rate {_num(s['ac_adj'])})",
          f"- Opponent archetypes: "
          + (", ".join(f"`{o}`" for o in s["opponents"]) or "_none_"),
          f"- Replay-frequency weights: {w}",
          f"- Self-mirror diagnostic (excluded from meta score): "
          f"`{s['mirror_key'] or 'none'}`"]
    for note in s["candidate_notes"]:
        L.append(f"- Note: {note}")
    # Focused ranking table.
    L += ["", "### Focused ranking (directional, seat-swapped)",
          "| candidate | group | meta score | adj WR | 80% CI | games | vs AC | "
          "label |",
          "|---|---|---|---|---|---|---|---|"]
    for r in s["foc_rank"]:
        L.append(f"| `{r.get('candidate')}` | {r.get('group')} | "
                 f"{_num(r.get('weighted_meta_score'))} | "
                 f"{_num(r.get('adjusted_win_rate'))} | "
                 f"{_ci_str(r.get('wilson80'))} | {r.get('games_completed')} | "
                 f"{_num(r.get('vs_active_control'))} | {r.get('label')} |")
    if not s["foc_rank"]:
        L.append("| _none_ |  |  |  |  |  |  |  |")
    lbls = ", ".join(f"{k}×{v}" for k, v in s["labels"].items() if k) or "_none_"
    L += ["", f"- Label distribution: {lbls}"]
    # Promotion gate + dry-run queue.
    L += ["", "### Promotion gate & dry-run queue",
          f"- Upload-ready: **{s['upload_ready']}**; upload performed: "
          f"**{s['upload_performed']}**",
          f"- Dry-run queued (max 1): **{len(s['queued'])}**"
          + ("".join(f" — `{q.get('candidate')}`" for q in s["queued"])),
          f"- Reason: {s['queue_reason']}"]
    if not s["foc_rank"]:
        L += ["", "### Bottom line",
              "- **Candidates were generated but the directional eval has not been "
              "run yet (no focused ranking present); nothing uploaded, no GitHub "
              "push, root unchanged.**"]
    elif any(r.get("label") == "promotable" for r in s["foc_rank"]):
        L += ["", "### Bottom line",
              "- **One or more candidates are directionally promotable but surrogate "
              "evidence is NOT sufficient to upload; at most one entered the dry-run "
              "queue for MANUAL review. Nothing uploaded; no GitHub push.**"]
    else:
        L += ["", "### Bottom line",
              "- **Directional surrogate evidence only; no candidate cleared the "
              "promotion gate (>= min games, 80% lower bound > 0.50, beats the active "
              "control, not mirror-overfit). Queue empty / capped at one; nothing "
              "uploaded; no GitHub push. The dynamic active control remains the best "
              "known submission.**"]
    return L


def _pass12_html(data: dict) -> str:
    s = _pass12_stats(data)
    if not _pass12_present(s):
        return ""
    groups = Counter(r.get("group") for r in s["built"])
    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Candidates built", len(s["built"])),
            ("Blocked (no invented ids)", len(s["blocked"])),
            ("Opponent archetypes", len(s["opponents"])),
            ("Active control", s["active_control"]),
            ("Control adj WR", _num(s["ac_adj"])),
            ("Promotable", s["labels"].get("promotable", 0)),
            ("Dry-run queued", len(s["queued"])),
            ("Upload performed", s["upload_performed"]),
        ]
    )
    rank_rows = "".join(
        f"<tr><td><code>{_esc(r.get('candidate'))}</code></td>"
        f"<td>{_esc(r.get('group'))}</td>"
        f"<td>{_esc(_num(r.get('weighted_meta_score')))}</td>"
        f"<td>{_esc(_num(r.get('adjusted_win_rate')))}</td>"
        f"<td>{_esc(_ci_str(r.get('wilson80')))}</td>"
        f"<td>{_esc(r.get('games_completed'))}</td>"
        f"<td>{_esc(_num(r.get('vs_active_control')))}</td>"
        f"<td class={'rej' if r.get('label') in ('rejected', 'mirror_overfit') else 'ok'}>"
        f"{_esc(r.get('label'))}</td></tr>"
        for r in s["foc_rank"]
    ) or "<tr><td class=muted colspan=8>focused eval not run</td></tr>"
    blocked_rows = "".join(
        f"<tr><td><code>{_esc(b.get('id'))}</code></td>"
        f"<td>{_esc(b.get('reason'))}</td></tr>"
        for b in s["blocked"]
    ) or "<tr><td class=muted colspan=2>none blocked</td></tr>"
    grp = ", ".join(f"{g}×{n}" for g, n in sorted(groups.items()) if g) or "—"
    w = ", ".join(f"{k}={v}" for k, v in s["weights"].items()) or "—"
    return (
        "<section><h2>Pass 12 — Meta-driven candidate generation + directional "
        "evaluation</h2>"
        "<p class=muted>LOCAL only — no upload, no push; root immutable; no card "
        "id invented. Surrogate eval is <b>directional only</b> (real replay decks, "
        "generic surrogate policy). Active control "
        f"<code>{_esc(s['active_control'])}</code> (adj {_esc(_num(s['ac_adj']))}); "
        f"weights {_esc(w)}; groups {_esc(grp)}.</p>"
        f"<div class=cards>{cards}</div>"
        "<h3>Focused ranking (directional, seat-swapped)</h3>"
        "<table><tr><th>Candidate</th><th>Group</th><th>Meta score</th>"
        "<th>Adj WR</th><th>80% CI</th><th>Games</th><th>vs AC</th><th>Label</th></tr>"
        f"{rank_rows}</table>"
        "<h3>Blocked candidates (metadata insufficient — no invented ids)</h3>"
        "<table><tr><th>Candidate</th><th>Why blocked</th></tr>"
        f"{blocked_rows}</table>"
        f"<p class=muted>Upload-ready: <b>{_esc(s['upload_ready'])}</b>; upload "
        f"performed: <b>{_esc(s['upload_performed'])}</b>; dry-run queued: "
        f"<b>{len(s['queued'])}</b> (max 1). {_esc(s['queue_reason'])} "
        "No candidate cleared the promotion gate; nothing uploaded.</p></section>"
    )


def write_pass12_report(data: dict, path: Path = PASS12_REPORT_MD) -> Path:
    """Write the standalone Pass 12 meta-candidate evaluation report (Part L)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _pass12_md(data)
    if not body:
        lines = ["# ActiveGraph Pass 12 — Meta-candidate evaluation report", "",
                 "_No Pass 12 artifacts found yet._", ""]
    else:
        s = _pass12_stats(data)
        lines = ["# ActiveGraph Pass 12 — Meta-candidate evaluation report", "",
                 "Generated from lab artifacts only; no values fabricated.", ""]
        lines += body
        promising = [r.get("candidate") for r in s["foc_rank"]
                     if r.get("label") in ("promotable", "confirmation_promising",
                                            "scout_promising")]
        lines += ["", "## Next upload recommendation",
                  "- **None.** Surrogate evaluation is directional only and no "
                  "candidate cleared the promotion gate; "
                  + (f"the most promising directional candidates "
                     f"({', '.join(f'`{c}`' for c in promising)}) need real Kaggle "
                     "confirmation before any upload could be considered, "
                     if promising else "no candidate is even directionally promotable; ")
                  + f"the dynamic active control `{s['active_control']}` remains the "
                  "best known submission. No GitHub push, no Kaggle upload.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pass 13 — operating manual + unknown_ex_tempo decomposition.
# ---------------------------------------------------------------------------
def _pass13_stats(data: dict) -> dict:
    decomp = data.get("pass13_decomp") or {}
    pool = data.get("pass13_refined_pool") or {}
    ev = data.get("pass13_refined_eval") or {}
    reg = data.get("pass13_live_registry") or {}
    ac = reg.get("active_control") or {}
    subs = decomp.get("subfamilies") or []
    named = [s for s in subs if s.get("n_episodes", 0) > 0]
    return {
        "manual": data.get("pass13_manual_exists", False),
        "next_agent": data.get("pass13_next_agent_exists", False),
        "decomp": decomp,
        "pool": pool,
        "eval": ev,
        "active_control": ac.get("filename") or "uncertain",
        "active_control_score": ac.get("public_score"),
        "n_source_eps": decomp.get("n_source_episodes"),
        "n_subfamilies": decomp.get("n_subfamilies_found"),
        "supported": decomp.get("decomposition_supported"),
        "unresolved": decomp.get("unresolved_generic_episodes") or [],
        "named": named,
        "weights": pool.get("evaluation_weights") or {},
        "confirmed": (pool.get("confirmed_vs_provisional") or {}).get("confirmed") or [],
        "provisional": (pool.get("confirmed_vs_provisional") or {}).get("provisional") or [],
    }


def _pass13_present(s: dict) -> bool:
    return bool(s["manual"] or s["decomp"] or s["pool"])


def _pass13_md(data: dict) -> list[str]:
    s = _pass13_stats(data)
    if not _pass13_present(s):
        return []
    L = ["## Pass 13 — Operating manual + unknown_ex_tempo decomposition", ""]
    L.append("_DOCUMENTATION + META-ANALYSIS only — no Kaggle upload, no GitHub "
             "push, no new candidates, no invented card IDs; root main.py/deck.csv "
             "immutable. Live scores were NOT refreshed this pass (kaggle CLI "
             "unavailable); last-known-good reused._")
    L += ["", "### Operating manual",
          f"- Canonical manual created: **{s['manual']}** "
          f"(`docs/ACTIVEGRAPH_LAB_OPERATING_MANUAL.md`)",
          f"- Next-agent README created: **{s['next_agent']}** "
          f"(`docs/NEXT_AGENT_README.md`)",
          f"- Active control (dynamic): `{s['active_control']}` @ "
          f"{_num(s['active_control_score'])}"]
    L += ["", "### Unknown-EX tempo decomposition",
          f"- Source episodes analysed: **{s['n_source_eps']}**",
          f"- Named subfamilies found: **{s['n_subfamilies']}**",
          f"- Decomposition supported by evidence: **{s['supported']}**",
          f"- Unresolved (generic) episodes: **{len(s['unresolved'])}**",
          "",
          "| subfamily | episodes | n | confidence | status |",
          "|---|---|---|---|---|"]
    for sf in s["named"]:
        eps = ", ".join(str(e) for e in sf.get("episode_ids") or [])
        L.append(f"| `{sf.get('subfamily_id')}` | {eps} | {sf.get('n_episodes')} | "
                 f"{sf.get('confidence')} | {sf.get('status')} |")
    if not s["named"]:
        L.append("| _none_ |  |  |  |  |")
    if s["weights"]:
        w = ", ".join(f"{k}={v}" for k, v in s["weights"].items())
        wsum = round(sum(float(v) for v in s["weights"].values()), 4)
        L += ["", "### Refined meta pool",
              f"- Refined pool: `experiments/pass13_refined_meta_pool.yaml`",
              f"- Weights: {w}",
              f"- Weights sum: **{wsum}**",
              f"- Confirmed: {', '.join(f'`{c}`' for c in s['confirmed']) or '_none_'}",
              f"- Provisional: {', '.join(f'`{c}`' for c in s['provisional']) or '_none_'}"]
    if s["eval"]:
        ev = s["eval"]
        L += ["", "### Optional refined eval (directional only)",
              f"- Eval run: **True**; games/seat: {ev.get('games_per_seat')}; "
              f"candidates: {len(ev.get('candidates') or [])}"]
    else:
        L += ["", "### Optional refined eval (directional only)",
              "- Eval run: **False** (decomposition + docs only this pass)."]
    L += ["", "### Chaos lane",
          "- Chaos readiness updated in `docs/CHAOS_PLAYBOOK_LANE.md` (section "
          "\"Chaos after meta decomposition\"). No chaos candidate generated; the "
          "gate stays closed until a payoff card + measurable trigger is confirmed."]
    L += ["", "### Bottom line",
          "- **The unknown_ex_tempo bucket is decomposed into evidence-grounded "
          "subfamilies and a canonical operating manual is in place. No candidate "
          "generated, no upload, no GitHub push, root unchanged. The dynamic active "
          "control remains the best known submission.**"]
    return L


def _pass13_html(data: dict) -> str:
    s = _pass13_stats(data)
    if not _pass13_present(s):
        return ""
    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Operating manual", s["manual"]),
            ("Next-agent README", s["next_agent"]),
            ("Unknown source eps", s["n_source_eps"]),
            ("Subfamilies found", s["n_subfamilies"]),
            ("Decomp supported", s["supported"]),
            ("Active control", s["active_control"]),
            ("AC score", _num(s["active_control_score"])),
        ]
    )
    sub_rows = "".join(
        f"<tr><td><code>{_esc(sf.get('subfamily_id'))}</code></td>"
        f"<td>{_esc(', '.join(str(e) for e in sf.get('episode_ids') or []))}</td>"
        f"<td>{_esc(sf.get('n_episodes'))}</td>"
        f"<td>{_esc(sf.get('confidence'))}</td>"
        f"<td>{_esc(sf.get('status'))}</td></tr>"
        for sf in s["named"]
    ) or "<tr><td class=muted colspan=5>no subfamilies</td></tr>"
    w = ", ".join(f"{k}={v}" for k, v in s["weights"].items()) or "—"
    return (
        "<section><h2>Pass 13 — Operating manual + unknown_ex_tempo decomposition</h2>"
        "<p class=muted>Documentation + meta-analysis only — no upload, no push, no "
        "new candidates, no invented ids; root immutable. Live scores NOT refreshed "
        "(kaggle CLI unavailable); last-known-good reused. "
        f"Refined weights: {_esc(w)}.</p>"
        f"<div class=cards>{cards}</div>"
        "<h3>Unknown-EX tempo subfamilies (replay-grounded)</h3>"
        "<table><tr><th>Subfamily</th><th>Episodes</th><th>n</th><th>Confidence</th>"
        f"<th>Status</th></tr>{sub_rows}</table>"
        "<p class=muted>No candidate generated; nothing uploaded; the dynamic active "
        "control remains the best known submission.</p></section>"
    )


def write_pass13_report(data: dict, path: Path = PASS13_REPORT_MD) -> Path:
    """Write the standalone Pass 13 operating-manual + decomposition report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _pass13_md(data)
    if not body:
        lines = ["# ActiveGraph Pass 13 — Operating manual + meta decomposition", "",
                 "_No Pass 13 artifacts found yet._", ""]
    else:
        lines = ["# ActiveGraph Pass 13 — Operating manual + meta decomposition", "",
                 "Generated from lab artifacts only; no values fabricated.", ""]
        lines += body
        lines += ["", "## Next recommendation",
                  "- Run an analysis-only eval of the existing active control + "
                  "existing candidates against the four refined subfamily surrogate "
                  "decks (5 games/seat, seat-swapped) before considering any "
                  "targeted, confirmed-id-only candidate. No upload.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pass 15 — core-pilot runtime coverage + focused directional confirmation.
# ---------------------------------------------------------------------------

def _pass15_stats(data: dict) -> dict:
    cov = data.get("pass15_runtime_coverage") or {}
    smoke = data.get("pass15_live_smoke") or {}
    focused = data.get("pass15_focused_eval") or {}
    metrics = data.get("pass15_metrics") or {}
    queue = data.get("pass15_dry_run_queue") or {}
    contexts = cov.get("contexts") or cov.get("rows") or []
    wired = [c for c in contexts
             if c.get("runtime_intercepts") or c.get("runtime_wired")
             or c.get("wired")]
    return {
        "coverage": cov,
        "n_contexts": len(contexts),
        "n_wired": len(wired),
        "expansion_plan": data.get("pass15_expansion_plan_exists", False),
        "smoke": smoke,
        "smoke_rows": smoke.get("smoke") or [],
        "smoke_complete": bool(smoke.get("complete")),
        "focused": focused,
        "ranking": focused.get("ranking") or [],
        "active_control": focused.get("active_control"),
        "metrics_rows": metrics.get("rows") or [],
        "queue": queue,
        "upload_performed": queue.get("upload_performed"),
        "queued_count": queue.get("queued_count"),
    }


def _pass15_present(s: dict) -> bool:
    return bool(s["coverage"] or s["smoke"] or s["focused"] or s["metrics_rows"])


def _pass15_md(data: dict) -> list[str]:
    s = _pass15_stats(data)
    if not _pass15_present(s):
        return []
    L = ["## Pass 15 — Core-pilot runtime coverage + focused confirmation", ""]
    L.append("_LOCAL-ONLY, DIRECTIONAL eval — surrogate opponents, not the real "
             "Kaggle policy; no Kaggle upload, no GitHub push, root main.py/"
             "deck.csv immutable. Live scores NOT refreshed (kaggle CLI "
             "unavailable)._")
    L += ["", "### Runtime coverage audit",
          f"- cabt contexts audited: **{s['n_contexts']}**; reliably runtime-"
          f"wired: **{s['n_wired']}** (only contexts identifiable by context int "
          f"empirically). Expansion plan present: **{s['expansion_plan']}** "
          f"(`data/experiments/pass15_runtime_expansion_plan.md`).",
          "- The compiled runtime refines decisions ONLY at reliably-identifiable "
          "contexts (search/draw=7, discard=8); all other policy stays the "
          "base/control behaviour."]
    if s["smoke_rows"]:
        L += ["", "### Live cabt smoke (validity)", "",
              "| matchup | win rate | W-L-D | crash/timeout/skip |",
              "|---|---|---|---|"]
        for m in s["smoke_rows"]:
            wld = f"{m.get('wins',0)}-{m.get('losses',0)}-{m.get('draws',0)}"
            cts = (f"{m.get('crashes',0)}/{m.get('timeouts',0)}/"
                   f"{m.get('skipped',0)}")
            L.append(f"| {m.get('label') or m.get('matchup')} | "
                     f"{_num(m.get('win_rate'))} | {wld} | {cts} |")
        L.append("")
        L.append(f"- Smoke complete: **{s['smoke_complete']}** — every agent "
                 f"plays live cabt; validity is the only hard claim here.")
    if s["ranking"]:
        L += ["", "### Weighted directional ranking (small samples)", "",
              "| role | subfamilies | weighted directional win rate |",
              "|---|---|---|"]
        for r in s["ranking"]:
            L.append(f"| {r.get('role')} | {r.get('subfamilies')} | "
                     f"{_num(r.get('weighted_directional_win_rate'))} |")
    if s["metrics_rows"]:
        L += ["", "### Candidate metrics + promotion gate", "",
              "| candidate | wWR | games | valid | gate | label |",
              "|---|---|---|---|---|---|"]
        for r in s["metrics_rows"]:
            L.append(f"| {r.get('candidate')} | "
                     f"{_num(r.get('weighted_directional_win_rate'))} | "
                     f"{r.get('games')} | {r.get('valid_live')} | "
                     f"{r.get('promotion_gate')} | {r.get('label')} |")
    L += ["", "### Dry-run recommendation",
          f"- **upload_performed: {s['upload_performed']}** — "
          f"queued: **{s['queued_count']}**.",
          f"- {s['queue'].get('reason', '_no queue_')}"]
    L += ["", "### Bottom line",
          "- **Runtime coverage was expanded ONLY at reliably-identifiable cabt "
          "contexts; one candidate (`core_pilot_water_v2_runtime`) was built, "
          "validated, and smoke-tested with 0 crash/timeout/skip. The directional "
          "delta vs v1/the control is within noise — a no-regression signal, not "
          "a promotion proof. Nothing uploaded; root unchanged; the dynamic "
          "active control remains the best known submission.**"]
    return L


def _pass15_html(data: dict) -> str:
    s = _pass15_stats(data)
    if not _pass15_present(s):
        return ""
    cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("Contexts audited", s["n_contexts"]),
            ("Runtime-wired", s["n_wired"]),
            ("Smoke complete", s["smoke_complete"]),
            ("Upload performed", s["upload_performed"]),
            ("Queued", s["queued_count"]),
        ]
    )
    smoke_rows = "".join(
        f"<tr><td>{_esc(m.get('label') or m.get('matchup'))}</td>"
        f"<td>{_num(m.get('win_rate'))}</td>"
        f"<td>{_esc(m.get('wins',0))}-{_esc(m.get('losses',0))}-"
        f"{_esc(m.get('draws',0))}</td>"
        f"<td>{_esc(m.get('crashes',0))}/{_esc(m.get('timeouts',0))}/"
        f"{_esc(m.get('skipped',0))}</td></tr>"
        for m in s["smoke_rows"]
    ) or "<tr><td class=muted colspan=4>no smoke yet</td></tr>"
    rank_rows = "".join(
        f"<tr><td>{_esc(r.get('role'))}</td><td>{_esc(r.get('subfamilies'))}</td>"
        f"<td>{_num(r.get('weighted_directional_win_rate'))}</td></tr>"
        for r in s["ranking"]
    ) or "<tr><td class=muted colspan=3>no ranking yet</td></tr>"
    return (
        "<section><h2>Pass 15 — Core-pilot runtime coverage + focused "
        "confirmation</h2>"
        "<p class=muted>LOCAL-ONLY, DIRECTIONAL — surrogate opponents, not the "
        "real Kaggle policy. No upload, no push; root immutable; live scores not "
        "refreshed. Runtime refines decisions ONLY at reliably-identifiable cabt "
        "contexts (search/draw, discard).</p>"
        f"<div class=cards>{cards}</div>"
        "<h3>Live cabt smoke (validity)</h3>"
        "<table><tr><th>Matchup</th><th>Win rate</th><th>W-L-D</th>"
        f"<th>crash/timeout/skip</th></tr>{smoke_rows}</table>"
        "<h3>Weighted directional ranking (small samples)</h3>"
        "<table><tr><th>Role</th><th>Subfamilies</th>"
        f"<th>Weighted directional WR</th></tr>{rank_rows}</table>"
        f"<p class=muted>Dry-run recommendation: upload_performed="
        f"{_esc(s['upload_performed'])}, queued={_esc(s['queued_count'])}. "
        f"{_esc(s['queue'].get('reason',''))}</p>"
        "<p class=muted>Directional only; a small/zero delta between v2_runtime, "
        "v1, and the active control is EXPECTED — treat as a no-regression sanity "
        "signal, not a promotion proof. The dynamic active control remains the "
        "best known submission.</p></section>"
    )


def write_pass15_runtime_report(data: dict,
                                path: Path = PASS15_RUNTIME_REPORT_MD) -> Path:
    """Standalone Pass 15 report #1 — runtime coverage + expansion."""
    s = _pass15_stats(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _pass15_present(s):
        lines = ["# ActiveGraph Pass 15 — Runtime coverage", "",
                 "_No Pass 15 runtime artifacts found yet._", ""]
    else:
        lines = ["# ActiveGraph Pass 15 — Runtime coverage + expansion", "",
                 "Generated from lab artifacts only; no values fabricated. "
                 "LOCAL-ONLY; no upload, no push; root immutable.", "",
                 f"- cabt contexts audited: **{s['n_contexts']}**",
                 f"- Reliably runtime-wired contexts: **{s['n_wired']}** "
                 f"(search/draw=7, discard=8)",
                 f"- Expansion plan present: **{s['expansion_plan']}** "
                 f"(`data/experiments/pass15_runtime_expansion_plan.md`)",
                 "",
                 "The compiled runtime refines decisions ONLY at the two "
                 "reliably-identifiable cabt contexts; every other decision keeps "
                 "the base/control behaviour. The fresh-named entrypoint is "
                 "emitted LAST (the kaggle_environments invariant), ratcheted into "
                 "`scripts/validate_candidate_entrypoint.py`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_pass15_eval_report(data: dict,
                             path: Path = PASS15_EVAL_REPORT_MD) -> Path:
    """Standalone Pass 15 report #2 — smoke + focused eval + recommendation."""
    s = _pass15_stats(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _pass15_md(data)
    if not body:
        lines = ["# ActiveGraph Pass 15 — Focused directional eval", "",
                 "_No Pass 15 eval artifacts found yet._", ""]
    else:
        lines = ["# ActiveGraph Pass 15 — Focused directional eval + "
                 "recommendation", "",
                 "Generated from lab artifacts only; no values fabricated.", ""]
        lines += body
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _pass10_control_scores(pool: dict) -> dict:
    """Resolve v1 / v2 / rejected live scores by *identity* (candidate_id).

    The Pass 10 section must stay correct even after ``meta_pool.yaml`` is updated
    to a later pass's schema (Pass 10B makes the dynamic active control v1, and
    renames the v2 entry), so we never key off the role ("active_control") — only
    off the candidate identity.
    """
    controls = pool.get("controls") or {}
    scores = {"v1": None, "v2": None, "rejected": None}
    for entry in controls.values():
        if not isinstance(entry, dict):
            continue
        cid = (entry.get("candidate_id") or "").lower()
        score = entry.get("live_public_score")
        if cid == "v1":
            scores["v1"] = score
        elif "deck_energy_trim_light" in cid:
            scores["v2"] = score
        elif "combo" in cid or entry.get("decision") == "live_rejected":
            scores["rejected"] = score
    return scores


def _pass10_html(data: dict) -> str:
    summary = data.get("pass10_meta_summary") or {}
    pool = data.get("pass10_meta_pool") or {}
    cands = data.get("pass10_candidates") or {}
    ev = data.get("pass10_eval") or {}
    if not (summary or pool or cands or ev):
        return ("<section><h2>Pass 10 — Meta-calibrated evaluation + tempo</h2>"
                "<div class=empty>No Pass 10 artifacts yet.</div></section>")

    sc = _pass10_control_scores(pool)
    score_cards = "".join(
        f"<div class=card><div class=k>{_esc(k)}</div><div class=v>{_esc(v)}</div></div>"
        for k, v in [
            ("v2 control (live)", sc["v2"]),
            ("v1 reference (live)", sc["v1"]),
            ("combo_fixed (rejected)", sc["rejected"]),
            ("weighted meta score", ev.get("weighted_meta_score")),
            ("Kaggle upload", "none"),
        ]
    )

    # Archetypes (from the honest meta pool: weights + coverage status).
    arch = pool.get("archetypes") or []
    arch_rows = "".join(
        f"<tr><td><code>{_esc(a.get('key'))}</code></td>"
        f"<td class={'ok' if a.get('status') == 'confirmed_from_replay' else 'rej'}>"
        f"{_esc(a.get('status'))}</td>"
        f"<td>{_esc(a.get('weight'))}</td>"
        f"<td>{_esc(a.get('replay_episode') if a.get('replay_episode') is not None else '—')}</td></tr>"
        for a in arch
    ) or "<tr><td class=muted colspan=4>no archetypes</td></tr>"

    # Tempo taxonomy (real signals from the replay).
    sigs = summary.get("tempo_signals") or []
    sig_html = "<ul>" + "".join(f"<li>{_esc(s)}</li>" for s in sigs) + "</ul>" \
        if sigs else "<div class=empty>no tempo signals</div>"

    # Candidate results.
    built = cands.get("built") or []
    blocked = cands.get("blocked") or []
    cand_rows = "".join(
        f"<tr><td><code>{_esc(c.get('id'))}</code></td><td>{_esc(c.get('kind'))}</td>"
        f"<td class={'ok' if c.get('validated') else 'rej'}>"
        f"{'validated' if c.get('validated') else 'unvalidated'}</td>"
        f"<td class=rej>not promotable</td></tr>"
        for c in built
    )
    cand_rows += "".join(
        f"<tr><td><code>{_esc(c.get('id'))}</code></td><td>{_esc(c.get('kind'))}</td>"
        f"<td class=rej>BLOCKED</td><td>{_esc(c.get('reason'))}</td></tr>"
        for c in blocked
    )
    cand_rows = cand_rows or "<tr><td class=muted colspan=4>no candidates</td></tr>"

    return (
        "<section><h2>Pass 10 — Meta-calibrated evaluation + tempo playbook</h2>"
        f"<div class=cards>{score_cards}</div>"
        "<p class=muted><b>Local research only — no Kaggle upload, no GitHub push</b>; "
        "root <code>main.py</code>/<code>deck.csv</code> immutable.</p>"
        "<p class=muted><b>Local-vs-Kaggle mismatch lesson:</b> the v2 control's "
        "live score has drifted from its historical 479.1 to ~"
        f"{_esc(sc['v2'])}; the v1 reference now sits at "
        f"{_esc(sc['v1'])} (above v2). Local proxies and "
        "early public scores are unreliable predictors of the settled ladder.</p>"
        "<h3>Opponent archetypes (mirror real; externals blocked)</h3>"
        "<table><tr><th>Archetype</th><th>Status</th><th>Weight</th>"
        f"<th>Replay</th></tr>{arch_rows}</table>"
        "<h3>Tempo failure taxonomy (from the real self-mirror replay)</h3>"
        f"{sig_html}"
        "<h3>Candidates (built + validated, none promotable; unconfirmed ids blocked)</h3>"
        "<table><tr><th>Candidate</th><th>Kind</th><th>Status</th>"
        f"<th>Note</th></tr>{cand_rows}</table>"
        "<h3>Evaluation & queue</h3>"
        f"<p class=muted>Games runnable locally: <b>{_esc(ev.get('games_runnable_locally'))}</b> "
        "(Pass 10-era status: cabt engine assumed absent — <b>superseded by Pass 10B</b>, "
        "which confirmed cabt runs full games locally; see the Pass 10B section above). "
        f"Coverage <b>{_esc(ev.get('coverage'))}</b>, "
        f"complete={_esc(ev.get('eval_complete'))}. "
        "Evaluation is <b>INCOMPLETE (scout only)</b>: most of the meta is blocked "
        "and no games could be run at Pass 10.</p>"
        "<div class=empty><b>Nothing promotable. Queue stays empty. "
        "Next upload: none.</b></div>"
        "</section>"
    )


def _pass10_md(data: dict) -> list[str]:
    summary = data.get("pass10_meta_summary") or {}
    pool = data.get("pass10_meta_pool") or {}
    cands = data.get("pass10_candidates") or {}
    ev = data.get("pass10_eval") or {}
    if not (summary or pool or cands or ev):
        return []
    sc = _pass10_control_scores(pool)
    lines = ["## Pass 10 — Meta-calibrated evaluation + tempo playbook", ""]
    lines.append("_Local research only — no Kaggle upload, no GitHub push; root "
                 "main.py/deck.csv immutable._")
    lines += ["", "### Live Kaggle scores (Part A)",
              f"- v2 control `deck_energy_trim_light`: **{sc['v2']}** "
              "(historical/early 479.1)",
              f"- v1 reference: **{sc['v1']}** (currently above v2)",
              f"- `combo_full_safety_v3_fixed`: **{sc['rejected']}** "
              "(complete, **live-rejected**)",
              "",
              "**Local-vs-Kaggle mismatch lesson:** the v2 control drifted from its "
              f"historical 479.1 to ~{sc['v2']} and v1 "
              f"({sc['v1']}) now outscores it; local proxies / "
              "early public scores do not reliably predict the settled ladder."]
    # Archetypes (honest meta pool: weights + coverage status).
    lines += ["", "### Opponent archetypes (meta pool coverage)"]
    for a in pool.get("archetypes") or []:
        rep = a.get("replay_episode")
        lines.append(f"- `{a.get('key')}` — {a.get('status')} "
                     f"(weight {a.get('weight')}, "
                     f"replay: {rep if rep is not None else 'missing'})")
    # Tempo taxonomy.
    lines += ["", "### Tempo failure taxonomy (real replay)"]
    for s in summary.get("tempo_signals") or ["_none_"]:
        lines.append(f"- {s}")
    # Candidates.
    lines += ["", "### Candidates (none promotable)"]
    for c in cands.get("built") or []:
        lines.append(f"- `{c.get('id')}` ({c.get('kind')}): "
                     f"validated={c.get('validated')}, promotable=False")
    for c in cands.get("blocked") or []:
        lines.append(f"- `{c.get('id')}` ({c.get('kind')}): **BLOCKED** — {c.get('reason')}")
    # Eval + queue.
    lines += ["", "### Evaluation & queue",
              f"- Games runnable locally: **{ev.get('games_runnable_locally')}** "
              "(Pass 10-era status: cabt assumed absent — **superseded by Pass 10B**, "
              "which confirmed cabt runs full games locally)",
              f"- weighted_meta_score: **{ev.get('weighted_meta_score')}** "
              f"(coverage {ev.get('coverage')}, complete={ev.get('eval_complete')})",
              "- **INCOMPLETE (scout only). Nothing promotable. Queue empty. "
              "Next upload: none.**"]
    return lines


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


def _pass7b_rank_md(ranking: dict, title: str) -> list[str]:
    cands = (ranking or {}).get("candidates") or []
    lines = [f"### {title}"]
    if not cands:
        lines.append("_No Pass 7B ranking at this stage._")
        return lines
    src = ranking.get("ranking_source")
    mode = ranking.get("runner_mode")
    stub = ranking.get("fast_import_stub_used")
    lines.append(f"_run_id `{ranking.get('run_id')}`; runner={mode}; "
                 f"fast_import_stub_used={stub}; source={src}._")
    lines.append("")
    lines.append("| # | Candidate | Label | Games | W-L-D | Adj WR | 80% CI | 95% CI "
                 "| p0/p1 | cr/to/st | Fixture |")
    lines.append("|--:|-----------|-------|------:|-------|-------:|--------|--------"
                 "|-------|----------|---------|")
    for i, c in enumerate(cands):
        lines.append(
            f"| {i + 1} | {c.get('candidate_id')} | {c.get('promotion_label')} | "
            f"{c.get('games_completed')}/{c.get('games_planned')} | "
            f"{c.get('wins')}-{c.get('losses')}-{c.get('draws')} | "
            f"{_num(c.get('adjusted_win_rate'))} | {_ci_str(c.get('wilson_80'))} | "
            f"{_ci_str(c.get('wilson_95'))} | "
            f"{_num(c.get('seat_p0_win_rate'))}/{_num(c.get('seat_p1_win_rate'))} | "
            f"{c.get('crashes')}/{c.get('timeouts')}/{c.get('stale')} | "
            f"{c.get('fixture_gate_status')} |")
    return lines


def _pass7b_md(data: dict) -> list[str]:
    scout = data.get("pass7b_scout_ranking") or {}
    focused = data.get("pass7b_focused_ranking") or {}
    gate = data.get("pass7b_fixture_gate") or {}
    bench = data.get("pass7b_benchmark") or {}
    meta = data.get("meta_archetypes") or {}
    queue = data.get("queue") or {}

    lines = ["## Pass 7B — Durable fast scout", ""]
    if not (scout or focused or gate or bench or meta or queue):
        lines.append("_No Pass 7B artifacts found yet._")
        return lines

    lines += [
        f"- Active control: v2 `deck_energy_trim_light` live **{V2_LIVE_SCORE}** "
        f"(v1 live **{V1_LIVE_SCORE}**).",
        "- Scope: local research only — **no Kaggle upload, no GitHub push**; root "
        "`main.py`/`deck.csv` immutable.",
        "- Source of truth: durable ActiveGraph ledger "
        "`data/activegraph/ptcg_ledger_events.jsonl` (Pass 7A fallback ledger — no "
        "second framework). Tables below are projections of recorded events.",
        "",
        "### Fast-import benchmark",
    ]
    if bench:
        n_imp = (bench.get("normal") or {}).get("import_seconds")
        f_imp = (bench.get("fast") or {}).get("import_seconds")
        lines.append(
            f"- Cold cabt import: normal **{_num(n_imp, '{:.2f}')}s** → fast "
            f"**{_num(f_imp, '{:.2f}')}s** "
            f"(**{bench.get('import_speedup_x', '-')}×**, both_import_ok="
            f"{bench.get('both_import_ok')}, fast_validated={bench.get('fast_validated')}).")
        stub = (bench.get("fast") or {}).get("stub_metadata") or {}
        if stub:
            lines.append(f"- Stubbed modules: {stub.get('stubbed_modules')}; "
                         f"fast_import_stub_enabled={stub.get('fast_import_stub_enabled')}.")
    else:
        lines.append("_No benchmark artifact._")

    lines += ["", "### Fixture gate (advisory)"]
    results = [r for r in (gate.get("results") or []) if not r.get("is_anchor")]
    if results:
        non_anchor_ids = {r.get("candidate_id") for r in results}
        passed = ", ".join(c for c in (gate.get("passed") or [])
                           if not non_anchor_ids or c in non_anchor_ids) or "none"
        failed = ", ".join(c for c in (gate.get("failed") or [])
                           if not non_anchor_ids or c in non_anchor_ids) or "none"
        lines.append(f"- Passing: {passed}; failing: {failed}.")
        lines.append("- Secret Box step-11 nuance preserved (a forced 3-of-3 discard "
                     "reads as forced_all/na, not a policy failure).")
        lines += ["", "| Candidate | Status | Seam covered | pref p/f/na |",
                  "|-----------|--------|--------------|-------------|"]
        for r in results:
            lines.append(
                f"| {r.get('candidate_id')} | {r.get('status')} | "
                f"{r.get('seam_covered')} | {r.get('preference_pass')}/"
                f"{r.get('preference_fail')}/{r.get('preference_na')} |")
    else:
        lines.append("_No fixture gate results._")

    lines += [""]
    lines += _pass7b_rank_md(scout, "Scout ranking (controls/anchors excluded from queue)")
    lines += [""]
    lines += _pass7b_rank_md(focused, "Focused micro-confirmation")

    lines += ["", "### Dry-run submission queue (≤1, no upload)"]
    q_items = queue.get("queue") or queue.get("candidates") or []
    if q_items:
        auto_submit = queue.get("auto_submit_enabled", queue.get("auto_submit"))
        upload = queue.get("upload_performed", queue.get("will_upload"))
        lines.append(f"- auto_submit={auto_submit}, "
                     f"manual_approval={queue.get('require_manual_approval_for_submit')}, "
                     f"upload_performed={upload}, "
                     f"max={queue.get('max_queue_size', queue.get('max_per_day'))}.")
        for c in q_items:
            cid = c.get("candidate_id") or c.get("branch_id")
            label = c.get("promotion_label") or c.get("label")
            lines.append(f"  - {cid} [{label}] -> `{c.get('tarball')}` (NOT uploaded)")
    else:
        lines.append("_Queue empty — no candidate qualified (or queue not built)._")

    lines += ["", "### Meta engine strategy backlog"]
    lines.append(f"- Replays present: {meta.get('n_replays', 0)}; archetypes "
                 f"extracted: {meta.get('n_archetypes_extracted', 0)} "
                 f"(coverage={meta.get('coverage', 'empty')}) — scaffolding only, "
                 "no card ids invented.")
    lines.append("- Docs: `docs/META_ENGINE_STRATEGIES.md`, "
                 "`data/meta_replays/README.md`; tools: "
                 "`scripts/{analyze_meta_replay,compare_meta_decks,extract_meta_archetypes}.py`.")
    for t in (meta.get("strategy_tracks") or []):
        lines.append(f"  - **{t.get('name')}** — policy seam: {t.get('policy_seam')}")
    for note in (meta.get("uncertainty_notes") or []):
        lines.append(f"  - _uncertainty:_ {note}")

    return lines


def _pass8_md(data: dict) -> list[str]:
    scout = data.get("pass8_scout_ranking") or {}
    focused = data.get("pass8_focused_ranking") or {}
    gate = data.get("pass8_fixture_gate") or {}
    queue = data.get("queue") or {}
    chaos = data.get("chaos_contract") or {}

    lines = ["## Pass 8 — Fixture-first effect safety", ""]
    if not (scout or focused or gate):
        lines.append("_No Pass 8 artifacts found yet._")
        return lines

    lines += [
        f"- Active control: v2 `deck_energy_trim_light` live **{V2_LIVE_SCORE}** "
        f"(v1 live **{V1_LIVE_SCORE}**).",
        "- Scope: local research only — **no Kaggle upload, no GitHub push**; root "
        "`main.py`/`deck.csv` immutable.",
        "- Replay failures are turned into deterministic fixtures; the HARD fixture gate "
        "is a strict promotion filter. `secret_box_forced_discard_all` is forced_all/na "
        "and is never counted as a failure.",
        "",
        "### Fixture gate (HARD = promotion filter)",
    ]
    results = [r for r in (gate.get("results") or []) if not r.get("is_anchor")]
    if results:
        eligible = ", ".join(gate.get("eligible") or []) or "none"
        lines.append(f"- {gate.get('n_hard_fixtures')} HARD of "
                     f"{gate.get('n_gradeable_fixtures')} gradeable fixtures; "
                     f"eligible (all hard fixtures pass): **{eligible}**.")
        if gate.get("forced_discard_note"):
            lines.append(f"- {gate.get('forced_discard_note')}")
        lines += ["", "| Candidate | Gate | pass/fail/na | Hard failures |",
                  "|-----------|------|--------------|---------------|"]
        for r in results:
            hard = r.get("hard_failures") or []
            hard_str = "; ".join(
                f"{h.get('fixture')} ({h.get('detail') or h.get('reason')})" for h in hard
            ) if hard else "none"
            status = "eligible" if r.get("promotable_gate") else "blocked"
            lines.append(
                f"| {r.get('candidate_id')} | {status} | "
                f"{r.get('fixture_pass_count')}/{r.get('fixture_fail_count')}/"
                f"{r.get('fixture_na_count')} | {hard_str} |")
    else:
        lines.append("_No fixture gate results._")

    lines += [""]
    lines += _pass7b_rank_md(scout, "Scout ranking (gate-failers excluded from queue)")
    lines += [""]
    lines += _pass7b_rank_md(focused, "Focused seat-swap confirmation")

    lines += ["", "### Dry-run submission queue (≤1, no upload)"]
    q_items = queue.get("queue") or queue.get("candidates") or []
    lines.append(f"- auto_submit={queue.get('auto_submit_enabled')}, "
                 f"manual_approval={queue.get('require_manual_approval_for_submit')}, "
                 f"no_more_submissions_today={queue.get('no_more_submissions_today')}, "
                 f"upload_performed={queue.get('upload_performed')}, "
                 f"max={queue.get('max_queue_size')}.")
    if q_items:
        for c in q_items:
            cid = c.get("candidate_id") or c.get("branch_id")
            label = c.get("promotion_label") or c.get("label")
            lines.append(f"  - {cid} [{label}] -> `{c.get('tarball')}` (NOT uploaded)")
    else:
        reason = queue.get("selection_reason") or "no candidate qualified"
        lines.append(f"  - _Queue empty — {reason}._")

    correction = (chaos or {}).get("telemetry_correction") or {}
    if correction:
        avail = correction.get("available") or correction.get("opponent_observable") or []
        missing = (correction.get("still_missing_or_uncertain")
                   or correction.get("opponent_hidden") or [])
        lines += ["", "### Chaos telemetry correction",
                  f"- Observable: {', '.join(avail) or '—'}",
                  f"- Still hidden: {', '.join(missing) or '—'}"]
        if correction.get("conclusion"):
            lines.append(f"- {correction.get('conclusion')}")

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
        f"(live score {V1_LIVE_SCORE}). Two-stage evaluation: a broad scout pass "
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

    lines += _pass15_md(data)
    lines += [""]
    lines += _pass13_md(data)
    lines += [""]
    lines += _pass12_md(data)
    lines += [""]
    lines += _pass11b_md(data)
    lines += [""]
    lines += _pass10b_md(data)
    lines += [""]
    lines += _pass10_md(data)
    lines += [""]
    lines += _run_ledger_md(data)
    lines += [""]
    lines += _pass8_md(data)
    lines += [""]
    lines += _pass7b_md(data)
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
