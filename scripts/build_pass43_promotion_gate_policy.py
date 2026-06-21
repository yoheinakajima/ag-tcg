#!/usr/bin/env python3
"""PASS 43 — Part F: emit the machine-readable Promotion Gate v1 policy.

Single source of truth for the locked thresholds is
``ptcg_activegraph.tournament.promotion.DEFAULT_THRESHOLDS``; this script serialises
them (plus the action set and rule summary) so the policy artifact can never drift
from the evaluator. Writes data/experiments/pass43_promotion_gate_policy.{json,md}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import promotion  # noqa: E402

EXP = REPO / "data" / "experiments"

ACTIONS = {
    promotion.STAY_PROBATION: "Keep on probation; not enough evidence or margin to act.",
    promotion.ACTIVATE: "probation → active: all activate gates pass.",
    promotion.PROMOTE_FAMILY_CHAMPION: "active → family_champion: stricter gate passes.",
    promotion.RETIRE_TO_RETIRED: "→ retired: clearly underperforms parent over adequate N.",
    promotion.QUARANTINE: "→ quarantined: complete/high hard-failure evidence.",
    promotion.INSUFFICIENT_EVIDENCE: "Not enough games/anchor/parent H2H to decide.",
    promotion.BLOCKED_PROTECTED_STATUS: "Protected (champion/anchor/held_probe); never demoted.",
    promotion.BLOCKED_INVALIDITY: "retired/quarantined/special_pilot_only/invalid; not a subject.",
    promotion.BLOCKED_PUBLIC_REFERENCE: "Public reference; benchmark-only, never promoted.",
}

RULES = {
    "raw_winrate_never_promotes": True,
    "activate": [
        "status == probation",
        "internal/generated (not a public reference)",
        "deck-delta OR non-inertness proven",
        "total_games >= activate_min_total_games",
        "decisive_games >= activate_min_decisive_games",
        "anchor_games >= activate_min_anchor_games and anchor_decisive >= "
        "activate_min_anchor_decisive",
        "parent H2H games >= activate_min_parent_h2h_games with seat balance "
        "(weaker seat >= activate_min_parent_seat_fraction of H2H, both seats > 0)",
        "(invalid+timeout+error)/games <= max_hardfail_rate",
        "AGGREGATE Wilson lower bound >= parent_baseline + activate_wilson_margin",
        "DIRECT parent-H2H Wilson lower bound >= parent_baseline + "
        "activate_wilson_margin (must beat the parent head-to-head, not out-farm "
        "weaker opponents in the aggregate)",
        "anchor Wilson lower bound >= parent_baseline - anchor_noninferior_margin",
    ],
    "promote_family_champion": [
        "status == active",
        "total_games >= champion_min_total_games",
        "parent H2H + family games >= champion_min_parent_family_games",
        "anchor_games >= champion_min_anchor_games",
        "a current family-champion baseline exists",
        "AGGREGATE Wilson lower bound >= champion baseline + champion_margin",
        "DIRECT champion-H2H decisive games >= champion_min_h2h_games AND "
        "champion-H2H Wilson lower bound >= parent_baseline + champion_margin "
        "(must beat the incumbent champion head-to-head; never crowned over an "
        "incumbent it never beat or never played)",
        "deck-delta OR non-inertness proven",
    ],
    "retire_to_retired": [
        "not a protected status",
        "full activate-level evidence accrued",
        "Wilson upper bound < parent_baseline - retire_wilson_high_margin "
        "(clearly worse than parent)",
    ],
    "quarantine": [
        "complete hard-failure evidence (invalid == games, games > 0), OR",
        "hard-fail rate >= quarantine_hardfail_rate over n >= "
        "quarantine_min_n_for_rate",
        "draws are non-decisive but are NOT failures",
    ],
    "never": [
        "delete or overwrite a tarball",
        "demote a protected status",
        "promote a public reference / let a reference enter the subject set",
        "emit CandidatePromoted / SubmissionQueued / SubmissionUploaded / "
        "KaggleScoreUpdated",
        "promote on raw win-rate alone",
    ],
}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    th = promotion.DEFAULT_THRESHOLDS
    policy = {
        "pass": "pass43_promotion_gate_policy",
        "version": "v1",
        "caveat": promotion._INTERNAL_CAVEAT,
        "thresholds": th.to_policy(),
        "actions": ACTIONS,
        "actionable_actions": sorted(promotion.ACTIONABLE),
        "action_to_status": promotion.ACTION_TO_STATUS,
        "rules": RULES,
    }
    (EXP / "pass43_promotion_gate_policy.json").write_text(
        json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    md = ["# PASS 43 — Promotion Gate v1 policy", "",
          f"> {policy['caveat']}", "",
          "## Thresholds (locked v1)", "",
          "| key | value |", "|---|---|"]
    for k, v in th.to_policy().items():
        md.append(f"| `{k}` | {v} |")
    md += ["", "## Actions", "", "| action | meaning | emits status change? |",
           "|---|---|---|"]
    for a, desc in ACTIONS.items():
        md.append(f"| `{a}` | {desc} | "
                  f"{'yes' if a in promotion.ACTIONABLE else 'no'} |")
    md += ["", "## Rule summary", ""]
    for name, items in RULES.items():
        if isinstance(items, bool):
            md.append(f"- **{name}**: {items}")
            continue
        md.append(f"- **{name}**:")
        md += [f"  - {it}" for it in items]
    (EXP / "pass43_promotion_gate_policy.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print("pass43 promotion gate policy written "
          f"({len(th.to_policy())} thresholds, {len(ACTIONS)} actions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
