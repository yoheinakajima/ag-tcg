#!/usr/bin/env python3
"""Pass 34 (Part D) — build transparent v0 60-card decklists. LOCAL.

Consumes data/experiments/pass34_deck_intake.json (Part C). For each buildable
deck it:
  * starts from the validated skeleton counts,
  * applies the reported evolution-Basic corrections (verified ids only),
  * flex-fills the remainder up to exactly 60 cards with the deck's resolved
    basic energy (transparently documented), and
  * enforces honesty gates: every id in DB, every non-basic-energy id <= 4 copies,
    final size == 60.

Basic energy is allowed to exceed 4 copies; nothing else is. No invented ids.
Writes experiments/pass34_decklists/<deck_id>/deck.csv plus
pass34_decklist_builds.{json,md}.
"""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
INTAKE = EXP / "pass34_deck_intake.json"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
OUT_DIR = EXP / "pass34_decklists"
OUT_JSON = EXP / "pass34_decklist_builds.json"
OUT_MD = EXP / "pass34_decklist_builds.md"

STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"
TARGET = 60


def _load_db():
    by_id, basic_energy = {}, set()
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("Card ID") or "").strip()
            if not cid.isdigit():
                continue
            cid = int(cid)
            stage = (row.get(STAGE_COL) or "").strip()
            by_id[cid] = {"name": (row.get("Card Name") or "").strip(),
                          "stage": stage}
            if stage == "Basic Energy":
                basic_energy.add(cid)
    return by_id, basic_energy


def _build_one(deck, by_id, basic_energy):
    deck_id = deck["deck_id"]
    if deck["intake_status"] != "buildable":
        return {"deck_id": deck_id, "built": False,
                "reason": f"intake status {deck['intake_status']}"}

    counts = collections.Counter()
    for cv in deck["cards_validated"]:
        if cv.get("exists"):
            counts[cv["id"]] += cv["count"]

    applied_corrections = []
    for e in deck["evolution_corrections"]:
        counts[e["added_basic_id"]] += e["add_count"]
        applied_corrections.append({
            "added_basic_id": e["added_basic_id"], "count": e["add_count"],
            "for_evolution": e["evolution"], "reason": e["reason"]})

    energy_id = deck["energy_resolution"][0]["resolved_card_id"]
    if energy_id is None:
        return {"deck_id": deck_id, "built": False,
                "reason": "basic energy id unresolved"}

    pre_fill_total = sum(counts.values())
    remainder = TARGET - pre_fill_total
    flex_fill = []
    if remainder < 0:
        return {"deck_id": deck_id, "built": False,
                "reason": f"skeleton + corrections = {pre_fill_total} > 60"}
    if remainder > 0:
        counts[energy_id] += remainder
        flex_fill.append({
            "card_id": energy_id, "name": by_id[energy_id]["name"],
            "added": remainder,
            "reason": ("v0 transparent flex-fill: remaining slots filled with the "
                       "deck's resolved basic energy to reach exactly 60. Basic "
                       "energy may exceed 4 copies; this is an unoptimized v0 line "
                       "to be refined by pilot-fit analysis.")})

    # honesty gates
    deck_ids = []
    for c in sorted(counts):
        deck_ids.extend([c] * counts[c])
    if len(deck_ids) != TARGET:
        return {"deck_id": deck_id, "built": False,
                "reason": f"final size {len(deck_ids)} != 60"}
    invented = sorted(set(deck_ids) - set(by_id))
    if invented:
        return {"deck_id": deck_id, "built": False,
                "reason": f"invented ids: {invented}"}
    overcap = {c: n for c, n in counts.items() if n > 4 and c not in basic_energy}
    if overcap:
        return {"deck_id": deck_id, "built": False,
                "reason": f"non-basic-energy over 4 copies: {overcap}"}

    out = OUT_DIR / deck_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "deck.csv").write_text("\n".join(str(c) for c in deck_ids) + "\n",
                                  encoding="utf-8")

    return {
        "deck_id": deck_id, "display_name": deck["display_name"],
        "lane": deck["lane"], "special_pilot_required": deck["special_pilot_required"],
        "built": True, "deck_size": len(deck_ids),
        "skeleton_total": pre_fill_total - sum(e["add_count"]
                                               for e in deck["evolution_corrections"]),
        "corrections_applied": applied_corrections,
        "flex_fill": flex_fill,
        "energy_id": energy_id, "energy_copies": counts[energy_id],
        "card_counts": {int(c): int(n) for c, n in sorted(counts.items())},
        "non_basic_energy_max_copies": max(
            [n for c, n in counts.items() if c not in basic_energy], default=0),
        "deck_csv": str((out / "deck.csv").relative_to(REPO)),
    }


def main() -> int:
    intake = json.loads(INTAKE.read_text(encoding="utf-8"))
    by_id, basic_energy = _load_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [_build_one(d, by_id, basic_energy) for d in intake["decks"]]
    built = [r for r in results if r.get("built")]
    failed = [r for r in results if not r.get("built")]

    doc = {"pass": "34", "part": "D", "local_only": True, "no_upload": True,
           "target_size": TARGET, "built_count": len(built),
           "failed_count": len(failed), "results": results}
    OUT_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    L = ["# Pass 34 — v0 60-card Decklist Builds (Part D)", "",
         "> LOCAL. No upload. Each list starts from the validated skeleton, "
         "applies verified evolution-Basic corrections, and flex-fills the "
         "remainder with the deck's resolved basic energy to exactly 60. Only "
         "basic energy may exceed 4 copies. These are unoptimized v0 lines.", "",
         f"- built: **{len(built)}**  failed: **{len(failed)}**", ""]
    for r in results:
        if not r.get("built"):
            L += [f"## {r['deck_id']} — BUILD FAILED", f"- reason: {r['reason']}", ""]
            continue
        L += [f"## {r['display_name']}  (`{r['deck_id']}`)",
              f"- lane: **{r['lane']}**  special_pilot_required: "
              f"**{r['special_pilot_required']}**",
              f"- deck size: **{r['deck_size']}**  "
              f"non-basic-energy max copies: {r['non_basic_energy_max_copies']}",
              f"- basic energy id {r['energy_id']} x{r['energy_copies']}"]
        if r["corrections_applied"]:
            L.append("- evolution corrections applied:")
            for c in r["corrections_applied"]:
                L.append(f"  - +{c['count']}x id {c['added_basic_id']} "
                         f"(for {c['for_evolution']})")
        for f in r["flex_fill"]:
            L.append(f"- flex-fill: +{f['added']}x {f['name']} (id {f['card_id']}) "
                     f"— {f['reason']}")
        L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    for r in results:
        if r.get("built"):
            print(f"{r['deck_id']}: built 60 "
                  f"(energy x{r['energy_copies']}, "
                  f"maxcopy {r['non_basic_energy_max_copies']})")
        else:
            print(f"{r['deck_id']}: FAILED — {r['reason']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
