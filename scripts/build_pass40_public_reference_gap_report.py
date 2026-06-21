#!/usr/bin/env python3
"""Pass 40 (Part J) — gap report: our gameplay vs public typed reference agents.

Synthesizes the Pass 40 benchmark lane into an honest gap analysis: how OUR
schedulable candidates fare against the public cg-SDK (typed) reference agents in the
local cabt harness, contextualized against our internal self-play rankings. Reads only
already-produced artifacts (benchmark ledger, internal rankings, smoke + cg_typed
validation). NO games are played here.

Honest framing (hard): the benchmark sample is small and is *feasibility / direction*,
NOT a strength claim and NOT a Kaggle score. References are benchmark opponents only.
NO upload / submit / promote / mutate. Outputs:
  data/experiments/pass40_public_reference_gap_report.{json,md}
  docs/PASS40_REFERENCE_AGENT_INTAKE.md
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
DOCS = REPO / "docs"
PROJ = REPO / "data" / "tournament" / "projections"

from ptcg_activegraph.tournament import benchmark as B  # noqa: E402


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    opponents = B.load_opponents()
    opp_label = {o.agent_id: o.label for o in opponents}
    opp_arch = {o.agent_id: o.deck_archetype for o in opponents}

    bench_events = B.benchmark_ledger().load()
    agg = B.fold_benchmark_games(bench_events)

    rankings = _load_json(PROJ / "rankings.json").get("rankings", [])
    rank_by_id = {r["candidate_id"]: r for r in rankings}
    cg_val = _load_json(EXP / "pass40_cg_typed_lane_validation.json")
    smoke = _load_json(EXP / "pass40_reference_agent_smoke.json")

    def dec_wr(s: dict) -> float | None:
        dec = s[B.OUR_WIN] + s[B.REFERENCE_WIN]
        return round(s[B.OUR_WIN] / dec, 4) if dec else None

    # Per our-candidate gap: internal self-play wr vs benchmark wr vs references.
    per_our = []
    for cid in sorted(agg["per_our"]):
        s = agg["per_our"][cid]
        internal = rank_by_id.get(cid, {})
        per_our.append({
            "our_candidate": cid,
            "internal_status": internal.get("status"),
            "internal_games": internal.get("games"),
            "internal_adj_win_rate": internal.get("adj_win_rate"),
            "benchmark_games": s["games"],
            "benchmark_our_wins": s[B.OUR_WIN],
            "benchmark_reference_wins": s[B.REFERENCE_WIN],
            "benchmark_draws": s[B.DRAW],
            "benchmark_invalid": s[B.INVALID],
            "benchmark_decisive_win_rate": dec_wr(s),
        })

    per_pair = []
    for pk in sorted(agg["per_pair"]):
        s = agg["per_pair"][pk]
        rid = s["reference_id"]
        per_pair.append({
            "our_candidate": s["our_candidate"], "reference_id": rid,
            "reference_label": opp_label.get(rid, rid),
            "reference_archetype": opp_arch.get(rid, ""),
            "games": s["games"], "our_wins": s[B.OUR_WIN],
            "reference_wins": s[B.REFERENCE_WIN], "draws": s[B.DRAW],
            "invalid": s[B.INVALID], "our_decisive_win_rate": dec_wr(s),
        })

    totals = agg["totals"]
    decisive = totals[B.OUR_WIN] + totals[B.REFERENCE_WIN]
    overall_wr = round(totals[B.OUR_WIN] / decisive, 4) if decisive else None

    findings = []
    if totals["games"] == 0:
        findings.append("No benchmark games recorded yet — run the Part I tick first.")
    else:
        findings.append(
            f"Across {totals['games']} controlled local games (0 invalid = the lane "
            f"runs cleanly end-to-end), our candidates won {totals[B.OUR_WIN]} and the "
            f"public typed references won {totals[B.REFERENCE_WIN]} "
            f"(our decisive win rate {overall_wr}).")
        findings.append(
            "This is a SMALL sample and benchmark-only: it is directional feasibility, "
            "NOT a strength claim and NOT predictive of any Kaggle leaderboard score.")
        findings.append(
            "Direction: the public cg-SDK (typed) sample agents currently out-perform "
            "our sampled stdlib candidates in head-to-head local cabt play. The cg_typed "
            "lane is validated and importable, so typed gameplay is a feasible future "
            "exploration seam — but no candidate generation is performed in this pass.")

    payload = {
        "schema": "pass40_public_reference_gap_report_v1", "pass": "40", "part": "J",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "caveat": B._BENCH_CAVEAT,
        "intake_status": {
            "references_total": len(opponents),
            "cg_typed_pass_count": cg_val.get("cg_typed_pass_count"),
            "all_reference_cg_typed_pass": cg_val.get("all_reference_cg_typed_pass"),
            "lanes_separate_and_intact": cg_val.get("lanes_separate_and_intact"),
            "smoke_agents_runnable": smoke.get("agents_runnable"),
            "smoke_all_runnable": smoke.get("all_runnable"),
        },
        "benchmark_totals": totals,
        "overall_decisive_win_rate": overall_wr,
        "by_our_candidate": per_our,
        "by_pair": per_pair,
        "findings": findings,
    }
    (EXP / "pass40_public_reference_gap_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 40 (Part J) — Gap Report: Our Gameplay vs Public Typed Agents", "",
        f"_{B._BENCH_CAVEAT}_", "",
        f"- generated: {payload['generated_at']}",
        f"- references intaken: {len(opponents)} "
        f"(cg_typed pass: {cg_val.get('cg_typed_pass_count')}/"
        f"{len(opponents)}; smoke runnable: {smoke.get('agents_runnable')})",
        f"- benchmark totals: {totals}  (our decisive win rate: {overall_wr})", "",
        "## Findings", "",
    ]
    lines += [f"- {f}" for f in findings]
    lines += ["", "## Our candidate gap (internal self-play vs benchmark vs references)",
              "", "| our_candidate | status | internal_g | internal_wr | bench_g "
              "| our_W | ref_W | invalid | bench_decisive_wr |",
              "|---|---|---|---|---|---|---|---|---|"]
    for p in per_our:
        iwr = "—" if p["internal_adj_win_rate"] is None else f"{p['internal_adj_win_rate']:.3f}"
        bwr = "—" if p["benchmark_decisive_win_rate"] is None else f"{p['benchmark_decisive_win_rate']:.3f}"
        lines.append(
            f"| {p['our_candidate']} | {p['internal_status']} | {p['internal_games']} "
            f"| {iwr} | {p['benchmark_games']} | {p['benchmark_our_wins']} "
            f"| {p['benchmark_reference_wins']} | {p['benchmark_invalid']} | {bwr} |")
    lines += ["", "## Per-matchup (our candidate vs each reference)", "",
              "| our_candidate | reference | archetype | games | our_W | ref_W | draw "
              "| invalid | our_decisive_wr |", "|---|---|---|---|---|---|---|---|---|"]
    for p in per_pair:
        wr = "—" if p["our_decisive_win_rate"] is None else f"{p['our_decisive_win_rate']:.3f}"
        lines.append(
            f"| {p['our_candidate']} | {p['reference_label']} | {p['reference_archetype']} "
            f"| {p['games']} | {p['our_wins']} | {p['reference_wins']} | {p['draws']} "
            f"| {p['invalid']} | {wr} |")
    (EXP / "pass40_public_reference_gap_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    # docs/PASS40_REFERENCE_AGENT_INTAKE.md
    doc = [
        "# Pass 40 — Public Reference Agent Intake", "",
        "_Status lane: `external_reference` (benchmark opponents only). "
        "Internal benchmark scores are NOT Kaggle scores and NOT a strength claim._",
        "",
        "## What this is", "",
        "Pass 40 intakes public Kaggle *rule-based sample* agents (the host's kiyotah "
        "samples + one optional public competitor notebook) as **benchmark opponents** "
        "for the standing ActiveGraph tournament engine. They let us calibrate our own "
        "gameplay against known public typed (cg-SDK) agents in the *local* cabt "
        "harness. They are never our candidates.",
        "", "## Hard guardrails", "",
        "- NO Kaggle upload / submit / auto-submit; every Pass 40 event carries "
        "`no_upload=true`.",
        "- NO root `main.py` / `deck.csv` mutation; NO candidate tarball mutation or "
        "deletion; NO GitHub push; NO candidate generation.",
        "- References are NEVER in the submission queue, promotion, mutation lineage, "
        "lifecycle, family-champion set, active-cap, or any \"our best\" ranking — "
        "proven by the zero-leakage checks (Part H) and the Pass 40 test suite.",
        "- The cg SDK / `libcg.so` / `*.csv` / PDFs / images stay gitignored; only "
        "manifests + hashes are committed.",
        "", "## Reference agents", "",
        "| agent_id | label | archetype | source | optional |",
        "|---|---|---|---|---|",
    ]
    for o in opponents:
        doc.append(f"| `{o.agent_id}` | {o.label} | {o.deck_archetype} "
                   f"| {'host sample' if not o.optional else 'public competitor'} "
                   f"| {'yes' if o.optional else 'no'} |")
    doc += [
        "", "## Lanes", "",
        "- **stdlib lane** — our own candidates (pure-stdlib `main.py`); unchanged and "
        "intact (the cg_typed validator does NOT weaken it).",
        "- **cg_typed lane** — reference agents import the bundled `cg` SDK; validated "
        "separately (see `docs/CG_TYPED_LANE_VALIDATOR.md`).",
        "- **benchmark lane** — references registered on a SEPARATE benchmark ledger "
        "(`data/tournament/benchmark/benchmark_events.jsonl`) via `PublicReferenceAgent"
        "Registered`; benchmark games use `PublicBenchmark*` events that the normal "
        "fold / scheduler / lifecycle never read.",
        "", "## How to run (local only)", "",
        "```bash",
        "python3 scripts/build_pass40_tournament_benchmark_integration.py  # Part H proof",
        "python3 scripts/build_pass40_benchmark_tick.py                     # Part I games",
        "python3 scripts/build_pass40_public_reference_gap_report.py        # Part J gap",
        "```",
        "", "## Current benchmark snapshot", "",
        f"- {totals}  (our decisive win rate: {overall_wr})",
    ]
    doc += [f"- {f}" for f in findings]
    (DOCS / "PASS40_REFERENCE_AGENT_INTAKE.md").write_text(
        "\n".join(doc) + "\n", encoding="utf-8")

    print(f"benchmark_totals={totals} overall_decisive_win_rate={overall_wr}")
    print(f"our_candidates_benchmarked={len(per_our)} pairs={len(per_pair)}")
    print(f"wrote {EXP / 'pass40_public_reference_gap_report.json'}")
    print(f"wrote {EXP / 'pass40_public_reference_gap_report.md'}")
    print(f"wrote {DOCS / 'PASS40_REFERENCE_AGENT_INTAKE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
