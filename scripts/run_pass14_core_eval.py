#!/usr/bin/env python3
"""Pass 14 — small DIRECTIONAL eval of the core-pilot candidate.

SURROGATE-BASED and DIRECTIONAL ONLY. Opponent decks are piloted by a generic
surrogate policy, not the real opponent policy. These results never equal Kaggle
results and are NEVER sufficient to promote or upload a candidate. No upload, no
submission, no GitHub push.

Compares ``core_pilot_water_v1`` against the active control across a few refined
Pass-13 surrogate subfamilies (seat-swapped), plus a direct head-to-head and an
active-control self-mirror diagnostic. The core-pilot runtime only refines the
ToHand-search target at the reliably identifiable cabt search context, so any
delta is expected to be small — this eval is a sanity/no-regression signal, not a
promotion proof.

Gated on cabt availability and a global time budget; writes partial results and
marks the run incomplete rather than hanging. Outputs:
  data/reports/pass14_core_eval.json / .md
  data/reports/pass14_core_eval_matrix.csv
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

import run_meta_pool_eval as eng  # reuse proven game primitives  # noqa: E402
from ptcg_activegraph.sim.surrogate_agents import (  # noqa: E402
    materialize_surrogate_agent,
)

REFINED = REPO / "experiments" / "pass13_refined_meta_pool.yaml"
CAND14 = REPO / "data" / "submissions" / "candidates_pass14"
CAND = REPO / "data" / "submissions" / "candidates"
OUT_JSON = REPO / "data" / "reports" / "pass14_core_eval.json"
OUT_MD = REPO / "data" / "reports" / "pass14_core_eval.md"
OUT_CSV = REPO / "data" / "reports" / "pass14_core_eval_matrix.csv"

DISCLAIMER = (
    "Surrogate-based and DIRECTIONAL ONLY. Opponent decks are piloted by a generic "
    "surrogate policy, not the real opponent policy. These results never equal "
    "Kaggle results and are not sufficient to promote or upload a candidate."
)


def _opponents(limit: int) -> list:
    if not REFINED.exists():
        return []
    pool = yaml.safe_load(REFINED.read_text(encoding="utf-8")) or {}
    opps = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours"):
            continue
        deck = a.get("surrogate_deck")
        if deck and (REPO / deck).exists():
            opps.append({"key": a["key"], "deck": str(REPO / deck),
                         "weight": a.get("weight"), "confidence": a.get("confidence")})
    return opps[:limit]


def run(max_opponents: int = 2) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    if not eng._cabt_available():
        return {"ok": False, "complete": False, "reason": "cabt not available",
                "disclaimer": DISCLAIMER, "started": started, "matchups": []}

    cand_tar = CAND14 / "core_pilot_water_v1.tar.gz"
    ac_name = eng._active_control_name()
    ac_tar = CAND / f"{ac_name}.tar.gz"
    if not (cand_tar.exists() and ac_tar.exists()):
        return {"ok": False, "complete": False,
                "reason": "candidate or active-control tarball missing",
                "disclaimer": DISCLAIMER, "started": started, "matchups": []}

    import time
    deadline = time.time() + eng.GLOBAL_BUDGET_S

    def budget_left():
        return deadline - time.time()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cand_agent = eng._extract_agent(cand_tar, tmp / "candidate")
        ac_agent = eng._extract_agent(ac_tar, tmp / "active_control")

        matchups = []
        # 1. Direct head-to-head vs the active control.
        matchups.append({"opponent": "active_control_head_to_head",
                         **eng._run_matchup(cand_agent, ac_agent, budget_left,
                                            "core_pilot_water_v1 vs active_control")})
        # 2. Active-control self-mirror diagnostic.
        matchups.append({"opponent": "active_control_self_mirror",
                         **eng._run_matchup(ac_agent, ac_agent, budget_left,
                                            "active_control mirror")})
        # 3. Candidate + active control vs each refined surrogate subfamily.
        for opp in _opponents(max_opponents):
            try:
                opp_agent = str(materialize_surrogate_agent(
                    opp["deck"], tmp / ("surr_" + opp["key"])))
            except Exception as exc:
                matchups.append({"opponent": opp["key"], "error": repr(exc),
                                 "ok": False})
                continue
            matchups.append({"opponent": opp["key"], "role": "candidate",
                             "weight": opp.get("weight"),
                             **eng._run_matchup(cand_agent, opp_agent, budget_left,
                                                f"core_pilot vs {opp['key']}")})
            matchups.append({"opponent": opp["key"], "role": "active_control",
                             "weight": opp.get("weight"),
                             **eng._run_matchup(ac_agent, opp_agent, budget_left,
                                                f"active_control vs {opp['key']}")})

        complete = all(m.get("skipped", 0) == 0 for m in matchups
                       if isinstance(m.get("skipped"), int))
        return {"ok": True, "complete": complete, "disclaimer": DISCLAIMER,
                "started": started, "ended": datetime.now(timezone.utc).isoformat(),
                "games_per_seat": eng.GAMES_PER_SEAT,
                "global_budget_s": eng.GLOBAL_BUDGET_S, "matchups": matchups}


def _write_outputs(rep: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    lines = ["# Pass 14 — Core-Pilot Directional Eval", "",
             f"> {rep['disclaimer']}", "",
             f"- started: {rep.get('started')}",
             f"- complete: **{rep.get('complete')}**  ok: {rep.get('ok')}",
             f"- games/seat: {rep.get('games_per_seat')}  "
             f"budget_s: {rep.get('global_budget_s')}"]
    if rep.get("reason"):
        lines.append(f"- reason: {rep['reason']}")
    lines += ["", "| opponent | role | win rate | W-L-D | crash/timeout/skip |",
              "|---|---|---|---|---|"]
    rows = []
    for m in rep.get("matchups", []):
        if "wins" not in m:
            lines.append(f"| {m.get('opponent')} | {m.get('role','-')} | error | - | - |")
            continue
        wr = m.get("win_rate")
        lines.append(f"| {m.get('opponent')} | {m.get('role','-')} | "
                     f"{wr if wr is not None else '-'} | "
                     f"{m['wins']}-{m['losses']}-{m['draws']} | "
                     f"{m['crashes']}/{m['timeouts']}/{m['skipped']} |")
        rows.append([m.get("opponent"), m.get("role", "-"), wr,
                     m["wins"], m["losses"], m["draws"],
                     m["crashes"], m["timeouts"], m["skipped"]])
    lines += ["", "Directional only; small samples. A small/zero delta vs the active "
              "control is expected because the core-pilot runtime only refines the "
              "ToHand-search target. This is a no-regression sanity signal.", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["opponent", "role", "win_rate", "wins", "losses", "draws",
                    "crashes", "timeouts", "skipped"])
        w.writerows(rows)


def main() -> int:
    import os
    rep = run(max_opponents=int(os.environ.get("PASS14_MAX_OPPONENTS", "2")))
    _write_outputs(rep)
    print(OUT_MD.read_text(encoding="utf-8"))
    print(f"wrote {OUT_JSON}\nwrote {OUT_MD}\nwrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
