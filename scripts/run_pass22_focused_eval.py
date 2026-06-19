#!/usr/bin/env python3
"""Pass 22 (Part I) — focused, seat-swapped surrogate eval. LOCAL ONLY.

SURROGATE-BASED AND DIRECTIONAL ONLY. Opponent subfamily decks (Pass 13 refined
pool) are piloted by the generic surrogate brain, NOT real opponent policies.
These numbers never equal Kaggle results and are NEVER sufficient on their own to
promote or upload anything. No upload, no submission, no candidate generation, no
root edits.

Compares the Pass-22 candidate against its own lineage and the weighted opponent
pool, seat-swapped:

  * league_water_anti_disruption_pivot_v1  (Pass 22 candidate under test)
  * league_water_core_reference            (proven reference, no Pass-22 hooks)
  * core_pilot_water_v2_runtime            (deck-safe base lineage)

vs each weighted Pass-13 subfamily + the entrypoint-safe anchor, GAMES_PER_SEAT
each seat. Writes pass22_focused_eval.{json,md}, matchup_matrix.csv, ranking.{json,md}.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import signal
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

REPORTS = REPO / "data" / "reports"
POOL = REPO / "experiments" / "pass13_refined_meta_pool.yaml"

CANDIDATES = [
    ("league_water_anti_disruption_pivot_v1", "candidate_pass22",
     REPO / "data" / "submissions" / "candidates_pass22"
     / "league_water_anti_disruption_pivot_v1.tar.gz"),
    ("league_water_core_reference", "reference",
     REPO / "data" / "submissions" / "candidates_pass17"
     / "league_water_core_reference.tar.gz"),
    ("core_pilot_water_v2_runtime", "base_lineage",
     REPO / "data" / "submissions" / "candidates_pass14"
     / "core_pilot_water_v2_runtime.tar.gz"),
]
ANCHOR_CLONE = (REPO / "data" / "submissions" / "candidates_pass16"
                / "combo_full_safety_v3_entrypoint_safe_local.tar.gz")

GAME_TIMEOUT_S = int(os.environ.get("P22_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P22_GLOBAL_BUDGET_S", "1800"))
GAMES_PER_SEAT = int(os.environ.get("P22_GAMES_PER_SEAT", "6"))

DISCLAIMER = (
    "SURROGATE-BASED AND DIRECTIONAL ONLY. Opponent subfamily decks are piloted "
    "by a generic surrogate policy, not real opponent policies. These local "
    "numbers never equal Kaggle results and never justify upload/promotion.")


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


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _run_game(agent_a: str, agent_b: str) -> dict:
    from kaggle_environments import make
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run([agent_a, agent_b])
        last = env.steps[-1]
        return {"ok": True, "steps": len(env.steps),
                "rewards": [s.get("reward") for s in last],
                "statuses": [s.get("status") for s in last], "timeout": False}
    except _Timeout:
        return {"ok": False, "timeout": True, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return round(center - half, 4), round(center + half, 4)


def _matchup(cand_agent: str, opp_agent: str, n_per_seat: int,
             budget_left, label: str) -> dict:
    games = []
    for (a, b, our) in [(cand_agent, opp_agent, 0), (opp_agent, cand_agent, 1)]:
        for _ in range(n_per_seat):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "our_seat": our})
                continue
            g = _run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = _outcome_for_seat(g, our)
            games.append(g)
    wins = sum(1 for g in games if g.get("outcome") == "win")
    losses = sum(1 for g in games if g.get("outcome") == "loss")
    draws = sum(1 for g in games if g.get("outcome") == "draw")
    decisive = wins + losses
    n = wins + losses + draws
    lo, hi = _wilson(wins, decisive)
    return {
        "label": label, "n_games": n, "wins": wins, "losses": losses, "draws": draws,
        "win_rate": round(wins / decisive, 4) if decisive else None,
        "wilson_low": lo, "wilson_high": hi,
        "crashes": sum(1 for g in games if not g.get("ok")
                       and not g.get("timeout") and not g.get("skipped")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games
                          if not g.get("ok") and g.get("error")}),
    }


def _load_subfamilies() -> list[dict]:
    if yaml is None or not POOL.exists():
        return []
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    out = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours") or not (a.get("weight") or 0) > 0:
            continue
        deck = a.get("surrogate_deck")
        if deck and (REPO / deck).exists():
            out.append({"key": a["key"], "deck": str(REPO / deck),
                        "weight": float(a["weight"])})
    return out


def _weighted(per_opp: dict, weights: dict) -> float | None:
    acc = tw = 0.0
    for k, m in per_opp.items():
        wr = m.get("win_rate")
        w = weights.get(k, 0.0)
        if wr is None or w <= 0:
            continue
        acc += wr * w
        tw += w
    return round(acc / tw, 4) if tw else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games-per-seat", type=int, default=GAMES_PER_SEAT)
    args = ap.parse_args()
    n_per_seat = args.games_per_seat

    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    notes: list[str] = []
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)

        cands = []
        for cid, role, tar in CANDIDATES:
            if tar.exists() and _validate_tarball(tar):
                cands.append({"id": cid, "role": role,
                              "agent": _extract_agent(tar, tmp / cid)})
            else:
                notes.append(f"{cid} tarball missing/invalid -> excluded")

        opponents = []
        from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent
        weights = {}
        for s in _load_subfamilies():
            od = tmp / ("opp_" + s["key"])
            opponents.append({"key": s["key"],
                              "agent": str(materialize_surrogate_agent(s["deck"], od))})
            weights[s["key"]] = s["weight"]
        if ANCHOR_CLONE.exists() and _validate_tarball(ANCHOR_CLONE):
            opponents.append({"key": "entrypoint_safe_anchor",
                              "agent": _extract_agent(ANCHOR_CLONE, tmp / "anchor")})
        else:
            notes.append("entrypoint-safe anchor missing/invalid")

        results = {}
        for c in cands:
            per_opp = {}
            for o in opponents:
                label = f"{c['id']} vs {o['key']}"
                per_opp[o["key"]] = _matchup(c["agent"], o["agent"],
                                             n_per_seat, budget_left, label)
            results[c["id"]] = {
                "role": c["role"], "per_opponent": per_opp,
                "weighted_pool_win_rate": _weighted(per_opp, weights),
            }

    rep = {
        "pass": "22", "part": "I", "mode": "focused_eval", "local_only": True,
        "upload_performed": False, "no_upload": True,
        "disclaimer": DISCLAIMER, "games_per_seat": n_per_seat,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "opponent_weights": weights, "notes": notes, "results": results,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "pass22_focused_eval.json").write_text(
        json.dumps(rep, indent=2), encoding="utf-8")

    # matchup_matrix.csv
    opp_keys = sorted({k for r in results.values() for k in r["per_opponent"]})
    mm = REPORTS / "pass22_matchup_matrix.csv"
    with mm.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["candidate"] + opp_keys + ["weighted_pool"])
        for cid, r in results.items():
            row = [cid]
            for k in opp_keys:
                m = r["per_opponent"].get(k, {})
                row.append(m.get("win_rate") if m.get("win_rate") is not None else "")
            row.append(r["weighted_pool_win_rate"])
            w.writerow(row)

    # ranking
    ranking = sorted(
        ({"candidate": cid, "role": r["role"],
          "weighted_pool_win_rate": r["weighted_pool_win_rate"]}
         for cid, r in results.items()),
        key=lambda x: (x["weighted_pool_win_rate"] is None,
                       -(x["weighted_pool_win_rate"] or 0)))
    rank_obj = {"pass": "22", "part": "I", "disclaimer": DISCLAIMER,
                "ranking": ranking, "no_upload": True}
    (REPORTS / "pass22_ranking.json").write_text(
        json.dumps(rank_obj, indent=2), encoding="utf-8")

    # markdown
    lines = ["# Pass 22 — Focused Surrogate Eval (directional only)", "",
             f"- generated: {rep['generated_at']}",
             f"- games/seat: {n_per_seat}  (seat-swapped)",
             f"- {DISCLAIMER}", ""]
    if notes:
        lines += ["**Notes:** " + "; ".join(notes), ""]
    lines += ["| candidate | role | " + " | ".join(opp_keys) + " | weighted_pool |",
              "|" + "---|" * (len(opp_keys) + 3)]
    for cid, r in results.items():
        cells = []
        for k in opp_keys:
            m = r["per_opponent"].get(k, {})
            wr = m.get("win_rate")
            cells.append("—" if wr is None else f"{wr:.2f}")
        lines.append(f"| {cid} | {r['role']} | " + " | ".join(cells)
                     + f" | {r['weighted_pool_win_rate']} |")
    lines += ["", "## Ranking (weighted pool win-rate)", ""]
    for i, e in enumerate(ranking, 1):
        lines.append(f"{i}. **{e['candidate']}** ({e['role']}): "
                     f"{e['weighted_pool_win_rate']}")
    lines.append("")
    (REPORTS / "pass22_focused_eval.md").write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "pass22_ranking.md").write_text(
        "\n".join(["# Pass 22 — Ranking (directional only)", "", f"- {DISCLAIMER}", ""]
                  + [f"{i}. **{e['candidate']}** ({e['role']}): "
                     f"{e['weighted_pool_win_rate']}" for i, e in enumerate(ranking, 1)]),
        encoding="utf-8")

    print(f"focused eval done: {len(results)} candidates x {len(opp_keys)} opponents")
    for e in ranking:
        print(f"  {e['candidate']:42s} weighted_pool={e['weighted_pool_win_rate']}")
    print(f"-> {(REPORTS / 'pass22_focused_eval.md').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
