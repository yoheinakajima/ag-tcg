#!/usr/bin/env python3
"""Analyze a single meta replay (or partial log) into a deck skeleton and an
early-game policy fingerprint.

Honest about coverage:

* A **full** replay (a Kaggle-style export with a ``steps`` array) yields a full
  skeleton + early policy fingerprint.
* A **partial** log (any JSON with a subset of fields) yields whatever can be
  read, with ``coverage="partial"`` and per-field ``unknown`` markers.

Hard rule: **never invent card IDs.** If a numeric id is not present in the
source JSON it is recorded as ``unknown`` — ids are never derived from card-name
text.

Usage:
    python scripts/analyze_meta_replay.py --replay data/meta_replays/<file>.json
    python scripts/analyze_meta_replay.py --replay <file>.json --json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

UNKNOWN = "unknown"


def load_replay(path: str | Path) -> dict | None:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _card_id_of(card: Any) -> Any:
    """Return a numeric card id if present, else ``unknown``. Never invents one."""
    if isinstance(card, bool):
        return UNKNOWN
    if isinstance(card, int):
        return card
    if isinstance(card, dict):
        for key in ("id", "cardId", "card_id"):
            v = card.get(key)
            if isinstance(v, int) and not isinstance(v, bool):
                return v
        return UNKNOWN
    return UNKNOWN


def _card_role(card: Any) -> str:
    """Best-effort role from explicit fields only (never inferred from id)."""
    if isinstance(card, dict):
        for key in ("supertype", "type", "category", "role"):
            v = card.get(key)
            if isinstance(v, str) and v:
                return v.lower()
    return UNKNOWN


def extract_deck_skeleton(replay: dict) -> dict:
    """Pull a deck skeleton from whatever deck representation exists."""
    deck = None
    for key in ("deck", "decklist", "cards"):
        if isinstance(replay.get(key), list):
            deck = replay[key]
            break

    skeleton: dict[str, Any] = {
        "coverage": "full" if deck is not None else "partial",
        "card_count": len(deck) if deck is not None else UNKNOWN,
        "card_ids": [],
        "card_id_counts": {},
        "energy_count": UNKNOWN,
        "pokemon_count": UNKNOWN,
        "trainer_count": UNKNOWN,
        "evolution_lines": UNKNOWN,
        "role_counts": {},
        "unknown_id_cards": 0,
        "uncertain": deck is None,
        "notes": [],
    }
    if deck is None:
        skeleton["notes"].append("no deck/decklist/cards array present; skeleton is unknown")
        return skeleton

    ids: list[Any] = []
    roles: Counter = Counter()
    unknown_ids = 0
    energy = pokemon = trainer = 0
    have_roles = False
    for card in deck:
        cid = _card_id_of(card)
        if cid == UNKNOWN:
            unknown_ids += 1
        else:
            ids.append(cid)
        role = _card_role(card)
        if role != UNKNOWN:
            have_roles = True
            roles[role] += 1
            if "energy" in role:
                energy += 1
            elif "pok" in role:  # pokemon / pokémon
                pokemon += 1
            elif "trainer" in role or "supporter" in role or "item" in role or "stadium" in role:
                trainer += 1

    skeleton["card_ids"] = sorted(i for i in ids if isinstance(i, int))
    skeleton["card_id_counts"] = {str(k): v for k, v in sorted(Counter(ids).items())}
    skeleton["unknown_id_cards"] = unknown_ids
    skeleton["role_counts"] = dict(roles)
    if have_roles:
        skeleton["energy_count"] = energy
        skeleton["pokemon_count"] = pokemon
        skeleton["trainer_count"] = trainer
    else:
        skeleton["notes"].append("cards carry no role/supertype; energy/pokemon/trainer unknown")
    if unknown_ids:
        skeleton["notes"].append(f"{unknown_ids} card(s) without a numeric id (recorded as unknown, not invented)")
    # Evolution lines require per-card stage/evolvesFrom metadata; only report
    # when present, never inferred.
    if any(isinstance(c, dict) and ("evolvesFrom" in c or "stage" in c) for c in deck):
        lines: Counter = Counter()
        for c in deck:
            if isinstance(c, dict):
                base = c.get("evolvesFrom")
                if isinstance(base, (str, int)):
                    lines[str(base)] += 1
        skeleton["evolution_lines"] = dict(lines)
    else:
        skeleton["notes"].append("no stage/evolvesFrom metadata; evolution_lines unknown")
    return skeleton


def extract_early_policy(replay: dict) -> dict:
    """Read early-game policy patterns from a ``steps`` array if present."""
    steps = replay.get("steps")
    fp: dict[str, Any] = {
        "coverage": "full" if isinstance(steps, list) and steps else "partial",
        "first_active": UNKNOWN,
        "bench_setup": UNKNOWN,
        "first_supporter": UNKNOWN,
        "first_attack_turn": UNKNOWN,
        "tutor_target_choices": [],
        "uncertain": not (isinstance(steps, list) and steps),
        "notes": [],
    }
    if not (isinstance(steps, list) and steps):
        fp["notes"].append("no steps array; early-game policy is unknown")
        return fp
    fp["n_steps"] = len(steps)
    fp["notes"].append(
        "steps array present; deep per-step policy extraction is a future-work "
        "hook — early fields remain unknown until a real replay schema is wired"
    )
    return fp


def analyze_replay(path: str | Path) -> dict:
    replay = load_replay(path)
    if replay is None:
        return {
            "replay": str(path),
            "ok": False,
            "error": "not a readable JSON object",
            "coverage": "none",
        }
    skeleton = extract_deck_skeleton(replay)
    policy = extract_early_policy(replay)
    coverage = "full" if skeleton["coverage"] == "full" and policy["coverage"] == "full" else "partial"
    return {
        "replay": str(path),
        "ok": True,
        "coverage": coverage,
        "deck_skeleton": skeleton,
        "early_policy": policy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = analyze_replay(args.replay)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"replay: {result['replay']}  coverage={result['coverage']}  ok={result['ok']}")
        if result.get("ok"):
            sk = result["deck_skeleton"]
            print(f"  cards={sk['card_count']} energy={sk['energy_count']} "
                  f"pokemon={sk['pokemon_count']} trainer={sk['trainer_count']} "
                  f"unknown_id_cards={sk['unknown_id_cards']}")
            for n in sk.get("notes", []):
                print(f"  - skeleton: {n}")
            for n in result["early_policy"].get("notes", []):
                print(f"  - policy: {n}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
