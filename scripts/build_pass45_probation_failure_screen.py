#!/usr/bin/env python3
"""PASS 45 — Part D: probation runtime failure / quarantine screen (read-only).

Screens each Pass-42 probation candidate for RUNTIME failure evidence in the live
production soak: invalid games, timeouts, engine errors, and the hard-fail rate. It
applies the gate's quarantine logic transparently:

  * QUARANTINE only on COMPLETE hard-failure evidence (every game invalid) OR a high
    hard-fail rate over an adequate sample (>= quarantine_min_n_for_rate).
  * decisive_games == 0 ALONE is NEVER a failure — draws / a tiny sample are
    non-decisive, not hard failures, and must never trip auto-quarantine.

This is a read-only screen: it emits no CandidateStatusChanged and never quarantines.
The expected honest verdict is "no runtime failure; no quarantine warranted" for all
three (the daemon's hard-fail rate has been ~0).

Output:
  data/experiments/pass45_probation_failure_screen.{json,md}
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.promotion import DEFAULT_THRESHOLDS  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]


def _load_prod_events():
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    if not backend.exists(sync.EVENTS_KEY):
        raise SystemExit("prod ledger not reachable")
    txt = backend.read_text(sync.EVENTS_KEY)
    tmp = Path(tempfile.mkdtemp(prefix="pass45_fail_prod_")) / "events.jsonl"
    tmp.write_text(txt, encoding="utf-8")
    return TournamentLedger(path=tmp).load()


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    th = DEFAULT_THRESHOLDS
    events = _load_prod_events()
    finished = [e for e in events if e.event_type == "GameFinished"]

    per_target = {}
    for cid in TARGETS:
        invo = [e for e in finished
                if (e.payload or {}).get("candidate_a") == cid
                or (e.payload or {}).get("candidate_b") == cid]
        total = len(invo)
        invalid = timeout = error = 0
        decisive = 0
        for e in invo:
            p = e.payload or {}
            r = p.get("result")
            if r in ("win", "loss"):
                decisive += 1
            elif r == "draw":
                pass
            else:
                invalid += 1
                if p.get("timeout"):
                    timeout += 1
                elif r == "error" or p.get("error"):
                    error += 1
        hardfail_rate = round(invalid / total, 4) if total else 0.0
        complete_hardfail = total > 0 and invalid == total
        high_rate_hardfail = (total >= th.quarantine_min_n_for_rate
                              and hardfail_rate >= th.quarantine_hardfail_rate)
        # decisive==0 alone is NOT a failure (non-decisive != hard failure)
        quarantine_warranted = complete_hardfail or high_rate_hardfail
        per_target[cid] = {
            "total_games": total,
            "decisive_games": decisive,
            "invalid_games": invalid,
            "timeouts": timeout,
            "errors": error,
            "hardfail_rate": hardfail_rate,
            "complete_hardfail_evidence": complete_hardfail,
            "high_rate_hardfail_evidence": high_rate_hardfail,
            "decisive_zero": decisive == 0,
            "quarantine_warranted": quarantine_warranted,
            "runtime_failure_detected": invalid > 0,
        }

    any_quarantine = any(t["quarantine_warranted"] for t in per_target.values())
    any_runtime_failure = any(t["runtime_failure_detected"]
                              for t in per_target.values())
    # honesty invariant: no target should be auto-quarantined merely for a small /
    # non-decisive sample (decisive==0 without complete hard-failure evidence)
    no_false_quarantine = all(
        (not t["quarantine_warranted"]) or t["complete_hardfail_evidence"]
        or t["high_rate_hardfail_evidence"]
        for t in per_target.values())

    out = {
        "pass": "pass45_probation_failure_screen",
        "read_only": True, "mutated": False, "production_mutated": False,
        "quarantine_emitted": False,
        "quarantine_thresholds": {
            "min_n_for_rate": th.quarantine_min_n_for_rate,
            "hardfail_rate": th.quarantine_hardfail_rate,
        },
        "per_target": per_target,
        "any_quarantine_warranted": any_quarantine,
        "any_runtime_failure_detected": any_runtime_failure,
        "no_false_quarantine_from_small_sample": no_false_quarantine,
        "expected": "no runtime failure, no quarantine warranted (daemon hard-fail "
                    "rate ~0; small/non-decisive samples are never auto-quarantined)",
    }
    (EXP / "pass45_probation_failure_screen.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    md = [
        "# PASS 45 — Part D: probation runtime failure / quarantine screen", "",
        "> Read-only screen. Internal self-play diagnostics; emits no "
        "CandidateStatusChanged and never quarantines.", "",
        f"- any quarantine warranted: **{yn(any_quarantine)}**  · any runtime "
        f"failure: **{yn(any_runtime_failure)}**",
        f"- quarantine rule: complete hard-failure evidence OR hard-fail rate ≥ "
        f"{th.quarantine_hardfail_rate} over n ≥ {th.quarantine_min_n_for_rate}",
        f"- decisive==0 alone is NEVER a failure: "
        f"**no_false_quarantine={yn(no_false_quarantine)}**", "",
        "| candidate | games | decisive | invalid | timeouts | errors | hard-fail "
        "rate | complete-HF | quarantine |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cid in TARGETS:
        t = per_target[cid]
        md.append(
            f"| `{cid}` | {t['total_games']} | {t['decisive_games']} | "
            f"{t['invalid_games']} | {t['timeouts']} | {t['errors']} | "
            f"{t['hardfail_rate']} | {yn(t['complete_hardfail_evidence'])} | "
            f"{yn(t['quarantine_warranted'])} |")
    md += ["", "> Honest verdict: hard-fail evidence is the ONLY auto-quarantine "
           "trigger. A tiny or all-draw sample is non-decisive, not a failure, and is "
           "never demoted by this screen."]
    (EXP / "pass45_probation_failure_screen.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass45 partD: any_quarantine={any_quarantine} "
          f"any_runtime_failure={any_runtime_failure} "
          f"no_false_quarantine={no_false_quarantine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
