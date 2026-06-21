#!/usr/bin/env python3
"""Pass 40 (Part H) — tournament benchmark-lane integration (structural / dry-run).

Wires the public reference agents into the standing engine as a PHYSICALLY SEPARATE
benchmark lane and PROVES zero leakage into our pool / rankings / scheduler queue /
lifecycle / mutation lineage. This script:

  1. loads the live main pool (``candidate_pool.json``) + main ledger (read-only);
  2. loads the Part F reference agents as benchmark opponents (status
     ``external_reference``);
  3. idempotently registers them into the SEPARATE benchmark ledger
     (``data/tournament/benchmark/benchmark_events.jsonl``) + ``reference_pool.json``;
  4. builds a benchmark worklist (our schedulable candidates x each reference);
  5. proves references are absent from: our pool, our rankings, the normal scheduler
     worklist, the lifecycle plan, and the main ledger (zero-leakage checks).

It NEVER mutates the main ledger, the candidate pool, root main.py/deck.csv, or any
candidate tarball. NO upload / submit / promote / mutate. Outputs:
  data/experiments/pass40_tournament_benchmark_integration.{json,md}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"

from ptcg_activegraph.tournament import benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.projections import (  # noqa: E402
    build_scheduler_state, compute_rankings, fold_games,
)
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.lifecycle import evaluate_lifecycle  # noqa: E402


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    # 1. live main state (read-only).
    pool = CandidatePool.load()
    main_events = TournamentLedger().load()
    schedulable = sorted(c.candidate_id for c in pool.schedulable())

    # 2. benchmark opponents from the Part F manifest.
    opponents = B.load_opponents()

    # 3. register them into the SEPARATE benchmark ledger (idempotent).
    reg = B.register_opponents(opponents)

    # 4. benchmark worklist (our schedulable candidates x references), bounded.
    bench_events = B.benchmark_ledger().load()
    worklist = B.build_benchmark_worklist(
        schedulable, opponents, bench_events, max_games=min(40, len(schedulable) * len(opponents)))
    ref_ids = {o.agent_id for o in opponents}
    worklist_ref_ids = {g.reference_id for g in worklist}
    worklist_our_ids = {g.our_candidate for g in worklist}

    # 5a. zero-leakage proof: references absent from pool / main ledger.
    leakage = B.assert_zero_leakage(pool, main_events, opponents)

    # 5b. references absent from our rankings.
    agg = fold_games(main_events)
    rankings = compute_rankings(pool, agg)
    rank_ids = {r["candidate_id"] for r in rankings}

    # 5c. references absent from the NORMAL scheduler worklist.
    state = build_scheduler_state(main_events,
                                  ranking=[r["candidate_id"] for r in rankings])
    norm_worklist = build_worklist(pool, state, cfg, max_games=cfg.tick_max_games)
    norm_ids = {g.candidate_a for g in norm_worklist} | {g.candidate_b for g in norm_worklist}

    # 5d. references absent from the lifecycle plan.
    plan = evaluate_lifecycle(pool, main_events, cfg)
    lifecycle_ids = {a["candidate_id"] for a in plan["actions"]}

    integration_checks = {
        **leakage["checks"],
        "references_absent_from_rankings": not (ref_ids & rank_ids),
        "references_absent_from_normal_worklist": not (ref_ids & norm_ids),
        "references_absent_from_lifecycle_plan": not (ref_ids & lifecycle_ids),
        "benchmark_worklist_only_references_as_opponents":
            worklist_ref_ids.issubset(ref_ids),
        "benchmark_worklist_only_our_candidates_as_subject":
            worklist_our_ids.issubset(set(schedulable)),
        "benchmark_uses_separate_ledger_file":
            str(B.BENCHMARK_EVENTS_PATH) != str(TournamentLedger().store.path),
    }
    integration_ok = all(integration_checks.values())

    payload = {
        "schema": "pass40_tournament_benchmark_integration_v1",
        "pass": "40", "part": "H",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "tarball_mutation": False, "main_ledger_mutated": False,
        "status_lane": B.EXTERNAL_REFERENCE_STATUS,
        "usage": "benchmark_opponent_only",
        "caveat": B._BENCH_CAVEAT,
        "integration_ok": integration_ok,
        "integration_checks": integration_checks,
        "zero_leakage": leakage["zero_leakage"],
        "main_pool": {
            "candidate_count": len(pool.candidates),
            "schedulable_count": len(schedulable),
            "schedulable_ids": schedulable,
            "status_counts": pool.stats(),
        },
        "registration": reg,
        "opponents": [o.to_dict() for o in opponents],
        "benchmark_worklist": {
            "max_games": min(40, len(schedulable) * len(opponents)),
            "count": len(worklist),
            "games": [g.to_dict() for g in worklist],
        },
        "evidence": {
            "rankings_candidate_ids": sorted(rank_ids),
            "normal_worklist_candidate_ids": sorted(norm_ids),
            "lifecycle_plan_candidate_ids": sorted(lifecycle_ids),
            "reference_pool_path": reg["reference_pool_path"],
            "benchmark_events_path": reg["benchmark_events_path"],
            "main_events_path": str(TournamentLedger().store.path),
        },
    }
    out_json = EXP / "pass40_tournament_benchmark_integration.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 40 (Part H) — Tournament Benchmark-Lane Integration", "",
        f"_{B._BENCH_CAVEAT}_", "",
        f"- generated: {payload['generated_at']}",
        f"- **integration_ok: {integration_ok}**  zero_leakage: {leakage['zero_leakage']}",
        f"- status lane: `{B.EXTERNAL_REFERENCE_STATUS}` (usage: benchmark_opponent_only)",
        f"- main pool: {len(pool.candidates)} candidates "
        f"({len(schedulable)} schedulable); references registered separately: "
        f"{reg['registered_total']} (newly: {len(reg['newly_registered'])})",
        f"- benchmark worklist: {len(worklist)} games "
        f"(our schedulable x {len(opponents)} references)",
        "", "## Zero-leakage / integration checks", "",
        "| check | pass |", "|---|---|",
    ]
    for k, v in integration_checks.items():
        lines.append(f"| {k} | {'yes' if v else 'NO'} |")
    lines += ["", "## Benchmark opponents (external_reference)", "",
              "| agent_id | label | archetype | optional |", "|---|---|---|---|"]
    for o in opponents:
        lines.append(f"| `{o.agent_id}` | {o.label} | {o.deck_archetype} "
                     f"| {'yes' if o.optional else 'no'} |")
    lines += ["", "## Benchmark worklist (sample, first 12)", "",
              "| game_id | our_candidate | reference | our_seat |",
              "|---|---|---|---|"]
    for g in worklist[:12]:
        lines.append(f"| `{g.game_id}` | {g.our_candidate} | {g.reference_id} "
                     f"| {g.our_seat} |")
    out_md = EXP / "pass40_tournament_benchmark_integration.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"integration_ok={integration_ok} zero_leakage={leakage['zero_leakage']}")
    print(f"schedulable={len(schedulable)} opponents={len(opponents)} "
          f"worklist={len(worklist)} newly_registered={len(reg['newly_registered'])}")
    for k, v in integration_checks.items():
        print(f"  {'OK ' if v else 'NO '} {k}")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    return 0 if integration_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
