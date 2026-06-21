#!/usr/bin/env python3
"""PASS 46F (Part I) — deterministic STRATEGY DECISION from the pre-registered gates.

Consumes the immutable Part-A..H artifacts and applies a fixed, pre-registered gate
ladder to emit exactly one decision state (LOCAL-ONLY; no promotion/upload of any
kind is implied by any outcome):

  unsafe_stop                                — a HARD safety/charter invariant failed.
  validation_failed                          — candidate not runnable / not non-inert.
  turnplanner_candidate_promising_local_only — edges its INTERNAL parent (Wilson lower
                                               > 0.5, BOTH seats, n>=20) AND the
                                               self-mirror null corroborates (Fisher).
  not_promising                              — candidate is decisively WORSE than parent
                                               (H2H Wilson upper < 0.5).
  insufficient_evidence                      — safe + runnable + non-inert, but the H2H
                                               edge is not resolvable at this sample.

Gate ladder (first failing/decisive gate wins):
  1. SAFETY (HARD): preflight.all_ok & validation.all_ok & root main.py/deck.csv
     unchanged across every lane & no forbidden events (local + prod scan) & public
     references benchmark-only (not source/parent/candidate, not in pool, not
     promotion-relevant).
  2. RUNNABILITY: smoke.ok & not smoke.hard_fail & 0 import/deck failures &
     non_inertness verdict == "non_inert_and_safe".
  3. STRENGTH: promising iff parent_h2h.edges_parent_local_only AND
     noise_control.noise_control_corroborates == "yes".
  4. WORSE: not_promising iff parent_h2h overall Wilson upper < 0.5.
  5. else insufficient_evidence.

NO online Search in any live hot path is asserted by construction (the candidate's
scorer is the OFFLINE-calibrated fast scorer; this script makes NO Kaggle/strength
claims beyond the local H2H reading). No exact-damage/lethal/missed-KO/Boss-gust/
spread/best-action claims.

Outputs: data/experiments/pass46f_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"


def _load(name: str) -> dict:
    p = EXP / f"pass46f_{name}.json"
    if not p.is_file():
        raise SystemExit(f"missing required artifact: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _gate(name: str, ok: bool, detail: dict) -> dict:
    return {"gate": name, "pass": bool(ok), **detail}


def main() -> int:
    pf = _load("safety_preflight")
    va = _load("candidate_validation")
    sm = _load("candidate_smoke")
    ni = _load("non_inertness")
    h = _load("parent_h2h")
    nc = _load("noise_control")
    rf = _load("public_reference_eval")

    # ---- Gate 1: SAFETY (HARD) --------------------------------------------
    root_ok = all(bool(x.get("root_main_deck_unchanged"))
                  for x in (sm, h, nc, rf))
    local_forbidden = pf.get("forbidden_events_in_local_ledger") or []
    prod_scan = pf.get("prod_ledger_scan") or {}
    prod_forbidden = prod_scan.get("forbidden_events") or prod_scan.get("forbidden") or []
    refs_pool_clean = bool(rf.get("references_not_in_pool", {}).get("clean"))
    refs_benchmark_only = bool(rf.get("benchmark_only")) and not bool(
        rf.get("promotion_relevant")) and not bool(
        rf.get("references_as_source_parent_candidate"))
    safety_ok = bool(
        pf.get("all_ok") and va.get("all_ok") and root_ok
        and not local_forbidden and not prod_forbidden
        and refs_pool_clean and refs_benchmark_only
        and not pf.get("production_mutated") and not va.get("production_mutated")
        and not sm.get("upload_performed"))
    g_safety = _gate("safety", safety_ok, {
        "preflight_all_ok": bool(pf.get("all_ok")),
        "validation_all_ok": bool(va.get("all_ok")),
        "root_main_deck_unchanged": root_ok,
        "no_forbidden_events_local": not local_forbidden,
        "no_forbidden_events_prod": not prod_forbidden,
        "references_not_in_pool": refs_pool_clean,
        "references_benchmark_only": refs_benchmark_only})

    # ---- Gate 2: RUNNABILITY ----------------------------------------------
    runnable_ok = bool(
        sm.get("ok") and not sm.get("hard_fail")
        and int(sm.get("import_or_deck_failures", 0)) == 0
        and ni.get("verdict") == "non_inert_and_safe"
        and ni.get("non_inert") and ni.get("safe"))
    g_runnable = _gate("runnability", runnable_ok, {
        "smoke_ok": bool(sm.get("ok")), "smoke_hard_fail": bool(sm.get("hard_fail")),
        "import_or_deck_failures": int(sm.get("import_or_deck_failures", 0)),
        "non_inertness_verdict": ni.get("verdict")})

    # ---- Gate 3 / 4: STRENGTH ---------------------------------------------
    overall = h.get("overall", {})
    ci = overall.get("wilson95") or [None, None]
    edges_parent = bool(h.get("edges_parent_local_only"))
    corroborates = nc.get("noise_control_corroborates")
    promising_ok = bool(edges_parent and corroborates == "yes")
    worse = bool(ci[1] is not None and ci[1] < 0.5)
    g_strength = _gate("strength", promising_ok, {
        "h2h_decisive_win_rate": overall.get("decisive_win_rate"),
        "h2h_wilson95": ci, "h2h_decisive_n": overall.get("decisive"),
        "edges_parent_local_only": edges_parent,
        "both_seats_winning": bool(h.get("both_seats_winning")),
        "noise_control_corroborates": corroborates,
        "demonstrably_worse": worse})

    # ---- Decision ladder ---------------------------------------------------
    if not safety_ok:
        decision = "unsafe_stop"
    elif not runnable_ok:
        decision = "validation_failed"
    elif promising_ok:
        decision = "turnplanner_candidate_promising_local_only"
    elif worse:
        decision = "not_promising"
    else:
        decision = "insufficient_evidence"

    rationale = {
        "unsafe_stop": "A hard safety/charter invariant failed; stop the pass.",
        "validation_failed": "Candidate not runnable or not non-inert.",
        "turnplanner_candidate_promising_local_only":
            "Candidate edges its internal parent (Wilson lower > 0.5, both seats, "
            "n>=20) and the self-mirror null corroborates — promising as LOCAL-ONLY "
            "turn-planner infrastructure (NOT a promotion, NOT a Kaggle claim).",
        "not_promising": "Candidate is decisively worse than its parent (H2H Wilson "
                         "upper < 0.5).",
        "insufficient_evidence":
            "Candidate is SAFE, RUNNABLE and NON-INERT, and its offline search-"
            "calibrated fast scorer drives a distinct legal policy, but the local "
            "H2H edge over its parent is not statistically resolvable at this sample "
            "(Wilson CI straddles 0.50; Fisher vs the self-mirror null is "
            "inconclusive). No promotion, no upload; more games or a stronger "
            "calibration would be required to demonstrate a live edge.",
    }[decision]

    out = {
        "pass": "46f", "part": "I", "kind": "strategy_decision",
        "candidate_id": h.get("candidate_id"), "parent_id": h.get("parent_id"),
        "local_only": True, "no_upload": True, "upload_performed": False,
        "promotion_performed": False,
        "decision": decision, "rationale": rationale,
        "gates": [g_safety, g_runnable, g_strength],
        "evidence": {
            "parent_h2h": {"decisive_win_rate": overall.get("decisive_win_rate"),
                           "wilson95": ci, "n": overall.get("decisive"),
                           "by_seat": h.get("by_seat"),
                           "both_seats_winning": bool(h.get("both_seats_winning"))},
            "noise_control": {"corroborates": corroborates,
                              "controls_clean": bool(nc.get("controls_clean")),
                              "fisher_h2h_vs_mirror_p": nc.get("fisher_h2h_vs_mirror_p")},
            "internal_anchor": _load("internal_anchor_eval").get("overall"),
            "public_reference_benchmark_only": {
                "pooled_win_rate": rf.get("pooled", {}).get("decisive_win_rate"),
                "promotion_relevant": False, "in_pool": not refs_pool_clean}},
        "note": "LOCAL-ONLY decision. No CandidatePromoted/SubmissionQueued/"
                "SubmissionUploaded/KaggleScoreUpdated implied. Public references are "
                "benchmark-only and never source/parent/candidate. No exact-damage/"
                "lethal/missed-KO/Boss-gust/spread/best-action claims.",
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46f_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    def yn(v):
        return "yes" if v else "no"
    md = [
        "# Pass 46F (Part I) — Strategy Decision", "",
        f"## DECISION: `{decision}`", "",
        f"> {rationale}", "",
        "**LOCAL-ONLY.** No promotion, no upload, no Kaggle claim. Public references "
        "are benchmark-only (never source/parent/candidate, never in pool). No exact-"
        "damage/lethal/missed-KO/Boss-gust/spread/best-action claims.", "",
        "### Pre-registered gate ladder",
        "| gate | pass | key inputs |", "|---|---|---|",
        f"| safety (HARD) | {yn(g_safety['pass'])} | preflight={yn(g_safety['preflight_all_ok'])}, "
        f"validation={yn(g_safety['validation_all_ok'])}, root unchanged={yn(root_ok)}, "
        f"no forbidden events={yn(g_safety['no_forbidden_events_local'] and g_safety['no_forbidden_events_prod'])}, "
        f"refs benchmark-only & not in pool={yn(refs_benchmark_only and refs_pool_clean)} |",
        f"| runnability | {yn(g_runnable['pass'])} | smoke ok={yn(g_runnable['smoke_ok'])}, "
        f"hard_fail={yn(g_runnable['smoke_hard_fail'])}, import/deck fails="
        f"{g_runnable['import_or_deck_failures']}, non-inertness={g_runnable['non_inertness_verdict']} |",
        f"| strength (promising?) | {yn(g_strength['pass'])} | H2H WR="
        f"{g_strength['h2h_decisive_win_rate']} {g_strength['h2h_wilson95']} "
        f"(n={g_strength['h2h_decisive_n']}), both seats={yn(g_strength['both_seats_winning'])}, "
        f"edges parent={yn(edges_parent)}, noise corroborates={corroborates}, "
        f"demonstrably worse={yn(worse)} |", "",
        "### Evidence summary",
        f"- parent H2H (internal `{h.get('parent_id')}`): "
        f"**{overall.get('decisive_win_rate')} {ci}** (n={overall.get('decisive')}); "
        f"seat0={h.get('by_seat',{}).get('seat0',{}).get('decisive_win_rate')}, "
        f"seat1={h.get('by_seat',{}).get('seat1',{}).get('decisive_win_rate')}",
        f"- self-mirror noise control: corroborates **{corroborates}** "
        f"(controls clean={yn(nc.get('controls_clean'))}, "
        f"Fisher pooled p={nc.get('fisher_h2h_vs_mirror_p',{}).get('pooled_mirror')})",
        f"- internal water anchor: "
        f"{_load('internal_anchor_eval').get('overall',{}).get('decisive_win_rate')} "
        "(supportive context only)",
        f"- public references (BENCHMARK-ONLY): pooled WR "
        f"{rf.get('pooled',{}).get('decisive_win_rate')} — **never** a promotion signal",
        "", f"- root main.py/deck.csv unchanged: **{yn(root_ok)}** · no_upload: yes · "
        "local_only: yes", ""]
    (EXP / "pass46f_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"DECISION: {decision}")
    print(f"  safety={safety_ok} runnable={runnable_ok} promising={promising_ok} worse={worse}")
    print(f"  H2H={overall.get('decisive_win_rate')} {ci} n={overall.get('decisive')} "
          f"both_seats={h.get('both_seats_winning')} corroborates={corroborates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
