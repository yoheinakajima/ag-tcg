#!/usr/bin/env python3
"""Pass 30 (Part H) — parent/child hardening confirmations. LOCAL ONLY.

NOT a Kaggle leaderboard. Focused, higher-volume (10 games/seat, seat-swapped)
head-to-heads that ask one question per pair: did the hardening variant change
behaviour vs its parent, in a real cabt game, with the same generic core pilot on
both sides? Win/loss is directional only; the value here is the DELTA and whether
both sides run cleanly.

Pairs (parent -> child / base -> variant):
  * Dragapult: league_dragapult_spread       vs search_only, vs draw_only
  * Venusaur:  league_mega_venusaur_tank      vs effect_loop_exit_guard_v1
               (child deck is byte-identical to parent; runtime loop-guard hook only)
  * Raging Bolt: league_raging_bolt_ogerpon   vs consistency_v1, vs energy_attacker_v1
  * Water benchmark: league_water_core_reference vs best non-water (dragapult search_only)

Reuses the Part-G matchup engine (in-proc cabt, SIGALRM watchdog, behavioral
metrics). RESUMABLE per pair. Writes data/experiments/
pass30_parent_child_confirmations.{json,md}. No upload/submit/push.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass30"
PROGRESS = EXP / "pass30_parent_child_confirmations_progress.json"
GAMES_PER_SEAT = 10
PER_CALL_BUDGET_S = int(os.environ.get("P30_PER_CALL_BUDGET_S", "55"))

DISCLAIMER = (
    "LOCAL parent/child confirmation — NOT a Kaggle leaderboard. Same generic core "
    "pilot on both sides; win/loss is directional and the signal is the behavioural "
    "DELTA + clean execution, never a promotion or upload decision.")

PAIRS = [
    {"id": "dragapult_parent_vs_search_only", "family": "dragapult",
     "parent": "league_dragapult_spread", "child": "league_dragapult_v1_search_only",
     "question": "Does the search-only child diverge from the spread parent?"},
    {"id": "dragapult_parent_vs_draw_only", "family": "dragapult",
     "parent": "league_dragapult_spread", "child": "league_dragapult_v1_draw_only",
     "question": "Does the draw-only child diverge from the spread parent?"},
    {"id": "venusaur_parent_vs_loop_guard", "family": "venusaur",
     "parent": "league_mega_venusaur_tank", "child": "effect_loop_exit_guard_v1",
     "question": ("Runtime loop-guard hook on a byte-identical deck: does it change "
                  "outcomes / does the tank stop stalling?")},
    {"id": "raging_bolt_base_vs_consistency", "family": "raging_bolt",
     "parent": "league_raging_bolt_ogerpon", "child": "league_raging_bolt_consistency_v1",
     "question": "Does the consistency rebuild (more draw/basics) help the base?"},
    {"id": "raging_bolt_base_vs_energy_attacker", "family": "raging_bolt",
     "parent": "league_raging_bolt_ogerpon",
     "child": "league_raging_bolt_energy_attacker_v1",
     "question": "Does the energy-attacker rebuild (more energy) help the base?"},
    {"id": "water_benchmark_vs_best_non_water", "family": "water",
     "parent": "league_water_core_reference", "child": "league_dragapult_v1_search_only",
     "question": "Water core benchmark vs the strongest non-water portfolio deck."},
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_T = _load("run_pass30_portfolio_tournament")


def _interpret(m: dict) -> str:
    wr = m["a_win_rate"]
    lo, hi = m["a_wilson"]
    if m["crashes"] or m["timeouts"] or m["invalids"]:
        return "NOT CLEAN — crash/timeout/invalid present; investigate before any use"
    if wr is None:
        return "no decisive games (all draws)"
    parent_fa = m.get("a_avg_first_attack_step")
    child_fa = m.get("b_avg_first_attack_step")
    fa_note = ""
    if parent_fa is not None and child_fa is not None:
        fa_note = (f" first-attack step parent={parent_fa} vs child={child_fa}"
                   f" (Δ={round(child_fa - parent_fa, 2)})")
    if lo is not None and lo > 0.5:
        return f"parent significantly ahead of child (CI>0.5).{fa_note}"
    if hi is not None and hi < 0.5:
        return f"child significantly ahead of parent (CI<0.5).{fa_note}"
    return ("no significant parent/child separation (CI spans 0.5): the variant "
            f"runs cleanly but is behaviourally close to its parent.{fa_note}")


def _play(pair: dict, agents: dict) -> dict:
    a, b = pair["parent"], pair["child"]
    m = _T._play_matchup(a, agents[a], b, agents[b], GAMES_PER_SEAT)
    # capture child (b) behavioural metrics too, mirroring the engine for seat b
    return {**pair, **m, "interpretation": _interpret(m)}


def _augment_child_metrics(games_module, pair, agents):
    return None  # behavioural deltas summarised from engine output; placeholder hook


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists()
            else {"pass": "30", "part": "H", "local_only": True, "no_upload": True,
                  "upload_performed": False, "is_kaggle_leaderboard": False,
                  "disclaimer": DISCLAIMER, "games_per_seat": GAMES_PER_SEAT,
                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "pairs": {}})
    pending = [p for p in PAIRS if p["id"] not in prog["pairs"]]
    if not pending:
        print("parent/child confirmations already complete")
    else:
        need = {x for p in pending for x in (p["parent"], p["child"])}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            agents = {}
            for pid in need:
                tar = CAND / f"{pid}.tar.gz"
                if tar.exists() and _T._validate_tarball(tar):
                    agents[pid] = _T._extract_agent(tar, tmp / pid)
            start = time.time()
            for pair in pending:
                if time.time() - start > PER_CALL_BUDGET_S and prog["pairs"]:
                    break
                if pair["parent"] not in agents or pair["child"] not in agents:
                    prog["pairs"][pair["id"]] = {**pair, "error": "agent missing"}
                    continue
                prog["pairs"][pair["id"]] = _play(pair, agents)
                PROGRESS.write_text(json.dumps(prog, indent=2, default=str),
                                    encoding="utf-8")

    done = all(p["id"] in prog["pairs"] for p in PAIRS)
    PROGRESS.write_text(json.dumps(prog, indent=2, default=str), encoding="utf-8")
    out = {**prog, "status": "complete" if done else "in_progress",
           "pairs": list(prog["pairs"].values())}
    (EXP / "pass30_parent_child_confirmations.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 30 — parent/child hardening confirmations (Part H)", "",
         f"> {DISCLAIMER}", "",
         f"- status: **{out['status']}**  games/seat: {GAMES_PER_SEAT} (seat-swapped)",
         f"- is Kaggle leaderboard: **False**  upload_performed: **False**", "",
         "| pair | family | parent | child | parent W-L-D | parent win_rate | 95% CI | "
         "inv/to/crash | interpretation |",
         "|---|---|---|---|---|---|---|---|---|"]
    for p in PAIRS:
        m = prog["pairs"].get(p["id"])
        if not m or "a_win_rate" not in m:
            L.append(f"| {p['id']} | {p['family']} | {p['parent']} | {p['child']} | "
                     f"_pending_ |  |  |  | {m.get('error', '') if m else ''} |")
            continue
        L.append(f"| {p['id']} | {p['family']} | {p['parent']} | {p['child']} | "
                 f"{m['a_wins']}-{m['b_wins']}-{m['draws']} | {m['a_win_rate']} | "
                 f"[{m['a_wilson'][0]}, {m['a_wilson'][1]}] | "
                 f"{m['invalids']}/{m['timeouts']}/{m['crashes']} | "
                 f"{m['interpretation']} |")
    L += ["", "## Questions per pair"]
    for p in PAIRS:
        L.append(f"- **{p['id']}** — {p['question']}")
    L += ["", "_Win/loss is directional only (identical generic pilot both seats). "
          "The Venusaur child deck is byte-identical to its parent — any delta is the "
          "runtime loop-guard hook, not a deck change._", ""]
    (EXP / "pass30_parent_child_confirmations.md").write_text("\n".join(L),
                                                              encoding="utf-8")
    for p in PAIRS:
        m = prog["pairs"].get(p["id"], {})
        print(f"{p['id']:40} parent_wr={m.get('a_win_rate')} "
              f"clean={not (m.get('crashes') or m.get('timeouts') or m.get('invalids'))}")
    print(f"\nstatus={out['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
