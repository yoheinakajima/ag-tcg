#!/usr/bin/env python3
"""PASS 46J (Part B) — Diamond source / deck audit for ``diamond_toolbox_diancie``.

READ-ONLY. Audits the INTERNAL parent deck this pass builds a specialist planner for:

  * resolves the canonical parent tarball (candidates_pass34 — the registered/pool path and
    Pass-46H ``parent_source_tarball``) and records main.py / deck.csv / tarball sha256;
    also records the candidates_pass35 sibling (byte-identical deck, later main.py revision);
  * verifies the 60-card deck is legal and EVERY card id resolves in data/cards/EN_Card_Data.csv
    (NO invented ids) — uses the audited ``pilot_typed.compiler`` classifier;
  * copy counts; basic / energy / trainer counts; search / draw counts; evolution requirements;
  * derives coarse deck ROLES from verified card metadata + the existing deck only. Card type /
    stage / ex / hp / retreat are READ from the card DB; attacker / ability / functional tags
    are computed across ALL of a card's move rows (a card spans one CSV row per move, so the
    single-row 46H ``classify_card_roles`` token is kept only for cross-reference). Every
    heuristic GROUPING (main/backup attacker, setup/support, discard-sensitive) is marked
    explicitly ``inferred``.

Honesty: role buckets, functional tags, and the attacker/backup/setup groupings are coarse
deck-composition labels and inferences from copy-count / HP / ex / attack-presence / effect
text. They assert NO card value, tempo, exact damage, lethal, missed-KO, forced-switch/gust
targeting, spread, or "best" card. No hidden zones are read (deck list only).

Writes data/experiments/pass46j_diamond_source_audit.{json,md}. Mutates nothing.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.pilot_typed.compiler import build_metadata_table  # noqa: E402
from ptcg_activegraph.analysis.option_value_features import classify_card_roles  # noqa: E402

EXP = REPO / "data" / "experiments"
CARD_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
PARENT_ID = "diamond_toolbox_diancie"
PARENT_TARBALL = REPO / "data" / "submissions" / "candidates_pass34" / f"{PARENT_ID}.tar.gz"
SIBLING_TARBALL = REPO / "data" / "submissions" / "candidates_pass35" / f"{PARENT_ID}.tar.gz"
STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"

_NA = ("", "n/a", "N/A", "None")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tar_member_shas(tarball: Path) -> dict:
    out = {"tarball_present": tarball.exists(), "tarball_sha256": None,
           "main_py_sha256": None, "deck_csv_sha256": None, "members": []}
    if not tarball.exists():
        return out
    out["tarball_sha256"] = _sha(tarball.read_bytes())
    with tarfile.open(tarball, "r:gz") as tar:
        out["members"] = sorted(m.name for m in tar.getmembers() if m.isfile())
        for nm, key in (("main.py", "main_py_sha256"), ("deck.csv", "deck_csv_sha256")):
            try:
                out[key] = _sha(tar.extractfile(nm).read())
            except Exception:  # noqa: BLE001
                pass
    return out


def _read_deck_ids(tarball: Path) -> list[int]:
    with tarfile.open(tarball, "r:gz") as tar:
        raw = tar.extractfile("deck.csv").read().decode("utf-8")
    return [int(x) for x in raw.split() if x.strip()]


def _all_rows_by_id(card_csv: Path, wanted: set[int]) -> dict[int, list[dict]]:
    """Read ALL CSV rows (cards span multiple move rows) for ``wanted`` ids."""
    rows: dict[int, list[dict]] = defaultdict(list)
    if not card_csv.exists():
        return rows
    with card_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int(str(row.get("Card ID")).strip())
            except (TypeError, ValueError):
                continue
            if cid in wanted:
                rows[cid].append(row)
    return rows


def _clean(v) -> str:
    s = str(v or "").strip()
    return "" if s in _NA else s


def _parse_moves(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a card's rows into (attack moves, abilities) across ALL rows."""
    attacks: list[dict] = []
    abilities: list[dict] = []
    for r in rows:
        mv = _clean(r.get("Move Name"))
        if not mv:
            continue
        eff = _clean(r.get("Effect Explanation"))
        if mv.lower().startswith("[ability]"):
            abilities.append({"name": mv.replace("[Ability]", "").strip() or mv,
                              "effect": eff})
        else:
            attacks.append({"name": mv, "cost": _clean(r.get("Cost")),
                            "damage": _clean(r.get("Damage")), "effect": eff})
    return attacks, abilities


def _all_effect_text(rows: list[dict]) -> str:
    """Lower-cased concatenation of EVERY row's Effect Explanation (trainers carry their
    effect on a Move Name == 'n/a' row, so move-only parsing would miss them)."""
    return " ".join(_clean(r.get("Effect Explanation")).lower() for r in rows)


def _functional_tags(text: str, attacks: list[dict], meta: dict) -> list[str]:
    """Honest, phrase-derived functional descriptors (inferred, not facts)."""
    tags: list[str] = []
    ctype = (meta or {}).get("card_type")
    searches_pkmn = "search your deck for" in text and ("pokémon" in text or "pokemon" in text)
    searches_energy = "search your deck for" in text and "energy" in text
    to_bench = "onto your bench" in text or "to your bench" in text or "your bench" in text
    if searches_energy and "attach" in text:
        tags.append("energy_accel_from_deck")
    elif searches_energy:
        tags.append("energy_search_to_hand")
    if searches_pkmn and to_bench:
        tags.append("pokemon_search_to_bench")
    elif searches_pkmn:
        tags.append("pokemon_search_to_hand")
    if "heal" in text:
        tags.append("healer")
    if "draw" in text:
        tags.append("draw")
    if "switch in 1 of your opponent" in text or ("switch" in text and "opponent" in text):
        tags.append("opponent_switch_disruption")
    if "less damage from attacks" in text:
        tags.append("damage_reduction_ability")
    if "use attacks during your first turn" in text:
        tags.append("turn1_attack_ability")
    if ("more damage" in text) and ("{ex}" in text or "pokémon ex" in text or "ex," in text):
        tags.append("anti_ex_tech")
    if "use it as this attack" in text or "choose 1 of your opponent" in text:
        tags.append("copy_attack_tech")
    if ctype == "pokemon":
        for a in attacks:
            if "120" in a["damage"] and "×" in a["damage"]:
                tags.append("scaling_discard_attacker")
                break
    # de-dup, preserve order
    seen: set[str] = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    parent = _tar_member_shas(PARENT_TARBALL)
    sibling = _tar_member_shas(SIBLING_TARBALL)
    deck_ids = _read_deck_ids(PARENT_TARBALL)
    counts = Counter(deck_ids)
    unique_ids = sorted(counts)
    wanted = set(unique_ids)

    metatable = build_metadata_table(str(CARD_CSV), unique_ids)
    rows_by_id = _all_rows_by_id(CARD_CSV, wanted)

    cards: list[dict] = []
    unknown_ids: list[int] = []
    for cid in unique_ids:
        meta = metatable.get(cid)
        rows = rows_by_id.get(cid, [])
        first = rows[0] if rows else {}
        if meta is None or not first:
            unknown_ids.append(cid)
        attacks, abilities = _parse_moves(rows)
        damage_attacks = [a for a in attacks if a["damage"]]
        tokens_single_row = classify_card_roles(meta or {}, first)  # 46H single-row, x-ref
        fn_tags = _functional_tags(_all_effect_text(rows), attacks, meta or {})
        cards.append({
            "card_id": cid,
            "copies": counts[cid],
            "name": (meta or {}).get("name") or first.get("Card Name"),
            "known_in_card_db": meta is not None and bool(first),
            "card_type": (meta or {}).get("card_type"),
            "stage": (meta or {}).get("stage"),
            "is_basic_pokemon": bool((meta or {}).get("is_basic_pokemon")),
            "is_basic_energy": bool((meta or {}).get("is_basic_energy")),
            "hp": (meta or {}).get("hp"),
            "retreat_cost": (meta or {}).get("retreat_cost"),
            "energy_type": (meta or {}).get("energy_type"),
            "ex": bool((meta or {}).get("ex")),
            "stage_type_col": first.get(STAGE_COL),
            "attacks": attacks,
            "abilities": abilities,
            "has_attack_move": attacks != [],
            "is_damage_attacker": damage_attacks != [],
            "has_ability": abilities != [],
            "functions_inferred": fn_tags,
            "role_tokens_46h_single_row": tokens_single_row,
        })

    by_id = {c["card_id"]: c for c in cards}

    def is_type(c, t):
        return c["card_type"] == t

    def has_fn(c, tag):
        return tag in c["functions_inferred"]

    energy_cards = [c["card_id"] for c in cards if is_type(c, "energy")]
    pokemon_cards = [c["card_id"] for c in cards if is_type(c, "pokemon")]
    trainer_cards = [c["card_id"] for c in cards if is_type(c, "trainer")]
    basic_pokemon = [c["card_id"] for c in cards
                     if is_type(c, "pokemon") and c["is_basic_pokemon"]]
    evolution_pokemon = [c["card_id"] for c in cards
                         if is_type(c, "pokemon") and not c["is_basic_pokemon"]]
    damage_attacker_pokemon = [c["card_id"] for c in cards
                               if is_type(c, "pokemon") and c["is_damage_attacker"]]
    ability_pokemon = [c["card_id"] for c in cards
                       if is_type(c, "pokemon") and c["has_ability"]]
    # search/draw counted across ALL rows via functional tags
    search_card_ids = [c["card_id"] for c in cards
                       if {"pokemon_search_to_bench", "pokemon_search_to_hand",
                           "energy_search_to_hand", "energy_accel_from_deck"}
                       & set(c["functions_inferred"])]
    draw_card_ids = [c["card_id"] for c in cards if has_fn(c, "draw")]
    energy_accel_ids = [c["card_id"] for c in cards if has_fn(c, "energy_accel_from_deck")]
    healer_ids = [c["card_id"] for c in cards if has_fn(c, "healer")]
    disruption_ids = [c["card_id"] for c in cards if has_fn(c, "opponent_switch_disruption")]
    bench_fill_ids = [c["card_id"] for c in cards if has_fn(c, "pokemon_search_to_bench")]

    # --- INFERRED groupings (heuristic; explicitly not asserted as fact) -------------------
    # Main attacker candidate: damage-attacker Pokémon ranked by (copies, hp, ex). Inference
    # from deck composition only — NOT a claim the card is strongest/optimal.
    ranked = sorted(
        (c for c in cards if c["card_id"] in damage_attacker_pokemon),
        key=lambda c: (c["copies"], c["hp"] or 0, 1 if c["ex"] else 0), reverse=True)
    main_attacker_candidates = [c["card_id"] for c in ranked[:1]]
    backup_attacker_candidates = [c["card_id"] for c in ranked[1:]]
    # Setup/support Pokémon: provide search / energy-accel / heal / turn-1 enable, and are not
    # the main attacker.
    setup_support_pokemon = [
        c["card_id"] for c in cards
        if is_type(c, "pokemon") and c["card_id"] not in main_attacker_candidates
        and ({"pokemon_search_to_bench", "pokemon_search_to_hand", "energy_search_to_hand",
              "energy_accel_from_deck", "healer", "turn1_attack_ability"}
             & set(c["functions_inferred"]))]
    # Discard-sensitive: energy + main attacker(s) — losing them most disrupts the plan.
    discard_sensitive = sorted(set(energy_cards) | set(main_attacker_candidates))

    total = sum(counts.values())
    over_limit = {cid: counts[cid] for cid in unique_ids
                  if counts[cid] > 4 and not by_id[cid]["is_basic_energy"]}
    legal_60 = total == 60
    all_known = unknown_ids == []
    legal = legal_60 and all_known and not over_limit

    n_basic = sum(counts[c] for c in basic_pokemon)
    n_energy = sum(counts[c] for c in energy_cards)
    n_trainer = sum(counts[c] for c in trainer_cards)
    n_pokemon = sum(counts[c] for c in pokemon_cards)
    n_search = sum(counts[c] for c in search_card_ids)
    n_draw = sum(counts[c] for c in draw_card_ids)
    pkmn_types = sorted({by_id[c]["energy_type"] for c in pokemon_cards
                         if by_id[c]["energy_type"]})

    deck_equal_sibling = (parent["deck_csv_sha256"] == sibling["deck_csv_sha256"]
                          and sibling["deck_csv_sha256"] is not None)

    data = {
        "pass": "46j", "part": "B", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "parent_id": PARENT_ID,
        "canonical_parent_tarball": str(PARENT_TARBALL.relative_to(REPO)),
        "canonical_parent": parent,
        "sibling_parent_tarball": str(SIBLING_TARBALL.relative_to(REPO)),
        "sibling_parent": sibling,
        "deck_equal_between_pass34_pass35": deck_equal_sibling,
        "sibling_main_py_differs": (parent["main_py_sha256"] != sibling["main_py_sha256"]),
        "card_db_csv": str(CARD_CSV.relative_to(REPO)),
        "deck_total_cards": total,
        "deck_unique_cards": len(unique_ids),
        "pokemon_energy_types": pkmn_types,
        "copy_counts": {str(k): counts[k] for k in unique_ids},
        "legality": {
            "exactly_60": legal_60,
            "all_card_ids_known": all_known,
            "unknown_card_ids": unknown_ids,
            "over_4_copy_non_basic_energy": {str(k): v for k, v in over_limit.items()},
            "legal": legal,
        },
        "composition": {
            "pokemon_count": n_pokemon, "basic_pokemon_count": n_basic,
            "evolution_pokemon_count": sum(counts[c] for c in evolution_pokemon),
            "energy_count": n_energy, "trainer_count": n_trainer,
            "search_card_count": n_search, "draw_card_count": n_draw,
        },
        "evolution_requirements": {
            "has_evolution_pokemon": evolution_pokemon != [],
            "evolution_pokemon_ids": evolution_pokemon,
            "note": "all Pokémon are Basic; no evolution lines / pre-stage requirements"
                    if evolution_pokemon == [] else "deck contains evolution Pokémon",
        },
        "roles_verified_from_metadata": {
            "energy_cards": energy_cards,
            "basic_pokemon": basic_pokemon,
            "evolution_pokemon": evolution_pokemon,
            "trainer_cards": trainer_cards,
            "damage_attacker_pokemon": damage_attacker_pokemon,
            "ability_pokemon": ability_pokemon,
            "search_cards": search_card_ids,
            "draw_cards": draw_card_ids,
            "energy_accel_cards": energy_accel_ids,
            "healer_cards": healer_ids,
            "bench_fill_cards": bench_fill_ids,
            "opponent_switch_disruption_cards": disruption_ids,
        },
        "roles_inferred": {
            "_disclaimer": "INFERRED heuristic groupings from copy-count / HP / ex / "
                           "attack-presence / effect text; NOT facts and NOT value/strength/"
                           "damage/lethal/gust claims. No hidden zones read.",
            "main_attacker_candidates": main_attacker_candidates,
            "backup_attacker_candidates": backup_attacker_candidates,
            "setup_support_pokemon": setup_support_pokemon,
            "discard_sensitive": discard_sensitive,
        },
        "cards": cards,
        "card_ids_all_resolved": all_known,
        "no_invented_card_ids": all_known,
    }
    (EXP / "pass46j_diamond_source_audit.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def nm(cid):
        return f"{cid} {by_id[cid]['name']}×{counts[cid]}"

    md = [
        "# Pass 46J — Part B: Diamond source / deck audit", "",
        f"Parent (internal): `{PARENT_ID}` — canonical tarball "
        f"`{PARENT_TARBALL.relative_to(REPO)}`.", "",
        "> READ-ONLY. Card type/stage/ex/hp/retreat are READ from the local card DB; "
        "attacker/ability/functional tags are computed across ALL of a card's move rows. "
        "Role buckets, functional tags, and attacker/backup/setup groupings are coarse "
        "deck-composition labels and inferences (copy-count / HP / ex / attack-presence / "
        "effect text). They assert NO card value, tempo, exact damage, lethal, missed-KO, "
        "forced-switch/gust targeting, spread, or 'best' card. No hidden zones are read "
        "(deck list only). Every card id is verified against the local card DB (no invented "
        "ids).", "",
        "## Source tarballs",
        f"- canonical (pass34): tarball=`{parent['tarball_sha256']}` "
        f"main.py=`{parent['main_py_sha256']}` deck.csv=`{parent['deck_csv_sha256']}`",
        f"- sibling (pass35): tarball=`{sibling['tarball_sha256']}` "
        f"main.py=`{sibling['main_py_sha256']}` deck.csv=`{sibling['deck_csv_sha256']}`",
        f"- deck byte-identical pass34==pass35: **{deck_equal_sibling}**; sibling main.py "
        f"differs: **{parent['main_py_sha256'] != sibling['main_py_sha256']}** (pass35 carries "
        "a later typed-strategy override; pass34 is the registered parent).", "",
        "## Legality",
        f"- total cards: **{total}** (exactly 60: {legal_60})",
        f"- unique cards: {len(unique_ids)} | all ids known: **{all_known}** | "
        f"unknown: {unknown_ids or 'none'}",
        f"- non-(basic-energy) over-4 copies: "
        f"{data['legality']['over_4_copy_non_basic_energy'] or 'none'}",
        f"- **legal = {legal}**", "",
        "## Composition",
        f"- Pokémon: {n_pokemon} (Basic {n_basic} / Evolution "
        f"{data['composition']['evolution_pokemon_count']}); types: {pkmn_types}",
        f"- Energy: {n_energy} | Trainer: {n_trainer}",
        f"- search cards: {n_search} | draw cards: {n_draw}",
        f"- evolution requirements: {data['evolution_requirements']['note']}", "",
        "## Cards (verified)",
        "| id×copies | name | type | hp | rtr | ex | attacks (dmg) | abilities | "
        "functions (inferred) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cards:
        atk = ", ".join(f"{a['name']}({a['damage'] or '—'})" for a in c["attacks"]) or "—"
        ab = ", ".join(a["name"] for a in c["abilities"]) or "—"
        md.append(
            f"| {c['card_id']}×{c['copies']} | {c['name']} | "
            f"{c['card_type']}{('/'+c['stage']) if c['stage'] else ''} | {c['hp']} | "
            f"{c['retreat_cost']} | {'Y' if c['ex'] else ''} | {atk} | {ab} | "
            f"{', '.join(c['functions_inferred']) or '—'} |")
    md += [
        "", "## Roles verified from metadata",
        f"- energy: {[nm(c) for c in energy_cards]}",
        f"- basic Pokémon: {[nm(c) for c in basic_pokemon]}",
        f"- damage-attacker Pokémon: {[nm(c) for c in damage_attacker_pokemon]}",
        f"- ability Pokémon: {[nm(c) for c in ability_pokemon]}",
        f"- search cards: {[nm(c) for c in search_card_ids]}",
        f"- draw cards: {[nm(c) for c in draw_card_ids]}",
        f"- energy-accel cards: {[nm(c) for c in energy_accel_ids] or 'none'}",
        f"- healer cards: {[nm(c) for c in healer_ids] or 'none'}",
        f"- bench-fill (search-to-bench) cards: {[nm(c) for c in bench_fill_ids] or 'none'}",
        f"- opponent-switch disruption cards: {[nm(c) for c in disruption_ids] or 'none'}",
        "", "## Roles inferred (heuristic — not facts)",
        f"- main attacker candidate: {[nm(c) for c in main_attacker_candidates]}",
        f"- backup attacker candidates: {[nm(c) for c in backup_attacker_candidates]}",
        f"- setup/support Pokémon: {[nm(c) for c in setup_support_pokemon]}",
        f"- discard-sensitive (energy + main attacker): {[nm(c) for c in discard_sensitive]}",
        "",
        f"**card_ids_all_resolved = {all_known}** — **no_invented_card_ids = {all_known}**",
    ]
    (EXP / "pass46j_diamond_source_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "legal": legal, "exactly_60": legal_60, "all_known": all_known,
        "unknown_ids": unknown_ids, "unique": len(unique_ids),
        "pokemon_energy_types": pkmn_types,
        "composition": data["composition"],
        "main_attacker_candidates": [nm(c) for c in main_attacker_candidates],
        "backup_attacker_candidates": [nm(c) for c in backup_attacker_candidates],
        "setup_support_pokemon": [nm(c) for c in setup_support_pokemon],
        "deck_equal_pass34_pass35": deck_equal_sibling,
    }, indent=2, default=str))
    return 0 if legal else 1


if __name__ == "__main__":
    raise SystemExit(main())
