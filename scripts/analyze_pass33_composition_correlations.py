#!/usr/bin/env python3
"""Pass 33 (Part H) — deck-composition vs internal-compatibility correlations.

LOCAL ONLY / DIRECTIONAL. Joins the Part-C composition audit with the Part-G
Stage-1 internal tournament adjusted win rate and reports rank (Spearman) and
linear (Pearson) association for each composition metric.

THIS IS NOT PREDICTIVE OF KAGGLE. n is tiny (the eligible tournament field), all
participants share one generic pilot, and opponents are our own decks. Every
correlation is described in strictly DIRECTIONAL language ("decks with more X
tended to win more internally"), never as a law, an effect size, or a Kaggle
forecast. No p-values are claimed beyond a coarse |rho| banding.

Writes pass33_composition_correlations.{json,md}.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
AUDIT = EXP / "pass33_deck_composition_audit.json"
RANKINGS = EXP / "pass33_composition_rankings.json"

OUT_JSON = EXP / "pass33_composition_correlations.json"
OUT_MD = EXP / "pass33_composition_correlations.md"

# Composition metrics to test against internal adj win rate, with the direction
# we'd naively expect more/less to help (for narration only, not asserted).
METRICS = [
    ("basic_pokemon", "more Basic Pokémon"),
    ("opening_no_basic_probability", "higher no-Basic opening risk"),
    ("non_basic_pokemon", "more evolving Pokémon"),
    ("evolution_count", "more evolution cards"),
    ("evolution_complexity_score", "higher evolution complexity"),
    ("bench_redundancy_score", "more bench redundancy"),
    ("energy_total", "more energy"),
    ("energy_ratio", "higher energy ratio"),
    ("trainer_total", "more trainers"),
    ("search_draw_count_heuristic", "more search/draw"),
    ("pilot_complexity_score", "higher pilot complexity"),
    ("no_pokemon_loss_risk_score", "higher no-Pokémon loss risk"),
    ("deckout_risk_score", "higher deckout risk"),
]


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / math.sqrt(sxx * syy), 4)


def _rank(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    if len(xs) < 3:
        return None
    return _pearson(_rank(xs), _rank(ys))


def _band(rho):
    if rho is None:
        return "n/a"
    a = abs(rho)
    if a >= 0.7:
        return "strong (directional)"
    if a >= 0.4:
        return "moderate (directional)"
    if a >= 0.2:
        return "weak (directional)"
    return "negligible"


def _narrate(label, rho):
    if rho is None:
        return f"{label}: insufficient variation to assess."
    direction = "won MORE" if rho > 0 else "won FEWER"
    if abs(rho) < 0.2:
        return (f"{label}: no clear internal association "
                f"(Spearman {rho}).")
    return (f"Decks with {label} tended to have {direction} internal games "
            f"(Spearman {rho}, {_band(rho)}).")


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    rankings = json.loads(RANKINGS.read_text(encoding="utf-8"))
    by_id = {d["candidate_id"]: d for d in audit["decks"]}
    standings = [r for r in rankings["standings"]
                 if r.get("adj_win_rate") is not None
                 and r["id"] in by_id]
    participants = [r["id"] for r in standings]
    win = {r["id"]: r["adj_win_rate"] for r in standings}

    results = []
    for key, label in METRICS:
        pairs = [(by_id[cid].get(key), win[cid]) for cid in participants
                 if isinstance(by_id[cid].get(key), (int, float))]
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        sp = _spearman(xs, ys)
        pe = _pearson(xs, ys)
        results.append({
            "metric": key, "label": label, "n": len(pairs),
            "spearman": sp, "pearson": pe, "band": _band(sp),
            "narrative": _narrate(label, sp),
            "values": {cid: by_id[cid].get(key) for cid in participants},
        })
    results.sort(key=lambda r: (r["spearman"] is not None, abs(r["spearman"] or 0)),
                 reverse=True)

    # Focused read on the Basic-density hypothesis the variants were built for.
    basic_row = next(r for r in results if r["metric"] == "basic_pokemon")
    nobasic_row = next(r for r in results
                       if r["metric"] == "opening_no_basic_probability")
    variants = {cid: {"basics": by_id[cid].get("basic_pokemon"),
                      "no_basic_p": by_id[cid].get("opening_no_basic_probability"),
                      "adj_win_rate": win.get(cid)}
                for cid in ("league_water_anti_disruption_pivot_v1",
                            "water_basic_density_v1", "water_basic_density_v2")
                if cid in win}

    rep = {
        "pass": "33", "part": "H", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "directional_only": True,
        "caveat": ("Tiny n, one shared generic pilot, self-play opponents. These "
                   "are DIRECTIONAL internal associations only and do NOT predict "
                   "Kaggle results or imply causation."),
        "n_participants": len(participants), "participants": participants,
        "win_rate_source": "pass33_composition_rankings.json (Stage 1)",
        "correlations": results,
        "basic_density_hypothesis": {
            "basic_pokemon_spearman": basic_row["spearman"],
            "opening_no_basic_probability_spearman": nobasic_row["spearman"],
            "water_density_ladder": variants,
            "read": ("Across the whole field the Basic-count signal is "
                     f"{basic_row['band']} (Spearman {basic_row['spearman']}); "
                     "within the Water family the two density variants out-scored "
                     "their Basic-light parent internally, but confidence "
                     "intervals overlap so this is directional, not proven."),
        },
    }
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    L = ["# Pass 33 — Composition ↔ Internal-Compatibility Correlations (Part H)",
         "", f"> DIRECTIONAL / LOCAL ONLY. {rep['caveat']}", "",
         f"- participants (n={len(participants)}): {', '.join(participants)}",
         f"- win-rate source: {rep['win_rate_source']}",
         "- is Kaggle leaderboard: **False**  upload_performed: **False**", "",
         "## Metric associations (sorted by |Spearman|)", "",
         "| metric | n | Spearman | Pearson | band | directional read |",
         "|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['metric']} | {r['n']} | {r['spearman']} | {r['pearson']} | "
                 f"{r['band']} | {r['narrative']} |")
    L += ["", "## Basic-density hypothesis (Water family)", "",
          "| deck | Basics | no-Basic P | internal adj win_rate |",
          "|---|---|---|---|"]
    for cid, v in variants.items():
        L.append(f"| {cid} | {v['basics']} | {v['no_basic_p']} | "
                 f"{v['adj_win_rate']} |")
    L += ["", rep["basic_density_hypothesis"]["read"], "",
          "_Correlation is not causation; n is tiny and all decks share one "
          "generic pilot. Use these only to choose the next human-approved probe, "
          "never as a Kaggle prediction._", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"n={len(participants)} basic_pokemon Spearman="
          f"{basic_row['spearman']} no_basic_p Spearman={nobasic_row['spearman']}")
    for r in results[:5]:
        print(f"  {r['metric']}: rho={r['spearman']} ({r['band']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
