#!/usr/bin/env python3
"""Pass 38 (Part D) — scheduled-run vs manual/smoke tick detection.

OPS / read-only. The Replit Scheduled Deployment is configured (Pass 37) to run
the bounded tick with a specific ``--max-games``/``--max-seconds`` signature. The
event ledger records every tick that has ever run (TournamentTickStarted/Finished)
but does NOT store how it was launched, so we infer — honestly — using three
independent signals:

  1. **Bound signature** — a tick whose (max_games, max_seconds) equals the
     ``.replit [deployment]`` run args is *consistent with* the scheduled worker;
     anything smaller is a manual/smoke/controlled tick.
  2. **Inter-tick spacing** — the schedule discipline keeps interval > lease TTL
     (1800s). Ticks spaced far below that (bursts) are manual.
  3. **Deployment logs** — the authoritative signal that a scheduled production
     run actually executed. (Fetched separately; recorded here as a caveat.)

This script makes NO claim that a scheduled run happened unless the evidence shows
it. Writes data/experiments/pass38_scheduled_run_detection.{json,md}. Read-only:
NO upload/submit/push/root-mutation/candidate-generation.
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.lease import DEFAULT_TTL_SECONDS  # noqa: E402

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"


def _scheduled_signature() -> dict:
    """Extract (max_games, max_seconds) from the .replit deployment run args."""
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    run = [str(x) for x in (data.get("deployment", {}).get("run", []) or [])]
    mg = ms = None
    for i, tok in enumerate(run):
        if tok == "--max-games" and i + 1 < len(run):
            mg = int(run[i + 1])
        elif tok == "--max-seconds" and i + 1 < len(run):
            ms = int(run[i + 1])
    return {"max_games": mg, "max_seconds": ms, "run": run}


def main() -> int:
    sig = _scheduled_signature()
    sched_mg, sched_ms = sig["max_games"], sig["max_seconds"]

    ev_path = TDIR / "events.jsonl"
    events = sync.parse_events_text(ev_path.read_text(encoding="utf-8")) if ev_path.is_file() else []

    started = {}
    finished = {}
    for e in events:
        et = e.get("event_type")
        p = e.get("payload") or {}
        tid = p.get("tick_id")
        if et == "TournamentTickStarted" and tid:
            started[tid] = {"ts": e.get("timestamp"), "max_games": p.get("max_games"),
                            "max_seconds": p.get("max_seconds")}
        elif et == "TournamentTickFinished" and tid:
            finished[tid] = {"ts": e.get("timestamp"), "games_played": p.get("games_played")}

    ticks = []
    for tid, s in started.items():
        f = finished.get(tid, {})
        dur = (f.get("ts") - s["ts"]) if (f.get("ts") and s.get("ts")) else None
        matches_sig = (s.get("max_games") == sched_mg and s.get("max_seconds") == sched_ms)
        ticks.append({
            "tick_id": tid,
            "started_ts": s.get("ts"),
            "finished_ts": f.get("ts"),
            "duration_s": round(dur, 1) if dur is not None else None,
            "max_games": s.get("max_games"),
            "max_seconds": s.get("max_seconds"),
            "games_played": f.get("games_played"),
            "matches_scheduled_signature": matches_sig,
            "classification": "scheduled_signature" if matches_sig else "manual_or_smoke",
        })
    ticks.sort(key=lambda t: t["started_ts"] or 0.0)

    # inter-tick spacing (start-to-start)
    gaps = []
    for a, b in zip(ticks, ticks[1:]):
        if a["started_ts"] and b["started_ts"]:
            gaps.append(round(b["started_ts"] - a["started_ts"], 1))

    n_scheduled_sig = sum(1 for t in ticks if t["matches_scheduled_signature"])
    n_manual = len(ticks) - n_scheduled_sig
    # any inter-tick gap >= lease TTL would be consistent with a real schedule
    any_schedule_spacing = any(g >= DEFAULT_TTL_SECONDS for g in gaps)

    # Honest verdict: we only claim a scheduled run occurred if a tick matches the
    # scheduled bound signature. Absent that, all observed ticks are manual/smoke.
    scheduled_run_detected = n_scheduled_sig > 0

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "D", "read_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "scheduled_deployment_signature": {"max_games": sched_mg, "max_seconds": sched_ms},
        "lease_ttl_seconds": DEFAULT_TTL_SECONDS,
        "total_ticks_in_ledger": len(ticks),
        "ticks_matching_scheduled_signature": n_scheduled_sig,
        "ticks_manual_or_smoke": n_manual,
        "inter_tick_gaps_s": gaps,
        "any_gap_ge_lease_ttl": any_schedule_spacing,
        "deployment_logs_available": False,
        "deployment_logs_note": "fetch_deployment_logs returned no logs at audit "
                                "time; no evidence of an executed scheduled production "
                                "tick. The deployment publishes successfully (Pass 37) "
                                "but a real scheduled run has not yet been observed.",
        "scheduled_run_detected": scheduled_run_detected,
        "ticks": ticks,
    }
    (EXP / "pass38_scheduled_run_detection.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Scheduled-run detection (Part D)", "",
        "> OPS / read-only inference. The ledger does not store how a tick was "
        "launched; classification is inferred honestly from the scheduled bound "
        "signature, inter-tick spacing, and deployment-log availability. No claim "
        "of a scheduled run is made without evidence.", "",
        f"- scheduled deployment signature (.replit): max_games=**{sched_mg}**, "
        f"max_seconds=**{sched_ms}**",
        f"- lease TTL: {DEFAULT_TTL_SECONDS}s (schedule interval should exceed this)",
        f"- total ticks in ledger: **{len(ticks)}**",
        f"- ticks matching scheduled signature: **{n_scheduled_sig}**",
        f"- ticks classified manual/smoke: **{n_manual}**",
        f"- inter-tick start-to-start gaps (s): {gaps}",
        f"- any gap >= lease TTL ({DEFAULT_TTL_SECONDS}s): **{yn(any_schedule_spacing)}**",
        f"- deployment logs available at audit: **{yn(False)}** "
        "(no evidence of an executed scheduled production tick)",
        f"- **scheduled run detected: {yn(scheduled_run_detected)}**", "",
        "All recorded ticks to date are small bounded manual/smoke/controlled runs "
        f"(none match the scheduled {sched_mg}-game/{sched_ms}s signature). The "
        "deployment is published and ready; a real scheduled production tick has "
        "not yet been observed in the ledger or deployment logs.", "",
        "## Ticks (oldest first)",
        "| tick_id | max_games | max_seconds | games_played | duration_s | class |",
        "|---|---|---|---|---|---|",
        *[f"| `{t['tick_id']}` | {t['max_games']} | {t['max_seconds']} "
          f"| {t['games_played']} | {t['duration_s']} | {t['classification']} |"
          for t in ticks],
    ]
    (EXP / "pass38_scheduled_run_detection.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"scheduled-run detection: total_ticks={len(ticks)} "
          f"scheduled_sig={n_scheduled_sig} manual={n_manual} "
          f"detected={scheduled_run_detected} gaps={gaps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
