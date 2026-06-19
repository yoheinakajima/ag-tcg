#!/usr/bin/env python3
"""Pass 30 (Part F) — live cabt smoke for the existing-portfolio candidates. LOCAL.

NOT a leaderboard and NOT a promotion signal. VALIDITY smoke: every built
candidate must complete real cabt games, seat-swapped, without any
INVALID / ERROR / TIMEOUT status, against two opponents:

  * self    — candidate vs itself (does the deck/pilot run at all)
  * control — candidate vs the Water core reference (head-to-head smoke)

Games run IN-PROCESS (kaggle_environments imported once) with a per-game SIGALRM
watchdog. Win/loss tallies are directional only (same generic pilot on both
sides) and never justify upload.

Durant is smoke-tested for honesty (its INVALID/clean status is recorded) but it
stays blocked_from_league by design regardless of the smoke verdict.

Writes data/experiments/pass30_live_smoke.{json,md}. Exit non-zero iff any
non-blocked candidate produced a bad status, crash, or timeout. No upload.
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
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import yaml  # type: ignore  # noqa: E402

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass30"
REGISTRY = REPO / "experiments" / "pass30_existing_portfolio.yaml"
CONTROL_ID = "league_water_core_reference"

GAME_TIMEOUT_S = int(os.environ.get("P30_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P30_GLOBAL_BUDGET_S", "1500"))
GAMES_PER_SEAT = int(os.environ.get("P30_SMOKE_GAMES_PER_SEAT", "1"))
BAD_STATUSES = {"INVALID", "ERROR", "TIMEOUT"}

DISCLAIMER = ("SURROGATE-BASED VALIDITY SMOKE, LOCAL ONLY. Both sides run the "
              "same generic core pilot; the verdict is clean-run only, win/loss "
              "is directional and never justifies upload or promotion.")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")


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
        statuses = [s.get("status") for s in env.state]
        legal = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
        last = env.steps[-1]
        return {"ok": legal, "steps": len(env.steps),
                "rewards": [s.get("reward") for s in last],
                "statuses": statuses, "timeout": False, "invalid": not legal}
    except _Timeout:
        return {"ok": False, "timeout": True, "invalid": False, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "invalid": False, "error": repr(exc)}
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
    invalids = sum(1 for g in games if g.get("invalid"))
    crashes = sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                  and not g.get("skipped") and not g.get("invalid"))
    timeouts = sum(1 for g in games if g.get("timeout"))
    return {
        "n_games": len(games),
        "completed": sum(1 for g in games if g.get("ok")),
        "bad_statuses": bad, "invalids": invalids, "crashes": crashes,
        "timeouts": timeouts,
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games
                          if not g.get("ok") and g.get("error")}),
        "outcomes": [g.get("outcome") for g in games if g.get("ok")],
        "clean": not bad and invalids == 0 and crashes == 0 and timeouts == 0,
    }


def _candidate_list() -> list[tuple[str, bool]]:
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    out = []
    for fam in (reg.get("families") or {}).values():
        for c in fam.get("candidates", []):
            out.append((c["candidate_id"], bool(c.get("blocked_from_league"))))
    return out


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
        cands = _candidate_list()
        agents: dict[str, str] = {}
        for cid, _blk in cands:
            tar = CAND / f"{cid}.tar.gz"
            if tar.exists() and _MEV._validate_tarball(tar):
                agents[cid] = _MEV._extract_agent(tar, tmp / cid)
            else:
                notes.append(f"{cid} tarball missing/invalid -> excluded from smoke")

        control_agent = agents.get(CONTROL_ID)
        for cid, blocked in cands:
            if cid not in agents:
                continue
            per_opp = {"self": _matchup(agents[cid], agents[cid], n_per_seat,
                                        budget_left)}
            if control_agent and cid != CONTROL_ID:
                per_opp["control"] = _matchup(agents[cid], control_agent,
                                              n_per_seat, budget_left)
            results[cid] = {
                "blocked_from_league": blocked,
                "per_opponent": per_opp,
                "clean": all(m["clean"] for m in per_opp.values()),
                "all_bad_statuses": sorted({s for m in per_opp.values()
                                            for s in m["bad_statuses"]}),
            }

    # Overall smoke passes if all NON-BLOCKED candidates are clean.
    non_blocked = {k: v for k, v in results.items() if not v["blocked_from_league"]}
    all_clean = bool(non_blocked) and all(r["clean"] for r in non_blocked.values())
    rep = {
        "pass": "30", "part": "F", "mode": "live_smoke", "local_only": True,
        "no_upload": True, "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER, "games_per_seat": n_per_seat,
        "opponents": ["self", "control"], "control": CONTROL_ID,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "smoke_ok": all_clean, "notes": notes, "results": results,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_live_smoke.json").write_text(json.dumps(rep, indent=2),
                                                encoding="utf-8")

    opp_cols = ["self", "control"]
    L = ["# Pass 30 — live cabt smoke (Part F)", "",
         "> LOCAL ONLY — surrogate validity smoke, NOT a leaderboard.", "",
         f"- generated: {rep['generated_at']}",
         f"- games/seat: {n_per_seat} (seat-swapped)  control: `{CONTROL_ID}`",
         f"- overall smoke (non-blocked): **{'PASS' if all_clean else 'FAIL'}**",
         f"- {DISCLAIMER}", ""]
    if notes:
        L += ["**Notes:** " + "; ".join(notes), ""]
    L += ["| candidate | blocked | " + " | ".join(opp_cols) + " | clean |",
          "|---|---|" + "|".join(["---"] * (len(opp_cols) + 1)) + "|"]
    for cid, r in results.items():
        cells = []
        for k in opp_cols:
            m = r["per_opponent"].get(k)
            cells.append("—" if not m else ("clean" if m["clean"]
                         else f"BAD:{m['bad_statuses'] or m['errors']}"))
        L.append(f"| {cid} | {r['blocked_from_league']} | " + " | ".join(cells)
                 + f" | {'yes' if r['clean'] else 'NO'} |")
    L += ["", "_Outcomes are directional only (same generic pilot both seats) and "
          "are NOT a promotion signal; this gate asserts clean execution only._", ""]
    (EXP / "pass30_live_smoke.md").write_text("\n".join(L), encoding="utf-8")

    for cid, r in results.items():
        print(f"{cid}: clean={r['clean']} bad={r['all_bad_statuses']} "
              f"blocked={r['blocked_from_league']}")
    print(f"\nsmoke_ok={all_clean}\nwrote {EXP / 'pass30_live_smoke.json'}")
    return 0 if all_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
