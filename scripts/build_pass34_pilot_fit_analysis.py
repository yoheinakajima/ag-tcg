#!/usr/bin/env python3
"""Pass 34 Part J — Composition + pilot-fit analysis. LOCAL. no upload.

Compares the tournament decks (Water basic-density, Dragapult search_only,
Miraidon, Diamond, Charizard, Venusaur, Gardevoir) plus the Toxic/Durant
special-lane status. Structural metrics (basic density, energy simplicity,
mono/multi color, evolution complexity, unique cards) are computed honestly from
each deck's deck.csv against the local card DB; deck/pilot compatibility is taken
from the internal tournament standings (Part H).

Honesty note: fine-grained per-game telemetry (no-pokemon losses, first attack
turn, attack conversion, effect-loop count) was NOT separately instrumented in
Pass 34 — the tournament stored aggregate W-L-D only. Those fields are reported
as "not_instrumented" with win-rate/draws used as the compatibility proxy, never
fabricated.
"""
from __future__ import annotations

import csv
import io
import json
import tarfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"

RANKINGS = EXP / "pass34_new_deck_rankings.json"
PROGRESS = EXP / "pass34_new_deck_tournament_progress.json"
DIAGNOSIS = EXP / "pass34_special_lane_diagnosis.json"

OUT_JSON = EXP / "pass34_pilot_fit_analysis.json"
OUT_MD = EXP / "pass34_pilot_fit_analysis.md"

NEW_DECKS = {"mono_lightning_miraidon_easy", "diamond_toolbox_diancie"}


def _load_card_db() -> dict:
    db = {}
    with CARD_DB.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int(str(row["Card ID"]).strip())
            except (ValueError, KeyError):
                continue
            db[cid] = {
                "name": row.get("Card Name", "").strip(),
                "stage": row.get(
                    "Stage (Pokémon)/Type (Energy and Trainer)", "").strip(),
                "type": (row.get("Type") or "").strip(),
                "prev": (row.get("Previous stage") or "").strip(),
            }
    return db


def _deck_counts_from_tarball(tar_path: Path) -> Counter:
    with tarfile.open(tar_path) as t:
        member = next((m for m in t.getmembers()
                       if m.name.endswith("deck.csv")), None)
        if member is None:
            return Counter()
        data = t.extractfile(member).read().decode("utf-8")
    counts = Counter()
    reader = csv.reader(io.StringIO(data))
    rows = list(reader)
    # tolerate header
    start = 1 if rows and not rows[0][0].strip().isdigit() else 0
    for r in rows[start:]:
        if not r:
            continue
        try:
            counts[int(str(r[0]).strip())] += 1
        except ValueError:
            continue
    return counts


_COLOR_CANON = {
    "{L}": "Lightning", "lightning": "Lightning", "l": "Lightning",
    "{P}": "Psychic", "psychic": "Psychic",
    "{D}": "Darkness", "darkness": "Darkness", "dark": "Darkness",
    "{W}": "Water", "water": "Water",
    "{R}": "Fire", "fire": "Fire",
    "{G}": "Grass", "grass": "Grass",
    "{F}": "Fighting", "fighting": "Fighting",
    "{M}": "Metal", "metal": "Metal", "steel": "Metal",
    "{Y}": "Fairy", "fairy": "Fairy",
    "{C}": "Colorless", "colorless": "Colorless",
    "{N}": "Dragon", "dragon": "Dragon", "竜": "Dragon",
}


def _canon_colors(token: str) -> set:
    """Map a raw type/energy token to a canonical color, dropping encoding noise.

    Colorless is the universal cost and is NOT counted toward a deck's color
    identity (a mono deck splashing Colorless costs is still mono)."""
    out = set()
    for part in token.split("/"):
        key = part.strip().lower()
        canon = _COLOR_CANON.get(part.strip()) or _COLOR_CANON.get(key)
        if canon and canon != "Colorless":
            out.add(canon)
    return out


def _metrics(counts: Counter, db: dict) -> dict:
    total = sum(counts.values())
    pokemon = basics = stage1 = stage2 = basic_energy = 0
    colors = set()
    unknown = []
    for cid, n in counts.items():
        info = db.get(cid)
        if info is None:
            unknown.append(cid)
            continue
        stage = info["stage"].lower()
        if "pok" in stage:  # Pokémon
            pokemon += n
            if "basic" in stage:
                basics += n
            elif "stage 1" in stage:
                stage1 += n
            elif "stage 2" in stage:
                stage2 += n
            if info["type"]:
                colors |= _canon_colors(info["type"])
        elif "energy" in stage:
            if "basic" in stage:
                basic_energy += n
                colors |= _canon_colors(info["name"])
    energy_colors = sorted(colors)
    return {
        "total_cards": total,
        "unique_ids": len(counts),
        "pokemon_count": pokemon,
        "basic_pokemon_count": basics,
        "stage1_count": stage1,
        "stage2_count": stage2,
        "evolution_cards": stage1 + stage2,
        "basic_energy_count": basic_energy,
        "basic_pokemon_density": round(basics / pokemon, 3) if pokemon else None,
        "pokemon_color_count": len(energy_colors),
        "colors": energy_colors,
        "mono_color": len(energy_colors) <= 1,
        "evolution_complexity": (
            "none" if (stage1 + stage2) == 0
            else "stage1_only" if stage2 == 0 else "stage2_lines"),
        "unknown_card_ids": unknown,
    }


FAMILY_NOTES = {
    "water_basic_density_v1": "high-Basic Water density build (Pass 33 winner)",
    "league_water_anti_disruption_pivot_v1": "Water anti-disruption pivot (current Water reference)",
    "league_dragapult_v1_search_only": "Dragapult search-only (non-Water reference)",
    "mono_lightning_miraidon_easy": "NEW: simple mono-Lightning Basic ex, low decision density",
    "diamond_toolbox_diancie": "NEW: mono-Psychic Mega Diancie ex Basic toolbox",
    "league_mega_charizard_x_burst": "Mega Charizard X burst (evolution/attacker)",
    "league_mega_venusaur_tank": "Mega Venusaur tank (stall-prone: 10 draws)",
    "league_mega_gardevoir_psychic_ramp": "Mega Gardevoir psychic ramp (collapses under generic pilot)",
}


def main() -> int:
    db = _load_card_db()
    rankings = json.loads(RANKINGS.read_text(encoding="utf-8"))["standings"]
    rank_by = {r["id"]: i + 1 for i, r in enumerate(rankings)}
    rank_row = {r["id"]: r for r in rankings}
    tarballs = json.loads(PROGRESS.read_text(encoding="utf-8"))["tarball_paths"]
    diag = {d["candidate_id"]: d
            for d in json.loads(DIAGNOSIS.read_text(encoding="utf-8"))["diagnoses"]}

    decks = []
    for cid, tar in tarballs.items():
        p = Path(tar)
        counts = _deck_counts_from_tarball(p) if p.exists() else Counter()
        m = _metrics(counts, db)
        r = rank_row.get(cid, {})
        decks.append({
            "id": cid,
            "family": r.get("family"),
            "is_new_deck": cid in NEW_DECKS,
            "rank": rank_by.get(cid),
            "adj_win_rate": r.get("adj_win_rate"),
            "wilson": r.get("wilson"),
            "wins": r.get("wins"), "losses": r.get("losses"), "draws": r.get("draws"),
            "invalids": r.get("invalids"), "timeouts": r.get("timeouts"),
            "crashes": r.get("crashes"),
            "compatibility_label": r.get("compatibility_label"),
            "family_note": FAMILY_NOTES.get(cid, ""),
            **m,
            "needs_non_attack_win_condition": False,
            "not_instrumented": [
                "no_pokemon_losses", "first_attack_turn", "attack_conversion",
                "effect_loop_count"],
        })
    decks.sort(key=lambda d: (d["rank"] is None, d["rank"] or 999))

    special = []
    for cid in ("toxic_trap_poison_lock", "deckout_carousel_durant_v2"):
        d = diag.get(cid, {})
        special.append({
            "id": cid,
            "lane": "special",
            "status": "needs_special_pilot",
            "decklist_valid": d.get("decklist_valid"),
            "built": d.get("built"),
            "smoke_valid": d.get("smoke_valid"),
            "blocked_by": "pilot" if d.get("pilot_emitted_illegal_action")
            else "decklist",
            "needs_non_attack_win_condition": True,
            "compatibility_label": "needs_special_pilot",
        })

    # ---- Answers to the four required questions (evidence-based) ----
    miraidon = rank_row.get("mono_lightning_miraidon_easy", {})
    diamond = rank_row.get("diamond_toolbox_diancie", {})
    water_density = rank_row.get("water_basic_density_v1", {})

    answers = {
        "did_simple_basic_deck_help": (
            "Partly. The simple mono-Lightning Basic deck (Miraidon) is the "
            f"strongest NEW deck at rank {rank_by.get('mono_lightning_miraidon_easy')} "
            f"/ {miraidon.get('adj_win_rate')} win-rate with 0 invalid/crash/timeout — "
            "it pilots cleanly under the generic pilot (no pilot mis-fit), but it "
            "lands at ~0.50 (promising_but_noisy), below the Water/Dragapult "
            "benchmarks. Simplicity bought clean piloting and legality, not yet "
            "benchmark-level strength."),
        "did_basic_toolbox_help": (
            "Less than the simple line. The mono-Psychic Mega Diancie Basic toolbox "
            f"(Diamond) ranks {rank_by.get('diamond_toolbox_diancie')} at "
            f"{diamond.get('adj_win_rate')} (below_benchmark) — also clean "
            "(0 invalid/crash/timeout) but a hair under 0.50. The wider toolbox of "
            "one-off Basics did not outperform the focused single-attacker line."),
        "are_weird_decks_blocked_by_decklist_or_pilot": (
            "By the PILOT, not the decklist. Both Toxic and Durant have VALID, "
            "constructible 60-card decklists (tarball + entrypoint validators PASS; "
            "a seat reaches DONE proving legality). They fail only because the "
            "generic prize-racing pilot emits an illegal action driving their "
            "passive-lock / deck-out win conditions (one seat INVALID). They are "
            "blocked_from_league pending a dedicated special pilot."),
        "which_family_to_improve_next": (
            "Miraidon (miraidon_new): it is the best-piloting NEW deck and the "
            "closest to benchmark, so tightening its list/curve has the highest "
            "expected return among league-eligible new families. In the special "
            "lane, Toxic is the first special-pilot target (simpler single lock "
            "vs. Durant's full deck-out engine)."),
    }

    out = {
        "pass": "34", "part": "J", "no_upload": True,
        "is_kaggle_leaderboard": False,
        "caveat": ("Compatibility labels come from the INTERNAL tournament (generic "
                   "pilot, our own decks) — not Kaggle. Structural metrics are from "
                   "deck.csv + local card DB. Fine-grained per-game telemetry was "
                   "not instrumented in Pass 34 (see not_instrumented)."),
        "decks": decks,
        "special_lane": special,
        "answers": answers,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# Pass 34 — Composition + pilot-fit analysis (Part J)",
        "",
        "> Compatibility labels are from the INTERNAL tournament (generic pilot, our "
        "own decks) — NOT Kaggle. Structural metrics computed from deck.csv + local "
        "card DB. Fine-grained per-game telemetry (no-pokemon losses, first attack "
        "turn, attack conversion, effect loops) was not instrumented in Pass 34 and "
        "is reported as not_instrumented (never fabricated). Nothing uploaded.",
        "",
        "## League-eligible / benchmark decks",
        "",
        "| rank | deck | new? | win_rate | label | uniq | basic-pkmn dens | evo | colors | mono | basic-E |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in decks:
        lines.append(
            f"| {d['rank']} | {d['id']} | {'Y' if d['is_new_deck'] else ''} | "
            f"{d['adj_win_rate']} | {d['compatibility_label']} | {d['unique_ids']} | "
            f"{d['basic_pokemon_density']} | {d['evolution_complexity']} | "
            f"{'/'.join(d['colors']) or '—'} | {'Y' if d['mono_color'] else 'N'} | "
            f"{d['basic_energy_count']} |")
    lines += [
        "",
        "## Special-lane status (isolated from ranking)",
        "",
        "| deck | decklist valid | built | smoke valid | blocked by | label |",
        "|---|---|---|---|---|---|",
    ]
    for s in special:
        lines.append(
            f"| {s['id']} | {s['decklist_valid']} | {s['built']} | "
            f"{s['smoke_valid']} | {s['blocked_by']} | {s['compatibility_label']} |")
    lines += ["", "## Findings (evidence-based answers)", ""]
    for q, a in answers.items():
        lines.append(f"- **{q.replace('_', ' ')}** — {a}")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
    unknown = {d["id"]: d["unknown_card_ids"] for d in decks if d["unknown_card_ids"]}
    print(f"decks analyzed: {len(decks)} ; special: {len(special)} ; "
          f"unknown_ids: {unknown or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
