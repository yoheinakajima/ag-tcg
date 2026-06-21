#!/usr/bin/env python3
"""Pass 40 (Part O) — strategy decision (records the discrete outcome code).

Selects exactly one decision code from the allowed set based on the produced Pass 40
artifacts, with the evidence behind it. Pure read of already-written artifacts; writes
no ledger events. Outputs:
  data/experiments/pass40_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"

ALLOWED = [
    "reference_benchmarks_registered", "fetch_blocked", "cg_lane_blocked",
    "local_only_pending_republish", "integration_blocked", "benchmark_smoke_failed",
]


def _g(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    rds = _g(EXP / "pass40_root_deploy_safety.json")
    fetch = _g(EXP / "pass40_reference_agent_fetch.json")
    cg = _g(EXP / "pass40_cg_typed_lane_validation.json")
    smoke = _g(EXP / "pass40_reference_agent_smoke.json")
    integ = _g(EXP / "pass40_tournament_benchmark_integration.json")
    tick = _g(EXP / "pass40_benchmark_tick.json")
    gap = _g(EXP / "pass40_public_reference_gap_report.json")
    search = _g(EXP / "pass40_search_api_feasibility.json")

    fetched_ok = bool(fetch.get("total_materialized")) or \
        (fetch.get("required_materialized") == fetch.get("required_count")
         and fetch.get("required_count"))
    cg_ok = bool(cg.get("all_reference_cg_typed_pass")) and \
        bool(cg.get("lanes_separate_and_intact"))
    smoke_ok = bool(smoke.get("all_runnable"))
    integ_ok = bool(integ.get("integration_ok")) and bool(integ.get("zero_leakage"))
    tick_clean = (tick.get("benchmark_results", {}).get("totals", {}).get("invalid")
                  == 0)
    root_safe = bool(rds.get("root_and_deploy_safe"))

    # Decision selection (first failing gate wins; else the success code).
    if not root_safe:
        decision = "integration_blocked"
        reason = "root/deploy safety not verified"
    elif not fetched_ok:
        decision = "fetch_blocked"
        reason = "required reference agents not all materialized"
    elif not cg_ok:
        decision = "cg_lane_blocked"
        reason = "cg_typed lane not validated or stdlib lane not intact"
    elif not smoke_ok:
        decision = "benchmark_smoke_failed"
        reason = "not all references runnable in local cabt smoke"
    elif not integ_ok:
        decision = "integration_blocked"
        reason = "benchmark-lane integration or zero-leakage check failed"
    else:
        decision = "reference_benchmarks_registered"
        reason = ("references materialized, cg_typed validated, smoke passed, "
                  "benchmark lane integrated with zero leakage, controlled tick clean")

    assert decision in ALLOWED, decision

    payload = {
        "schema": "pass40_strategy_decision_v1", "pass": "40", "part": "O",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "decision": decision, "reason": reason, "allowed_decisions": ALLOWED,
        "republish_required": False,
        "republish_note": ("Local-only diagnostics; root main.py/deck.csv and the "
                            "deployment config are unchanged, so nothing is "
                            "prod-registered and no republish is required."),
        "gates": {
            "root_and_deploy_safe": root_safe,
            "fetch_ok": fetched_ok,
            "cg_typed_ok": cg_ok,
            "smoke_ok": smoke_ok,
            "integration_ok": integ_ok,
            "tick_clean_zero_invalid": tick_clean,
        },
        "evidence": {
            "references_materialized": fetch.get("total_materialized"),
            "cg_typed_pass_count": cg.get("cg_typed_pass_count"),
            "smoke_agents_runnable": smoke.get("agents_runnable"),
            "benchmark_worklist": integ.get("benchmark_worklist", {}).get("count"),
            "benchmark_tick_totals": tick.get("benchmark_results", {}).get("totals"),
            "gap_overall_decisive_win_rate": gap.get("overall_decisive_win_rate"),
            "search_api_feasible": search.get("all_feasible"),
        },
    }
    (EXP / "pass40_strategy_decision.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 40 (Part O) — Strategy Decision", "",
        f"- generated: {payload['generated_at']}",
        f"- **decision: `{decision}`**",
        f"- reason: {reason}",
        f"- republish_required: **{payload['republish_required']}** "
        f"({payload['republish_note']})", "",
        "## Gates", "", "| gate | pass |", "|---|---|",
    ]
    for k, v in payload["gates"].items():
        lines.append(f"| {k} | {'yes' if v else 'NO'} |")
    lines += ["", "## Evidence", ""]
    for k, v in payload["evidence"].items():
        lines.append(f"- {k}: {v}")
    (EXP / "pass40_strategy_decision.md").write_text("\n".join(lines) + "\n",
                                                     encoding="utf-8")

    print(f"decision={decision} republish_required={payload['republish_required']}")
    print(f"gates={payload['gates']}")
    print(f"wrote {EXP / 'pass40_strategy_decision.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
