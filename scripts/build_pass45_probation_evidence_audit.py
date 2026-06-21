#!/usr/bin/env python3
"""PASS 45 — Part C: probation candidate evidence audit (read-only).

For each of the 3 Pass-42 probation candidates, reads the PRODUCTION ledger (fast,
events-only) and reports the full promotion-gate evidence the deployed daemon has
accrued during the soak, broken down gate-by-gate against the locked v1 thresholds,
with an explicit "games still needed" distance to each sample-size minimum and an
honest promotion-readiness verdict.

This is a transparent readiness audit, not a promotion. It emits nothing and mutates
nothing. The expected honest verdict is "not promotion-ready — insufficient evidence"
for all three: the soak has accrued only a handful of placement games each.

Output:
  data/experiments/pass45_probation_evidence_audit.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import promotion, sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.promotion import (  # noqa: E402
    ACTIVATE, PROMOTE_FAMILY_CHAMPION, DEFAULT_THRESHOLDS)
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]
PROMOTION_READY_ACTIONS = {ACTIVATE, PROMOTE_FAMILY_CHAMPION}


def _load_prod():
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    if not backend.exists(sync.EVENTS_KEY):
        raise SystemExit("prod ledger not reachable")
    txt = backend.read_text(sync.EVENTS_KEY)
    tmp = Path(tempfile.mkdtemp(prefix="pass45_evid_prod_")) / "events.jsonl"
    tmp.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmp).load()
    pool = CandidatePool.from_events(events)
    return pool, events


def _gap(have: int, need: int) -> int:
    return max(0, need - have)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    th = DEFAULT_THRESHOLDS
    pool, events = _load_prod()
    evaluation = promotion.evaluate(pool, events)
    recs = {r["candidate_id"]: r for r in evaluation["recommendations"]}

    per_target = {}
    for cid in TARGETS:
        r = recs.get(cid)
        if not r:
            per_target[cid] = {"in_prod_pool": False}
            continue
        e = r["evidence"]
        sample_gaps = {
            "total_games": {"have": e["total_games"], "need": th.activate_min_total_games,
                            "still_needed": _gap(e["total_games"],
                                                 th.activate_min_total_games)},
            "decisive_games": {"have": e["decisive_games"],
                               "need": th.activate_min_decisive_games,
                               "still_needed": _gap(e["decisive_games"],
                                                    th.activate_min_decisive_games)},
            "anchor_games": {"have": e["anchor_games"],
                             "need": th.activate_min_anchor_games,
                             "still_needed": _gap(e["anchor_games"],
                                                  th.activate_min_anchor_games)},
            "anchor_decisive": {"have": e["anchor_decisive"],
                                "need": th.activate_min_anchor_decisive,
                                "still_needed": _gap(e["anchor_decisive"],
                                                     th.activate_min_anchor_decisive)},
            "parent_h2h_games": {"have": e["parent_h2h_games"],
                                 "need": th.activate_min_parent_h2h_games,
                                 "still_needed": _gap(e["parent_h2h_games"],
                                                      th.activate_min_parent_h2h_games)},
        }
        promotion_ready = bool(r["actionable"] and r["action"] in PROMOTION_READY_ACTIONS)
        per_target[cid] = {
            "in_prod_pool": True,
            "status": r["status"],
            "action": r["action"],
            "actionable": r["actionable"],
            "promotion_ready": promotion_ready,
            "reasons": r["reasons"],
            "gate_checks": r["checks"],
            "sample_size_gaps": sample_gaps,
            "evidence": e,
        }

    any_ready = any(t.get("promotion_ready") for t in per_target.values())
    all_in_pool = all(t.get("in_prod_pool") for t in per_target.values())
    all_insufficient = all(
        (not t.get("promotion_ready"))
        and t.get("action") in ("insufficient_evidence", "stay_probation")
        for t in per_target.values() if t.get("in_prod_pool"))

    out = {
        "pass": "pass45_probation_evidence_audit",
        "read_only": True, "mutated": False, "production_mutated": False,
        "caveat": evaluation["caveat"],
        "thresholds": th.to_policy(),
        "targets_all_in_prod_pool": all_in_pool,
        "any_target_promotion_ready": any_ready,
        "all_targets_insufficient_or_stay": all_insufficient,
        "per_target": per_target,
        "expected": "all targets not promotion-ready (insufficient_evidence): the "
                    "soak has accrued far fewer than the locked v1 minimums.",
    }
    (EXP / "pass45_probation_evidence_audit.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 45 — Part C: probation candidate evidence audit", "",
        f"> {evaluation['caveat']}", "",
        f"- all targets in prod pool: **{yn(all_in_pool)}**  · any promotion-ready: "
        f"**{yn(any_ready)}**",
        f"- locked v1 activate minimums: total ≥ {th.activate_min_total_games}, "
        f"decisive ≥ {th.activate_min_decisive_games}, anchor games ≥ "
        f"{th.activate_min_anchor_games} / decisive ≥ {th.activate_min_anchor_decisive}, "
        f"parent-H2H ≥ {th.activate_min_parent_h2h_games}", "",
    ]
    for cid in TARGETS:
        t = per_target[cid]
        md += [f"## `{cid}`"]
        if not t.get("in_prod_pool"):
            md += ["- **not present in production pool**", ""]
            continue
        e = t["evidence"]
        md += [
            f"- status: `{t['status']}`  · action: **{t['action']}**  · "
            f"promotion-ready: **{yn(t['promotion_ready'])}**",
            f"- record: {e['total_games']} games "
            f"({e['wins']}W / {e['losses']}L / {e['draws']}D), decisive "
            f"{e['decisive_games']}, invalid {e['invalid_count']} "
            f"(hard-fail rate {e['hardfail_rate']})",
            f"- win-rate {e['win_rate']}  · Wilson [{e['wilson_low']}, "
            f"{e['wilson_high']}]  · parent-H2H {e['parent_h2h_games']} games "
            f"(seat0 {e['parent_seat0']} / seat1 {e['parent_seat1']})  · anchor "
            f"decisive {e['anchor_decisive']}",
            "", "| gate | have | need | still needed |", "|---|---|---|---|"]
        for g, v in t["sample_size_gaps"].items():
            md.append(f"| {g} | {v['have']} | {v['need']} | {v['still_needed']} |")
        md += [f"- reasons: {'; '.join(t['reasons'])}", ""]
    md += ["> Honest verdict: a candidate is never promoted on raw win-rate or a tiny "
           "sample. All three remain on probation, accruing evidence under the live "
           "daemon until the locked v1 sample-size and Wilson gates are met."]
    (EXP / "pass45_probation_evidence_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass45 partC: all_in_pool={all_in_pool} any_ready={any_ready} "
          f"all_insufficient_or_stay={all_insufficient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
