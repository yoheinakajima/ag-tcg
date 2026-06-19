#!/usr/bin/env python3
"""Pass 25 (Part I) — lean, seat-swapped focused eval. LOCAL ONLY.

SURROGATE-BASED AND DIRECTIONAL ONLY. The two seam opponents are subfamily decks
(Pass-13 refined pool) piloted by the GENERIC surrogate brain, NOT real opponent
policies. These local numbers never equal Kaggle results and are NEVER sufficient
on their own to promote or upload anything. No upload, no submission, no candidate
generation, no root edits.

Per the architect milestone review, this is NOT an exhaustive all-pairs league
(Part-H proved all three candidates are legal/narrow but produce ZERO behaviour
deltas over 262 real analysed-seat decisions, so a broad league is dominated by
H2H noise). It runs only the decision-relevant matchups:

  * H2H: control (Pass-22 pivot) vs each Pass-25 candidate    -- promotion signal
  * H2H calibration: control vs each historical reference     -- noise floor
  * seam: {control + candidates} vs the two Part-C surrogates  -- seam axis
      - fighting/prize-liability: ``mega_lucario_ex_tempo``    (episode 80623232)
      - mirror/deckout:           ``water_kyogre_abomasnow_maxbelt`` (80622626)

Metrics: outcome/win-rate with Wilson intervals, statuses, timeouts, crashes,
skips, and the ROBUST log-derived proxies (attack count, first attack, first
evolution). Deep board metrics (deckout rate, no-pokemon/no-bench loss, Mega
exposure, prize-liability tags) are reported as NOT_MEASURED: the cabt board
state is an opaque encoded blob and the Part-H decision replay is the richer,
honest behavioural evidence (see pass25_decision_replay).

RESUMABLE / CHUNKED: the sandbox kills detached background processes, and the
full run exceeds a single shell budget, so the eval is sharded by participant.
Run each shard (each ~20 games, well under the shell limit), then aggregate::

    python3 scripts/run_pass25_focused_eval.py --list-shards
    python3 scripts/run_pass25_focused_eval.py --shard h2h:deckout_guard_v1
    ...
    python3 scripts/run_pass25_focused_eval.py --aggregate

Shard results land in data/experiments/_p25_eval_shards/<shard>.json. Aggregate
writes data/experiments/pass25_focused_eval.{json,md}, pass25_matchup_matrix.csv,
pass25_rankings.{json,md}. ``--all`` runs every shard then aggregates in one
process (only use when within the shell budget). Exit 0 on completion.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

EXP = REPO / "data" / "experiments"
SHARD_DIR = EXP / "_p25_eval_shards"
POOL = REPO / "experiments" / "pass13_refined_meta_pool.yaml"

CONTROL = ("control_pass22_pivot", "active_control",
           REPO / "data" / "submissions" / "candidates_pass22"
           / "league_water_anti_disruption_pivot_v1.tar.gz")
CANDIDATES = [
    ("deckout_guard_v1", "candidate",
     REPO / "data" / "submissions" / "candidates_pass25" / "deckout_guard_v1.tar.gz"),
    ("prize_liability_guard_v1", "candidate",
     REPO / "data" / "submissions" / "candidates_pass25"
     / "prize_liability_guard_v1.tar.gz"),
    ("hybrid_guard_v1", "candidate",
     REPO / "data" / "submissions" / "candidates_pass25" / "hybrid_guard_v1.tar.gz"),
]
REFS = [
    ("league_water_core_reference", "reference",
     REPO / "data" / "submissions" / "candidates_pass17"
     / "league_water_core_reference.tar.gz"),
    ("core_pilot_water_v2_runtime", "base_lineage",
     REPO / "data" / "submissions" / "candidates_pass14"
     / "core_pilot_water_v2_runtime.tar.gz"),
]
FIGHTING_KEY = "mega_lucario_ex_tempo"
MIRROR_KEY = "water_kyogre_abomasnow_maxbelt"
SEAMS = [("fighting", FIGHTING_KEY), ("mirror", MIRROR_KEY)]

GLOBAL_BUDGET_S = int(os.environ.get("P25E_GLOBAL_BUDGET_S", "600"))
H2H_PER_SEAT = int(os.environ.get("P25E_H2H_PER_SEAT", "10"))
SEAM_PER_SEAT = int(os.environ.get("P25E_SEAM_PER_SEAT", "5"))

NOT_MEASURED = ["deckout_rate", "no_pokemon_loss_rate", "mega_exposure_rate",
                "prize_liability_tag_rate"]

DISCLAIMER = (
    "SURROGATE-BASED AND DIRECTIONAL ONLY. The seam opponents are subfamily decks "
    "piloted by a generic surrogate policy, not real opponent policies. These "
    "local numbers never equal Kaggle results and never justify upload/promotion. "
    "Deep board metrics are NOT_MEASURED (opaque cabt board blob); the Part-H "
    "decision replay is the richer behavioural evidence.")

PROMOTION_BAR = (
    "future_kaggle_probe requires: H2H-vs-control Wilson interval not clearly "
    "negative AND a material seam gain over control (>= +0.08 aggregate "
    "win-rate), seat-swapped, with no positive-control regression.")


def _load_meta_eval_mod():
    spec = importlib.util.spec_from_file_location(
        "run_meta_pool_eval", REPO / "scripts" / "run_meta_pool_eval.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load_meta_eval_mod()
_extract_agent = _MEV._extract_agent
_validate_tarball = _MEV._validate_tarball
_outcome_for_seat = _MEV._outcome_for_seat
_run_game = _MEV._run_game  # includes _extract_metrics (robust proxies)

BAD_STATUSES = {"INVALID", "ERROR", "TIMEOUT"}


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _our_proxy(g: dict, our: int) -> dict | None:
    if not g.get("ok"):
        return None
    fa = (g.get("first_attack_step") or {}).get(our)
    ac = (g.get("attack_count") or {}).get(our, 0)
    fe = (g.get("first_evolution_step") or {}).get(our)
    return {"attacked": fa is not None, "attack_count": ac,
            "evolved": fe is not None}


def _matchup(our_agent: str, opp_agent: str, n_per_seat: int,
             budget_left, label: str) -> dict:
    games = []
    for (a, b, our) in [(our_agent, opp_agent, 0), (opp_agent, our_agent, 1)]:
        for _ in range(n_per_seat):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "our_seat": our})
                continue
            g = _run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = _outcome_for_seat(g, our) if g.get("ok") else None
            games.append(g)
    wins = sum(1 for g in games if g.get("outcome") == "win")
    losses = sum(1 for g in games if g.get("outcome") == "loss")
    draws = sum(1 for g in games if g.get("outcome") == "draw")
    decisive = wins + losses
    n = wins + losses + draws
    lo, hi = _wilson(wins, decisive)
    proxies = [p for g in games
               if (p := _our_proxy(g, g["our_seat"])) is not None]
    n_px = len(proxies)
    bad = sorted({s for g in games for s in (g.get("statuses") or [])
                  if s in BAD_STATUSES})
    return {
        "label": label, "n_games": n, "n_played": len(games),
        "wins": wins, "losses": losses, "draws": draws,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "wilson_low": lo, "wilson_high": hi,
        "our_attack_rate": round(sum(p["attacked"] for p in proxies) / n_px, 4)
        if n_px else None,
        "our_mean_attacks": round(sum(p["attack_count"] for p in proxies) / n_px, 3)
        if n_px else None,
        "our_evolution_rate": round(sum(p["evolved"] for p in proxies) / n_px, 4)
        if n_px else None,
        "bad_statuses": bad,
        "crashes": sum(1 for g in games if not g.get("ok")
                       and not g.get("timeout") and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games
                          if not g.get("ok") and g.get("error")}),
    }


def _seam_deck(key: str) -> str | None:
    if yaml is None or not POOL.exists():
        return None
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    for a in pool.get("archetypes", []):
        if a.get("key") == key:
            d = a.get("surrogate_deck")
            return str(REPO / d) if d and (REPO / d).exists() else None
    return None


def _seam_aggregate(per_seam: dict) -> dict:
    wins = sum(m["wins"] for m in per_seam.values())
    losses = sum(m["losses"] for m in per_seam.values())
    draws = sum(m["draws"] for m in per_seam.values())
    decisive = wins + losses
    lo, hi = _wilson(wins, decisive)
    return {"wins": wins, "losses": losses, "draws": draws,
            "win_rate": round(wins / decisive, 4) if decisive else None,
            "wilson_low": lo, "wilson_high": hi}


# --------------------------------------------------------------------------- #
# Shard plumbing.
# --------------------------------------------------------------------------- #
def _shard_names() -> list[str]:
    names = [f"h2h:{cid}" for cid, _r, _t in CANDIDATES]
    names += [f"h2h:{rid}" for rid, _r, _t in REFS]
    names += [f"seam:{CONTROL[0]}"] + [f"seam:{cid}" for cid, _r, _t in CANDIDATES]
    return names


def _by_id(target: str):
    for cid, role, tar in [CONTROL] + CANDIDATES + REFS:
        if cid == target:
            return cid, role, tar
    return None


def _run_shard(name: str) -> dict:
    kind, _, ident = name.partition(":")
    if kind not in {"h2h", "seam"} or not ident:
        raise SystemExit(f"bad shard name: {name!r}")
    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        if kind == "h2h":
            who = _by_id(ident)
            if who is None:
                raise SystemExit(f"unknown h2h participant: {ident}")
            cid, role, tar = who
            if not (tar.exists() and _validate_tarball(tar)):
                raise SystemExit(f"{cid} tarball missing/invalid")
            if not (CONTROL[2].exists() and _validate_tarball(CONTROL[2])):
                raise SystemExit("control tarball missing/invalid")
            agent = _extract_agent(tar, tmp / cid)
            control = _extract_agent(CONTROL[2], tmp / "control")
            res = _matchup(agent, control, H2H_PER_SEAT, budget_left,
                           f"{cid} vs control")
            payload = {"kind": "h2h", "id": cid, "role": role, "vs": "control",
                       "result": res}
        else:  # seam
            who = _by_id(ident)
            if who is None:
                raise SystemExit(f"unknown seam participant: {ident}")
            pid, role, tar = who
            if not (tar.exists() and _validate_tarball(tar)):
                raise SystemExit(f"{pid} tarball missing/invalid")
            agent = _extract_agent(tar, tmp / pid)
            from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent
            per_seam = {}
            for label, key in SEAMS:
                deck = _seam_deck(key)
                if not deck:
                    raise SystemExit(f"{label} surrogate deck ({key}) missing")
                opp = str(materialize_surrogate_agent(deck, tmp / ("opp_" + label)))
                per_seam[label] = _matchup(agent, opp, SEAM_PER_SEAT, budget_left,
                                           f"{pid} vs {label}")
            payload = {"kind": "seam", "id": pid, "role": role,
                       "per_seam": per_seam}
    payload["elapsed_s"] = round(time.time() - start, 1)
    payload["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload["h2h_per_seat"] = H2H_PER_SEAT
    payload["seam_per_seat"] = SEAM_PER_SEAT
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    out = SHARD_DIR / (name.replace(":", "__") + ".json")
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# Aggregation.
# --------------------------------------------------------------------------- #
def _load_shards() -> dict[str, dict]:
    shards = {}
    if not SHARD_DIR.exists():
        return shards
    for p in SHARD_DIR.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        name = ("h2h:" if d["kind"] == "h2h" else "seam:") + d["id"]
        shards[name] = d
    return shards


def _aggregate() -> int:
    shards = _load_shards()
    notes: list[str] = []
    expected = _shard_names()
    missing = [n for n in expected if n not in shards]
    if missing:
        notes.append("missing shards (run them first): " + ", ".join(missing))

    h2h: dict = {}
    seam: dict = {}
    seam_agg: dict = {}
    h2h_per_seat = seam_per_seat = None
    for name, d in shards.items():
        if d["kind"] == "h2h":
            h2h_per_seat = d.get("h2h_per_seat", h2h_per_seat)
            h2h[d["id"]] = {"role": d["role"], "vs": d.get("vs", "control"),
                            **d["result"]}
        else:
            seam_per_seat = d.get("seam_per_seat", seam_per_seat)
            seam[d["id"]] = {"role": d["role"], "per_seam": d["per_seam"]}
            seam_agg[d["id"]] = _seam_aggregate(d["per_seam"])

    ctrl_seam_wr = seam_agg.get(CONTROL[0], {}).get("win_rate")
    seam_deltas = {}
    for pid, agg in seam_agg.items():
        wr = agg.get("win_rate")
        seam_deltas[pid] = (round(wr - ctrl_seam_wr, 4)
                            if wr is not None and ctrl_seam_wr is not None else None)

    rep = {
        "pass": "25", "part": "I", "mode": "focused_eval", "local_only": True,
        "upload_performed": False, "no_upload": True, "disclaimer": DISCLAIMER,
        "h2h_per_seat": h2h_per_seat, "seam_per_seat": seam_per_seat,
        "fighting_surrogate": FIGHTING_KEY, "mirror_surrogate": MIRROR_KEY,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "not_measured": NOT_MEASURED, "promotion_bar": PROMOTION_BAR,
        "shards_present": sorted(shards), "shards_missing": missing,
        "h2h_vs_control": h2h, "seam": seam, "seam_aggregate": seam_agg,
        "seam_delta_vs_control": seam_deltas, "notes": notes,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass25_focused_eval.json").write_text(json.dumps(rep, indent=2),
                                                  encoding="utf-8")
    _write_matrix(rep)
    _write_rankings(rep)
    _write_md(rep)
    print("Pass 25 focused eval aggregated "
          f"({len(shards)}/{len(expected)} shards)")
    if missing:
        print("  MISSING:", ", ".join(missing))
    print(f"  control seam win-rate: {ctrl_seam_wr}")
    for pid in [CONTROL[0]] + [c for c, _r, _ in CANDIDATES]:
        agg = seam_agg.get(pid, {})
        print(f"  {pid:28s} seam_wr={agg.get('win_rate')} "
              f"delta={seam_deltas.get(pid)}")
    for cid, _role, _ in CANDIDATES:
        m = h2h.get(cid, {})
        print(f"  {cid:28s} H2H-vs-control wr={m.get('win_rate')} "
              f"[{m.get('wilson_low')},{m.get('wilson_high')}]")
    print(f"-> {(EXP / 'pass25_focused_eval.md').relative_to(REPO)}")
    return 0


def _write_matrix(rep: dict) -> None:
    mm = EXP / "pass25_matchup_matrix.csv"
    with mm.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["axis", "participant", "role", "opponent", "n_games",
                    "wins", "losses", "draws", "win_rate",
                    "wilson_low", "wilson_high", "our_attack_rate",
                    "our_mean_attacks", "our_evolution_rate",
                    "bad_statuses", "crashes", "timeouts", "skipped"])
        for cid, m in rep["h2h_vs_control"].items():
            w.writerow(["h2h", cid, m.get("role"), "control", m.get("n_games"),
                        m.get("wins"), m.get("losses"), m.get("draws"),
                        m.get("win_rate"), m.get("wilson_low"), m.get("wilson_high"),
                        m.get("our_attack_rate"), m.get("our_mean_attacks"),
                        m.get("our_evolution_rate"),
                        "|".join(m.get("bad_statuses") or []),
                        m.get("crashes"), m.get("timeouts"), m.get("skipped")])
        for pid, s in rep["seam"].items():
            for label, m in s["per_seam"].items():
                w.writerow(["seam", pid, s.get("role"), label, m.get("n_games"),
                            m.get("wins"), m.get("losses"), m.get("draws"),
                            m.get("win_rate"), m.get("wilson_low"),
                            m.get("wilson_high"), m.get("our_attack_rate"),
                            m.get("our_mean_attacks"), m.get("our_evolution_rate"),
                            "|".join(m.get("bad_statuses") or []),
                            m.get("crashes"), m.get("timeouts"), m.get("skipped")])


def _write_rankings(rep: dict) -> None:
    cand_ids = [c for c, _r, _ in CANDIDATES]
    h2h_rank = sorted(
        ({"candidate": cid,
          "h2h_win_rate": rep["h2h_vs_control"].get(cid, {}).get("win_rate"),
          "wilson_low": rep["h2h_vs_control"].get(cid, {}).get("wilson_low"),
          "wilson_high": rep["h2h_vs_control"].get(cid, {}).get("wilson_high"),
          "seam_delta_vs_control": rep["seam_delta_vs_control"].get(cid)}
         for cid in cand_ids),
        key=lambda x: (x["h2h_win_rate"] is None, -(x["h2h_win_rate"] or 0),
                       -(x["seam_delta_vs_control"] or 0)))
    seam_rank = sorted(
        ({"participant": pid, "role": rep["seam"][pid]["role"],
          "seam_win_rate": rep["seam_aggregate"].get(pid, {}).get("win_rate"),
          "delta_vs_control": rep["seam_delta_vs_control"].get(pid)}
         for pid in rep["seam"]),
        key=lambda x: (x["seam_win_rate"] is None, -(x["seam_win_rate"] or 0)))
    obj = {"pass": "25", "part": "I", "disclaimer": DISCLAIMER, "no_upload": True,
           "promotion_bar": PROMOTION_BAR,
           "h2h_vs_control_ranking": h2h_rank, "seam_ranking": seam_rank}
    (EXP / "pass25_rankings.json").write_text(json.dumps(obj, indent=2),
                                              encoding="utf-8")
    L = ["# Pass 25 — Rankings (Part I, directional only)", "",
         f"- {DISCLAIMER}", "",
         "## Candidates by H2H win-rate vs control", "",
         "| # | candidate | H2H win-rate | Wilson 95% | seam Δ vs control |",
         "|---|---|---|---|---|"]
    for i, e in enumerate(h2h_rank, 1):
        L.append(f"| {i} | {e['candidate']} | {e['h2h_win_rate']} | "
                 f"[{e['wilson_low']}, {e['wilson_high']}] | "
                 f"{e['seam_delta_vs_control']} |")
    L += ["", "## Seam axis (control + candidates) by aggregate win-rate", "",
          "| # | participant | role | seam win-rate | Δ vs control |",
          "|---|---|---|---|---|"]
    for i, e in enumerate(seam_rank, 1):
        L.append(f"| {i} | {e['participant']} | {e['role']} | "
                 f"{e['seam_win_rate']} | {e['delta_vs_control']} |")
    L += ["", "_Promotion bar: " + PROMOTION_BAR + "_", ""]
    (EXP / "pass25_rankings.md").write_text("\n".join(L), encoding="utf-8")


def _write_md(rep: dict) -> None:
    L = ["# Pass 25 — Focused Eval (Part I, directional only)", "",
         "> LOCAL ONLY — lean seat-swapped surrogate eval, NOT a leaderboard.", "",
         f"- generated: {rep['generated_at']}",
         f"- H2H games/seat: {rep['h2h_per_seat']}  seam games/seat: "
         f"{rep['seam_per_seat']}  (seat-swapped)",
         f"- fighting surrogate: `{FIGHTING_KEY}`  mirror surrogate: `{MIRROR_KEY}`",
         f"- NOT_MEASURED (opaque board blob): {', '.join(rep['not_measured'])}",
         f"- {DISCLAIMER}", ""]
    if rep.get("shards_missing"):
        L += ["**WARNING — incomplete:** missing shards: "
              + ", ".join(rep["shards_missing"]), ""]
    if rep["notes"]:
        L += ["**Notes:** " + "; ".join(rep["notes"]), ""]
    L += ["## H2H vs control", "",
          "| participant | role | win-rate | Wilson 95% | W/L/D | our attack% "
          "| our evo% | bad |", "|---|---|---|---|---|---|---|---|"]
    for cid, m in rep["h2h_vs_control"].items():
        L.append(f"| {cid} | {m.get('role')} | {m.get('win_rate')} | "
                 f"[{m.get('wilson_low')}, {m.get('wilson_high')}] | "
                 f"{m.get('wins')}/{m.get('losses')}/{m.get('draws')} | "
                 f"{m.get('our_attack_rate')} | {m.get('our_evolution_rate')} | "
                 f"{m.get('bad_statuses') or '—'} |")
    L += ["", "## Seam axis (vs Part-C surrogates)", "",
          "| participant | role | fighting wr | mirror wr | seam agg wr "
          "| Δ vs control |", "|---|---|---|---|---|---|"]
    for pid, s in rep["seam"].items():
        f = s["per_seam"].get("fighting", {})
        mi = s["per_seam"].get("mirror", {})
        agg = rep["seam_aggregate"].get(pid, {})
        L.append(f"| {pid} | {s.get('role')} | {f.get('win_rate')} | "
                 f"{mi.get('win_rate')} | {agg.get('win_rate')} | "
                 f"{rep['seam_delta_vs_control'].get(pid)} |")
    L += ["", "_Outcomes are directional only (surrogate opponents) and are NOT a "
          "promotion signal. The Part-H decision replay (zero behaviour deltas over "
          "262 real decisions) is the authoritative behavioural evidence; deep board "
          "metrics are NOT_MEASURED because the cabt board state is an opaque blob._",
          ""]
    (EXP / "pass25_focused_eval.md").write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-shards", action="store_true")
    g.add_argument("--shard", help="run one shard, e.g. h2h:deckout_guard_v1")
    g.add_argument("--aggregate", action="store_true")
    g.add_argument("--all", action="store_true",
                   help="run every shard then aggregate (only within shell budget)")
    args = ap.parse_args()

    if args.list_shards:
        for n in _shard_names():
            print(n)
        return 0
    if args.shard:
        d = _run_shard(args.shard)
        print(f"shard {args.shard} done in {d['elapsed_s']}s -> "
              f"{(SHARD_DIR / (args.shard.replace(':', '__') + '.json')).relative_to(REPO)}")
        return 0
    if args.all:
        for n in _shard_names():
            d = _run_shard(n)
            print(f"  shard {n:38s} {d['elapsed_s']}s")
        return _aggregate()
    if args.aggregate:
        return _aggregate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
