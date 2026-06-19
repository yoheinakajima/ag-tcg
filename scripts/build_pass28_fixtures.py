#!/usr/bin/env python3
"""Pass 28 (Part I) — core gameplay fixture backlog. LOCAL/READ-ONLY.

Creates a fixture backlog for high/medium-confidence gaps. Per the spec, fixtures
are marked executable_now ONLY if a reduced model can faithfully represent the
issue; the Pass-28 gaps are engine/effect-coupled and cannot be faithfully reduced
without the full simulator, so they are planned (not executable) with reasons.
Writes data/fixtures/pass28_core_gameplay_backlog.{yaml,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PRIO = EXP / "pass28_core_gap_priority.json"
FIX_DIR = REPO / "data" / "fixtures"
OUT_YAML = FIX_DIR / "pass28_core_gameplay_backlog.yaml"
OUT_MD = FIX_DIR / "pass28_core_gameplay_backlog.md"


def main() -> int:
    prio = json.loads(PRIO.read_text(encoding="utf-8"))
    by_id = {g["gap_id"]: g for g in prio["gaps_ranked"]}

    fixtures = [
        {
            "fixture_id": "fx_effect_loop_termination",
            "gap_id": "effect_loop_termination",
            "candidate_source_deck": "league_mega_venusaur_tank",
            "source_run_replay_step": ("pass28_action_trace.jsonl: "
                                       "candidate_id=league_mega_venusaur_tank, "
                                       "select_context in {33,21} (~1957 repeats/game)"),
            "reduced_model": ("a board where an optional/forced effect (context 33, "
                              "single type-6 option) re-presents indefinitely; agent "
                              "must reach a terminating choice"),
            "expected_behavior": ("pilot exits the repeated effect within a bounded "
                                  "number of iterations and proceeds to attack"),
            "required_resolver_support": ("effect-loop / repeated-context termination "
                                          "policy; ability-activation budget"),
            "executable_now": False,
            "why_blocked": ("the loop is produced by the live cabt effect engine; a "
                            "faithful reduced model needs the engine's effect-context "
                            "state machine, which is not available standalone"),
            "priority": "high",
            "deck_scope": "deck-specific (venusaur), but termination policy is generic",
        },
        {
            "fixture_id": "fx_mill_deckout_init_legality",
            "gap_id": "mill_deckout_unsupported",
            "candidate_source_deck": "league_durant_deckout_carousel",
            "source_run_replay_step": ("pass28_diagnostic_trace.json: durant__self, "
                                       "step 1 INVALID, 0 gameplay decisions"),
            "reduced_model": ("submit the Durant deck and assert the engine reaches a "
                              "legal turn-1 state (or capture the exact init rejection)"),
            "expected_behavior": ("deck passes engine init and reaches turn 1 so a mill "
                                  "line can be attempted"),
            "required_resolver_support": ("engine init-legality diagnostics + a special "
                                          "deckout pilot once init passes"),
            "executable_now": False,
            "why_blocked": ("the engine rejects at init without surfacing a reason to "
                            "the agent observation; cannot faithfully reduce the cause "
                            "without engine-internal validation output"),
            "priority": "high",
            "deck_scope": "deck-specific (durant)",
        },
        {
            "fixture_id": "fx_ramp_sequencing",
            "gap_id": "ramp_sequencing",
            "candidate_source_deck": "league_mega_gardevoir_psychic_ramp",
            "source_run_replay_step": ("pass28_action_trace.jsonl: "
                                       "candidate_id=league_mega_gardevoir_psychic_ramp "
                                       "(low attach + low in_play_action counts)"),
            "reduced_model": ("board with energy in discard and a ramp ability "
                              "available; agent should use the ability to re-attach"),
            "expected_behavior": ("pilot activates the from-discard ramp before/with "
                                  "attacking to power a bigger attack"),
            "required_resolver_support": ("ability-driven energy re-attachment "
                                          "recognition in the option resolver"),
            "executable_now": False,
            "why_blocked": ("ramp is an ability whose option is not surfaced with "
                            "resolvable identity; faithful reduction needs the engine's "
                            "ability-option encoding"),
            "priority": "medium",
            "deck_scope": "deck-specific (gardevoir)",
        },
        {
            "fixture_id": "fx_evolution_sequencing_speed",
            "gap_id": "evolution_sequencing_speed",
            "candidate_source_deck": "league_mega_charizard_x_burst",
            "source_run_replay_step": ("pass28_action_trace.jsonl: "
                                       "candidate_id=league_mega_charizard_x_burst, "
                                       "first attack median step 6 / min 4, with a long "
                                       "tail of stalled games (~turn 33)"),
            "reduced_model": ("Stage-2/Mega line in hand/bench; agent should complete "
                              "the line (Rare Candy if present) by a target turn"),
            "expected_behavior": ("evolution completes earlier so the first attack "
                                  "lands closer to aggro tempo"),
            "required_resolver_support": ("evolution-path planning + Rare Candy "
                                          "recognition (play_from_hand identity)"),
            "executable_now": False,
            "why_blocked": ("Rare Candy / evolution plays are not resolved in the "
                            "play_from_hand option schema, so the model cannot faithfully "
                            "represent the sequencing decision yet"),
            "priority": "medium",
            "deck_scope": "partial (Mega/Stage-2 decks)",
        },
    ]
    # Attach the gap confidence for traceability.
    for fx in fixtures:
        g = by_id.get(fx["gap_id"], {})
        fx["gap_confidence"] = g.get("confidence")

    out = {
        "schema": "activegraph.pass28.core_gameplay_backlog/v1",
        "pass": "28", "part": "I",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "note": ("Fixtures are PLANNED, not executable: every Pass-28 gap is coupled to "
                 "the live cabt effect/option engine and cannot be faithfully reduced to "
                 "a standalone fixture yet. Each item references its trace evidence."),
        "executable_now_count": sum(1 for f in fixtures if f["executable_now"]),
        "planned_count": sum(1 for f in fixtures if not f["executable_now"]),
        "fixtures": fixtures,
    }
    FIX_DIR.mkdir(parents=True, exist_ok=True)
    OUT_YAML.write_text(yaml.safe_dump(out, sort_keys=False), encoding="utf-8")

    L = ["# Pass 28 — Core Gameplay Fixture Backlog (Part I)", "",
         f"> {out['note']}", "",
         f"- executable_now: {out['executable_now_count']}  "
         f"planned: {out['planned_count']}", ""]
    for fx in fixtures:
        L += [f"## {fx['fixture_id']} ({fx['priority']}, {fx['gap_confidence']})",
              f"- gap: {fx['gap_id']}",
              f"- source deck: {fx['candidate_source_deck']}",
              f"- source step: {fx['source_run_replay_step']}",
              f"- reduced model: {fx['reduced_model']}",
              f"- expected behavior: {fx['expected_behavior']}",
              f"- required resolver support: {fx['required_resolver_support']}",
              f"- executable_now: {fx['executable_now']}",
              f"- why blocked: {fx['why_blocked']}",
              f"- deck scope: {fx['deck_scope']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"fixtures: {len(fixtures)} planned={out['planned_count']} "
          f"executable={out['executable_now_count']} -> {OUT_YAML.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
