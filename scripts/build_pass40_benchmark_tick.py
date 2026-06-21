#!/usr/bin/env python3
"""Pass 40 (Part I) — controlled LOCAL benchmark tick (4-8 games).

Plays a small, bounded set of REAL local cabt games of OUR schedulable candidates vs
public reference agents, recording results on the SEPARATE benchmark ledger
(``PublicBenchmark*`` events). This is the live counterpart to the Part H structural
proof: it exercises the benchmark lane end-to-end without touching our pool, rankings,
queue, lifecycle, or mutation lineage.

Subject set (deterministic): the first 2 schedulable candidates (by id) vs the first 2
REQUIRED references (by id), both seats -> 8 games, capped at ``MAX_GAMES``.

The reference agent is always the subprocess 'candidate' (its dir holds the bundled
``cg/`` the child chdirs into); our candidate is the control with its deck forced. The
reference's ``candidate_won`` is therefore inverted to our perspective via
``benchmark.classify_result``.

RESUMABLE: every finished game is durable on the benchmark ledger and skipped on
re-run; each invocation stops after a wall budget so it fits one tool call. Re-invoke
until it prints ``ALL DONE``.

Benchmark-only / feasibility: win/loss counts are context, NOT a strength claim and
NOT a Kaggle score. NO upload / submit / promote / mutate; root main.py/deck.csv and
all candidate tarballs are read-only. Outputs:
  data/experiments/pass40_benchmark_tick.{json,md}
"""
from __future__ import annotations

import json
import sys
import tarfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"
EXTRACTED = REF / "tarballs" / "_extracted"
OUR_EXTRACTED = REPO / "data" / "tournament" / "benchmark" / "_our_extracted"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import artifacts, benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_cg_reference_game_subprocess.py")
GAME_TIMEOUT = 110            # parent SIGTERM->SIGKILL bound per game
INVOCATION_WALL_BUDGET = 85   # stop before the tool call would time out
N_SUBJECTS = 2                # our candidates under test
N_REFERENCES = 2              # references to benchmark against
MAX_GAMES = 8
SUBMISSIONS = REPO / "data" / "submissions"


def _ensure_ref_extracted(agent_id: str) -> Path:
    run = EXTRACTED / agent_id
    if not (run / "cg" / "libcg.so").is_file():
        run.mkdir(parents=True, exist_ok=True)
        with tarfile.open(REF / "tarballs" / f"{agent_id}.tar.gz") as t:
            artifacts.safe_extract_all(t, run)
    return run


def _ensure_our_extracted(cid: str, tarball_path: str) -> tuple[Path, list[int]]:
    dest = OUR_EXTRACTED / cid
    main = dest / "main.py"
    if not main.is_file():
        main = Path(artifacts.extract_agent_main(SUBMISSIONS / tarball_path, dest))
    deck = load_deck(dest / "deck.csv")
    return main, deck


def _select_worklist(pool: CandidatePool):
    subjects = sorted(c.candidate_id for c in pool.schedulable())[:N_SUBJECTS]
    opponents = [o for o in B.load_opponents(include_optional=False)][:N_REFERENCES]
    bench_events = B.benchmark_ledger().load()
    worklist = B.build_benchmark_worklist(subjects, opponents, bench_events,
                                          max_games=MAX_GAMES)
    return subjects, opponents, worklist


def _play(game: B.BenchmarkGame, pool: CandidatePool,
          opp_by_id: dict[str, B.BenchmarkOpponent]) -> dict:
    c = pool.by_id(game.our_candidate)
    our_main, our_deck = _ensure_our_extracted(c.candidate_id, c.tarball_path)
    ref_run = _ensure_ref_extracted(game.reference_id)
    ref_main = ref_run / "main.py"
    ref_deck = load_deck(ref_run / "deck.csv")
    candidate_seat = 1 - game.our_seat  # reference is the subprocess 'candidate'
    t0 = time.time()
    res = run_one_game_subprocess(
        control_main=our_main, control_deck=our_deck,
        cand_main=ref_main, cand_deck=ref_deck,
        candidate_seat=candidate_seat, timeout_seconds=GAME_TIMEOUT,
        child_script=CG_CHILD,
    )
    result = B.classify_result(res)
    return {
        "game_id": game.game_id, "our_candidate": game.our_candidate,
        "reference_id": game.reference_id, "our_seat": game.our_seat,
        "result": result, "seconds": round(time.time() - t0, 1),
        "completed": bool(res.get("completed")), "draw": bool(res.get("draw")),
        "timeout": bool(res.get("timeout")), "error": res.get("error"),
        "steps": res.get("steps"), "status": res.get("status"),
    }


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    pool = CandidatePool.load()
    subjects, opponents, worklist = _select_worklist(pool)
    opp_by_id = {o.agent_id: o for o in opponents}

    # Ensure the chosen references are registered in the benchmark lane.
    led = B.benchmark_ledger()
    B.register_opponents(opponents, led)

    finished = B.finished_benchmark_game_ids(led.load())
    todo = [g for g in worklist if g.game_id not in finished]

    tick_id = f"benchtick_{uuid.uuid4().hex[:8]}"
    played: list[dict] = []
    if todo:
        led.emit(EventType.PublicBenchmarkTickStarted, {
            "tick_id": tick_id, "planned_games": len(worklist),
            "remaining": len(todo), "subjects": subjects,
            "references": [o.agent_id for o in opponents],
        }, tags=["pass40", "benchmark"])

    deadline = time.time() + INVOCATION_WALL_BUDGET
    stop_reason = "all_planned_done"
    for g in todo:
        if time.time() >= deadline:
            stop_reason = "wall_budget"
            break
        sched = led.emit(EventType.PublicBenchmarkGameScheduled, {
            "game_id": g.game_id, "tick_id": tick_id,
            "our_candidate": g.our_candidate, "reference_id": g.reference_id,
            "our_seat": g.our_seat,
        }, tags=["pass40", "benchmark"])
        started = led.emit(EventType.PublicBenchmarkGameStarted, {
            "game_id": g.game_id, "tick_id": tick_id,
        }, parent_event_ids=[sched.event_id], tags=["pass40", "benchmark"])
        rec = _play(g, pool, opp_by_id)
        led.emit(EventType.PublicBenchmarkGameFinished, rec,
                 parent_event_ids=[started.event_id],
                 tags=["pass40", "benchmark", "external_reference"])
        played.append(rec)

    bench_events = led.load()
    remaining = [g for g in worklist
                 if g.game_id not in B.finished_benchmark_game_ids(bench_events)]
    if todo:
        led.emit(EventType.PublicBenchmarkTickFinished, {
            "tick_id": tick_id, "stop_reason": stop_reason,
            "games_played_this_invocation": len(played),
            "remaining": len(remaining),
        }, tags=["pass40", "benchmark"])

    proj = B.write_benchmark_projection(bench_events, opponents)
    led.emit(EventType.PublicBenchmarkProjectionUpdated, {
        "tick_id": tick_id, "totals": proj["totals"],
    }, tags=["pass40", "benchmark"])

    all_done = not remaining
    payload = {
        "schema": "pass40_benchmark_tick_v1", "pass": "40", "part": "I",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "tarball_mutation": False, "main_ledger_mutated": False,
        "caveat": B._BENCH_CAVEAT, "all_done": all_done,
        "planned_games": len(worklist), "remaining": len(remaining),
        "stop_reason": stop_reason, "subjects": subjects,
        "references": [o.agent_id for o in opponents],
        "played_this_invocation": played,
        "benchmark_results": proj,
        "benchmark_events_path": str(B.BENCHMARK_EVENTS_PATH),
    }
    (EXP / "pass40_benchmark_tick.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 40 (Part I) — Controlled Local Benchmark Tick", "",
        f"_{B._BENCH_CAVEAT}_", "",
        f"- generated: {payload['generated_at']}",
        f"- **all_done: {all_done}**  planned: {len(worklist)}  "
        f"remaining: {len(remaining)}  (stop: {stop_reason})",
        f"- subjects (our schedulable): {subjects}",
        f"- references: {[o.agent_id for o in opponents]}",
        f"- totals: {proj['totals']}", "",
        "## Our candidate vs each public reference", "",
        "| our_candidate | reference | games | our_W | ref_W | draw | invalid "
        "| our_decisive_wr |", "|---|---|---|---|---|---|---|---|",
    ]
    for p in proj["per_pair"]:
        wr = "—" if p["our_decisive_win_rate"] is None else f"{p['our_decisive_win_rate']:.3f}"
        lines.append(
            f"| {p['our_candidate']} | {p['reference_label']} | {p['games']} "
            f"| {p['our_wins']} | {p['reference_wins']} | {p['draws']} "
            f"| {p['invalid']} | {wr} |")
    (EXP / "pass40_benchmark_tick.md").write_text("\n".join(lines) + "\n",
                                                  encoding="utf-8")

    print(f"all_done={all_done} played_this_invocation={len(played)} "
          f"planned={len(worklist)} remaining={len(remaining)} stop={stop_reason}")
    for rec in played:
        print(f"  {rec['game_id']}: {rec['result']} ({rec['seconds']}s, "
              f"steps={rec['steps']}, err={rec['error']})")
    print(f"totals={proj['totals']}")
    print("ALL DONE" if all_done else "MORE TO DO — re-invoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
