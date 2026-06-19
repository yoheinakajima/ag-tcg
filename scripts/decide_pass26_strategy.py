#!/usr/bin/env python3
"""Pass 26 — Part M: record the honest strategy decision.

Reads the trigger-coverage gate, the candidate manifest, and the live-score
status, then records the decision from the allowed label set. Because NO class
clears the Part-G gate the decision is ``no_build_no_trigger``. The
``future_kaggle_probe_candidate`` label is explicitly forbidden here: it requires
a hook that passed trigger coverage AND a built+validated candidate AND a
decision replay with nonzero on-seam deltas -- none of which exist. No upload.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

ALLOWED_LABELS = [
    "no_build_no_trigger", "block_inert_hook", "keep_current_best",
    "candidate_for_deeper_confirmation", "future_kaggle_probe_candidate",
    "need_more_replays", "build_specific_hook_next", "no_action",
]


def main() -> int:
    gate = json.loads((EXP / "pass26_trigger_coverage.json").read_text("utf-8"))
    classes = json.loads(
        (EXP / "pass26_true_opportunity_classes.json").read_text("utf-8"))
    live = json.loads((EXP / "pass26_live_score_status.json").read_text("utf-8"))

    any_allowed = gate["any_build_allowed"]
    primary = "no_build_no_trigger" if not any_allowed else "build_specific_hook_next"
    assert primary in ALLOWED_LABELS

    decision = {
        "schema": "activegraph.pass26.strategy_decision/v1",
        "pass": 26,
        "primary_decision": primary,
        "secondary_decision": "keep_current_best",
        "allowed_labels": ALLOWED_LABELS,
        "current_best": live["water_family_current_best"]["fileName"],
        "live_score_leader": {
            "file": live["live_score_leader"]["fileName"],
            "publicScore": live["live_score_leader"]["publicScore"],
        },
        "water_family_current_best": {
            "file": live["water_family_current_best"]["fileName"],
            "publicScore": live["water_family_current_best"]["publicScore"],
        },
        "distinction_preserved": live["distinction_preserved"],
        "promote": False,
        "upload": False,
        "submit": False,
        "github_push": False,
        "future_kaggle_probe": False,
        "future_probe_forbidden_because": [
            "no hook passed Part-G trigger coverage",
            "no candidate was built or validated",
            "no decision replay (no candidate) -> no nonzero on-seam delta",
        ],
        "rationale": (
            "Across 1533 real our-seat Water decisions (15 minable episodes / 19 "
            "in corpus), no opportunity class clears the trigger-coverage gate. "
            "The Pass-25 deckout lever has ZERO low-deck windows; search-steering "
            "targets are hidden in the deck; the discard-preservation class has "
            "only 1 high-confidence loss window; every other class is broad-Main "
            "or already covered by the proven base. Building any guard would ship "
            "a hook that provably never fires on real evidence. The correct, "
            "honest action is to keep the current Water control and build nothing."
        ),
        "lesson": (
            "A trigger context occurring in replays is NOT the same as a hook "
            "being able to fire: Pass-25 guards were inert by PREDICATE-FAIL "
            "(deckout clamp only bites at deck<=8, but ctx38 only ever fires at "
            "deck=47) and HIDDEN-TARGET (search targets live in the unobservable "
            "deck), not by absence. Mine option-level legal alternatives before "
            "designing a hook."),
        "next_action": (
            "Keep league_water_anti_disruption_pivot_v1 as the live Water "
            "control; do not build, upload, or probe. Revisit only if replays "
            "containing genuine low-deck / observable-target windows are "
            "captured (label would become need_more_replays)."),
        "source": [
            "data/experiments/pass26_trigger_coverage.json",
            "data/experiments/pass26_true_opportunity_classes.json",
            "data/experiments/pass26_pass25_inert_hook_diagnosis.json",
        ],
        "no_upload": True,
    }

    (EXP / "pass26_strategy_decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8")

    md = [
        "# Pass 26 — Strategy Decision",
        "",
        f"## Primary decision: `{decision['primary_decision']}`",
        f"Secondary: `{decision['secondary_decision']}`",
        "",
        f"- current Water best / live control: "
        f"`{decision['current_best']}` @ "
        f"{decision['water_family_current_best']['publicScore']}",
        f"- live_score_leader: `{decision['live_score_leader']['file']}` @ "
        f"{decision['live_score_leader']['publicScore']}",
        f"- distinction preserved: {decision['distinction_preserved']}",
        "- promote / upload / submit / github_push / future_probe: "
        "**all False**",
        "",
        "### Why not `future_kaggle_probe_candidate`",
    ]
    md += [f"- {r}" for r in decision["future_probe_forbidden_because"]]
    md += ["", "### Rationale", decision["rationale"],
           "", "### Lesson", decision["lesson"],
           "", "### Next action", decision["next_action"],
           "", "_No upload. No GitHub push. `no_upload=true`._"]
    (EXP / "pass26_strategy_decision.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"strategy decision -> {decision['primary_decision']} "
          f"(future_probe={decision['future_kaggle_probe']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
