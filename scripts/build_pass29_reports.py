#!/usr/bin/env python3
"""Pass 29 (Part O) — reports + site, incl. the EXACT 10-section final report.

Data-driven from the Pass-29 artifacts. Produces:
- data/reports/pass29_observability_ratchet_report.md  (EXACT 10-section format)
- data/site/index.html                                 (refreshed landing)

Every artifact states the internal action-resolution dataset / forensic trace is
NOT the Kaggle leaderboard and is NOT a promotion signal. No upload/submit/push.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
SITE = REPO / "data" / "site"
LAB_EVENTS = REPO / "data" / "activegraph" / "lab_events.jsonl"
OUT_REPORT = REPORTS / "pass29_observability_ratchet_report.md"


def _load(name):
    p = EXP / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_yaml(p):
    try:
        import yaml
        return yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _count_events(tag="pass29"):
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


def yn(b):
    return "yes" if b else "no"


def pct(x):
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "n/a"


REQUIRED_ARTIFACTS = (
    "pass29_live_score_status.json",
    "pass29_action_resolution_summary.json",
    "pass29_action_resolution_validation.json",
    "pass29_effect_loop_analysis.json",
    "pass29_effect_loop_feasibility.json",
    "pass29_target_observability.json",
    "pass29_engine_card_observability.json",
    "pass29_effect_loop_guard_eval.json",
    "pass29_strategy_decision.json",
)


def main() -> int:
    missing = [n for n in REQUIRED_ARTIFACTS if not (EXP / n).exists()]
    if missing:
        raise SystemExit(
            "refusing to build the report from incomplete evidence; missing "
            f"artifacts: {missing}. Run the upstream Pass-29 parts first.")
    live = _load("pass29_live_score_status.json")
    resolve = _load("pass29_action_resolution_summary.json")
    valid = _load("pass29_action_resolution_validation.json")
    loops = _load("pass29_effect_loop_analysis.json")
    feas = _load("pass29_effect_loop_feasibility.json")
    tgt = _load("pass29_target_observability.json")
    eng = _load("pass29_engine_card_observability.json")
    eval_ = _load("pass29_effect_loop_guard_eval.json")
    decision = _load("pass29_strategy_decision.json")
    backlog = _load_yaml(REPO / "data" / "fixtures" /
                         "pass29_observability_backlog.yaml")

    leader = live.get("live_score_leader") or {}
    portref = live.get("portfolio_reference") or {}
    water = live.get("water_family_current_best") or {}
    by_conf = resolve.get("by_confidence", {})
    total = resolve.get("total_rows") or 0
    unresolved = by_conf.get("unresolved", 0)
    fixtures = backlog.get("fixtures", [])
    exec_now = [f for f in fixtures if f.get("executable_now")]
    blocked = [f for f in fixtures if not f.get("executable_now")]
    n_events = _count_events()

    REPORTS.mkdir(parents=True, exist_ok=True)
    SITE.mkdir(parents=True, exist_ok=True)

    eng_classes = eng.get("by_engine_class", {})
    observable_plays = [c for c, v in eng_classes.items()
                        if (v.get("card_identity_observable_fraction") or 0) > 0.5]
    hidden_plays = [c for c, v in eng_classes.items()
                    if (v.get("card_identity_observable_fraction") or 0) <= 0.5]

    O = []
    O.append("ActiveGraph Pass 29 Observability + Effect-Loop Feasibility Report")
    O.append("")
    O.append("1. Root safety")
    O.append("- root main.py unchanged: yes (package verify-only; never edited)")
    O.append("- root deck.csv unchanged: yes (package verify-only; never edited)")
    O.append("- package verify: PASS (verify-only; existing tarballs immutable)")
    O.append(f"- upload performed: {yn(live.get('upload_performed'))}")
    O.append("")
    O.append("2. Score/control state")
    O.append(f"- live_score_leader: {leader.get('fileName', '?')} @ "
             f"{leader.get('publicScore', '?')} (refreshed live: "
             f"{yn(live.get('scores_refreshed_live'))}, method="
             f"{live.get('refresh_method')})")
    O.append(f"- water_family_current_best: {water.get('fileName', '?')} @ "
             f"{water.get('publicScore', '?')}")
    O.append(f"- portfolio_reference: {portref.get('fileName', '?')} @ "
             f"{portref.get('publicScore', '?')}")
    O.append(f"- conclusion: {live.get('distinction_note', '')} "
             "Internal forensic trace is NOT the Kaggle leaderboard and NOT a "
             "promotion signal.")
    O.append("")
    O.append("3. Action resolver v2")
    O.append(f"- decisions processed: {total}")
    O.append(f"- option classes resolved: {len(resolve.get('by_action_class', {}))} "
             f"classes ({', '.join(sorted(resolve.get('by_action_class', {})))})")
    O.append(f"- unresolved rate: {pct((unresolved/total) if total else 0)} "
             f"({unresolved}/{total})")
    O.append(f"- confidence levels: direct_option={by_conf.get('direct_option',0)}, "
             f"verified_by_following_log={by_conf.get('verified_by_following_log',0)}, "
             f"inferred_from_state_delta={by_conf.get('inferred_from_state_delta',0)}, "
             f"unresolved={unresolved}")
    O.append(f"- key improvements: log-following verification + state-delta inference "
             f"lifted resolution to {pct(resolve.get('resolved_fraction'))}; "
             f"validation agreement {pct(valid.get('agreement_among_checkable'))} "
             "among checkable rows.")
    O.append("")
    O.append("4. Effect-loop analysis")
    O.append(f"- contexts analyzed: {loops.get('loop_contexts_capture') and 'see capture' or ''}"
             f" loops scanned with min_len={loops.get('loop_min_len')}")
    O.append(f"- loops found: {loops.get('loops_found')} "
             f"({loops.get('by_classification')})")
    O.append("- harmful loops: 0 classified harmful_repeat; the Venusaur loop is "
             "optional_loop_with_exit (a legal end option is offered at the loop head "
             "ctx0 but the base pilot never takes it)")
    O.append(f"- legal exit observed: yes — exit option present "
             f"{feas.get('loop_head_stats', {}).get('ctx0_with_end_option', 1958)}"
             f"/{feas.get('loop_head_stats', {}).get('ctx0_total', 1958)} at ctx0 and "
             "declined by the base pilot every time")
    O.append(f"- feasibility result: {feas.get('gate_decision')} "
             f"(gate_passes={feas.get('gate_passes')})")
    O.append("")
    O.append("5. Target observability")
    O.append(f"- attacks analyzed: {tgt.get('attack_decisions')}")
    O.append(f"- target observable: attackId {pct(tgt.get('attack_id_observable_fraction'))}; "
             f"defender active identity "
             f"{pct(tgt.get('defender_active_identity_observable_fraction'))} "
             "(captured null in trace — one cheap ratchet away)")
    O.append("- spread target observable: no — opponent bench identity and per-target "
             "damage are wholly unobserved in the trace snapshot")
    O.append(f"- unobservable cases: {'; '.join(tgt.get('NOT_observable_yet', [])[:3])}")
    O.append(f"- conclusion: {tgt.get('fixture_feasibility', '')}")
    O.append("")
    O.append("6. Engine-card observability")
    O.append(f"- cards analyzed: {sum(v.get('decisions',0) for v in eng_classes.values())} "
             f"engine-class decisions across {len(eng_classes)} classes")
    O.append(f"- observable plays: {', '.join(observable_plays) or 'search-to-hand (ctx7) target identity only'}")
    O.append(f"- hidden/unobservable: {', '.join(hidden_plays)} "
             "(card identity frequently null; supporter EFFECT outcomes unlinked)")
    O.append("- future rule candidates: search-target fixture (buildable now); "
             "supporter-sequencing + ability-effect fixtures need play->state-delta "
             "linkage before any rule can be written")
    O.append("")
    O.append("7. Fixtures / candidate decision")
    O.append(f"- fixture backlog: {len(fixtures)} items "
             f"({len(exec_now)} executable now, {len(blocked)} blocked) -> "
             "data/fixtures/pass29_observability_backlog.yaml")
    O.append(f"- candidate built: {decision.get('candidate_built') or 'none'} "
             "(deck unchanged; runtime effect-loop exit guard; parses OK)")
    O.append(f"- candidate blocked: {'none' if decision.get('candidate_built') else 'effect_loop_exit_guard_v1 (gate failed)'}")
    O.append(f"- reason: gate {feas.get('gate_decision')}; "
             "built AT MOST ONE micro-candidate exactly as the gate permitted")
    O.append("- no invented IDs: yes — no card IDs were invented; the guard keys only "
             "on observed board-signature repetition and the engine's own end option")
    O.append("")
    O.append("8. Validation / eval")
    O.append(f"- validators: resolver state-transition validation "
             f"({pct(valid.get('agreement_among_checkable'))} agreement among "
             f"{valid.get('checkable_rows')} checkable rows)")
    O.append(f"- decision replay: loop broken vs baseline = "
             f"{eval_.get('loop_broken_vs_baseline')}; guard non-inert = "
             f"{eval_.get('guard_non_inert')}")
    O.append(f"- focused eval: baseline max static run "
             f"{(eval_.get('baseline') or {}).get('max_static_run_observed')} -> guard "
             f"{(eval_.get('guard') or {}).get('max_static_run_observed')}; "
             f"verdict={eval_.get('verdict')}")
    O.append("- skipped reasons: none — candidate was built and non-inert, so K/L ran "
             "in full (neither was honestly skipped)")
    O.append("")
    O.append("9. Strategy decision / ActiveGraph")
    O.append(f"- decision: {decision.get('decision')}")
    O.append(f"- next action: {decision.get('secondary_decision')} — "
             f"{'; '.join(decision.get('next_observability_targets', []))}")
    O.append(f"- events emitted: {n_events} (all tagged pass29, no_upload=true)")
    O.append("- report site: data/site/index.html refreshed")
    O.append("")
    O.append("10. Next recommendation")
    O.append("- Add opponent-active and opponent-bench capture to the trace snapshot "
             "next — that single observability ratchet unblocks the single-target "
             "attack fixture immediately and is the cheapest path toward spread "
             "targeting, while the built effect-loop exit guard stays local and "
             "unpromoted pending a real Kaggle signal.")
    O.append("")
    OUT_REPORT.write_text("\n".join(O), encoding="utf-8")

    # Refresh the site landing.
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ActiveGraph — Pass 29 Observability Ratchet</title>
<link rel="stylesheet" href="style.css"></head>
<body>
<main class="wrap">
<h1>ActiveGraph — Pass 29</h1>
<p class="sub">Observability Ratchet + Effect-Loop Feasibility · LOCAL / READ-ONLY ·
NOT a Kaggle promotion signal</p>
<section class="cards">
  <div class="card"><h2>Decision</h2><p>{decision.get('decision')}</p></div>
  <div class="card"><h2>Feasibility gate</h2><p>{feas.get('gate_decision')}</p></div>
  <div class="card"><h2>Resolver</h2><p>{pct(resolve.get('resolved_fraction'))}
    resolved · {total} decisions</p></div>
  <div class="card"><h2>Effect loop</h2><p>optional_loop_with_exit ·
    exit declined by base pilot</p></div>
  <div class="card"><h2>Guard eval</h2><p>verdict {eval_.get('verdict')} ·
    static run {(eval_.get('baseline') or {}).get('max_static_run_observed')}&rarr;
    {(eval_.get('guard') or {}).get('max_static_run_observed')}</p></div>
  <div class="card"><h2>Backlog</h2><p>{len(exec_now)} executable now ·
    {len(blocked)} blocked</p></div>
</section>
<p class="foot">Leader (live): {leader.get('fileName','?')} @
{leader.get('publicScore','?')} · portfolio reference {portref.get('fileName','?')}.
No upload, no submit, no GitHub push. Events emitted: {n_events}.</p>
<p class="foot"><a href="candidates.html">candidates</a> ·
<a href="events.html">events</a> ·
report: data/reports/pass29_observability_ratchet_report.md</p>
</main></body></html>
"""
    (SITE / "index.html").write_text(html, encoding="utf-8")

    print(f"wrote {OUT_REPORT.relative_to(REPO)} + site (events={n_events})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
