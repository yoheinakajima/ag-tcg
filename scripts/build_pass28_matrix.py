#!/usr/bin/env python3
"""Pass 28 (Part G) — core mechanics coverage matrix (20 rows). LOCAL/READ-ONLY.

Derives support/observability for each of the 20 core mechanics from the Part-F
forensics + action trace. Columns per spec. Writes
data/experiments/pass28_mechanics_coverage_matrix.{json,md,csv}.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
FOREN = EXP / "pass28_deck_forensics.json"
OUT_JSON = EXP / "pass28_mechanics_coverage_matrix.json"
OUT_MD = EXP / "pass28_mechanics_coverage_matrix.md"
OUT_CSV = EXP / "pass28_mechanics_coverage_matrix.csv"

COLUMNS = ["id", "mechanic", "supported_by_current_core_pilot",
           "role_taxonomy_support", "runtime_context_observable", "fixture_exists",
           "evidence_decks", "failure_evidence_count", "confidence", "deck_agnostic",
           "next_action"]


def main() -> int:
    foren = json.loads(FOREN.read_text(encoding="utf-8"))
    fam = foren["families"]
    ev = {k: v.get("evidence", {}) for k, v in fam.items()}

    total_atk_not_taken = sum(e.get("attack_available_not_taken", 0)
                              for e in ev.values())
    total_off_plan = sum(e.get("attach_off_deck_plan", 0) for e in ev.values())
    venu_loop = max(ev["venusaur"].get("context_histogram", {}).values(), default=0)

    rows = [
        {"id": 1, "mechanic": "setup active choice",
         "supported_by_current_core_pilot": "yes", "role_taxonomy_support": "yes",
         "runtime_context_observable": "yes", "fixture_exists": "plan",
         "evidence_decks": "all 6 league decks reach turn 1; Durant fails at init",
         "failure_evidence_count": 0, "confidence": "high", "deck_agnostic": "yes",
         "next_action": "no_action"},
        {"id": 2, "mechanic": "setup bench",
         "supported_by_current_core_pilot": "yes", "role_taxonomy_support": "yes",
         "runtime_context_observable": "yes", "fixture_exists": "plan",
         "evidence_decks": "all (bench populated; place_card stream)",
         "failure_evidence_count": 0, "confidence": "high", "deck_agnostic": "yes",
         "next_action": "no_action"},
        {"id": 3, "mechanic": "backup maintenance",
         "supported_by_current_core_pilot": "yes", "role_taxonomy_support": "partial",
         "runtime_context_observable": "partial", "fixture_exists": "yes",
         "evidence_decks": "water (anti-disruption pivot); all keep bench",
         "failure_evidence_count": 0, "confidence": "medium", "deck_agnostic": "yes",
         "next_action": "no_action"},
        {"id": 4, "mechanic": "color-matched energy attachment",
         "supported_by_current_core_pilot": "yes", "role_taxonomy_support": "yes",
         "runtime_context_observable": "yes", "fixture_exists": "plan",
         "evidence_decks": "ALL — every attach is a deck-plan color "
         f"({total_off_plan} off-plan across all decks)",
         "failure_evidence_count": total_off_plan, "confidence": "high",
         "deck_agnostic": "yes",
         "next_action": "no_action"},
        {"id": 5, "mechanic": "attack pressure",
         "supported_by_current_core_pilot": "yes", "role_taxonomy_support": "yes",
         "runtime_context_observable": "yes", "fixture_exists": "plan",
         "evidence_decks": "ALL — attack taken every available turn "
         f"({total_atk_not_taken} attack-available-not-taken across all decks)",
         "failure_evidence_count": total_atk_not_taken, "confidence": "high",
         "deck_agnostic": "yes",
         "next_action": "no_action"},
        {"id": 6, "mechanic": "attack-target selection",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "all (attack options expose only attackId, no target)",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 7, "mechanic": "spread / bench damage targeting",
         "supported_by_current_core_pilot": "no", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "dragapult (attacks frequently; targets not surfaced)",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "no",
         "next_action": "gather_replays"},
        {"id": 8, "mechanic": "evolution sequencing",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "partial",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "charizard (first attack median step 6 / min 4 — on tempo in most games, long tail of stalled Mega-line games)",
         "failure_evidence_count": 1, "confidence": "medium", "deck_agnostic": "partial",
         "next_action": "gather_replays"},
        {"id": 9, "mechanic": "rare-candy evolution",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "charizard/venusaur (play_from_hand identity not resolved)",
         "failure_evidence_count": 0, "confidence": "unknown", "deck_agnostic": "partial",
         "next_action": "gather_replays"},
        {"id": 10, "mechanic": "search target planning",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "all (Ultra Ball/Nest seen as place_card; choice not surfaced)",
         "failure_evidence_count": 0, "confidence": "unknown", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 11, "mechanic": "discard safety",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "none directly observable",
         "failure_evidence_count": 0, "confidence": "unknown", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 12, "mechanic": "engine supporter play",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "partial",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "raging_bolt (Crispin not resolvable in play_from_hand)",
         "failure_evidence_count": 0, "confidence": "unknown", "deck_agnostic": "no",
         "next_action": "gather_replays"},
        {"id": 13, "mechanic": "Pokémon ability use",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "partial",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "venusaur (ability/effect LOOP ~"
         f"{venu_loop} iters); gardevoir (ramp ability under-used)",
         "failure_evidence_count": venu_loop, "confidence": "medium",
         "deck_agnostic": "no",
         "next_action": "deck_specific_playbook"},
        {"id": 14, "mechanic": "ramp sequencing",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "partial",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "gardevoir (only "
         f"{ev['gardevoir'].get('attach_count')} attaches; ramp barely used)",
         "failure_evidence_count": 1, "confidence": "medium", "deck_agnostic": "no",
         "next_action": "deck_specific_playbook"},
        {"id": 15, "mechanic": "deck conservation",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "deck_count tracked in board snapshots; no policy observed",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 16, "mechanic": "retreat/switch",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "partial",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "in_play_action present but switch choice not surfaced",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 17, "mechanic": "prize-race awareness",
         "supported_by_current_core_pilot": "no", "role_taxonomy_support": "no",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "prize_count in board snapshots; no policy observed",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 18, "mechanic": "lethal counting / all-in attack timing",
         "supported_by_current_core_pilot": "no", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "raging_bolt/charizard (energy-discard all-in not surfaced)",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "no",
         "next_action": "special_pilot_required"},
        {"id": 19, "mechanic": "recursion/recovery",
         "supported_by_current_core_pilot": "partial", "role_taxonomy_support": "no",
         "runtime_context_observable": "partial", "fixture_exists": "no",
         "evidence_decks": "raging_bolt (Night Stretcher placed); choice not surfaced",
         "failure_evidence_count": 0, "confidence": "low", "deck_agnostic": "yes",
         "next_action": "gather_replays"},
        {"id": 20, "mechanic": "mill/deckout win condition",
         "supported_by_current_core_pilot": "no", "role_taxonomy_support": "no",
         "runtime_context_observable": "no", "fixture_exists": "no",
         "evidence_decks": "durant (INVALID at init; never reaches a playable turn)",
         "failure_evidence_count": ev["durant"].get("invalid_games", 4),
         "confidence": "high", "deck_agnostic": "no",
         "next_action": "special_pilot_required"},
    ]
    assert len(rows) == 20, "matrix must have exactly 20 mechanic rows"

    def tally(col, val):
        return sum(1 for r in rows if r[col] == val)

    out = {
        "pass": "28", "part": "G",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "row_count": len(rows),
        "summary": {
            "supported": tally("supported_by_current_core_pilot", "yes"),
            "partial": tally("supported_by_current_core_pilot", "partial"),
            "unsupported": tally("supported_by_current_core_pilot", "no"),
        },
        "note": ("'supported' is judged from RECORDED ACTIONS, not win rate. Many "
                 "mechanics are 'partial' because the pilot's option schema does not "
                 "surface the choice (observability limit), NOT because it is proven "
                 "broken. Color-matched energy (#4) and attack pressure (#5) are "
                 "SUPPORTED positive controls that refute the Pass-27 color hypothesis."),
        "columns": COLUMNS,
        "rows": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    OUT_CSV.write_text(sio.getvalue(), encoding="utf-8")

    L = ["# Pass 28 — Core Mechanics Coverage Matrix (Part G)", "",
         f"> 20 mechanics. supported={out['summary']['supported']} "
         f"partial={out['summary']['partial']} unsupported={out['summary']['unsupported']}. "
         "Judged from recorded actions, not win rate.", "",
         f"- {out['note']}", "",
         "| # | mechanic | supported | role_tax | observable | fixture | "
         "fail_evidence | confidence | agnostic | next_action |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['id']} | {r['mechanic']} | "
                 f"{r['supported_by_current_core_pilot']} | {r['role_taxonomy_support']} "
                 f"| {r['runtime_context_observable']} | {r['fixture_exists']} | "
                 f"{r['failure_evidence_count']} | {r['confidence']} | "
                 f"{r['deck_agnostic']} | {r['next_action']} |")
    L += ["", "## Evidence decks per mechanic", ""]
    for r in rows:
        L.append(f"- **{r['id']}. {r['mechanic']}** — {r['evidence_decks']}")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"matrix: {len(rows)} rows supported={out['summary']['supported']} "
          f"partial={out['summary']['partial']} "
          f"unsupported={out['summary']['unsupported']} -> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
