#!/usr/bin/env python3
"""Pass 34 (Part C) — new deck intake + ID / stage / energy validation. LOCAL.

Ingests the four user-provided deck SKELETONS, validates every listed card id
against the local card DB (EN_Card_Data.csv, never committed), resolves basic
energies by NAME (not user numeric placeholders), and detects missing evolution
prerequisites. Where an evolution's root Basic is missing it proposes a VERIFIED
Basic correction (by name, from the DB) and reports it explicitly — no invented
ids, ever. Mega Diancie's "is it Basic?" is read straight from the DB.

Counts in the skeletons are intentionally a v0 starting point and need NOT sum to
60 — the 60-card fill happens transparently in Part D. This part only validates
the card pool and records corrections.

Writes data/experiments/pass34_deck_intake.{json,md} and
data/experiments/pass34_deck_ideas.yaml.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
OUT_JSON = EXP / "pass34_deck_intake.json"
OUT_MD = EXP / "pass34_deck_intake.md"
OUT_YAML = EXP / "pass34_deck_ideas.yaml"

STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"
NAME_COL = "Card Name"
PREV_COL = "Previous stage"

# Basic energy NAME -> resolved from DB at runtime (never user placeholders).
ENERGY_NAME = {
    "lightning": "Basic {L} Energy",
    "psychic": "Basic {P} Energy",
    "darkness": "Basic {D} Energy",
}

# Four user-provided skeletons. counts are a v0 start, may not sum to 60.
# Each card: (card_id, count, role). Energy is given by COLOR NAME, resolved below.
SKELETONS = {
    "mono_lightning_miraidon_easy": {
        "display_name": "Mono-Lightning Miraidon ex",
        "design_class": "simple Basic ex / low decision density",
        "lane": "normal",
        "energy_color": "lightning",
        "special_pilot_required": False,
        "cards": [
            (957, 4, "main_attacker_basic_ex"), (809, 3, "basic_evo_base"),
            (810, 1, "stage1"), (811, 3, "stage2_attacker"),
            (514, 2, "basic_support"), (1254, 2, "stadium"),
            (1224, 4, "draw_supporter"), (1231, 2, "draw_supporter"),
            (1182, 2, "gust_supporter"), (1121, 4, "search_item"),
            (1086, 4, "basic_search_item"), (1079, 3, "evo_item"),
        ],
    },
    "diamond_toolbox_diancie": {
        "display_name": "Diamond Toolbox — Mega Diancie ex (mono-Psychic)",
        "design_class": "mono-Psychic Basic toolbox",
        "lane": "normal",
        "energy_color": "psychic",
        "special_pilot_required": False,
        "cards": [
            (766, 4, "main_attacker_basic_ex"), (183, 2, "basic_toolbox"),
            (186, 2, "basic_toolbox"), (767, 2, "basic_toolbox"),
            (751, 2, "basic_toolbox"), (331, 1, "basic_ex_toolbox"),
            (525, 2, "basic_ex_toolbox"), (765, 1, "basic_toolbox"),
            (434, 1, "basic_toolbox"), (1231, 2, "draw_supporter"),
            (1121, 4, "search_item"), (1086, 4, "basic_search_item"),
            (1224, 4, "draw_supporter"), (1182, 2, "gust_supporter"),
        ],
    },
    "toxic_trap_poison_lock": {
        "display_name": "Toxic Trap — Pecharunt poison lock",
        "design_class": "passive poison/status lock; special-pilot likely required",
        "lane": "special",
        "energy_color": "darkness",
        "special_pilot_required": True,
        "cards": [
            (230, 3, "passive_lock_basic"), (1011, 3, "basic_evo_base"),
            (1012, 2, "stage1"), (813, 2, "stage1_ex_attacker"),
            (1243, 2, "stadium"), (1095, 2, "disruption_item"),
            (1162, 2, "tool"), (1212, 2, "heal_supporter"),
            (1222, 2, "draw_supporter"), (1231, 2, "draw_supporter"),
            (1224, 3, "draw_supporter"), (1182, 2, "gust_supporter"),
            (1121, 4, "search_item"), (1086, 4, "basic_search_item"),
        ],
    },
    "deckout_carousel_durant_v2": {
        "display_name": "Deck-Out Carousel — Durant ex (mill-control)",
        "design_class": "non-prize / deckout / mill-control; special-pilot required",
        "lane": "special",
        "energy_color": "darkness",
        "special_pilot_required": True,
        "cards": [
            (198, 4, "mill_attacker_basic_ex"), (227, 3, "basic_evo_base"),
            (228, 2, "stage1_wall"), (1247, 2, "stadium"),
            (162, 1, "basic_tech"), (27, 1, "basic_tech"),
            (815, 2, "stage1_tech"), (1199, 2, "disruption_supporter"),
            (1228, 2, "disruption_supporter"), (1213, 3, "disruption_supporter"),
            (1182, 2, "gust_supporter"), (1231, 2, "draw_supporter"),
            (1121, 4, "search_item"), (1086, 4, "basic_search_item"),
        ],
    },
}


def _load_db():
    by_id, by_name = {}, {}
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("Card ID") or "").strip()
            if not cid.isdigit():
                continue
            rec = {
                "id": int(cid),
                "name": (row.get(NAME_COL) or "").strip(),
                "stage": (row.get(STAGE_COL) or "").strip(),
                "prev": (row.get(PREV_COL) or "").strip(),
            }
            by_id[int(cid)] = rec
            by_name.setdefault(rec["name"], []).append(rec)
    return by_id, by_name


def _is_basic_pokemon(rec):
    return rec["stage"] == "Basic Pokémon"


def _is_pokemon(rec):
    return rec["stage"].endswith("Pokémon")


def _root_basic_name(rec, by_name):
    """Walk the Previous-stage chain back to the root Basic NAME."""
    seen = set()
    cur = rec
    while cur and _is_pokemon(cur) and not _is_basic_pokemon(cur):
        prev_name = cur["prev"]
        if not prev_name or prev_name == "n/a" or prev_name in seen:
            return None
        seen.add(prev_name)
        cands = by_name.get(prev_name) or []
        cur = cands[0] if cands else None
    return cur["name"] if (cur and _is_basic_pokemon(cur)) else None


def _resolve_energy(color, by_name):
    name = ENERGY_NAME[color]
    cands = by_name.get(name) or []
    return (cands[0]["id"] if cands else None), name


def main() -> int:
    by_id, by_name = _load_db()
    decks_out = []
    yaml_lines = ["# Pass 34 deck ideas registry (intake). LOCAL. no upload.",
                  "deck_ideas:"]

    for deck_id, spec in SKELETONS.items():
        cards_validated, missing_ids, energy_corr = [], [], []
        present_names = set()
        for cid, cnt, role in spec["cards"]:
            rec = by_id.get(cid)
            if not rec:
                missing_ids.append(cid)
                cards_validated.append({"id": cid, "count": cnt, "role": role,
                                        "exists": False})
                continue
            present_names.add(rec["name"])
            cards_validated.append({
                "id": cid, "name": rec["name"], "count": cnt, "role": role,
                "stage": rec["stage"], "is_basic": _is_basic_pokemon(rec),
                "is_pokemon": _is_pokemon(rec), "prev_stage": rec["prev"],
                "exists": True,
                "copy_cap_ok": cnt <= 4,
            })

        # evolution-prerequisite check (root Basic must be present by name).
        evo_corrections = []
        for cv in cards_validated:
            if not cv.get("exists") or not cv.get("is_pokemon"):
                continue
            if cv.get("is_basic"):
                continue
            root = _root_basic_name(by_id[cv["id"]], by_name)
            cv["root_basic_name"] = root
            if root and root not in present_names:
                # propose a verified Basic correction: prefer the id adjacent to
                # the evolution (same expansion heuristic), else lowest verified id.
                cands = sorted(by_name.get(root, []), key=lambda r: r["id"])
                pick = min(cands, key=lambda r: abs(r["id"] - cv["id"])) \
                    if cands else None
                if pick:
                    evo_corrections.append({
                        "evolution": cv["name"], "evolution_id": cv["id"],
                        "missing_root_basic": root, "added_basic_id": pick["id"],
                        "add_count": 2,
                        "reason": (f"{cv['name']} (id {cv['id']}) is "
                                   f"{cv['stage']} with root Basic '{root}' absent "
                                   f"from skeleton; added verified Basic id "
                                   f"{pick['id']} x2."),
                    })
                    present_names.add(root)
                else:
                    cv["blocked_reason"] = (f"missing root Basic '{root}' and no "
                                            "verified Basic id in DB")

        energy_id, energy_name = _resolve_energy(spec["energy_color"], by_name)
        energy_corr.append({
            "user_specified": f"Basic {spec['energy_color'].title()} Energy (by name)",
            "resolved_card_id": energy_id, "resolved_name": energy_name,
            "note": "energy id resolved from card DB by name, not a user placeholder",
        })

        # Mega Diancie stage read straight from DB (explicit per spec).
        diancie_note = None
        if 766 in [c[0] for c in spec["cards"]]:
            md = by_id.get(766)
            diancie_note = {
                "card": "Mega Diancie ex (766)", "stage_from_db": md["stage"],
                "is_basic": _is_basic_pokemon(md),
                "conclusion": ("Mega Diancie ex IS Basic per DB — deck buildable as "
                               "a Basic toolbox." if _is_basic_pokemon(md) else
                               "Mega Diancie ex is NOT Basic per DB — deck requires "
                               "correction."),
            }

        blocked = [cv for cv in cards_validated if cv.get("blocked_reason")]
        overcap = [cv for cv in cards_validated if cv.get("exists")
                   and cv.get("is_pokemon") is not None and not cv.get("copy_cap_ok")]
        intake_status = "buildable"
        if missing_ids or blocked:
            intake_status = "blocked"
        elif energy_id is None:
            intake_status = "blocked"

        deck_rec = {
            "deck_id": deck_id, "display_name": spec["display_name"],
            "design_class": spec["design_class"], "lane": spec["lane"],
            "special_pilot_required": spec["special_pilot_required"],
            "energy_color": spec["energy_color"],
            "energy_resolution": energy_corr,
            "mega_diancie_stage_check": diancie_note,
            "cards_validated": cards_validated,
            "missing_ids": missing_ids,
            "evolution_corrections": evo_corrections,
            "copy_cap_violations": [{"id": cv["id"], "count": cv["count"]}
                                    for cv in overcap],
            "skeleton_card_total": sum(c[1] for c in spec["cards"]),
            "skeleton_sums_to_60": sum(c[1] for c in spec["cards"]) == 60,
            "intake_status": intake_status,
            "no_invented_ids": not missing_ids,
        }
        decks_out.append(deck_rec)

        yaml_lines += [
            f"  - id: {deck_id}",
            f"    display_name: \"{spec['display_name']}\"",
            f"    design_class: \"{spec['design_class']}\"",
            f"    lane: {spec['lane']}",
            f"    special_pilot_required: {str(spec['special_pilot_required']).lower()}",
            f"    energy_color: {spec['energy_color']}",
            f"    energy_id: {energy_id}",
            f"    intake_status: {intake_status}",
            f"    evolution_corrections: {len(evo_corrections)}",
        ]

    doc = {
        "pass": "34", "part": "C", "local_only": True, "no_upload": True,
        "upload_performed": False,
        "card_db": "data/cards/EN_Card_Data.csv (NOT committed)",
        "note": ("Skeleton counts are a v0 start and need not sum to 60; the "
                 "60-card fill is performed transparently in Part D."),
        "decks": decks_out,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    OUT_YAML.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    L = ["# Pass 34 — New Deck Intake + ID/Stage/Energy Validation (Part C)", "",
         "> LOCAL. No upload. Card ids validated against the local card DB "
         "(never committed). Energy ids resolved by NAME from the DB, not user "
         "placeholders. Evolution prerequisites checked; missing root Basics are "
         "fixed only with VERIFIED ids and reported. Skeleton counts are a v0 "
         "start and need not sum to 60.", ""]
    for d in decks_out:
        L += [f"## {d['display_name']}  (`{d['deck_id']}`)",
              f"- design class: {d['design_class']}",
              f"- lane: **{d['lane']}**  special_pilot_required: "
              f"**{d['special_pilot_required']}**",
              f"- intake status: **{d['intake_status']}**",
              f"- skeleton card total: {d['skeleton_card_total']} "
              f"(sums to 60: {d['skeleton_sums_to_60']})",
              f"- no invented ids: **{d['no_invented_ids']}**  missing ids: "
              f"{d['missing_ids'] or 'none'}",
              f"- energy resolution: {d['energy_resolution'][0]['resolved_name']} "
              f"-> id {d['energy_resolution'][0]['resolved_card_id']}"]
        if d["mega_diancie_stage_check"]:
            md = d["mega_diancie_stage_check"]
            L.append(f"- {md['card']}: stage **{md['stage_from_db']}** — "
                     f"{md['conclusion']}")
        if d["evolution_corrections"]:
            L.append("- evolution corrections:")
            for e in d["evolution_corrections"]:
                L.append(f"  - {e['reason']}")
        else:
            L.append("- evolution corrections: none (all lines complete)")
        if d["copy_cap_violations"]:
            L.append(f"- **copy cap violations:** {d['copy_cap_violations']}")
        L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    for d in decks_out:
        print(f"{d['deck_id']}: {d['intake_status']} "
              f"(evo_corr={len(d['evolution_corrections'])}, "
              f"energy_id={d['energy_resolution'][0]['resolved_card_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
