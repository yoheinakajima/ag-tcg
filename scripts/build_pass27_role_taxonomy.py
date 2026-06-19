#!/usr/bin/env python3
"""Pass 27 (Part D) — cross-deck role taxonomy normalization. LOCAL ONLY.

Defines ONE role vocabulary shared across every portfolio archetype, maps each
card in each deck (from experiments/pass27_portfolio_decks.yaml) to its roles,
and — critically — records which roles the current generic core pilot has NO
runtime support for. Those unsupported roles are the bridge to the Part-J gap
analysis: a deck that leans on an unsupported role is the deck the one pilot
cannot drive.

No invented cards: every id is taken straight from the deck registry (which is
itself validated against data/cards/EN_Card_Data.csv). Energy roles are assigned
per deck by copy-count (dominant basic = primary_energy).

Writes docs/CORE_PILOT_ROLE_TAXONOMY.md, data/experiments/pass27_role_taxonomy.json
and .md. No upload, no root edits.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore

REPO = Path(__file__).resolve().parents[1]
DECKS = REPO / "experiments" / "pass27_portfolio_decks.yaml"
EXP = REPO / "data" / "experiments"
DOC = REPO / "docs" / "CORE_PILOT_ROLE_TAXONOMY.md"

ROLE_VOCAB = {
    "pokemon": ["setup_basic", "backup_basic", "primary_basic_attacker",
                "primary_evolution_attacker", "secondary_attacker", "evolution_mid",
                "evolution_payoff", "ramp_engine", "draw_engine_pokemon",
                "utility_pokemon", "wall", "mill_attacker", "spread_attacker",
                "finisher"],
    "trainer": ["search_cards", "draw_support", "disruption", "gust", "recovery",
                "rare_candy", "stadium_engine", "tool_damage", "tool_defense",
                "energy_search", "energy_acceleration", "switch_or_retreat",
                "deck_conservation", "recursion", "chaos_payoff"],
    "energy": ["primary_energy", "secondary_energy", "splash_energy",
               "discard_fuel", "ramp_fuel"],
}

# Roles the CURRENT generic core pilot has no dedicated runtime support for.
# It can still place/play these cards legally, but it does not pilot the role's
# intent (e.g. it will not target spread damage or pursue a deckout win).
UNSUPPORTED_RUNTIME_ROLES = {
    "spread_attacker": "no bench-damage target selection; attacks default target",
    "ramp_engine": "no energy-ramp accumulation plan; attaches greedily/at random",
    "mill_attacker": "no deckout/mill win condition; races prizes instead",
    "finisher": "no lethal-counting/all-in timing; cannot recognise a closing turn",
    "chaos_payoff": "no chaos/stall win condition; will misplay the carousel",
    "recursion": "no recursion loop planning for a mill/value engine",
    "energy_acceleration": ("attaches without a colour/scaling plan; cannot "
                            "sequence selective acceleration"),
}

# Curated card -> (canonical name, [roles]). Names/roles come from the registry's
# own annotations; ids are validated there. Energy ids handled separately.
CARD_ROLES: dict[int, tuple[str, list[str]]] = {
    721: ("Kyogre", ["primary_basic_attacker"]),
    722: ("Snover", ["setup_basic"]),
    723: ("Mega Abomasnow ex", ["evolution_payoff", "primary_evolution_attacker"]),
    1092: ("Secret Box", ["search_cards"]),
    1121: ("Ultra Ball", ["search_cards"]),
    1145: ("Mega Signal", ["search_cards"]),
    1163: ("Powerglass", ["energy_acceleration", "tool_defense"]),
    1219: ("Team Rocket's Petrel", ["draw_support"]),
    1227: ("Lillie's Determination", ["draw_support"]),
    1262: ("Surfing Beach", ["stadium_engine"]),
    63: ("Raging Bolt ex", ["primary_basic_attacker", "finisher"]),
    96: ("Teal Mask Ogerpon ex", ["secondary_attacker", "draw_engine_pokemon"]),
    1198: ("Crispin", ["energy_search", "energy_acceleration"]),
    1231: ("Dawn", ["draw_support", "energy_acceleration"]),
    1224: ("Cheren", ["draw_support"]),
    1086: ("Buddy-Buddy Poffin", ["search_cards"]),
    1182: ("Boss's Orders", ["gust"]),
    1097: ("Night Stretcher", ["recovery"]),
    119: ("Dreepy", ["setup_basic"]),
    120: ("Drakloak", ["evolution_mid"]),
    121: ("Dragapult ex", ["evolution_payoff", "spread_attacker"]),
    131: ("Duskull", ["setup_basic", "utility_pokemon"]),
    133: ("Dusknoir", ["utility_pokemon", "spread_attacker"]),
    1079: ("Rare Candy", ["rare_candy"]),
    198: ("Durant ex", ["mill_attacker"]),
    227: ("Deino", ["setup_basic"]),
    228: ("Zweilous", ["evolution_mid", "wall"]),
    162: ("Slowpoke", ["utility_pokemon"]),
    27: ("Iron Leaves", ["secondary_attacker", "utility_pokemon"]),
    815: ("Whimsicott", ["draw_engine_pokemon", "utility_pokemon"]),
    1199: ("Lacey", ["draw_support"]),
    1228: ("Acerola's Mischief", ["recursion", "recovery"]),
    1213: ("Judge", ["disruption", "draw_support"]),
    1247: ("Neutralization Zone", ["stadium_engine", "chaos_payoff"]),
    745: ("Ralts", ["setup_basic"]),
    746: ("Kirlia", ["evolution_mid", "ramp_engine"]),
    747: ("Mega Gardevoir ex", ["evolution_payoff", "finisher", "ramp_engine"]),
    788: ("Charmander", ["setup_basic"]),
    789: ("Charmeleon", ["evolution_mid"]),
    790: ("Mega Charizard X ex", ["evolution_payoff", "finisher"]),
    795: ("Oricorio ex", ["backup_basic", "secondary_attacker"]),
    1232: ("Firebreather", ["energy_acceleration"]),
    650: ("Bulbasaur", ["setup_basic"]),
    651: ("Ivysaur", ["evolution_mid"]),
    652: ("Mega Venusaur ex", ["evolution_payoff", "wall"]),
    1261: ("Forest of Vitality", ["stadium_engine", "energy_acceleration"]),
}

ENERGY_NAMES = {1: "Basic {G}", 2: "Basic {R}", 3: "Basic {W}", 4: "Basic {L}",
                5: "Basic {P}", 6: "Basic {F}", 7: "Basic {D}", 8: "Basic {M}"}
BASIC_ENERGY_IDS = set(ENERGY_NAMES)


def _energy_roles(deck_cards: dict[int, int]) -> dict[int, tuple[str, list[str]]]:
    energies = {cid: n for cid, n in deck_cards.items() if cid in BASIC_ENERGY_IDS}
    if not energies:
        return {}
    ranked = sorted(energies.items(), key=lambda kv: kv[1], reverse=True)
    out = {}
    for i, (cid, _n) in enumerate(ranked):
        role = "primary_energy" if i == 0 else (
            "secondary_energy" if i == 1 else "splash_energy")
        out[cid] = (f"{ENERGY_NAMES[cid]} Energy", [role])
    return out


def main() -> int:
    reg = yaml.safe_load(DECKS.read_text(encoding="utf-8"))
    decks = reg["decks"]

    deck_maps = {}
    missing_role_cards: dict[str, list[int]] = {}
    all_roles_seen: set[str] = set()
    for key, spec in decks.items():
        cards = {int(k): int(v) for k, v in (spec.get("cards") or {}).items()}
        emap = _energy_roles(cards)
        rows = []
        for cid, count in cards.items():
            if cid in emap:
                name, roles = emap[cid]
            elif cid in CARD_ROLES:
                name, roles = CARD_ROLES[cid]
            else:
                name, roles = (f"card_{cid}", [])
                missing_role_cards.setdefault(key, []).append(cid)
            all_roles_seen.update(roles)
            rows.append({"card_id": cid, "name": name, "count": count, "roles": roles})
        deck_unsupported = sorted({r for row in rows for r in row["roles"]
                                   if r in UNSUPPORTED_RUNTIME_ROLES})
        deck_maps[key] = {
            "candidate_id": spec.get("candidate_id"),
            "family": spec.get("family"), "archetype": spec.get("archetype"),
            "buildable": bool(spec.get("buildable")),
            "blocked_from_league": bool(spec.get("blocked_from_league")),
            "cards": rows,
            "roles_present": sorted({r for row in rows for r in row["roles"]}),
            "unsupported_runtime_roles": deck_unsupported,
        }

    taxonomy = {
        "pass": "27", "part": "D", "local_only": True, "upload_performed": False,
        "schema": "activegraph.pass27.role_taxonomy/v1",
        "role_vocabulary": ROLE_VOCAB,
        "unsupported_runtime_roles": UNSUPPORTED_RUNTIME_ROLES,
        "roles_seen_in_portfolio": sorted(all_roles_seen),
        "cards_without_mapped_role": missing_role_cards,
        "decks": deck_maps,
        "note": ("Unsupported roles mean the generic pilot can legally place the "
                 "card but does not pilot the role's intent; they are the direct "
                 "input to the Part-J core gameplay gap analysis."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass27_role_taxonomy.json").write_text(
        json.dumps(taxonomy, indent=2), encoding="utf-8")

    L = ["# Pass 27 — Role Taxonomy (Part D)", "",
         "> LOCAL ONLY. One role vocabulary shared across all archetypes. "
         "Cards taken from the validated deck registry — no invented ids.", "",
         "## Role vocabulary", ""]
    for group, roles in ROLE_VOCAB.items():
        L.append(f"- **{group}**: " + ", ".join(f"`{r}`" for r in roles))
    L += ["", "## Roles with NO generic-pilot runtime support", "",
          "| role | why unsupported |", "|---|---|"]
    for r, why in UNSUPPORTED_RUNTIME_ROLES.items():
        L.append(f"| `{r}` | {why} |")
    L += ["", "## Per-deck role maps", ""]
    for key, dm in deck_maps.items():
        L += [f"### {key} — `{dm['candidate_id']}` ({dm['archetype']})",
              f"- buildable: {dm['buildable']}  blocked_from_league: "
              f"{dm['blocked_from_league']}",
              f"- roles present: {', '.join('`'+r+'`' for r in dm['roles_present'])}",
              (f"- **unsupported roles this deck leans on:** "
               + (", ".join('`'+r+'`' for r in dm['unsupported_runtime_roles'])
                  or "none")), "",
              "| card | name | n | roles |", "|---|---|---|---|"]
        for c in dm["cards"]:
            L.append(f"| {c['card_id']} | {c['name']} | {c['count']} | "
                     + ", ".join(c["roles"]) + " |")
        L.append("")
    if missing_role_cards:
        L += ["## Cards without a mapped role (flagged honestly)", ""]
        for key, ids in missing_role_cards.items():
            L.append(f"- {key}: {ids}")
        L.append("")
    L += [f"_{taxonomy['note']}_", ""]
    md = "\n".join(L)
    (EXP / "pass27_role_taxonomy.md").write_text(md, encoding="utf-8")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(md, encoding="utf-8")

    print(f"decks mapped: {len(deck_maps)}  roles seen: {len(all_roles_seen)}")
    print(f"cards without role: {missing_role_cards or 'none'}")
    print(f"-> {(EXP / 'pass27_role_taxonomy.json').relative_to(REPO)} + docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
