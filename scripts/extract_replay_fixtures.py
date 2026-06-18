#!/usr/bin/env python3
"""Extract replay-derived decision fixtures from a Kaggle cabt episode.

A *fixture* freezes one real decision prompt (the ``observation`` the engine
showed a seat, plus the ``select`` choices) together with:

* the card id each option resolves to (``option_cards``; ``null`` when the
  option points at a board slot we do not resolve),
* the seat's own observable pre-state (deck_count / hand_count / board pokemon),
* the action the replay actually recorded (``replay_action``) for reference,
* an honest, machine-checkable ``check`` describing the legality gate and an
  optional advisory ``preference`` (decline / avoid_cards / prefer_cards /
  forced_all).

These fixtures are a *pre-cabt gate*: a candidate ``main.py`` can be fed each
observation and graded for legality (hard) and strategy preference (advisory)
without running a full game. The targets below were chosen against episode
80374966 (module 1.30.1) and verified by reading the raw schema; every card id
used is confirmed in ``data/cards`` (no invented ids). Where the engine's
intent cannot be proven from the schema alone, the fixture records the nuance
rather than asserting a fabricated conclusion.

Usage:
    python scripts/extract_replay_fixtures.py
    python scripts/extract_replay_fixtures.py --replay data/replays/80374966.json \
        --out data/replay_fixtures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
from ptcg_activegraph.replays.analyzers import (
    AREA_DECK,
    AREA_HAND,
    CTX_DISCARD,
    CTX_SEARCH_TO_HAND,
    KYOGRE,
    MEGA_ABOMASNOW,
    SNOVER,
    WATER_ENERGY,
)
from ptcg_activegraph.replays.kaggle_replay import load_replay

DEFAULT_REPLAY = "data/replays/80374966.json"
DEFAULT_OUT = "data/replay_fixtures"

SETUP_POKEMON_IDS = sorted({KYOGRE, SNOVER, MEGA_ABOMASNOW})

# ---------------------------------------------------------------------------
# Fixture targets. Each entry names a (step, seat) decision in the replay and
# the honest check we attach to it. ``preference`` is advisory: v2 may fail it
# (that is the point — we record the baseline's behaviour); a v3 policy is
# expected to satisfy it. ``legality`` is the hard gate every candidate must
# pass (in-range, unique, count-respecting selection, no crash).
# ---------------------------------------------------------------------------
FIXTURE_TARGETS: list[dict] = [
    {
        "id": "step11_secret_box_discard",
        "step": 11,
        "seat": 0,
        "context_name": "discard",
        "nuance": (
            "minCount == maxCount == n_options (3): every option must be "
            "selected, so the Snover (722) among the three cards cannot be "
            "spared. There is no safe discard here — the only legal selection "
            "is all options. We record this as a forced discard rather than a "
            "policy failure."
        ),
        "preference": {
            "kind": "forced_all",
            "reason": (
                "minCount equals the number of options; the discard set is "
                "forced and no avoidance is possible."
            ),
        },
    },
    {
        "id": "step17_mega_signal_search",
        "step": 17,
        "seat": 0,
        "context_name": "search_to_hand",
        "nuance": (
            "Mega Signal search where all three options resolve to Mega "
            "Abomasnow (723) and no Snover (722) is on the board. Fetching a "
            "Mega with no Snover line to evolve from is a dead draw; with "
            "minCount 0 the safe play is to decline."
        ),
        "preference": {
            "kind": "decline",
            "reason": (
                "every option is Mega Abomasnow (723) and the board has no "
                "Snover (722) to evolve from; minCount is 0 so declining is "
                "legal and avoids a dead fetch."
            ),
        },
    },
    {
        "id": "step28_ultra_ball_discard",
        "step": 28,
        "seat": 0,
        "context_name": "discard",
        "nuance": (
            "Ultra Ball cost: discard 2 of 6 hand cards. The options include "
            "Basic {W} Energy (3) as safe fodder alongside setup pieces "
            "(Mega Abomasnow 723) and utility cards. Discarding energy is "
            "preferred over discarding a setup Pokemon."
        ),
        "preference": {
            "kind": "avoid_cards",
            "cards": SETUP_POKEMON_IDS,
            "reason": (
                "setup Pokemon (Kyogre 721 / Snover 722 / Mega Abomasnow 723) "
                "should not be paid as Ultra Ball's discard cost while energy "
                "fodder (3) is available."
            ),
        },
    },
    {
        "id": "step112_low_deck_search",
        "step": 112,
        "seat": 0,
        "context_name": "search_to_hand",
        "nuance": (
            "Search/draw effect offered with deckCount 7 (<= 8). Resolving a "
            "draw effect this close to empty risks decking out; with minCount "
            "0 the deckout-safe play is to decline."
        ),
        "preference": {
            "kind": "decline",
            "reason": (
                "deckCount is 7 (<= 8); a draw/search effect this near empty "
                "risks deck-out and minCount is 0, so declining is the "
                "deckout-safe choice."
            ),
        },
    },
    {
        "id": "setup_active_choice",
        "step": 4,
        "seat": 1,
        "context_name": "choose_active",
        "nuance": (
            "Initial setup: choose the starting active Pokemon from the "
            "basics in hand. All legal options are setup-line basics "
            "(Snover 722 / Kyogre 721); any of them is a valid active."
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


def _card_id(entry: Any) -> Any:
    if isinstance(entry, dict):
        v = entry.get("id")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _my_player(obs: dict) -> dict | None:
    cur = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(cur, dict):
        return None
    me = cur.get("yourIndex")
    players = cur.get("players")
    if isinstance(players, list) and isinstance(me, int) and 0 <= me < len(players):
        p = players[me]
        return p if isinstance(p, dict) else None
    return None


def _resolve_option_card(opt: Any, obs: dict, sel: dict) -> Any:
    """Resolve the card id an option refers to, or None if it is a board slot."""
    if not isinstance(opt, dict):
        return None
    area = opt.get("area")
    index = opt.get("index")
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    if area == AREA_DECK:
        deck = sel.get("deck")
        ids = deck if isinstance(deck, list) else []
        if 0 <= index < len(ids):
            return _card_id(ids[index])
    elif area == AREA_HAND:
        player = _my_player(obs)
        hand = player.get("hand") if isinstance(player, dict) else None
        ids = hand if isinstance(hand, list) else []
        if 0 <= index < len(ids):
            return _card_id(ids[index])
    return None


def _board_pokemon_ids(player: dict | None) -> list[int]:
    if not isinstance(player, dict):
        return []
    ids: list[int] = []
    for slot in ("active", "bench"):
        zone = player.get(slot)
        if isinstance(zone, list):
            for e in zone:
                cid = _card_id(e)
                if cid is not None:
                    ids.append(cid)
    return ids


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def build_fixture(replay, target: dict) -> dict:
    """Build one fixture dict from a (step, seat) target. Raises on bad target."""
    step = target["step"]
    seat = target["seat"]
    steps = replay.steps
    if step >= len(steps) or not isinstance(steps[step], list) or len(steps[step]) <= seat:
        raise ValueError(f"target {target['id']}: step {step} seat {seat} not present")
    rec = steps[step][seat]
    if not isinstance(rec, dict):
        raise ValueError(f"target {target['id']}: record at step {step} seat {seat} not a dict")
    obs = rec.get("observation")
    if not isinstance(obs, dict):
        raise ValueError(f"target {target['id']}: no observation at step {step} seat {seat}")
    sel = obs.get("select")
    if not isinstance(sel, dict):
        raise ValueError(f"target {target['id']}: no select at step {step} seat {seat}")
    options = sel.get("option")
    if not isinstance(options, list) or not options:
        raise ValueError(f"target {target['id']}: no options at step {step} seat {seat}")

    option_cards = [_resolve_option_card(o, obs, sel) for o in options]
    option_types = [o.get("type") if isinstance(o, dict) else None for o in options]
    player = _my_player(obs)
    board = _board_pokemon_ids(player)
    n_options = len(options)
    min_count = _coerce_int(sel.get("minCount"))
    max_count = _coerce_int(sel.get("maxCount"))

    replay_action = rec.get("action")
    if not isinstance(replay_action, list):
        replay_action = None

    fixture = {
        "id": target["id"],
        "source": {
            "replay": str(replay.episode_id),
            "step": step,
            "seat": seat,
            "module_version": replay.module_version,
        },
        "context": sel.get("context"),
        "context_name": target["context_name"],
        "select_type": sel.get("type"),
        "effect_card_id": _card_id(sel.get("effect")),
        "min_count": min_count,
        "max_count": max_count,
        "n_options": n_options,
        "option_types": option_types,
        "option_cards": option_cards,
        "board_pokemon": board,
        "deck_count": player.get("deckCount") if isinstance(player, dict) else None,
        "hand_count": player.get("handCount") if isinstance(player, dict) else None,
        "replay_action": replay_action,
        "nuance": target["nuance"],
        "check": {
            "legality": True,
            "preference": target["preference"],
        },
        # The full prompt the engine showed this seat. A candidate agent is fed
        # exactly this dict; nothing here exposes the opponent's hidden hand or
        # deck contents.
        "observation": obs,
    }
    return fixture


def extract_fixtures(replay_path: str, out_dir: str) -> list[dict]:
    replay = load_replay(replay_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []
    for target in FIXTURE_TARGETS:
        fixture = build_fixture(replay, target)
        path = out / f"{fixture['id']}.json"
        path.write_text(json.dumps(fixture, indent=2, sort_keys=False), encoding="utf-8")
        written.append(fixture)
    # An index for quick inspection (no observation payloads, just the gist).
    index = [
        {
            "id": f["id"],
            "context_name": f["context_name"],
            "effect_card_id": f["effect_card_id"],
            "min_count": f["min_count"],
            "max_count": f["max_count"],
            "n_options": f["n_options"],
            "option_cards": f["option_cards"],
            "preference_kind": f["check"]["preference"]["kind"],
        }
        for f in written
    ]
    (out / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--replay", default=DEFAULT_REPLAY,
                        help=f"path to the replay JSON (default {DEFAULT_REPLAY})")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"output directory for fixtures (default {DEFAULT_OUT})")
    args = parser.parse_args()

    written = extract_fixtures(args.replay, args.out)
    print(f"Wrote {len(written)} fixtures to {args.out}/")
    for f in written:
        eff = f["effect_card_id"]
        print(
            f"  {f['id']:<28} ctx={f['context_name']:<14} "
            f"eff={eff} min={f['min_count']} max={f['max_count']} "
            f"n={f['n_options']} cards={f['option_cards']} "
            f"pref={f['check']['preference']['kind']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
