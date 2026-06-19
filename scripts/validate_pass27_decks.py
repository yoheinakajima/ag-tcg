#!/usr/bin/env python3
"""Pass 27 (Part C) -- validate the multi-archetype portfolio deck registry.

LOCAL ONLY. Reads experiments/pass27_portfolio_decks.yaml and checks every
deck's FINAL 60-card composition against data/cards/EN_Card_Data.csv:

  * every card id exists in the card database (NO invented ids);
  * exactly 60 cards total;
  * at most 4 copies of any non-basic-energy card (basic energy is unlimited);
  * declared basic_energy ids really are "Basic Energy" in the database.

Writes data/experiments/pass27_portfolio_registry.{json,md}. Exit code 0 when
every BUILDABLE deck passes, else 1. The card CSV itself is never copied or
committed -- only ids/names are echoed.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
REGISTRY = REPO / "experiments" / "pass27_portfolio_decks.yaml"
OUT_DIR = REPO / "data" / "experiments"

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


def load_registry() -> dict:
    import yaml  # type: ignore
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}


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
            resolved.append({"id": cid, "count": cnt, "name": None, "found": False})
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

    return {
        "key": key,
        "name": spec.get("name"),
        "family": spec.get("family"),
        "archetype": spec.get("archetype"),
        "candidate_id": spec.get("candidate_id"),
        "buildable": bool(spec.get("buildable")),
        "blocked_from_league": bool(spec.get("blocked_from_league")),
        "block_reason": (spec.get("block_reason") or "").strip() or None,
        "playbook": spec.get("playbook"),
        "runtime_contexts": spec.get("runtime_contexts"),
        "deck_source": spec.get("deck_source"),
        "total": total,
        "unique_ids": len(cards),
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
        "cards": resolved,
    }


def build_report() -> dict:
    db = load_card_db()
    reg = load_registry()
    decks = reg.get("decks") or {}

    global_errors: list[str] = []
    for raw_id in reg.get("basic_energy_ids", []) or []:
        cid = int(raw_id)
        entry = db.get(cid)
        if entry is None or not entry["is_basic_energy"]:
            global_errors.append(
                f"basic_energy_ids entry {cid} is not Basic Energy in the database")

    results = [validate_deck(k, v, db) for k, v in decks.items()]
    buildable = [r for r in results if r["buildable"]]
    all_buildable_valid = all(r["valid"] for r in buildable) and not global_errors

    return {
        "pass": "27", "part": "C", "local_only": True, "upload_performed": False,
        "no_upload": True,
        "card_db_rows": len(db),
        "global_errors": global_errors,
        "decks": results,
        "summary": {
            "total_decks": len(results),
            "buildable": len(buildable),
            "buildable_valid": sum(1 for r in buildable if r["valid"]),
            "all_buildable_valid": all_buildable_valid,
            "blocked_from_league": sum(1 for r in results if r["blocked_from_league"]),
        },
    }


def md(rep: dict) -> str:
    s = rep["summary"]
    L = ["# Pass 27 — Multi-Archetype Portfolio deck registry (Part C)", "",
         "> LOCAL ONLY. Card ids validated against `data/cards/EN_Card_Data.csv` "
         "(gitignored, never committed). No invented ids. No upload.", "",
         f"- card database rows: {rep['card_db_rows']}",
         f"- decks: {s['total_decks']}  buildable: {s['buildable']}  "
         f"buildable valid: {s['buildable_valid']}  blocked from league: "
         f"{s['blocked_from_league']}",
         f"- **all buildable decks valid: {s['all_buildable_valid']}**", ""]
    if rep["global_errors"]:
        L += ["## Global errors"] + [f"- {e}" for e in rep["global_errors"]] + [""]
    L += ["| deck | family | archetype | candidate | buildable | blocked | total | unique | valid |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["decks"]:
        L.append(f"| {r['key']} | {r['family']} | {r['archetype']} | "
                 f"{r['candidate_id']} | {r['buildable']} | "
                 f"{r['blocked_from_league']} | {r['total']} | {r['unique_ids']} | "
                 f"{'PASS' if r['valid'] else 'FAIL'} |")
    for r in rep["decks"]:
        if r["errors"]:
            L += ["", f"### Errors — {r['key']}"] + [f"- {e}" for e in r["errors"]]
    L.append("")
    return "\n".join(L)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep = build_report()
    (OUT_DIR / "pass27_portfolio_registry.json").write_text(
        json.dumps(rep, indent=2), encoding="utf-8")
    (OUT_DIR / "pass27_portfolio_registry.md").write_text(md(rep), encoding="utf-8")
    s = rep["summary"]
    print(f"portfolio registry: buildable_valid={s['buildable_valid']}/"
          f"{s['buildable']} all_valid={s['all_buildable_valid']}")
    for r in rep["decks"]:
        flag = "OK" if r["valid"] else "FAIL"
        blk = " [BLOCKED FROM LEAGUE]" if r["blocked_from_league"] else ""
        print(f"  [{flag}] {r['key']} total={r['total']} errors={len(r['errors'])}{blk}")
    return 0 if s["all_buildable_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
