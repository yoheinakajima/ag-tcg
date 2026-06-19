#!/usr/bin/env python3
"""Pass 29 (Part I) — observability / fixture backlog. LOCAL / READ-ONLY.

Synthesises the Part F/G/H observability findings into a prioritised backlog of
fixtures, split into (a) executable NOW, (b) one cheap capture-ratchet away, and
(c) genuinely needs_more_observability. Data-driven from the analysis JSONs so it
never overclaims what is buildable.

Outputs data/fixtures/pass29_observability_backlog.{yaml,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
OUT_DIR = REPO / "data" / "fixtures"
OUT_YAML = OUT_DIR / "pass29_observability_backlog.yaml"
OUT_MD = OUT_DIR / "pass29_observability_backlog.md"


def _load(name):
    p = EXP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    feas = _load("pass29_effect_loop_feasibility.json")
    eval_ = _load("pass29_effect_loop_guard_eval.json")
    tgt = _load("pass29_target_observability.json")
    eng = _load("pass29_engine_card_observability.json")

    fixtures = [
        {
            "fixture_id": "effect_loop_exit_guard",
            "observability": "fully_observable",
            "executable_now": True,
            "status": "BUILT_AND_VALIDATED",
            "candidate": "effect_loop_exit_guard_v1",
            "evidence": ("exit option observable 1958/1958 at ctx0; eval verdict "
                         f"{eval_.get('verdict')}"),
            "priority": "P0",
        },
        {
            "fixture_id": "search_target_ctx7",
            "observability": "observable",
            "executable_now": True,
            "status": "ready_to_build",
            "evidence": ("search-to-hand (ctx7) target identity resolvable from "
                         "select.deck / candidate resolver"),
            "priority": "P1",
        },
        {
            "fixture_id": "single_target_attack",
            "observability": "one_capture_ratchet_away",
            "executable_now": False,
            "status": "blocked_on_cheap_capture",
            "evidence": ("attackId observable "
                         f"{tgt.get('attack_id_observable_fraction')}; defender "
                         "active identity captured as null in trace "
                         f"({tgt.get('defender_active_identity_observable_fraction')})"
                         " — exists in raw obs, add opponent_active to the snapshot"),
            "priority": "P1",
        },
        {
            "fixture_id": "spread_bench_target",
            "observability": "needs_more_observability",
            "executable_now": False,
            "status": "needs_more_observability",
            "evidence": ("opponent bench identity and per-target damage are wholly "
                         "unobserved; spread cannot be attributed to a bench slot"),
            "priority": "P2",
        },
        {
            "fixture_id": "supporter_effect_sequencing",
            "observability": "needs_more_observability",
            "executable_now": False,
            "status": "needs_more_observability",
            "evidence": ("supporter/Trainer effect OUTCOMES are not linked to the "
                         "play event; play_from_hand identity "
                         f"{eng.get('by_engine_class',{}).get('play_from_hand',{}).get('card_identity_observable_fraction')}"),
            "priority": "P2",
        },
        {
            "fixture_id": "in_play_action_source",
            "observability": "needs_more_observability",
            "executable_now": False,
            "status": "needs_more_observability",
            "evidence": ("in_play_action source Pokemon identity rarely resolvable "
                         f"({eng.get('by_engine_class',{}).get('in_play_action',{}).get('card_identity_observable_fraction')})"
                         "; this is the very loop-head action the guard now fences"),
            "priority": "P3",
        },
    ]

    doc = {
        "pass": "29", "part": "I",
        "note": "observability / fixture backlog; honestly split by what is "
                "executable now vs blocked on more observability",
        "feasibility_gate_passed": feas.get("gate_passes"),
        "summary": {
            "executable_now": sum(1 for f in fixtures if f["executable_now"]),
            "one_capture_away": sum(
                1 for f in fixtures if f["observability"] == "one_capture_ratchet_away"),
            "needs_more_observability": sum(
                1 for f in fixtures
                if f["observability"] == "needs_more_observability"),
            "total": len(fixtures),
        },
        "fixtures": fixtures,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        OUT_YAML.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    except Exception:
        OUT_YAML.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Observability / Fixture Backlog (Part I)", "",
         f"- Executable now: **{doc['summary']['executable_now']}**; one capture "
         f"away: **{doc['summary']['one_capture_away']}**; needs more "
         f"observability: **{doc['summary']['needs_more_observability']}**.", "",
         "| fixture | observability | executable now | status | priority |",
         "|---|---|---|---|---|"]
    for f in fixtures:
        L.append(f"| {f['fixture_id']} | {f['observability']} | "
                 f"{f['executable_now']} | {f['status']} | {f['priority']} |")
    L += ["", "## Evidence", ""]
    for f in fixtures:
        L.append(f"- **{f['fixture_id']}** — {f['evidence']}")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"backlog: {doc['summary']} -> {OUT_YAML.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
