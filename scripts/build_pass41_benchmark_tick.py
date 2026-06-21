#!/usr/bin/env python3
"""Pass 41 (Part B) — larger calibrated public-reference benchmark batch (resumable).

Generalises the Pass 40 controlled benchmark tick to the FULL calibration grid:

    all schedulable internal candidates  x  all 5 public reference agents
    (load_opponents(include_optional=True))  x  both seats  x  >= 2 games

= up to ``TARGET_TOTAL`` (= n_subjects * n_refs * 2 seats * 2 games) directed
games, scheduled least-played-first and seat-balanced by
``benchmark.build_benchmark_worklist``. The worklist is self-sizing: it only
schedules the games still MISSING from the (cumulative) benchmark ledger, so
Pass-40 games already played are reused, not repeated.

The reference agent is always the subprocess 'candidate' (its dir holds the
bundled ``cg/`` the child chdirs into); our candidate is the control with its deck
forced, and ``benchmark.classify_result`` inverts the reference outcome to our
perspective.

RESUMABLE & bounded: every finished game is durable on the SEPARATE benchmark
ledger (skipped on re-run) and mirrored to a per-game JSONL sidecar; each
invocation stops after a wall budget (and never STARTS a game that could exceed
the per-call deadline), so it fits one tool call. Re-invoke until ``ALL DONE``.

Benchmark-only / feasibility: win/loss counts are context, NOT a strength claim
and NOT a Kaggle score. NO upload / submit / promote / mutate; root
main.py/deck.csv and all candidate/reference tarballs are read-only. Outputs:
  data/experiments/pass41_public_benchmark_calibration.{json,md}
  data/experiments/pass41_public_benchmark_games.jsonl   (per-game sidecar)
  data/tournament/benchmark/projections/pass41_public_benchmark_matrix.{json,md,csv}
"""
from __future__ import annotations

import json
import math
import sys
import tarfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"
EXTRACTED = REF / "tarballs" / "_extracted"
OUR_EXTRACTED = REPO / "data" / "tournament" / "benchmark" / "_our_extracted"
BENCH_PROJ = REPO / "data" / "tournament" / "benchmark" / "projections"
GAMES_JSONL = EXP / "pass41_public_benchmark_games.jsonl"

from ptcg_activegraph.decks.deck_io import load_deck  # noqa: E402
from ptcg_activegraph.experiments.runner import run_one_game_subprocess  # noqa: E402
from ptcg_activegraph.graph.events import EventType  # noqa: E402
from ptcg_activegraph.tournament import artifacts, benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

CG_CHILD = str(REPO / "src/ptcg_activegraph/experiments/_cg_reference_game_subprocess.py")
GAME_TIMEOUT = 30             # parent SIGTERM->SIGKILL bound per game (~2x observed max)
WORKERS = 3                   # parallel games per wave (4 vCPU; ledger writes stay serial)
TOOL_LIMIT = 118              # hard wall: the bash tool kills us at ~120s
TAIL_RESERVE = 8              # reserve for end-of-run projection + file writes (~instant)
STARTUP_RESERVE = 20          # interpreter start + heavy imports happen BEFORE proc_start
KILL_GRACE_BUF = 12           # SIGTERM(5s)+SIGKILL(5s) grace on a hung child + overhead
WORST_GAME = GAME_TIMEOUT + KILL_GRACE_BUF  # true worst-case wall for one game (~42s)
SUBMISSIONS = REPO / "data" / "submissions"
GAMES_PER_PAIR_SEAT = 2       # target >= 2 games per (pair, seat)


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


def _in_universe_finished(events, subjects: set[str], opp_ids: set[str]) -> int:
    n = 0
    for e in events:
        if e.event_type != EventType.PublicBenchmarkGameFinished.value:
            continue
        if (e.payload.get("our_candidate") in subjects
                and e.payload.get("reference_id") in opp_ids):
            n += 1
    return n


def _play(game: B.BenchmarkGame, pool: CandidatePool) -> dict:
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


def _append_sidecar(rec: dict, seen: set[str]) -> None:
    if rec["game_id"] in seen:
        return
    GAMES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(GAMES_JSONL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    seen.add(rec["game_id"])


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _write_matrix(events, subjects: list[str], opponents) -> dict:
    BENCH_PROJ.mkdir(parents=True, exist_ok=True)
    opp_ids = [o.agent_id for o in opponents]
    labels = {o.agent_id: o.label for o in opponents}
    cells: dict[str, dict[str, dict]] = {
        s: {r: {"games": 0, "our_win": 0, "reference_win": 0, "draw": 0,
                "invalid": 0} for r in opp_ids} for s in subjects}
    for e in events:
        if e.event_type != EventType.PublicBenchmarkGameFinished.value:
            continue
        s = e.payload.get("our_candidate")
        r = e.payload.get("reference_id")
        res = e.payload.get("result")
        if s in cells and r in cells.get(s, {}) and res in (
                "our_win", "reference_win", "draw", "invalid"):
            cells[s][r]["games"] += 1
            cells[s][r][res] += 1
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {"schema": "pass41_public_benchmark_matrix_v1", "generated_at": now,
               "no_upload": True, "caveat": B._BENCH_CAVEAT,
               "subjects": subjects, "references": opp_ids,
               "reference_labels": labels, "cells": cells}
    (BENCH_PROJ / "pass41_public_benchmark_matrix.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    short = {r: labels.get(r, r).replace("public_reference_", "") for r in opp_ids}
    header = "| our_candidate | " + " | ".join(short[r] for r in opp_ids) + " |"
    sep = "|---" * (len(opp_ids) + 1) + "|"
    md = ["# Pass 41 — Public-Reference Benchmark Matrix (benchmark-only)", "",
          f"_{B._BENCH_CAVEAT}_", "", f"- generated: {now}",
          "- cell format: our_W-ref_W-draw (inv) over both seats", "",
          header, sep]
    csv = ["our_candidate," + ",".join(short[r] for r in opp_ids)]
    for s in subjects:
        row_md, row_csv = [], []
        for r in opp_ids:
            c = cells[s][r]
            row_md.append(f"{c['our_win']}-{c['reference_win']}-{c['draw']} "
                          f"({c['invalid']})")
            row_csv.append(f"{c['our_win']}-{c['reference_win']}-{c['draw']}-{c['invalid']}")
        md.append(f"| {s} | " + " | ".join(row_md) + " |")
        csv.append(f"{s}," + ",".join(row_csv))
    (BENCH_PROJ / "pass41_public_benchmark_matrix.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    (BENCH_PROJ / "pass41_public_benchmark_matrix.csv").write_text(
        "\n".join(csv) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    proc_start = time.time()  # budget anchor: covers setup + pre-extraction + games
    EXP.mkdir(parents=True, exist_ok=True)
    pool = CandidatePool.load()
    subjects = sorted(c.candidate_id for c in pool.schedulable())
    opponents = B.load_opponents(include_optional=True)
    opp_ids = {o.agent_id for o in opponents}

    led = B.benchmark_ledger()
    B.register_opponents(opponents, led)
    bench_events = led.load()

    target_total = len(subjects) * len(opponents) * 2 * GAMES_PER_PAIR_SEAT
    existing = _in_universe_finished(bench_events, set(subjects), opp_ids)
    max_games = max(0, target_total - existing)
    worklist = B.build_benchmark_worklist(subjects, opponents, bench_events,
                                          max_games=max_games)
    finished = B.finished_benchmark_game_ids(bench_events)
    todo = [g for g in worklist if g.game_id not in finished]

    seen_sidecar: set[str] = set()
    if GAMES_JSONL.is_file():
        for line in GAMES_JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    seen_sidecar.add(json.loads(line)["game_id"])
                except Exception:  # noqa: BLE001
                    pass

    # Pre-extract every subject + reference ONCE (serial) so the parallel waves
    # below only ever READ from the extracted dirs (no extraction race).
    if todo:
        for cid in {g.our_candidate for g in todo}:
            _ensure_our_extracted(cid, pool.by_id(cid).tarball_path)
        for rid in {g.reference_id for g in todo}:
            _ensure_ref_extracted(rid)

    tick_id = f"p41bench_{uuid.uuid4().hex[:8]}"
    played: list[dict] = []
    if todo:
        led.emit(EventType.PublicBenchmarkTickStarted, {
            "tick_id": tick_id, "pass": "41", "planned_games": len(worklist),
            "remaining": len(todo), "target_total": target_total,
            "subjects": subjects, "references": sorted(opp_ids),
            "workers": WORKERS,
        }, tags=["pass41", "benchmark"])

    start = proc_start  # report elapsed over the WHOLE invocation (setup included)
    # Stop starting waves early enough that even a worst-case hung game in the
    # final wave (timeout + SIGTERM/SIGKILL grace) plus the tail projection writes
    # all finish before the bash tool's ~120s kill.
    deadline = proc_start + (TOOL_LIMIT - TAIL_RESERVE - STARTUP_RESERVE)
    stop_reason = "all_planned_done"
    # Run games in small parallel WAVES. Each game is a fully isolated subprocess
    # (own tempdir; the child only reads the reference dir), so parallelism only
    # overlaps wall time — it never shares game state or changes outcomes. ALL
    # ledger writes happen here on the main thread, serialized.
    with ThreadPoolExecutor(max_workers=WORKERS) as poolex:
        idx = 0
        while idx < len(todo):
            if time.time() + WORST_GAME > deadline:
                stop_reason = "wall_budget"
                break
            wave = todo[idx:idx + WORKERS]
            idx += len(wave)
            futures = {}
            for g in wave:
                sched = led.emit(EventType.PublicBenchmarkGameScheduled, {
                    "game_id": g.game_id, "tick_id": tick_id, "pass": "41",
                    "our_candidate": g.our_candidate, "reference_id": g.reference_id,
                    "our_seat": g.our_seat,
                }, tags=["pass41", "benchmark"])
                started = led.emit(EventType.PublicBenchmarkGameStarted, {
                    "game_id": g.game_id, "tick_id": tick_id,
                }, parent_event_ids=[sched.event_id], tags=["pass41", "benchmark"])
                futures[poolex.submit(_play, g, pool)] = started.event_id
            for fut in as_completed(futures):
                started_id = futures[fut]
                rec = fut.result()
                led.emit(EventType.PublicBenchmarkGameFinished, rec,
                         parent_event_ids=[started_id],
                         tags=["pass41", "benchmark", "external_reference"])
                _append_sidecar(rec, seen_sidecar)
                played.append(rec)

    bench_events = led.load()
    finished2 = B.finished_benchmark_game_ids(bench_events)
    remaining = [g for g in worklist if g.game_id not in finished2]
    if todo:
        led.emit(EventType.PublicBenchmarkTickFinished, {
            "tick_id": tick_id, "stop_reason": stop_reason,
            "games_played_this_invocation": len(played),
            "remaining": len(remaining),
        }, tags=["pass41", "benchmark"])

    # Refresh both the generic projection and the Pass-41 matrix.
    proj = B.write_benchmark_projection(bench_events, opponents)
    matrix = _write_matrix(bench_events, subjects, opponents)
    led.emit(EventType.PublicBenchmarkProjectionUpdated, {
        "tick_id": tick_id, "pass": "41", "totals": proj["totals"],
    }, tags=["pass41", "benchmark"])

    # Per-subject calibration summary (decisive WR + Wilson CI), cumulative.
    per_subj = []
    for row in proj["per_our"]:
        dec = row["our_wins"] + row["reference_wins"]
        ci = _wilson(row["our_wins"], dec) if dec else None
        per_subj.append({**row, "decisive_games": dec, "our_decisive_ci95": ci})

    all_done = not remaining
    payload = {
        "schema": "pass41_public_benchmark_calibration_v1", "pass": "41",
        "part": "B", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "no_upload": True, "upload_performed": False, "auto_submit": False,
        "github_push": False, "candidate_generation": False,
        "tarball_mutation": False, "main_ledger_mutated": False,
        "caveat": B._BENCH_CAVEAT, "all_done": all_done,
        "target_total": target_total, "existing_at_start": existing,
        "planned_this_grid": len(worklist), "remaining": len(remaining),
        "stop_reason": stop_reason, "elapsed_s": round(time.time() - start, 1),
        "subjects": subjects, "references": sorted(opp_ids),
        "played_this_invocation": played,
        "totals": proj["totals"], "per_subject": per_subj,
        "matrix_path": "data/tournament/benchmark/projections/pass41_public_benchmark_matrix.json",
        "games_jsonl": str(GAMES_JSONL.relative_to(REPO)),
        "benchmark_events_path": str(B.BENCHMARK_EVENTS_PATH.relative_to(REPO)),
    }
    (EXP / "pass41_public_benchmark_calibration.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Pass 41 (Part B) — Calibrated Public-Reference Benchmark", "",
        f"_{B._BENCH_CAVEAT}_", "",
        f"- generated: {payload['generated_at']}",
        f"- **all_done: {all_done}**  target_total: {target_total}  "
        f"remaining: {len(remaining)}  (stop: {stop_reason})",
        f"- existing games at start: {existing}  played this invocation: {len(played)}",
        f"- totals: {proj['totals']}", "",
        "## Per-subject vs all public references (cumulative)", "",
        "| our_candidate | games | our_W | ref_W | draw | invalid | dec_WR | "
        "dec_CI95 |", "|---|---|---|---|---|---|---|---|",
    ]
    for p in per_subj:
        wr = "—" if p["our_decisive_win_rate"] is None else f"{p['our_decisive_win_rate']:.3f}"
        ci = "—" if not p["our_decisive_ci95"] else f"[{p['our_decisive_ci95'][0]:.2f},{p['our_decisive_ci95'][1]:.2f}]"
        lines.append(
            f"| {p['our_candidate']} | {p['games']} | {p['our_wins']} | "
            f"{p['reference_wins']} | {p['draws']} | {p['invalid']} | {wr} | {ci} |")
    (EXP / "pass41_public_benchmark_calibration.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    print(f"all_done={all_done} played={len(played)} target={target_total} "
          f"existing_at_start={existing} remaining={len(remaining)} "
          f"stop={stop_reason} elapsed={payload['elapsed_s']}s")
    for rec in played:
        print(f"  {rec['game_id']}: {rec['result']} ({rec['seconds']}s, "
              f"steps={rec['steps']}, err={rec['error']})")
    print(f"totals={proj['totals']}")
    print("ALL DONE" if all_done else "MORE TO DO — re-invoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
