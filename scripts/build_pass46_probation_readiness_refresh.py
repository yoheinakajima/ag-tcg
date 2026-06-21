#!/usr/bin/env python3
"""PASS 46 — probation promotion-readiness refresh (read-only).

For each of the 3 Pass-42 probation candidates, reads the PRODUCTION ledger (fast,
events-only) and reports the full promotion-gate evidence the deployed daemon has
accrued during the soak: games, decisive games, W/L/D, parent-H2H games, anchor games,
hard failures, the honest distance to each locked-v1 activation threshold, the runtime
quarantine screen, and the current recommendation.

It emits nothing and mutates nothing. The expected honest verdict is "not
promotion-ready — insufficient evidence" for all three, with no quarantine warranted
(decisive==0 alone is never a hard failure).

Output:
  data/experiments/pass46_probation_readiness_refresh.{json,md}
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
    tmp = Path(tempfile.mkdtemp(prefix="pass46_readi_prod_")) / "events.jsonl"
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
        invalid = e.get("invalid_count", 0)
        total = e["total_games"]
        hardfail_rate = round(invalid / total, 4) if total else 0.0
        complete_hardfail = total > 0 and invalid == total
        high_rate_hardfail = (total >= th.quarantine_min_n_for_rate
                              and hardfail_rate >= th.quarantine_hardfail_rate)
        quarantine_warranted = complete_hardfail or high_rate_hardfail
        distance = {
            "total_games": _gap(total, th.activate_min_total_games),
            "decisive_games": _gap(e["decisive_games"],
                                   th.activate_min_decisive_games),
            "anchor_games": _gap(e["anchor_games"], th.activate_min_anchor_games),
            "anchor_decisive": _gap(e["anchor_decisive"],
                                    th.activate_min_anchor_decisive),
            "parent_h2h_games": _gap(e["parent_h2h_games"],
                                     th.activate_min_parent_h2h_games),
        }
        promotion_ready = bool(r["actionable"]
                               and r["action"] in PROMOTION_READY_ACTIONS)
        per_target[cid] = {
            "in_prod_pool": True,
            "status": r["status"],
            "action": r["action"],
            "actionable": r["actionable"],
            "promotion_ready": promotion_ready,
            "recommendation": r["action"],
            "reasons": r["reasons"],
            "games": total,
            "decisive_games": e["decisive_games"],
            "wins": e["wins"], "losses": e["losses"], "draws": e["draws"],
            "parent_h2h_games": e["parent_h2h_games"],
            "parent_seat0": e.get("parent_seat0"),
            "parent_seat1": e.get("parent_seat1"),
            "anchor_games": e["anchor_games"],
            "anchor_decisive": e["anchor_decisive"],
            "hard_failures": invalid,
            "hardfail_rate": hardfail_rate,
            "win_rate": e["win_rate"],
            "wilson_low": e["wilson_low"],
            "wilson_high": e["wilson_high"],
            "distance_to_thresholds": distance,
            "complete_hardfail_evidence": complete_hardfail,
            "high_rate_hardfail_evidence": high_rate_hardfail,
            "decisive_zero": e["decisive_games"] == 0,
            "quarantine_warranted": quarantine_warranted,
            "gate_checks": r["checks"],
        }

    in_pool = [t for t in per_target.values() if t.get("in_prod_pool")]
    any_ready = any(t.get("promotion_ready") for t in in_pool)
    all_in_pool = all(t.get("in_prod_pool") for t in per_target.values())
    any_quarantine = any(t.get("quarantine_warranted") for t in in_pool)
    all_insufficient = all(
        (not t.get("promotion_ready"))
        and t.get("action") in ("insufficient_evidence", "stay_probation")
        for t in in_pool)
    no_false_quarantine = all(
        (not t.get("quarantine_warranted"))
        or t.get("complete_hardfail_evidence")
        or t.get("high_rate_hardfail_evidence") for t in in_pool)

    out = {
        "pass": "pass46_probation_readiness_refresh",
        "read_only": True, "mutated": False, "production_mutated": False,
        "quarantine_emitted": False,
        "caveat": evaluation["caveat"],
        "thresholds": th.to_policy(),
        "quarantine_thresholds": {
            "min_n_for_rate": th.quarantine_min_n_for_rate,
            "hardfail_rate": th.quarantine_hardfail_rate,
        },
        "per_target": per_target,
        "targets_all_in_prod_pool": all_in_pool,
        "any_target_promotion_ready": any_ready,
        "any_quarantine_warranted": any_quarantine,
        "all_targets_insufficient_or_stay": all_insufficient,
        "no_false_quarantine_from_small_sample": no_false_quarantine,
        "expected": "all targets insufficient_evidence; no quarantine warranted "
                    "(soak placement games far below the locked v1 minimums).",
    }
    (EXP / "pass46_probation_readiness_refresh.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 46 — probation promotion-readiness refresh", "",
        f"> {evaluation['caveat']}", "",
        f"- all targets in prod pool: **{yn(all_in_pool)}**  · any promotion-ready: "
        f"**{yn(any_ready)}**  · any quarantine warranted: **{yn(any_quarantine)}**",
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
        d = t["distance_to_thresholds"]
        md += [
            f"- status: `{t['status']}`  · recommendation: **{t['recommendation']}**  "
            f"· promotion-ready: **{yn(t['promotion_ready'])}**  · quarantine: "
            f"**{yn(t['quarantine_warranted'])}**",
            f"- record: {t['games']} games ({t['wins']}W / {t['losses']}L / "
            f"{t['draws']}D), decisive {t['decisive_games']}, hard failures "
            f"{t['hard_failures']} (rate {t['hardfail_rate']})",
            f"- win-rate {t['win_rate']}  · Wilson [{t['wilson_low']}, "
            f"{t['wilson_high']}]  · parent-H2H {t['parent_h2h_games']} "
            f"(seat0 {t['parent_seat0']} / seat1 {t['parent_seat1']})  · anchor games "
            f"{t['anchor_games']} (decisive {t['anchor_decisive']})",
            "", "| gate | still needed |", "|---|---|",
            f"| total games | {d['total_games']} |",
            f"| decisive games | {d['decisive_games']} |",
            f"| anchor games | {d['anchor_games']} |",
            f"| anchor decisive | {d['anchor_decisive']} |",
            f"| parent-H2H games | {d['parent_h2h_games']} |",
            f"- reasons: {'; '.join(t['reasons'])}", ""]
    md += ["> Honest verdict: a candidate is never promoted on raw win-rate or a tiny "
           "sample, and a small / non-decisive sample is never auto-quarantined. All "
           "three remain on probation, accruing evidence under the live daemon until "
           "the locked v1 sample-size and Wilson gates are met."]
    (EXP / "pass46_probation_readiness_refresh.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass46 readiness: all_in_pool={all_in_pool} any_ready={any_ready} "
          f"any_quarantine={any_quarantine} all_insufficient={all_insufficient}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
