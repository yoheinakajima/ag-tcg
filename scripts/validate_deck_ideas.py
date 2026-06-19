#!/usr/bin/env python3
"""Pass 17 (Part C) -- validate deck ideas against the real card database.

LOCAL ONLY. Reads experiments/deck_ideas.yaml and checks every deck's FINAL
60-card composition against data/cards/EN_Card_Data.csv:

  * every card id exists in the card database (NO invented ids);
  * exactly 60 cards total;
  * at most 4 copies of any non-basic-energy card (basic energy is unlimited);
  * declared basic_energy ids really are "Basic Energy" in the database;
  * skeleton (if present) is a subset whose counts do not exceed the final deck
    (i.e. filler only ADDS validated cards).

Writes data/experiments/pass17_deck_idea_validation.{json,md}. Exit code is 0
when every BUILDABLE deck passes, else 1. The card CSV itself is never copied or
committed -- only ids/names are echoed.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
DECK_IDEAS = REPO / "experiments" / "deck_ideas.yaml"
OUT_DIR = REPO / "data" / "experiments"

# Column index for "Stage (Pokémon)/Type (Energy and Trainer)"; value
# "Basic Energy" marks an unlimited-copy basic energy card.
_STAGE_TYPE_COL = 4
_NAME_COL = 1
_ID_COL = 0
MAX_COPIES = 4


def load_card_db() -> dict[int, dict]:
    db: dict[int, dict] = {}
    with CARD_CSV.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for row in reader:
            if not row or not row[_ID_COL].strip().isdigit():
                continue
            cid = int(row[_ID_COL])
            stage_type = row[_STAGE_TYPE_COL].strip() if len(row) > _STAGE_TYPE_COL else ""
            db[cid] = {
                "name": row[_NAME_COL].strip() if len(row) > _NAME_COL else "",
                "stage_type": stage_type,
                "is_basic_energy": stage_type == "Basic Energy",
            }
    return db


def load_deck_ideas() -> dict:
    try:
        import yaml  # type: ignore
    except Exception:
        print("PyYAML required for validate_deck_ideas.py", file=sys.stderr)
        raise
    return yaml.safe_load(DECK_IDEAS.read_text(encoding="utf-8")) or {}


def validate_deck(key: str, spec: dict, db: dict[int, dict]) -> dict:
    cards = spec.get("cards") or {}
    errors: list[str] = []
    warnings: list[str] = []
    resolved: list[dict] = []

    total = 0
    for raw_id, count in cards.items():
        cid = int(raw_id)
        cnt = int(count)
        total += cnt
        entry = db.get(cid)
        if entry is None:
            errors.append(f"id {cid} (x{cnt}) NOT FOUND in card database")
            resolved.append({"id": cid, "count": cnt, "name": None,
                             "found": False})
            continue
        is_be = entry["is_basic_energy"]
        if cnt < 0:
            errors.append(f"id {cid} has negative count {cnt}")
        if not is_be and cnt > MAX_COPIES:
            errors.append(
                f"id {cid} ({entry['name']}) has {cnt} copies > {MAX_COPIES} "
                f"(non-basic-energy limit)")
        resolved.append({"id": cid, "count": cnt, "name": entry["name"],
                         "found": True, "is_basic_energy": is_be})

    if total != 60:
        errors.append(f"deck total is {total}, must be exactly 60")

    # declared basic_energy ids really are basic energy
    for raw_id in spec.get("basic_energy_local", []) or []:
        cid = int(raw_id)
        entry = db.get(cid)
        if entry is None or not entry["is_basic_energy"]:
            errors.append(f"declared basic-energy id {cid} is not Basic Energy")

    # skeleton must not exceed final deck (filler only adds)
    skeleton = spec.get("skeleton") or {}
    for raw_id, scount in skeleton.items():
        cid = int(raw_id)
        fcount = int(cards.get(cid, cards.get(str(cid), 0)) or 0)
        if int(scount) > fcount:
            errors.append(
                f"skeleton id {cid} count {scount} exceeds final {fcount}")

    return {
        "key": key,
        "name": spec.get("name"),
        "candidate_id": spec.get("candidate_id"),
        "buildable": bool(spec.get("buildable")),
        "blocked_from_league": bool(spec.get("blocked_from_league")),
        "total": total,
        "unique_ids": len(cards),
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
        "cards": resolved,
    }


def build_report() -> dict:
    db = load_card_db()
    ideas = load_deck_ideas()
    decks = ideas.get("decks") or {}

    # validate declared basic-energy ids globally too
    global_errors: list[str] = []
    for raw_id in ideas.get("basic_energy_ids", []) or []:
        cid = int(raw_id)
        entry = db.get(cid)
        if entry is None or not entry["is_basic_energy"]:
            global_errors.append(
                f"basic_energy_ids entry {cid} is not Basic Energy in the database")

    results = [validate_deck(k, v, db) for k, v in decks.items()]
    buildable = [r for r in results if r["buildable"]]
    all_buildable_valid = all(r["valid"] for r in buildable) and not global_errors

    return {
        "pass": "17",
        "part": "C",
        "local_only": True,
        "card_db_rows": len(db),
        "global_errors": global_errors,
        "decks": results,
        "summary": {
            "total_decks": len(results),
            "buildable": len(buildable),
            "buildable_valid": sum(1 for r in buildable if r["valid"]),
            "all_buildable_valid": all_buildable_valid,
        },
    }


def md(rep: dict) -> str:
    s = rep["summary"]
    L = ["# Pass 17 — deck idea validation (Part C)", "",
         "> LOCAL ONLY. Card ids validated against `data/cards/EN_Card_Data.csv` "
         "(gitignored, never committed). No invented ids.", "",
         f"- card database rows: {rep['card_db_rows']}",
         f"- decks: {s['total_decks']}  buildable: {s['buildable']}  "
         f"buildable valid: {s['buildable_valid']}",
         f"- **all buildable decks valid: {s['all_buildable_valid']}**", ""]
    if rep["global_errors"]:
        L += ["## Global errors"] + [f"- {e}" for e in rep["global_errors"]] + [""]
    L += ["| deck | candidate | buildable | blocked | total | unique | valid | errors |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rep["decks"]:
        L.append(f"| {r['key']} | {r['candidate_id']} | {r['buildable']} | "
                 f"{r['blocked_from_league']} | {r['total']} | {r['unique_ids']} | "
                 f"{'✅' if r['valid'] else '❌'} | {len(r['errors'])} |")
    for r in rep["decks"]:
        if r["errors"]:
            L += ["", f"### Errors — {r['key']}"] + [f"- {e}" for e in r["errors"]]
    L.append("")
    return "\n".join(L)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep = build_report()
    (OUT_DIR / "pass17_deck_idea_validation.json").write_text(
        json.dumps(rep, indent=2), encoding="utf-8")
    (OUT_DIR / "pass17_deck_idea_validation.md").write_text(md(rep), encoding="utf-8")
    s = rep["summary"]
    print(f"deck idea validation: buildable_valid={s['buildable_valid']}/"
          f"{s['buildable']} all_valid={s['all_buildable_valid']}")
    for r in rep["decks"]:
        flag = "OK" if r["valid"] else "FAIL"
        print(f"  [{flag}] {r['key']} total={r['total']} errors={len(r['errors'])}")
    return 0 if s["all_buildable_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
