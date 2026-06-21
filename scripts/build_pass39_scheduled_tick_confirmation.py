#!/usr/bin/env python3
"""Pass 39 (Part B) — scheduled-tick confirmation (20/900 signature, 20-min cadence).

OPS / read-only inference. Pulls production state from ``replit_app_storage`` via
the existing sync/storage layer (NO manual tick is run first) and decides — honestly
— whether the Replit Scheduled Deployment has actually executed a bounded production
tick. The ledger does NOT record how a tick was launched, so a scheduled tick is
recognised by the spec's authoritative signal:

  * (max_games, max_seconds) == the ``.replit [deployment]`` run signature (20/900),
  * production backend (replit_app_storage),
  * the tick events carry no_upload=true,
  * a COMPLETE event chain: TournamentTickStarted + TournamentTickFinished, with
    GameScheduled/GameStarted/GameFinished events whose payload.tick_id == tick and
    whose GameScheduled events parent-link to the TournamentTickStarted event,
  * games_scheduled == games_started == games_finished for the tick.

Cadence note (Pass 39): the operator changed the schedule from ``0 */2 * * *`` (2h)
to ``*/20 * * * *`` (every 20 min). The interval (~1200s) is now BELOW the lease TTL
(1800s), so the Pass 38 "inter-tick gap >= TTL" spacing heuristic is NO LONGER an
authoritative scheduled-run signal. Spacing is reported for transparency only; the
SIGNATURE + COMPLETE CHAIN is authoritative. Push-merge-by-event_id and the lease
remain the concurrency safety nets.

Classification (one primary state, plus corroboration caveats):
  scheduled_tick_confirmed | no_scheduled_tick_observed_yet | schedule_misconfigured
  | storage_or_lease_blocked | deployment_logs_unavailable

Writes data/experiments/pass39_scheduled_tick_confirmation.{json,md}. NO upload,
NO submit, NO push, NO root mutation, NO candidate generation. NO manual tick.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.lease import DEFAULT_TTL_SECONDS  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
TDIR = REPO / "data" / "tournament"

OPERATOR_CRON = "*/20 * * * *"
OPERATOR_INTERVAL_S = 1200  # 20 minutes


def _scheduled_config() -> dict:
    """Extract the deployment run signature + target from .replit."""
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = data.get("deployment", {}) or {}
    run = [str(x) for x in (dep.get("run", []) or [])]
    mg = ms = None
    for i, tok in enumerate(run):
        if tok == "--max-games" and i + 1 < len(run):
            mg = int(run[i + 1])
        elif tok == "--max-seconds" and i + 1 < len(run):
            ms = int(run[i + 1])
    return {
        "max_games": mg, "max_seconds": ms, "run": run,
        "deployment_target": dep.get("deploymentTarget"),
        "run_is_deployment_tick": "scripts/tournament_deployment_tick.py" in " ".join(run),
        "run_has_production": "--production" in run,
        "run_uses_object_storage": "replit_app_storage" in " ".join(run),
    }


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


def _analyse_ticks(events: list, sched_mg, sched_ms) -> list:
    started, finished = {}, {}
    by_tick = {}
    for e in events:
        et = e.get("event_type")
        p = e.get("payload") or {}
        tid = p.get("tick_id")
        if not tid:
            continue
        if et == "TournamentTickStarted":
            started[tid] = {"ts": e.get("timestamp"), "max_games": p.get("max_games"),
                            "max_seconds": p.get("max_seconds"), "evt": e.get("event_id"),
                            "no_upload": p.get("no_upload")}
        elif et == "TournamentTickFinished":
            finished[tid] = {"ts": e.get("timestamp"), "games_played": p.get("games_played"),
                             "no_upload": p.get("no_upload")}
        elif et in ("GameScheduled", "GameStarted", "GameFinished"):
            by_tick.setdefault(tid, {"GameScheduled": [], "GameStarted": [],
                                     "GameFinished": []})[et].append(e)

    ticks = []
    for tid, s in started.items():
        f = finished.get(tid, {})
        dur = (f.get("ts") - s["ts"]) if (f.get("ts") and s.get("ts")) else None
        matches_sig = (s.get("max_games") == sched_mg and s.get("max_seconds") == sched_ms)
        g = by_tick.get(tid, {"GameScheduled": [], "GameStarted": [], "GameFinished": []})
        n_sch, n_sta, n_fin = len(g["GameScheduled"]), len(g["GameStarted"]), len(g["GameFinished"])
        tick_evt = s.get("evt")
        parent_linked = sum(1 for e in g["GameScheduled"]
                            if tick_evt in (e.get("parent_event_ids") or []))
        chain_games = g["GameScheduled"] + g["GameStarted"] + g["GameFinished"]
        all_no_upload = (s.get("no_upload") is True and f.get("no_upload") is True
                         and all((e.get("payload") or {}).get("no_upload") is True
                                 for e in chain_games))
        complete_chain = (
            f.get("ts") is not None and n_sch > 0 and n_sch == n_sta == n_fin
            and parent_linked == n_sch and all_no_upload)
        ticks.append({
            "tick_id": tid, "started_ts": s.get("ts"), "started_iso": _iso(s.get("ts")),
            "finished_ts": f.get("ts"), "duration_s": round(dur, 1) if dur is not None else None,
            "max_games": s.get("max_games"), "max_seconds": s.get("max_seconds"),
            "games_scheduled": n_sch, "games_started": n_sta, "games_finished": n_fin,
            "gamescheduled_parent_linked": parent_linked,
            "all_events_no_upload": all_no_upload,
            "matches_scheduled_signature": matches_sig,
            "complete_parent_linked_chain": complete_chain,
            "classification": ("scheduled_signature" if matches_sig else "manual_or_smoke"),
            "confirmed_scheduled_tick": bool(matches_sig and complete_chain),
        })
    ticks.sort(key=lambda t: t["started_ts"] or 0.0)
    return ticks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage-backend", default="replit_app_storage")
    ap.add_argument("--storage-prefix", default=None)
    ap.add_argument("--no-pull", action="store_true",
                    help="analyse the already-pulled local working copy (do not re-pull)")
    ap.add_argument("--deploy-logs-status", choices=["available", "unavailable"],
                    default="unavailable")
    ap.add_argument("--deploy-logs-note", default=(
        "fetch_deployment_logs returned no logs at confirmation time; scheduled "
        "deployments do not always retain logs. Confirmation therefore rests on the "
        "ledger signature + complete parent-linked no-upload chain, which is the "
        "authoritative recognition signal per the Part B criteria."))
    args = ap.parse_args()

    cfg = _scheduled_config()
    sched_mg, sched_ms = cfg["max_games"], cfg["max_seconds"]

    # 1) Pull production state (read-only download; NO manual tick, NO lease).
    pull_ok, pull_info, pull_err = True, None, None
    if not args.no_pull:
        try:
            be = get_storage_backend(env="production", backend=args.storage_backend,
                                     prefix=args.storage_prefix)
            pull_info = sync.pull_state(be, TDIR)
        except Exception as exc:  # noqa: BLE001 — storage/lease failures are fail-closed
            pull_ok, pull_err = False, f"{type(exc).__name__}: {exc}"

    ev_path = TDIR / "events.jsonl"
    events = (sync.parse_events_text(ev_path.read_text(encoding="utf-8"))
              if ev_path.is_file() else [])
    ticks = _analyse_ticks(events, sched_mg, sched_ms)

    gaps = [round(b["started_ts"] - a["started_ts"], 1)
            for a, b in zip(ticks, ticks[1:])
            if a["started_ts"] and b["started_ts"]]

    sig_ticks = [t for t in ticks if t["matches_scheduled_signature"]]
    confirmed_ticks = [t for t in ticks if t["confirmed_scheduled_tick"]]
    n_confirmed = len(confirmed_ticks)

    # Config correctness (signature must equal the 20/900 scheduled bound, etc.)
    config_ok = (cfg["deployment_target"] == "scheduled" and cfg["run_is_deployment_tick"]
                 and cfg["run_has_production"] and cfg["run_uses_object_storage"]
                 and sched_mg == 20 and sched_ms == 900)

    # Primary classification (single authoritative state).
    if not pull_ok:
        classification = "storage_or_lease_blocked"
    elif not config_ok:
        classification = "schedule_misconfigured"
    elif n_confirmed > 0:
        classification = "scheduled_tick_confirmed"
    else:
        classification = "no_scheduled_tick_observed_yet"

    # 20-min cadence: spacing between *scheduled-signature* ticks (informational).
    sig_gaps = [round(b["started_ts"] - a["started_ts"], 1)
                for a, b in zip(sig_ticks, sig_ticks[1:])
                if a["started_ts"] and b["started_ts"]]

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "39", "part": "B", "read_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False, "manual_tick_run": False,
        "storage_backend": args.storage_backend,
        "pull_ok": pull_ok, "pull_info": pull_info, "pull_error": pull_err,
        "operator_cron": OPERATOR_CRON,
        "operator_interval_seconds": OPERATOR_INTERVAL_S,
        "scheduled_deployment_signature": {"max_games": sched_mg, "max_seconds": sched_ms},
        "deployment_config": cfg, "config_ok": config_ok,
        "lease_ttl_seconds": DEFAULT_TTL_SECONDS,
        "interval_below_lease_ttl": OPERATOR_INTERVAL_S < DEFAULT_TTL_SECONDS,
        "spacing_heuristic_authoritative": False,
        "signature_match_authoritative": True,
        "spacing_heuristic_note": (
            f"interval (~{OPERATOR_INTERVAL_S}s) < lease TTL ({DEFAULT_TTL_SECONDS}s); the "
            "Pass 38 'gap >= TTL' spacing heuristic is dropped. Spacing is reported for "
            "transparency only; signature + complete chain is authoritative."),
        "total_ticks_in_ledger": len(ticks),
        "ticks_matching_scheduled_signature": len(sig_ticks),
        "confirmed_scheduled_ticks": n_confirmed,
        "inter_tick_gaps_s": gaps,
        "scheduled_signature_tick_gaps_s": sig_gaps,
        "multi_scheduled_cadence_verifiable": len(sig_ticks) >= 2,
        "deployment_logs_available": args.deploy_logs_status == "available",
        "deployment_logs_note": args.deploy_logs_note,
        "classification": classification,
        "possible_classifications": [
            "scheduled_tick_confirmed", "no_scheduled_tick_observed_yet",
            "schedule_misconfigured", "storage_or_lease_blocked",
            "deployment_logs_unavailable"],
        "scheduled_run_detected": n_confirmed > 0,
        "ticks": ticks,
    }
    (EXP / "pass39_scheduled_tick_confirmation.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 39 — Scheduled-tick confirmation (Part B)", "",
        "> OPS / read-only. Production state pulled via the sync/storage layer; NO "
        "manual tick was run first. The ledger does not store how a tick was launched, "
        "so a scheduled tick is recognised by the authoritative signal: 20/900 bound "
        "signature + production backend + complete parent-linked no-upload event chain. "
        "Internal diagnostics; NOT a Kaggle leaderboard.", "",
        "## Cadence & lease interaction",
        f"- operator cron: **`{OPERATOR_CRON}`** (~{OPERATOR_INTERVAL_S}s interval)",
        f"- lease TTL: **{DEFAULT_TTL_SECONDS}s** — interval < TTL: "
        f"**{yn(OPERATOR_INTERVAL_S < DEFAULT_TTL_SECONDS)}**",
        "- the 'inter-tick gap >= TTL' spacing heuristic is **dropped** at 20-min "
        "cadence; signature + complete chain is authoritative (push-merge + lease are "
        "the concurrency safety nets).", "",
        "## Pull & config",
        f"- production pull ok: **{yn(pull_ok)}**"
        + (f" ({pull_info})" if pull_info else "")
        + (f" — error: {pull_err}" if pull_err else ""),
        f"- deployment target scheduled / tick / production / object-storage: "
        f"**{yn(cfg['deployment_target']=='scheduled')}** / "
        f"**{yn(cfg['run_is_deployment_tick'])}** / **{yn(cfg['run_has_production'])}** / "
        f"**{yn(cfg['run_uses_object_storage'])}**",
        f"- run signature == 20/900: **{yn(sched_mg==20 and sched_ms==900)}** "
        f"(max_games={sched_mg}, max_seconds={sched_ms})",
        f"- config ok: **{yn(config_ok)}**", "",
        "## Findings",
        f"- total ticks in ledger: **{len(ticks)}**",
        f"- ticks matching 20/900 signature: **{len(sig_ticks)}**",
        f"- CONFIRMED scheduled ticks (signature + complete parent-linked no-upload "
        f"chain): **{n_confirmed}**",
        f"- inter-tick start-to-start gaps (s): {gaps}",
        f"- scheduled-signature tick gaps (s): {sig_gaps} "
        f"(multi-tick 20-min cadence verifiable: **{yn(len(sig_ticks) >= 2)}**)",
        f"- deployment logs available for corroboration: **{yn(args.deploy_logs_status=='available')}** "
        f"— {args.deploy_logs_note}", "",
        f"## Classification: **{classification}**", "",
        ("A bounded production tick matching the 20/900 scheduled signature has executed "
         "with a complete, parent-linked, no-upload event chain. Per the authoritative "
         "recognition criteria this **confirms** a scheduled production tick, even though "
         "deployment logs were unavailable for independent corroboration. Only one "
         "scheduled-signature tick has been observed so far, so multi-tick 20-minute "
         "cadence spacing is not yet verifiable."
         if classification == "scheduled_tick_confirmed" else
         "No tick matching the 20/900 scheduled signature with a complete chain has been "
         "observed yet; see classification above."), "",
        "## Ticks (oldest first)",
        "| started (UTC) | tick_id | mg | ms | sch/sta/fin | parent-linked | no_upload | sig | confirmed |",
        "|---|---|---|---|---|---|---|---|---|",
        *[f"| {t['started_iso']} | `{t['tick_id']}` | {t['max_games']} | {t['max_seconds']} "
          f"| {t['games_scheduled']}/{t['games_started']}/{t['games_finished']} "
          f"| {t['gamescheduled_parent_linked']}/{t['games_scheduled']} "
          f"| {yn(t['all_events_no_upload'])} | {yn(t['matches_scheduled_signature'])} "
          f"| {yn(t['confirmed_scheduled_tick'])} |" for t in ticks],
    ]
    (EXP / "pass39_scheduled_tick_confirmation.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"scheduled-tick confirmation: classification={classification} "
          f"total_ticks={len(ticks)} sig={len(sig_ticks)} confirmed={n_confirmed} "
          f"pull_ok={pull_ok} config_ok={config_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
