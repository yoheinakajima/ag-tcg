#!/usr/bin/env python3
"""Pass 8 effect-resolution fixtures derived from Kaggle episode 80374966.

This freezes the *real* decision prompts that the replay analysis flagged as the
true failure regime (effect-resolution safety: Ultra Ball / Secret Box / Mega
Signal / deckout), turning each into a deterministic, machine-checkable fixture.

Every card id used is confirmed against ``data/cards/EN_Card_Data.csv`` and the
replay's own resolved options (no invented ids). Where the engine's intent
cannot be proven from the schema (the Secret Box *pre-play* decision), the
fixture is recorded as a documented, non-gradeable seam rather than a fabricated
graded check.

Each fixture carries a ``severity``:

* ``hard``     — a safety check; a policy candidate that *fails* its preference
                 here is blocked from promotion (in addition to the always-hard
                 legality gate). These encode the exact mistakes that lost the
                 replayed game.
* ``advisory`` — a role/quality preference; failures are reported, never block.

The special ``secret_box_forced_discard_all`` fixture is ``forced_all`` and can
never be a failure (minCount == maxCount == n_options, so the only legal
selection is all options).

Output (LOCAL ONLY; never mutates root main.py / deck.csv):
    data/fixtures/replay_80374966_effect_resolution.json   (combined)
    data/fixtures/replay_80374966_effect_resolution.md

Usage:
    python scripts/extract_pass8_fixtures.py
    python scripts/extract_pass8_fixtures.py --replay data/replays/80374966.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from extract_replay_fixtures import build_fixture
from ptcg_activegraph.replays.analyzers import (
    KYOGRE,
    MEGA_ABOMASNOW,
    SNOVER,
)
from ptcg_activegraph.replays.kaggle_replay import load_replay

DEFAULT_REPLAY = "data/replays/80374966.json"
DEFAULT_OUT_JSON = "data/fixtures/replay_80374966_effect_resolution.json"
DEFAULT_OUT_MD = "data/fixtures/replay_80374966_effect_resolution.md"

# Confirmed card ids (EN_Card_Data.csv + replay resolved options).
SECRET_BOX = 1092
ULTRA_BALL = 1121
MEGA_SIGNAL = 1145
POWERGLASS = 1163
LILLIE = 1227
PETREL = 1219
SURFING_BEACH = 1262
SETUP_POKEMON_IDS = sorted({KYOGRE, SNOVER, MEGA_ABOMASNOW})

# ---------------------------------------------------------------------------
# Extractable fixture targets (each names a real (step, seat) decision).
# ---------------------------------------------------------------------------
PASS8_TARGETS: list[dict] = [
    {
        "id": "ultra_ball_discard_energy_safe",
        "spec_case": "ultra_ball_discard_energy_safe",
        "step": 28,
        "seat": 0,
        "context_name": "discard",
        "severity": "hard",
        "nuance": (
            "Ultra Ball cost: discard 2 of 6 hand cards. Options include three "
            "Basic {W} Energy (3) as safe fodder alongside a setup Mega "
            "Abomasnow ex (723). The replay discarded the Mega (a setup piece) "
            "while energy fodder was available — the discard that bricked the "
            "Snover line. Safe energy discards must be preferred over setup "
            "Pokemon."
        ),
        "preference": {
            "kind": "avoid_cards",
            "cards": SETUP_POKEMON_IDS,
            "reason": (
                "setup Pokemon (Kyogre 721 / Snover 722 / Mega Abomasnow 723) "
                "must not be paid as Ultra Ball's discard cost while Basic {W} "
                "Energy (3) fodder is available."
            ),
        },
    },
    {
        "id": "ultra_ball_search_missing_basic_or_evolution",
        "spec_case": "ultra_ball_search_missing_basic_or_evolution",
        "step": 9,
        "seat": 0,
        "context_name": "search_to_hand",
        "severity": "advisory",
        "nuance": (
            "Ultra Ball search-to-hand with Snover (722) / Kyogre (721) / Mega "
            "Abomasnow ex (723) all available and no Snover on board (active "
            "Kyogre only). Fetching a Mega with no Snover line to evolve from "
            "is a dead draw; the basic Snover/Kyogre line should be taken "
            "first. minCount 0 so declining is also legal."
        ),
        "preference": {
            "kind": "avoid_cards",
            "cards": [MEGA_ABOMASNOW],
            "reason": (
                "no Snover (722) is on the board, so taking Mega Abomasnow ex "
                "(723) here fetches an orphan evolution; prefer the Snover/"
                "Kyogre basics."
            ),
        },
    },
    {
        "id": "secret_box_forced_discard_all",
        "spec_case": "secret_box_forced_discard_all",
        "step": 11,
        "seat": 0,
        "context_name": "discard",
        "severity": "hard",
        "nuance": (
            "Secret Box discard with minCount == maxCount == n_options == 3: "
            "the only legal selection is all three options, so the Snover (722) "
            "among them cannot be spared. This is a FORCED discard, classified "
            "forced_all / na — NEVER a policy failure. The real 'should Secret "
            "Box have been played' seam is a pre-play decision the in-resolution "
            "fixtures cannot represent (see secret_box_play_safety)."
        ),
        "preference": {
            "kind": "forced_all",
            "reason": (
                "minCount equals the number of options; the discard set is "
                "forced and no avoidance is possible (na, never a failure)."
            ),
        },
    },
    {
        "id": "secret_box_to_hand_coherent_package",
        "spec_case": "secret_box_to_hand_coherent_package",
        "step": 12,
        "seat": 0,
        "context_name": "search_to_hand",
        "severity": "advisory",
        "nuance": (
            "Secret Box search-to-hand: options are Mega Signal (1145) and "
            "Ultra Ball (1121) with no Snover line on board (active Kyogre) and "
            "a healthy deck (45). Mega Signal only advances a Snover line that "
            "does not yet exist, so it would set up an orphan Mega; a flexible "
            "Ultra Ball is the more coherent pick here. Full coherent-package "
            "reasoning (Powerglass when an attacker has no tool; Lillie/Petrel "
            "only when deck is healthy; avoid redundant stadium) spans the "
            "step 12-15 pick sequence; this fixture grades the orphan-Mega "
            "Signal half deterministically."
        ),
        "preference": {
            "kind": "avoid_cards",
            "cards": [MEGA_SIGNAL],
            "reason": (
                "no Snover (722) line exists, so taking Mega Signal (1145) here "
                "commits to an orphan Mega package; prefer the flexible Ultra "
                "Ball (1121)."
            ),
        },
    },
    {
        "id": "mega_signal_no_orphan_mega",
        "spec_case": "mega_signal_no_orphan_mega",
        "step": 17,
        "seat": 0,
        "context_name": "search_to_hand",
        "severity": "hard",
        "nuance": (
            "Mega Signal search where all three options resolve to Mega "
            "Abomasnow ex (723) and no Snover (722) is on the board. Fetching a "
            "Mega with no Snover line to evolve from is a dead draw; minCount 0 "
            "so the safe play is to decline. The replay took the orphan Mega "
            "(flagged fetched_mega_without_snover_line)."
        ),
        "preference": {
            "kind": "decline",
            "reason": (
                "every option is Mega Abomasnow ex (723) and the board has no "
                "Snover (722) to evolve from; minCount is 0 so declining is "
                "legal and avoids a dead fetch."
            ),
        },
    },
    {
        "id": "deckout_guard_low_deck",
        "spec_case": "deckout_guard_low_deck",
        "step": 112,
        "seat": 0,
        "context_name": "search_to_hand",
        "severity": "hard",
        "nuance": (
            "Team Rocket's Petrel search offered with deckCount 7 (<= 8) — the "
            "replayed seat went on to deck out (final deckCount 0). Resolving "
            "an optional draw/search this near empty risks self-loss; minCount "
            "0 so the deckout-safe play is to decline. The policy deckout guard "
            "escalates this penalty at <=8, <=4 and <=2; the replay provides "
            "the deck=7 instance, the tighter thresholds are policy targets "
            "(no separate replay frame exists for them)."
        ),
        "preference": {
            "kind": "decline",
            "reason": (
                "deckCount is 7 (<= 8); an optional draw/search this near empty "
                "risks deck-out and minCount is 0, so declining is the "
                "deckout-safe choice."
            ),
        },
    },
    {
        "id": "setup_active_kyogre_vs_snover__kyogre",
        "spec_case": "setup_active_kyogre_vs_snover",
        "step": 3,
        "seat": 0,
        "context_name": "choose_active",
        "severity": "advisory",
        "nuance": (
            "Initial active choice, seat 0: both legal options are Kyogre "
            "(721). The Kyogre line (immediate attack/energy plan) is taken. "
            "This is the Kyogre-active variant — any setup-line basic is a "
            "valid active; the fixture asserts a correct pick lands on a setup "
            "basic, not a single hard-coded answer."
        ),
        "preference": {
            "kind": "prefer_cards",
            "cards": SETUP_POKEMON_IDS,
            "reason": (
                "the active must be a basic Pokemon; every legal option is a "
                "setup-line basic, so a correct pick lands on one of them."
            ),
        },
    },
    {
        "id": "setup_active_kyogre_vs_snover__snover",
        "spec_case": "setup_active_kyogre_vs_snover",
        "step": 4,
        "seat": 1,
        "context_name": "choose_active",
        "severity": "advisory",
        "nuance": (
            "Initial active choice, seat 1: options are Snover (722) / Snover / "
            "Kyogre (721); Snover is taken to lean on evolution support. This "
            "is the Snover-active variant — the complement of the Kyogre "
            "variant. Both are valid; the fixture asserts the pick is a "
            "setup-line basic, not a single hard-coded answer."
        ),
        "preference": {
            "kind": "prefer_cards",
            "cards": SETUP_POKEMON_IDS,
            "reason": (
                "the active must be a basic Pokemon; every legal option is a "
                "setup-line basic, so a correct pick lands on one of them."
            ),
        },
    },
]

# ---------------------------------------------------------------------------
# Documented (non-gradeable) seams: real failure regimes the replay schema
# cannot turn into a deterministic graded prompt. Recorded honestly so the
# report does not pretend coverage it does not have.
# ---------------------------------------------------------------------------
PASS8_DOCUMENTED: list[dict] = [
    {
        "id": "secret_box_play_safety",
        "spec_case": "secret_box_play_safety",
        "severity": "advisory",
        "gradeable": False,
        "context_name": "main_play_decision",
        "effect_card_id": SECRET_BOX,
        "observation": None,
        "nuance": (
            "Secret Box PRE-PLAY safety: whether to play Secret Box (1092) at "
            "all when fewer than 3 safe discards would remain. This is a "
            "main-menu (context 0) decision. In episode 80374966 no context-0 "
            "option resolves to a hand card id (play options reference board "
            "slots via inPlayArea/inPlayIndex, not a resolvable hand index), so "
            "the pre-play choice cannot be frozen as a deterministic graded "
            "fixture. Recorded as a documented seam, not a fabricated check. "
            "Real downstream evidence of the bad play: the forced step-11 "
            "Snover discard (secret_box_forced_discard_all) and the eventual "
            "deck-out. The policy guard (policy_secret_box_play_guard_v1) "
            "targets this seam at the live decision; if a forced unsafe play "
            "occurs it is marked forced_bad/unsafe and never blamed on the "
            "discard subprompt."
        ),
        "check": {"legality": True, "preference": {"kind": "documented_seam"}},
    },
]


def build_pass8_fixtures(replay_path: str) -> list[dict]:
    replay = load_replay(replay_path)
    fixtures: list[dict] = []
    for target in PASS8_TARGETS:
        fx = build_fixture(replay, target)
        fx["spec_case"] = target["spec_case"]
        fx["severity"] = target["severity"]
        fx["gradeable"] = True
        fixtures.append(fx)
    for doc in PASS8_DOCUMENTED:
        entry = dict(doc)
        entry["source"] = {"replay": str(replay.episode_id),
                           "module_version": replay.module_version}
        fixtures.append(entry)
    return fixtures


def _format_md(fixtures: list[dict], replay_path: str) -> str:
    lines: list[str] = []
    lines.append("# Pass 8 effect-resolution fixtures — episode 80374966")
    lines.append("")
    lines.append(
        "Deterministic decision fixtures frozen from the replay's true failure "
        "regime (effect-resolution safety). Each fixture freezes one real "
        "prompt; the candidate `agent(observation)` is graded for **legality** "
        "(always hard) and a per-fixture **preference** whose `severity` is "
        "`hard` (blocks promotion on failure) or `advisory` (reported only)."
    )
    lines.append("")
    grade = [f for f in fixtures if f.get("gradeable", True)]
    hard = [f for f in grade if f.get("severity") == "hard"]
    adv = [f for f in grade if f.get("severity") == "advisory"]
    doc = [f for f in fixtures if not f.get("gradeable", True)]
    lines.append(f"- source replay: `{replay_path}`")
    lines.append(f"- gradeable fixtures: {len(grade)} "
                 f"({len(hard)} hard, {len(adv)} advisory)")
    lines.append(f"- documented (non-gradeable) seams: {len(doc)}")
    lines.append("")
    lines.append("## Fixtures")
    lines.append("")
    for f in fixtures:
        sev = f.get("severity", "?")
        tag = "documented" if not f.get("gradeable", True) else sev
        pref = f.get("check", {}).get("preference", {})
        lines.append(f"### {f['id']}  _({tag})_")
        if f.get("gradeable", True):
            lines.append(
                f"- step {f['source']['step']} seat {f['source']['seat']} "
                f"| context `{f.get('context_name')}` "
                f"| effect {f.get('effect_card_id')} "
                f"| min {f.get('min_count')} max {f.get('max_count')} "
                f"n {f.get('n_options')}"
            )
            lines.append(f"- option cards: {f.get('option_cards')}")
            lines.append(f"- board: {f.get('board_pokemon')} "
                         f"| deck {f.get('deck_count')} hand {f.get('hand_count')}")
            lines.append(f"- preference: `{pref.get('kind')}`"
                         + (f" cards={pref.get('cards')}" if pref.get('cards') else ""))
        else:
            lines.append(f"- context `{f.get('context_name')}` "
                         f"| effect {f.get('effect_card_id')} "
                         f"| **not gradeable** (documented seam)")
        lines.append(f"- nuance: {f.get('nuance')}")
        lines.append("")
    return "\n".join(lines)


def write_pass8_fixtures(replay_path: str, out_json: str, out_md: str) -> list[dict]:
    fixtures = build_pass8_fixtures(replay_path)
    payload = {
        "stage": "pass8_effect_resolution_fixtures",
        "source_replay": replay_path,
        "n_fixtures": len(fixtures),
        "n_gradeable": sum(1 for f in fixtures if f.get("gradeable", True)),
        "n_hard": sum(1 for f in fixtures
                      if f.get("gradeable", True) and f.get("severity") == "hard"),
        "n_advisory": sum(1 for f in fixtures
                          if f.get("gradeable", True) and f.get("severity") == "advisory"),
        "n_documented": sum(1 for f in fixtures if not f.get("gradeable", True)),
        "fixtures": fixtures,
    }
    jp = Path(out_json)
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    Path(out_md).write_text(_format_md(fixtures, replay_path), encoding="utf-8")
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--replay", default=DEFAULT_REPLAY)
    parser.add_argument("--out-json", default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    fixtures = write_pass8_fixtures(args.replay, args.out_json, args.out_md)
    grade = [f for f in fixtures if f.get("gradeable", True)]
    print(f"Wrote {len(fixtures)} Pass 8 fixtures "
          f"({len(grade)} gradeable) to {args.out_json}")
    for f in fixtures:
        sev = "documented" if not f.get("gradeable", True) else f.get("severity")
        pref = f.get("check", {}).get("preference", {}).get("kind")
        print(f"  {f['id']:<45} sev={sev:<10} pref={pref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
