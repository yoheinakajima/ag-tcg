#!/usr/bin/env python3
"""Pass 33 (Part F) — candidate validation + live cabt smoke. LOCAL / no upload.

Two gates over every candidate in data/submissions/candidates_pass33/:

  1. STATIC validation — validate_candidate_tarball (top-level main.py+deck.csv,
     60 ids, no invented ids, stdlib-only) AND validate_candidate_entrypoint
     (agent importable, returns the same 60 ids during deck selection).
  2. LIVE smoke — real seat-swapped cabt games vs two opponents:
       * self    — candidate vs itself (does the deck/pilot run);
       * control — candidate vs the Water core reference.
     A candidate is smoke-clean iff no game returns INVALID/ERROR/TIMEOUT.

Eligibility = static PASS AND smoke clean AND not blocked_from_league. Durant is
smoked for honesty but stays blocked regardless of verdict. Outcomes are
directional only (same generic pilot on both seats) and never justify upload.

Writes pass33_candidate_validation.{json,md} and pass33_live_smoke.{json,md}.
Exit non-zero iff any NON-blocked candidate fails a gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass33"
PLAN = EXP / "pass33_stress_test_plan.json"
CONTROL_ID = "league_water_core_reference"

GAME_TIMEOUT_S = int(os.environ.get("P33_GAME_TIMEOUT_S", "60"))
GLOBAL_BUDGET_S = int(os.environ.get("P33_GLOBAL_BUDGET_S", "1800"))
GAMES_PER_SEAT = int(os.environ.get("P33_SMOKE_GAMES_PER_SEAT", "1"))
BAD = {"INVALID", "ERROR", "TIMEOUT"}
DISCLAIMER = ("SURROGATE-BASED VALIDITY SMOKE, LOCAL ONLY. Both sides run the "
              "same generic core pilot; the verdict is clean-run only, win/loss "
              "is directional and never justifies upload or promotion.")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_MEV = _load("run_meta_pool_eval")
_VTAR = _load("validate_candidate_tarball")
_VENT = _load("validate_candidate_entrypoint")


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
        statuses = [s.get("status") for s in last]
        return {"ok": True, "steps": len(env.steps),
                "rewards": [s.get("reward") for s in last],
                "statuses": statuses, "timeout": False,
                "invalid": any(s in BAD for s in statuses)}
    except _Timeout:
        return {"ok": False, "timeout": True, "invalid": False, "error": "watchdog"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "invalid": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _matchup(a_agent, b_agent, n, budget_left):
    games = []
    for (a, b, seat) in [(a_agent, b_agent, 0), (b_agent, a_agent, 1)]:
        for _ in range(n):
            if budget_left() <= 0:
                games.append({"ok": False, "skipped": True, "our_seat": seat,
                              "reason": "budget_exhausted"})
                continue
            g = _run_game(a, b)
            g["our_seat"] = seat
            g["outcome"] = _MEV._outcome_for_seat(g, seat) if g.get("ok") else None
            games.append(g)
    bad = sorted({s for g in games for s in (g.get("statuses") or []) if s in BAD})
    return {
        "n_games": len(games),
        "completed": sum(1 for g in games if g.get("ok")),
        "bad_statuses": bad,
        "invalids": sum(1 for g in games if g.get("invalid")),
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "crashes": sum(1 for g in games if not g.get("ok") and not g.get("timeout")
                       and not g.get("skipped") and not g.get("invalid")),
        "skipped": sum(1 for g in games if g.get("skipped")),
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
        "outcomes": [g.get("outcome") for g in games if g.get("ok")],
        "clean": (not bad
                  and all(g.get("ok") or g.get("skipped") for g in games)),
    }


def _static_validate(tar: Path) -> dict:
    rc_tar = _VTAR.validate(str(tar))
    rc_ent = _VENT.validate(str(tar), smoke=False)
    return {"tarball_rc": rc_tar, "entrypoint_rc": rc_ent,
            "passed": rc_tar == 0 and rc_ent == 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games-per-seat", type=int, default=GAMES_PER_SEAT)
    args = ap.parse_args()
    n = args.games_per_seat

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    blocked_map = {c["candidate_id"]: bool(c.get("blocked_from_league"))
                   for c in plan["candidates"]}
    cand_ids = [c["candidate_id"] for c in plan["candidates"]]

    start = time.time()

    def budget_left():
        return GLOBAL_BUDGET_S - (time.time() - start)

    # --- static validation ---
    static = {}
    for cid in cand_ids:
        tar = CAND / f"{cid}.tar.gz"
        static[cid] = ({"passed": False, "reason": "tarball missing"}
                       if not tar.exists() else _static_validate(tar))

    val_rep = {
        "pass": "33", "part": "F", "stage": "static_validation",
        "no_upload": True, "upload_performed": False,
        "is_kaggle_leaderboard": False,
        "candidates_dir": str(CAND.relative_to(REPO)),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": {cid: {**static[cid], "blocked_from_league": blocked_map.get(cid)}
                    for cid in cand_ids},
        "all_passed": all(static[c]["passed"] for c in cand_ids
                          if not blocked_map.get(c)),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass33_candidate_validation.json").write_text(
        json.dumps(val_rep, indent=2), encoding="utf-8")
    VL = ["# Pass 33 — Candidate Static Validation (Part F)", "",
          "> LOCAL / no upload. tarball + entrypoint validators.", "",
          f"- generated: {val_rep['generated_at']}",
          f"- all non-blocked passed: **{val_rep['all_passed']}**", "",
          "| candidate | tarball_rc | entrypoint_rc | passed | blocked |",
          "|---|---|---|---|---|"]
    for cid in cand_ids:
        r = static[cid]
        VL.append(f"| {cid} | {r.get('tarball_rc','-')} | "
                  f"{r.get('entrypoint_rc','-')} | "
                  f"{'yes' if r.get('passed') else 'NO'} | "
                  f"{blocked_map.get(cid)} |")
    (EXP / "pass33_candidate_validation.md").write_text("\n".join(VL) + "\n",
                                                        encoding="utf-8")

    # --- live smoke (only over statically-valid tarballs) ---
    notes = []
    results = {}
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        agents = {}
        for cid in cand_ids:
            tar = CAND / f"{cid}.tar.gz"
            if tar.exists() and _MEV._validate_tarball(tar):
                agents[cid] = _MEV._extract_agent(tar, tmp / cid)
            else:
                notes.append(f"{cid}: tarball missing/invalid -> excluded from smoke")
        control = agents.get(CONTROL_ID)
        for cid in cand_ids:
            if cid not in agents:
                continue
            per = {"self": _matchup(agents[cid], agents[cid], n, budget_left)}
            if control and cid != CONTROL_ID:
                per["control"] = _matchup(agents[cid], control, n, budget_left)
            results[cid] = {
                "blocked_from_league": blocked_map.get(cid),
                "per_opponent": per,
                "clean": all(m["clean"] for m in per.values()),
                "all_bad_statuses": sorted({s for m in per.values()
                                            for s in m["bad_statuses"]}),
            }

    non_blocked = {k: v for k, v in results.items() if not v["blocked_from_league"]}
    smoke_ok = bool(non_blocked) and all(r["clean"] for r in non_blocked.values())
    eligible = sorted(cid for cid in cand_ids
                      if static[cid].get("passed")
                      and results.get(cid, {}).get("clean")
                      and not blocked_map.get(cid))
    smoke_rep = {
        "pass": "33", "part": "F", "mode": "live_smoke", "local_only": True,
        "no_upload": True, "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER, "games_per_seat": n,
        "opponents": ["self", "control"], "control": CONTROL_ID,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "smoke_ok": smoke_ok, "tournament_eligible": eligible,
        "notes": notes, "results": results,
    }
    (EXP / "pass33_live_smoke.json").write_text(json.dumps(smoke_rep, indent=2),
                                                encoding="utf-8")
    SL = ["# Pass 33 — Live cabt Smoke (Part F)", "",
          f"> LOCAL ONLY. {DISCLAIMER}", "",
          f"- generated: {smoke_rep['generated_at']}",
          f"- games/seat: {n} (seat-swapped); control: `{CONTROL_ID}`",
          f"- overall smoke (non-blocked): **{'PASS' if smoke_ok else 'FAIL'}**",
          f"- tournament-eligible: {eligible}", ""]
    if notes:
        SL += ["**Notes:** " + "; ".join(notes), ""]
    SL += ["| candidate | blocked | self | control | clean |",
           "|---|---|---|---|---|"]
    for cid in cand_ids:
        r = results.get(cid)
        if not r:
            SL.append(f"| {cid} | {blocked_map.get(cid)} | — | — | NO |")
            continue
        cells = []
        for k in ("self", "control"):
            m = r["per_opponent"].get(k)
            cells.append("—" if not m else ("clean" if m["clean"]
                         else f"BAD:{m['bad_statuses'] or m['errors']}"))
        SL.append(f"| {cid} | {r['blocked_from_league']} | {cells[0]} | "
                  f"{cells[1]} | {'yes' if r['clean'] else 'NO'} |")
    SL += ["", "_Win/loss is directional only (same generic pilot both seats); "
           "this gate asserts clean execution, never promotion._", ""]
    (EXP / "pass33_live_smoke.md").write_text("\n".join(SL), encoding="utf-8")

    for cid in cand_ids:
        r = results.get(cid, {})
        print(f"{cid}: static={static[cid].get('passed')} "
              f"smoke_clean={r.get('clean')} blocked={blocked_map.get(cid)}")
    print(f"\nstatic_all_passed={val_rep['all_passed']} smoke_ok={smoke_ok}")
    print(f"eligible={eligible}")
    bad_nonblocked = [c for c in cand_ids if not blocked_map.get(c)
                      and not (static[c].get("passed")
                               and results.get(c, {}).get("clean"))]
    return 1 if bad_nonblocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
