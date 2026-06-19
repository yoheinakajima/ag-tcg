#!/usr/bin/env python3
"""Pass 25 (Part G) — live cabt smoke for the hardening candidates. LOCAL ONLY.

NOT a leaderboard and NOT a promotion signal. This is a VALIDITY smoke: every
candidate must complete real cabt games, seat-swapped, against four opponents
without any INVALID / ERROR / TIMEOUT status:

  * self    — candidate vs itself
  * control — candidate vs the Pass-22 pivot (the live-active family reference)
  * fighting— candidate vs the ``mega_lucario_ex_tempo`` surrogate (the Part-C
              prize-liability seam, episode 80623232)
  * mirror  — candidate vs the ``water_kyogre_abomasnow_maxbelt`` surrogate (the
              Part-C deckout seam, episode 80622626)

Opponent subfamily decks are piloted by the GENERIC surrogate brain, not real
opponent policies -- any win/loss tallies are directional only. The pass/fail
verdict here is purely "did it run cleanly" (no bad statuses, no crashes).

Writes data/experiments/pass25_live_smoke.{json,md}. Exit non-zero iff any
candidate produced a bad status, crash, or timeout. No upload, no root edits.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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

EXP = REPO / "data" / "experiments"
POOL = REPO / "experiments" / "pass13_refined_meta_pool.yaml"

CONTROL = ("control_pass22_pivot",
           REPO / "data" / "submissions" / "candidates_pass22"
           / "league_water_anti_disruption_pivot_v1.tar.gz")
CANDIDATES = [
    ("deckout_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25" / "deckout_guard_v1.tar.gz"),
    ("prize_liability_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25"
     / "prize_liability_guard_v1.tar.gz"),
    ("hybrid_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25" / "hybrid_guard_v1.tar.gz"),
]
FIGHTING_KEY = "mega_lucario_ex_tempo"
MIRROR_KEY = "water_kyogre_abomasnow_maxbelt"

GAME_TIMEOUT_S = int(os.environ.get("P25_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P25_GLOBAL_BUDGET_S", "1500"))
GAMES_PER_SEAT = int(os.environ.get("P25_GAMES_PER_SEAT", "1"))
BAD_STATUSES = {"INVALID", "ERROR", "TIMEOUT"}

DISCLAIMER = ("SURROGATE-BASED VALIDITY SMOKE, LOCAL ONLY. Opponent decks are "
              "piloted by a generic surrogate policy, not real opponent policies. "
              "The verdict is clean-run only; win/loss is directional and never "
              "justifies upload or promotion.")


def _load_meta_eval_mod():
    spec = importlib.util.spec_from_file_location(
        "run_meta_pool_eval", REPO / "scripts" / "run_meta_pool_eval.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load_meta_eval_mod()


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


def _matchup(cand_agent: str, opp_agent: str, n_per_seat: int, budget_left) -> dict:
    games = []
    for (a, b, our) in [(cand_agent, opp_agent, 0), (opp_agent, cand_agent, 1)]:
        for _ in range(n_per_seat):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True,
                              "reason": "global_budget_exhausted", "our_seat": our})
                continue
            g = _run_game(a, b)
            g["our_seat"] = our
            g["outcome"] = _MEV._outcome_for_seat(g, our) if g.get("ok") else None
            games.append(g)
    bad = sorted({s for g in games for s in (g.get("statuses") or [])
                  if s in BAD_STATUSES})
    crashes = sum(1 for g in games if not g.get("ok")
                  and not g.get("timeout") and not g.get("skipped"))
    timeouts = sum(1 for g in games if g.get("timeout"))
    return {
        "n_games": len(games),
        "completed": sum(1 for g in games if g.get("ok")),
        "bad_statuses": bad,
        "crashes": crashes,
        "timeouts": timeouts,
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games
                          if not g.get("ok") and g.get("error")}),
        "outcomes": [g.get("outcome") for g in games if g.get("ok")],
        "clean": not bad and crashes == 0 and timeouts == 0,
    }


def _subfamily_deck(key: str) -> str | None:
    if yaml is None or not POOL.exists():
        return None
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    for a in pool.get("archetypes", []):
        if a.get("key") == key:
            d = a.get("surrogate_deck")
            return str(REPO / d) if d and (REPO / d).exists() else None
    return None


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
    results: dict = {}
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        from ptcg_activegraph.sim.surrogate_agents import materialize_surrogate_agent

        # Opponents (shared across candidates).
        opp_agents: dict = {}
        if CONTROL[1].exists() and _MEV._validate_tarball(CONTROL[1]):
            opp_agents["control"] = _MEV._extract_agent(CONTROL[1], tmp / "control")
        else:
            notes.append("control tarball missing/invalid -> control matchup skipped")
        for label, key in (("fighting", FIGHTING_KEY), ("mirror", MIRROR_KEY)):
            deck = _subfamily_deck(key)
            if deck:
                opp_agents[label] = str(
                    materialize_surrogate_agent(deck, tmp / ("opp_" + label)))
            else:
                notes.append(f"{label} surrogate ({key}) deck missing -> skipped")

        for cid, tar in CANDIDATES:
            if not (tar.exists() and _MEV._validate_tarball(tar)):
                notes.append(f"{cid} tarball missing/invalid -> excluded")
                continue
            cand_agent = _MEV._extract_agent(tar, tmp / cid)
            per_opp = {"self": _matchup(cand_agent, cand_agent, n_per_seat,
                                        budget_left)}
            for label, agent in opp_agents.items():
                per_opp[label] = _matchup(cand_agent, agent, n_per_seat, budget_left)
            results[cid] = {
                "per_opponent": per_opp,
                "clean": all(m["clean"] for m in per_opp.values()),
                "all_bad_statuses": sorted({s for m in per_opp.values()
                                            for s in m["bad_statuses"]}),
            }

    all_clean = bool(results) and all(r["clean"] for r in results.values())
    rep = {
        "pass": "25", "part": "G", "mode": "live_smoke", "local_only": True,
        "no_upload": True, "upload_performed": False,
        "disclaimer": DISCLAIMER, "games_per_seat": n_per_seat,
        "opponents": ["self", "control", "fighting", "mirror"],
        "fighting_surrogate": FIGHTING_KEY, "mirror_surrogate": MIRROR_KEY,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "smoke_ok": all_clean, "notes": notes, "results": results,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass25_live_smoke.json").write_text(json.dumps(rep, indent=2),
                                                encoding="utf-8")

    opp_cols = ["self", "control", "fighting", "mirror"]
    L = ["# Pass 25 — live cabt smoke (Part G)", "",
         "> LOCAL ONLY — surrogate validity smoke, NOT a leaderboard.", "",
         f"- generated: {rep['generated_at']}",
         f"- games/seat: {n_per_seat} (seat-swapped)",
         f"- fighting surrogate: `{FIGHTING_KEY}`  mirror surrogate: `{MIRROR_KEY}`",
         f"- overall smoke: **{'PASS' if all_clean else 'FAIL'}**",
         f"- {DISCLAIMER}", ""]
    if notes:
        L += ["**Notes:** " + "; ".join(notes), ""]
    L += ["| candidate | " + " | ".join(opp_cols) + " | clean |",
          "|---|" + "|".join(["---"] * (len(opp_cols) + 1)) + "|"]
    for cid, r in results.items():
        cells = []
        for k in opp_cols:
            m = r["per_opponent"].get(k)
            if not m:
                cells.append("—")
            else:
                cells.append("clean" if m["clean"]
                             else f"BAD:{m['bad_statuses'] or m['errors']}")
        L.append(f"| {cid} | " + " | ".join(cells)
                 + f" | {'yes' if r['clean'] else 'NO'} |")
    L += ["", "_Outcomes are directional only (surrogate opponents) and are NOT a "
          "promotion signal; this gate asserts clean execution only._", ""]
    (EXP / "pass25_live_smoke.md").write_text("\n".join(L), encoding="utf-8")

    for cid, r in results.items():
        print(f"{cid}: clean={r['clean']} bad={r['all_bad_statuses']}")
    print(f"\nsmoke_ok={all_clean}\nwrote {EXP / 'pass25_live_smoke.json'}")
    return 0 if all_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
