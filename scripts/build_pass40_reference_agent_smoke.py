#!/usr/bin/env python3
"""Pass 40 (Part G) — local cabt smoke matrix for cg_typed reference agents.

Proves each public reference agent is *runnable* in the local cabt harness from its
Part F immutable tarball (cg/ alongside main.py + deck.csv). Two modes per agent:

  * ``self``        — reference vs itself (does it play a full cabt game at all?)
  * ``vs_baseline`` — reference vs OUR frozen root baseline, BOTH seats (does it
                      cross-play against our own agent without ERROR/TIMEOUT?)

Each game runs in a killable child process (``run_one_game_subprocess`` + the cg
child) with a hard wall-clock budget; a wedged native game is reaped, never hangs the
batch. The harness is RESUMABLE: every finished game is persisted immediately to a
progress file and skipped on re-run, and each invocation stops after a wall budget so
it always fits inside one tool call. Re-invoke until it prints ``ALL DONE``.

Benchmark-only / feasibility: win/loss counts are recorded for context but are NOT a
strength claim and NOT a Kaggle score. NO upload/submit/promote/mutate; root main.py /
deck.csv are read-only; references never enter the queue/lifecycle/rankings.

Outputs (final, on completion):
  data/experiments/pass40_reference_agent_smoke.{json,md}
Progress (transient, gitignored under data/experiments):
  data/experiments/pass40_reference_agent_smoke_progress.json
"""
from __future__ import annotations

import json
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"
EXTRACTED = REF / "tarballs" / "_extracted"
PROGRESS = EXP / "pass40_reference_agent_smoke_progress.json"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
from ptcg_activegraph.reference_agents import (  # noqa: E402
    EXTERNAL_REFERENCE_STATUS, REFERENCE_AGENTS,
)

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_cg_reference_game_subprocess.py")
GAME_TIMEOUT = 110          # parent SIGTERM->SIGKILL bound per game
INVOCATION_WALL_BUDGET = 85  # stop this tick before the tool call would time out
ROOT_MAIN = REPO / "main.py"
ROOT_DECK = REPO / "deck.csv"


def _ensure_extracted(agent_id: str) -> Path:
    run = EXTRACTED / agent_id
    if not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REF / "tarballs" / f"{agent_id}.tar.gz") as t:
            safe_extract_all(t, run)
    return run


def _game_list() -> list[tuple[str, str, int]]:
    games = []
    for spec in REFERENCE_AGENTS:
        games.append((spec.agent_id, "self", 0))
        games.append((spec.agent_id, "vs_baseline", 0))
        games.append((spec.agent_id, "vs_baseline", 1))
    return games


def _load_progress() -> dict:
    if PROGRESS.is_file():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"games": {}}


def _run_game(agent_id: str, mode: str, seat: int, root_deck: list[int]) -> dict:
    run = _ensure_extracted(agent_id)
    ref_main = run / "main.py"
    ref_deck = load_deck(run / "deck.csv")
    if mode == "self":
        ctrl_main, ctrl_deck = ref_main, ref_deck
    else:
        ctrl_main, ctrl_deck = ROOT_MAIN, root_deck
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=ctrl_main, control_deck=ctrl_deck,
        cand_main=ref_main, cand_deck=ref_deck,
        candidate_seat=seat, timeout_seconds=GAME_TIMEOUT, child_script=CG_CHILD,
    )
    return {
        "agent_id": agent_id, "mode": mode, "candidate_seat": seat,
        "seconds": round(time.time() - t0, 1),
        "completed": bool(res.get("completed")),
        "error": res.get("error"), "timeout": bool(res.get("timeout")),
        "steps": res.get("steps"), "status": res.get("status"),
        "candidate_won": res.get("candidate_won"), "draw": bool(res.get("draw")),
        "decisions": res.get("decisions"), "attacks": res.get("attacks"),
        "passes": res.get("passes"),
    }


def _finalize(progress: dict) -> int:
    games = progress["games"]
    per_agent = {}
    for spec in REFERENCE_AGENTS:
        sid = spec.agent_id
        sp = games.get(f"{sid}::self::seat0", {})
        vb0 = games.get(f"{sid}::vs_baseline::seat0", {})
        vb1 = games.get(f"{sid}::vs_baseline::seat1", {})
        def ok(g):
            return bool(g) and g.get("completed") and not g.get("error") \
                and not g.get("timeout")
        self_ok = ok(sp)
        vs_ok = ok(vb0) and ok(vb1)
        per_agent[sid] = {
            "agent_id": sid, "label": spec.label,
            "deck_archetype": spec.deck_archetype, "optional": spec.optional,
            "self_play_ok": self_ok, "vs_baseline_ok": vs_ok,
            "runnable": self_ok and vs_ok,
            "self_play": sp, "vs_baseline_p0": vb0, "vs_baseline_p1": vb1,
        }
    runnable = [a for a in per_agent.values() if a["runnable"]]
    n_runnable = len(runnable)
    all_runnable = n_runnable == len(REFERENCE_AGENTS)

    out = {
        "pass": "40", "part": "G", "kind": "reference_agent_smoke",
        "local_only": True, "no_upload": True, "upload_performed": False,
        "pool_status": EXTERNAL_REFERENCE_STATUS,
        "note": ("feasibility smoke: win/loss is context only, NOT a strength claim "
                 "and NOT a Kaggle score"),
        "agents_total": len(REFERENCE_AGENTS), "agents_runnable": n_runnable,
        "all_runnable": all_runnable, "agents": list(per_agent.values()),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass40_reference_agent_smoke.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")

    def yn(v):
        return "yes" if v else "no"
    md = [
        "# Pass 40 — cg_typed reference-agent smoke matrix (Part G)", "",
        "> Each public reference agent run locally in cabt from its immutable Part F "
        f"tarball (`cg/` alongside `main.py`). Status `{EXTERNAL_REFERENCE_STATUS}`; "
        "win/loss shown is **feasibility context only, not a strength or Kaggle "
        "score**.", "",
        f"- agents runnable: **{n_runnable}/{len(REFERENCE_AGENTS)}**  ·  all "
        f"runnable: **{yn(all_runnable)}**", "",
        "| agent_id | archetype | self-play | vs-baseline P0 | vs-baseline P1 | "
        "runnable |", "|---|---|---|---|---|---|",
    ]
    for a in per_agent.values():
        def cell(g):
            if not g:
                return "—"
            if g.get("completed") and not g.get("error"):
                return f"DONE {g.get('steps')}st/{g.get('seconds')}s"
            if g.get("timeout"):
                return "TIMEOUT"
            return "ERROR"
        md.append(
            f"| `{a['agent_id']}` | {a['deck_archetype']} | "
            f"{cell(a['self_play'])} | {cell(a['vs_baseline_p0'])} | "
            f"{cell(a['vs_baseline_p1'])} | {yn(a['runnable'])} |")
    md.append("")
    (EXP / "pass40_reference_agent_smoke.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"ALL DONE: runnable={n_runnable}/{len(REFERENCE_AGENTS)} "
          f"all_runnable={all_runnable}")
    return 0 if all_runnable else 1


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    root_deck = load_deck(ROOT_DECK)
    progress = _load_progress()
    games = progress["games"]
    pending = [g for g in _game_list()
               if f"{g[0]}::{g[1]}::seat{g[2]}" not in games]
    if not pending:
        return _finalize(progress)

    start = time.time()
    ran = 0
    for agent_id, mode, seat in pending:
        if time.time() - start > INVOCATION_WALL_BUDGET and ran > 0:
            break
        key = f"{agent_id}::{mode}::seat{seat}"
        res = _run_game(agent_id, mode, seat, root_deck)
        games[key] = res
        PROGRESS.write_text(json.dumps(progress, indent=2, default=str),
                            encoding="utf-8")
        ran += 1
        flag = "OK" if (res["completed"] and not res["error"]) else "FAIL"
        print(f"[{flag}] {key}  {res['seconds']}s steps={res.get('steps')} "
              f"err={res.get('error')}")

    remaining = [g for g in _game_list()
                 if f"{g[0]}::{g[1]}::seat{g[2]}" not in games]
    if remaining:
        print(f"TICK DONE: ran {ran} this invocation, {len(remaining)} remaining "
              f"— re-invoke to continue")
        return 2
    return _finalize(progress)


if __name__ == "__main__":
    raise SystemExit(main())
