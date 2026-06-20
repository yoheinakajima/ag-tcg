#!/usr/bin/env python3
"""Pass 33 (Part C) — deck composition audit. LOCAL / READ-ONLY.

Audits every existing candidate tarball under data/submissions/candidates_pass*/
against the local card DB (data/cards/EN_Card_Data.csv, NOT committed). For each
unique deck (canonical = highest pass-number copy of a given filename) computes
composition counts, an opening no-Basic-Pokémon probability (hypergeometric over
a 7-card opening hand), and directional fragility/deckout risk estimates.

Honesty rules:
  * Card stage/type/rule come straight from the card DB. If a deck id is absent
    from the DB it is reported as unknown rather than guessed.
  * Mega / ex Pokémon are NOT counted Basic unless the DB stage says Basic.
  * search/draw and recovery counts are keyword HEURISTICS over card name/effect
    and are labelled directional, not authoritative.
  * No upload, no submit, no GitHub push, no card-DB commit.

Writes data/experiments/pass33_deck_composition_audit.{json,md,csv}.
"""
from __future__ import annotations

import csv
import json
import math
import re
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
SUB_ROOT = REPO / "data" / "submissions"
EXP = REPO / "data" / "experiments"
LIVE = EXP / "pass33_live_score_status.json"

OUT_JSON = EXP / "pass33_deck_composition_audit.json"
OUT_MD = EXP / "pass33_deck_composition_audit.md"
OUT_CSV = EXP / "pass33_deck_composition_audit.csv"

STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"

FAMILY = {
    "league_water_anti_disruption_pivot_v1": "water",
    "league_water_core_reference": "water",
    "core_pilot_water_v2_runtime": "water",
    "water_basic_density_v1": "water",
    "water_basic_density_v2": "water",
    "league_dragapult_spread": "dragapult",
    "league_dragapult_v1_search_only": "dragapult",
    "league_dragapult_v1_draw_only": "dragapult",
    "league_mega_venusaur_tank": "venusaur",
    "effect_loop_exit_guard_v1": "venusaur",
    "league_raging_bolt_ogerpon": "raging_bolt",
    "league_raging_bolt_consistency_v1": "raging_bolt",
    "league_raging_bolt_energy_attacker_v1": "raging_bolt",
    "league_mega_charizard_x_burst": "charizard",
    "league_mega_gardevoir_psychic_ramp": "gardevoir",
    "league_durant_deckout_carousel": "durant",
}

# Directional keyword heuristics (card name / effect text).
SEARCH_DRAW_KW = re.compile(
    r"\b(ball|professor|research|iono|marnie|cynthia|hop|bianca|colress|"
    r"pok[eé]gear|pok[eé]nav|trekking shoes|acro bike|buddy-buddy poffin|"
    r"earthen vessel|capturing aid|nest|arven|lana's aid|jacq|tasting|"
    r"superior energy retrieval|night stretcher)\b", re.I)
DRAW_EFFECT_KW = re.compile(
    r"(draw \d+ card|draw cards|search your deck|put .* into your hand|"
    r"shuffle your deck and draw)", re.I)
RECOVERY_KW = re.compile(
    r"(super rod|night stretcher|rescue|energy retrieval|ordinary rod|"
    r"pal pad|klara|penny|from your discard pile (?:into|to) your hand|"
    r"put .* from your discard pile)", re.I)


def _load_card_db():
    by_id = {}
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int((row.get("Card ID") or "").strip())
            except ValueError:
                continue
            by_id[cid] = {
                "name": (row.get("Card Name") or "").strip(),
                "stage": (row.get(STAGE_COL) or "").strip(),
                "rule": (row.get("Rule") or "").strip(),
                "effect": (row.get("Effect Explanation") or "").strip(),
                "prev_stage": (row.get("Previous stage") or "").strip(),
            }
    return by_id


def _tar_names(tp):
    with tarfile.open(tp, "r:gz") as t:
        return t.getnames()


def _read_member(tp, name):
    with tarfile.open(tp, "r:gz") as t:
        m = t.extractfile(name)
        return m.read().decode("utf-8") if m else None


def _deck_ids(tp):
    txt = _read_member(tp, "deck.csv")
    if txt is None:
        return None
    ids = []
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            ids.append(int(s))
        except ValueError:
            return None
    return ids


def _hyper_no_basic(n_basic_pokemon, deck_size=60, hand=7):
    """P(0 Basic Pokémon in opening hand) = C(N-B,h)/C(N,h)."""
    if n_basic_pokemon <= 0:
        return 1.0
    if n_basic_pokemon >= deck_size:
        return 0.0
    return math.comb(deck_size - n_basic_pokemon, hand) / math.comb(deck_size, hand)


def _risk_label(p):
    if p >= 0.12:
        return "high"
    if p >= 0.07:
        return "medium"
    return "low"


def _clean_id(tp):
    n = tp.name
    return n[:-7] if n.endswith(".tar.gz") else tp.stem


def audit_deck(tp, by_id, kaggle_scores):
    cid = _clean_id(tp)
    names = _tar_names(tp)
    top_level_ok = sorted(names) == ["deck.csv", "main.py"]
    ids = _deck_ids(tp)
    if ids is None:
        return {"candidate_id": cid, "tarball": str(tp.relative_to(REPO)),
                "valid_60": False, "error": "deck.csv unparseable"}
    n = len(ids)
    uniq = len(set(ids))
    unknown_ids = sorted({c for c in ids if c not in by_id})

    cnt = {"basic_pokemon": 0, "stage1": 0, "stage2": 0, "item": 0,
           "supporter": 0, "tool": 0, "stadium": 0, "basic_energy": 0,
           "special_energy": 0, "unknown": 0}
    ex_count = mega_count = 0
    search_draw = recovery = 0
    for c in ids:
        info = by_id.get(c)
        if info is None:
            cnt["unknown"] += 1
            continue
        st = info["stage"]
        if st == "Basic Pokémon":
            cnt["basic_pokemon"] += 1
        elif st == "Stage 1 Pokémon":
            cnt["stage1"] += 1
        elif st == "Stage 2 Pokémon":
            cnt["stage2"] += 1
        elif st == "Item":
            cnt["item"] += 1
        elif st == "Supporter":
            cnt["supporter"] += 1
        elif st == "Pokémon Tool":
            cnt["tool"] += 1
        elif st == "Stadium":
            cnt["stadium"] += 1
        elif st == "Basic Energy":
            cnt["basic_energy"] += 1
        elif st == "Special Energy":
            cnt["special_energy"] += 1
        else:
            cnt["unknown"] += 1
        rule = info["rule"]
        if "Mega Pokémon ex" in rule:
            mega_count += 1
            ex_count += 1
        elif rule == "Pokémon ex":
            ex_count += 1
        blob = f"{info['name']} {info['effect']}"
        if SEARCH_DRAW_KW.search(info["name"]) or DRAW_EFFECT_KW.search(info["effect"]):
            search_draw += 1
        if RECOVERY_KW.search(blob):
            recovery += 1

    pokemon = cnt["basic_pokemon"] + cnt["stage1"] + cnt["stage2"]
    non_basic_pokemon = cnt["stage1"] + cnt["stage2"]
    evolution = cnt["stage1"] + cnt["stage2"]
    energy = cnt["basic_energy"] + cnt["special_energy"]
    trainer = cnt["item"] + cnt["supporter"] + cnt["tool"] + cnt["stadium"]
    no_basic_p = round(_hyper_no_basic(cnt["basic_pokemon"]), 5)
    exp_basic_open = round(7 * cnt["basic_pokemon"] / 60, 3) if n == 60 else None
    evo_complexity = round((cnt["stage1"] + 2 * cnt["stage2"]) /
                           pokemon, 3) if pokemon else 0.0
    energy_ratio = round(energy / n, 3) if n else None
    # Pilot complexity: blend of unique-card variety, evolution depth, special
    # energy presence. Directional 0..1.
    pilot_complexity = round(min(1.0,
                                 0.4 * (uniq / 30)
                                 + 0.4 * evo_complexity
                                 + 0.2 * (1 if cnt["special_energy"] else 0)), 3)
    # no-pokemon-loss risk: opening no-basic prob plus thin-basic penalty.
    npl = no_basic_p + (0.05 if cnt["basic_pokemon"] < 8 else 0.0) \
        + (0.05 * evo_complexity)
    no_pokemon_risk = _risk_label(no_basic_p)
    no_pokemon_risk_score = round(min(1.0, npl), 4)
    # deckout risk: directional — no recovery + heavy thinning + energy glut
    # (over-committed energy thins the draw library faster). Discriminating but
    # explicitly heuristic.
    deckout_score = round(min(1.0,
                              (0.06 if recovery == 0 else 0.0)
                              + max(0, search_draw - 14) * 0.02
                              + max(0, energy - 28) * 0.01), 4)
    deckout_risk = "high" if deckout_score >= 0.16 else (
        "medium" if deckout_score >= 0.08 else "low")

    return {
        "candidate_id": cid,
        "family_id": FAMILY.get(cid, "unknown"),
        "tarball": str(tp.relative_to(REPO)),
        "top_level_only": top_level_ok,
        "valid_60": n == 60,
        "card_count": n,
        "unique_card_count": uniq,
        "unknown_card_ids": unknown_ids,
        "basic_pokemon": cnt["basic_pokemon"],
        "non_basic_pokemon": non_basic_pokemon,
        "pokemon_total": pokemon,
        "stage1": cnt["stage1"], "stage2": cnt["stage2"],
        "evolution_count": evolution,
        "ex_count": ex_count, "mega_count": mega_count,
        "basic_energy": cnt["basic_energy"],
        "special_energy": cnt["special_energy"],
        "energy_total": energy,
        "trainer_total": trainer,
        "item": cnt["item"], "supporter": cnt["supporter"],
        "tool": cnt["tool"], "stadium": cnt["stadium"],
        "search_draw_count_heuristic": search_draw,
        "recovery_count_heuristic": recovery,
        "opening_no_basic_probability": no_basic_p,
        "expected_basics_in_opener": exp_basic_open,
        "bench_redundancy_score": exp_basic_open,
        "evolution_complexity_score": evo_complexity,
        "energy_ratio": energy_ratio,
        "pilot_complexity_score": pilot_complexity,
        "no_pokemon_loss_risk": no_pokemon_risk,
        "no_pokemon_loss_risk_score": no_pokemon_risk_score,
        "deckout_risk": deckout_risk,
        "deckout_risk_score": deckout_score,
        "previous_kaggle_score": kaggle_scores.get(tp.name),
    }


def main() -> int:
    by_id = _load_card_db()
    kaggle_scores = {}
    if LIVE.exists():
        live = json.loads(LIVE.read_text(encoding="utf-8"))
        for r in live.get("complete_submissions_ranked", []):
            kaggle_scores[r["fileName"]] = r["publicScore"]

    # Canonical = highest pass-number copy of each filename.
    canon: dict[str, tuple[int, Path]] = {}
    sources: dict[str, list[str]] = {}
    for d in sorted(SUB_ROOT.glob("candidates_pass*")):
        m = re.search(r"candidates_pass(\d+)", d.name)
        pno = int(m.group(1)) if m else 0
        for tp in d.glob("*.tar.gz"):
            sources.setdefault(tp.name, []).append(str(tp.relative_to(REPO)))
            cur = canon.get(tp.name)
            if cur is None or pno > cur[0]:
                canon[tp.name] = (pno, tp)

    decks = []
    for fn in sorted(canon):
        _, tp = canon[fn]
        rec = audit_deck(tp, by_id, kaggle_scores)
        rec["all_source_paths"] = sorted(sources[fn])
        decks.append(rec)

    valid = [d for d in decks if d.get("valid_60")]
    basics = [d["basic_pokemon"] for d in valid]
    energies = [d["energy_total"] for d in valid]
    by_no_basic = sorted(valid, key=lambda d: d["opening_no_basic_probability"])
    out = {
        "pass": "33", "part": "C", "no_upload": True, "upload_performed": False,
        "card_db": "data/cards/EN_Card_Data.csv (local, NOT committed)",
        "decks_audited": len(decks),
        "decks_valid_60": len(valid),
        "basic_count_range": [min(basics), max(basics)] if basics else None,
        "energy_count_range": [min(energies), max(energies)] if energies else None,
        "highest_no_basic_risk": (
            {"candidate_id": by_no_basic[-1]["candidate_id"],
             "opening_no_basic_probability": by_no_basic[-1]["opening_no_basic_probability"]}
            if by_no_basic else None),
        "lowest_no_basic_risk": (
            {"candidate_id": by_no_basic[0]["candidate_id"],
             "opening_no_basic_probability": by_no_basic[0]["opening_no_basic_probability"]}
            if by_no_basic else None),
        "notes": [
            "Mega/ex Pokémon are not counted Basic unless the DB stage says Basic.",
            "search_draw_count and recovery_count are keyword heuristics (directional).",
            "Unknown card ids (absent from card DB) are reported, not guessed.",
        ],
        "decks": decks,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    cols = ["candidate_id", "family_id", "valid_60", "card_count",
            "unique_card_count", "basic_pokemon", "non_basic_pokemon",
            "evolution_count", "ex_count", "mega_count", "basic_energy",
            "special_energy", "energy_total", "trainer_total",
            "search_draw_count_heuristic", "recovery_count_heuristic",
            "opening_no_basic_probability", "bench_redundancy_score",
            "evolution_complexity_score", "energy_ratio",
            "pilot_complexity_score", "no_pokemon_loss_risk", "deckout_risk",
            "previous_kaggle_score"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for d in decks:
            w.writerow([d.get(c) for c in cols])

    L = ["# Pass 33 — Deck Composition Audit (Part C)", "",
         "> LOCAL / read-only. Card metadata from local `EN_Card_Data.csv` "
         "(not committed). Mega/ex are not Basic unless the DB says so; "
         "search/draw & recovery counts are directional keyword heuristics.", "",
         f"- decks audited: **{out['decks_audited']}** "
         f"({out['decks_valid_60']} valid 60-card)",
         f"- Basic Pokémon count range: **{out['basic_count_range']}**",
         f"- Energy count range: **{out['energy_count_range']}**",
         f"- highest no-Basic risk: **{out['highest_no_basic_risk']}**",
         f"- lowest no-Basic risk: **{out['lowest_no_basic_risk']}**", "",
         "| candidate | family | 60 | uniq | Basic | nonBasicPkmn | evo | ex/Mega | "
         "BasicE | SpecE | E tot | Trn | s/d* | rec* | noBasic P | evoCplx | "
         "E ratio | pilot | NPL risk | deckout | Kaggle |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
         "---|---|---|"]
    for d in decks:
        if not d.get("valid_60"):
            L.append(f"| {d['candidate_id']} | {d.get('family_id')} | "
                     f"**INVALID** | | | | | | | | | | | | | | | | | | |")
            continue
        L.append(
            f"| {d['candidate_id']} | {d['family_id']} | {d['card_count']} | "
            f"{d['unique_card_count']} | {d['basic_pokemon']} | "
            f"{d['non_basic_pokemon']} | {d['evolution_count']} | "
            f"{d['ex_count']}/{d['mega_count']} | {d['basic_energy']} | "
            f"{d['special_energy']} | {d['energy_total']} | {d['trainer_total']} | "
            f"{d['search_draw_count_heuristic']} | {d['recovery_count_heuristic']} | "
            f"{d['opening_no_basic_probability']} | "
            f"{d['evolution_complexity_score']} | {d['energy_ratio']} | "
            f"{d['pilot_complexity_score']} | {d['no_pokemon_loss_risk']} | "
            f"{d['deckout_risk']} | {d['previous_kaggle_score']} |")
    L += ["", "_* search/draw (s/d) and recovery (rec) are directional keyword "
          "heuristics, not authoritative._", "",
          "## Notes"] + [f"- {n}" for n in out["notes"]] + [""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"audited {out['decks_audited']} decks ({out['decks_valid_60']} valid); "
          f"basic range {out['basic_count_range']}, energy range "
          f"{out['energy_count_range']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
