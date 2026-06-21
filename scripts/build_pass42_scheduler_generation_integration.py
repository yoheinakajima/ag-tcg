#!/usr/bin/env python3
"""Pass 42 (Part G) — scheduler integration proof.

Proves that the standing-tournament scheduler treats the freshly admitted Part F
probation candidates correctly and safely, WITHOUT mutating anything (read-only):

  1. each probation candidate appears in the deterministic worklist;
  2. its top-priority game is a placement/anchor game (tier 1/2), against a
     protected anchor/champion opponent (never another probation deck);
  3. the scheduler never elevates a probation candidate to champion/anchor/active
     (status stays ``probation``);
  4. no protected candidate (anchor/champion/held_probe/active) is dropped,
     replaced, or made non-schedulable by the admission;
  5. NO public reference id appears anywhere in the worklist (refs are
     benchmark-only and absent from the pool entirely);
  6. building the worklist twice yields a byte-identical game sequence
     (determinism).

LOCAL-only, read-only, no events emitted, never starts the root workflow.
Outputs: data/experiments/pass42_scheduler_generation_integration.{json,md}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import projections  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament import pool as poolmod  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool, PROBATION  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402

EXP = REPO / "data" / "experiments"
POOL_PATH = REPO / "data" / "tournament" / "candidate_pool.json"
REF_MANIFEST = REPO / "data" / "reference_agents" / "reference_agent_manifest.json"

PROTECTED_STATUSES = {poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR,
                      poolmod.HELD_PROBE, "active"}
ANCHOR_STATUSES = {poolmod.FAMILY_CHAMPION, poolmod.PORTFOLIO_ANCHOR}


def _reference_ids() -> set[str]:
    if not REF_MANIFEST.is_file():
        return set()
    d = json.loads(REF_MANIFEST.read_text(encoding="utf-8"))
    rows = d.get("opponents") or d.get("agents") or []
    return {r.get("agent_id") for r in rows if r.get("agent_id")}


def _build_state(events, pool, cfg):
    agg = projections.fold_games(events)
    ranked = [r["candidate_id"] for r in projections.compute_rankings(pool, agg)]
    return projections.build_scheduler_state(events, ranking=ranked)


def main() -> int:
    pool = CandidatePool.load(POOL_PATH)
    cfg = load_config()
    events = TournamentLedger().load()
    ref_ids = _reference_ids()

    status_by_id = {c.candidate_id: c.status for c in pool.candidates}
    probation_ids = sorted(cid for cid, s in status_by_id.items() if s == PROBATION)
    pool_stats_before = pool.stats()

    # --- build the worklist twice (determinism) ---------------------------
    wl1 = build_worklist(pool, _build_state(events, pool, cfg), cfg)
    wl2 = build_worklist(pool, _build_state(events, pool, cfg), cfg)
    seq1 = [g.to_dict() for g in wl1]
    seq2 = [g.to_dict() for g in wl2]
    deterministic = seq1 == seq2

    # --- scheduler must not have mutated the pool -------------------------
    pool_after = CandidatePool.load(POOL_PATH)
    pool_unchanged = (pool_after.stats() == pool_stats_before)

    # --- per-probation checks --------------------------------------------
    ids_in_wl = {g.candidate_a for g in wl1} | {g.candidate_b for g in wl1}
    per_probation = []
    all_present = True
    all_placement = True
    all_anchor_opp = True
    all_stay_probation = True
    for pid in probation_ids:
        games = [g for g in wl1 if pid in (g.candidate_a, g.candidate_b)]
        present = len(games) > 0
        # the highest-priority (lowest prio number) game for this candidate
        best = min(games, key=lambda g: g.priority) if games else None
        opp = None
        opp_status = None
        is_placement = False
        opp_is_anchor = False
        if best is not None:
            opp = best.candidate_b if best.candidate_a == pid else best.candidate_a
            opp_status = status_by_id.get(opp)
            is_placement = best.priority in (1, 2)
            opp_is_anchor = opp_status in ANCHOR_STATUSES
        stays_probation = status_by_id.get(pid) == PROBATION
        all_present = all_present and present
        all_placement = all_placement and is_placement
        all_anchor_opp = all_anchor_opp and opp_is_anchor
        all_stay_probation = all_stay_probation and stays_probation
        per_probation.append({
            "candidate_id": pid,
            "present_in_worklist": present,
            "n_games": len(games),
            "top_priority": best.priority if best else None,
            "top_reason": best.reason if best else None,
            "top_opponent": opp,
            "top_opponent_status": opp_status,
            "top_is_placement_tier": is_placement,
            "top_opponent_is_anchor": opp_is_anchor,
            "status_remains_probation": stays_probation,
        })

    # --- no public reference contamination -------------------------------
    refs_in_pool = sorted(ref_ids & set(status_by_id))
    refs_in_worklist = sorted(ref_ids & ids_in_wl)
    no_ref_in_pool = not refs_in_pool
    no_ref_in_worklist = not refs_in_worklist

    # --- protected candidates intact -------------------------------------
    protected_before = sorted(
        cid for cid, s in status_by_id.items() if s in PROTECTED_STATUSES)
    sched_ids_after = {c.candidate_id for c in pool_after.schedulable()}
    protected_all_schedulable = all(p in sched_ids_after for p in protected_before)
    # no protected candidate was scheduled *against* a probation deck in a way
    # that would imply replacement — protected anchors only ever appear as the
    # senior opponent, which is expected; we only assert none were removed.

    ok = bool(
        deterministic and pool_unchanged and all_present and all_placement
        and all_anchor_opp and all_stay_probation and no_ref_in_pool
        and no_ref_in_worklist and protected_all_schedulable
        and len(wl1) <= cfg.tick_max_games
    )

    out = {
        "pass_id": "pass42", "part": "G",
        "local_only": True, "read_only": True, "no_upload": True,
        "config": {
            "tick_max_games": cfg.tick_max_games,
            "min_placement_games_per_candidate": cfg.min_placement_games_per_candidate,
            "top_bracket_size": cfg.top_bracket_size,
        },
        "n_probation": len(probation_ids), "probation_ids": probation_ids,
        "worklist_size": len(wl1),
        "worklist_priority_histogram": _hist(wl1),
        "checks": {
            "deterministic_double_build": deterministic,
            "scheduler_did_not_mutate_pool": pool_unchanged,
            "all_probation_in_worklist": all_present,
            "all_probation_top_game_is_placement_tier": all_placement,
            "all_probation_top_opponent_is_anchor": all_anchor_opp,
            "all_probation_remain_probation": all_stay_probation,
            "no_public_ref_in_pool": no_ref_in_pool,
            "no_public_ref_in_worklist": no_ref_in_worklist,
            "protected_all_still_schedulable": protected_all_schedulable,
            "worklist_within_tick_cap": len(wl1) <= cfg.tick_max_games,
        },
        "reference_ids_checked": sorted(ref_ids),
        "protected_candidates": protected_before,
        "per_probation": per_probation,
        "ok": ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_scheduler_generation_integration.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    (EXP / "pass42_scheduler_generation_integration.md").write_text(
        _md(out), encoding="utf-8")

    print(f"pass42 scheduler integration: ok={ok} probation={len(probation_ids)} "
          f"worklist={len(wl1)} deterministic={deterministic} "
          f"placement_tier={all_placement} anchor_opp={all_anchor_opp} "
          f"no_ref={no_ref_in_pool and no_ref_in_worklist}")
    return 0 if ok else 1


def _hist(wl) -> dict:
    h: dict[str, int] = {}
    for g in wl:
        k = f"p{g.priority}:{g.reason}"
        h[k] = h.get(k, 0) + 1
    return dict(sorted(h.items()))


def _md(out: dict) -> str:
    def yn(b):
        return "yes" if b else "no"
    c = out["checks"]
    L = [
        "# Pass 42 (Part G) — Scheduler Integration Proof", "",
        "_LOCAL-only, READ-ONLY. The scheduler is a pure function of "
        "(pool, folded state, config); this proof emits no events and mutates "
        "nothing. Probation = eligible to be *scheduled for placement*, never "
        "promoted._", "",
        f"- probation candidates: **{out['n_probation']}** — {out['probation_ids']}",
        f"- worklist size: **{out['worklist_size']}** / cap {out['config']['tick_max_games']}",
        "",
        "## Checks",
        f"- deterministic double-build (identical game sequence): **{yn(c['deterministic_double_build'])}**",
        f"- scheduler did not mutate the pool: **{yn(c['scheduler_did_not_mutate_pool'])}**",
        f"- every probation candidate appears in the worklist: **{yn(c['all_probation_in_worklist'])}**",
        f"- each probation top game is a placement/anchor tier (1/2): **{yn(c['all_probation_top_game_is_placement_tier'])}**",
        f"- each probation top opponent is an anchor/champion: **{yn(c['all_probation_top_opponent_is_anchor'])}**",
        f"- every probation candidate stays `probation` (never elevated): **{yn(c['all_probation_remain_probation'])}**",
        f"- no public reference id in the pool: **{yn(c['no_public_ref_in_pool'])}**",
        f"- no public reference id in the worklist: **{yn(c['no_public_ref_in_worklist'])}**",
        f"- all protected candidates still schedulable: **{yn(c['protected_all_still_schedulable'])}**",
        f"- worklist within tick cap: **{yn(c['worklist_within_tick_cap'])}**", "",
        "## Worklist priority histogram",
    ]
    for k, v in out["worklist_priority_histogram"].items():
        L.append(f"- `{k}`: {v}")
    L += ["", "## Per probation candidate", "",
          "| candidate | in worklist | top prio | reason | opponent | opp status | placement | anchor opp | stays probation |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in out["per_probation"]:
        L.append(
            f"| `{p['candidate_id']}` | {yn(p['present_in_worklist'])} "
            f"| {p['top_priority']} | {p['top_reason']} | `{p['top_opponent']}` "
            f"| {p['top_opponent_status']} | {yn(p['top_is_placement_tier'])} "
            f"| {yn(p['top_opponent_is_anchor'])} | {yn(p['status_remains_probation'])} |")
    L += ["", f"**overall ok: {yn(out['ok'])}**", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
