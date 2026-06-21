#!/usr/bin/env python3
"""PASS 45 — Part B: scheduled daemon SOAK + tick-cadence audit (read-only).

Reads ONLY the production ledger (events.jsonl) and storage manifest — never the
~950 game sidecars — and characterises the live Scheduled Deployment daemon:

  * tick lifecycle: every TournamentTickStarted has a matching TournamentTickFinished
    (by run_id); no orphaned / crashed ticks;
  * tick cadence: spacing between consecutive ticks (min/median/mean/max), derived
    from TournamentTickStarted timestamps — NOT from lease-TTL spacing;
  * daemon liveness: wall-clock staleness since the last tick;
  * throughput: games scheduled / started / finished, games per tick;
  * runtime health: overall and recent hard-fail rate (invalid+timeout+error);
  * upload safety: every tick / game event carries no_upload truthy;
  * manifest/ledger lockstep: prod manifest event_count == ledger length;
  * forbidden-event scan (must be empty);
  * soak progress for the 3 Pass-42 probation targets since their registration.

Read-only. NO mutation / upload / promotion / tick execution. Output:
  data/experiments/pass45_scheduled_daemon_soak_audit.{json,md}
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]
NOMINAL_INTERVAL_S = 1200.0   # cron nominal ~20 min (informational only)
MAX_HARDFAIL_RATE = 0.05
RECENT_WINDOW = 100           # most-recent N games for the recent hard-fail rate


def _load_prod_events() -> tuple[list[dict], dict | None]:
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    if not backend.exists(sync.EVENTS_KEY):
        raise SystemExit("prod ledger not reachable")
    raw = sync.parse_events_text(backend.read_text(sync.EVENTS_KEY))
    manifest = None
    try:
        if backend.exists(sync.MANIFEST_KEY):
            manifest = json.loads(backend.read_text(sync.MANIFEST_KEY))
    except Exception:  # noqa: BLE001
        manifest = None
    return raw, manifest


def _et(e: dict) -> str:
    return e.get("event_type")


def _ts(e: dict) -> float:
    return float(e.get("timestamp") or 0.0)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    raw, manifest = _load_prod_events()
    now = time.time()

    starts = [e for e in raw if _et(e) == "TournamentTickStarted"]
    finishes = [e for e in raw if _et(e) == "TournamentTickFinished"]
    scheduled = [e for e in raw if _et(e) == "GameScheduled"]
    started = [e for e in raw if _et(e) == "GameStarted"]
    finished = [e for e in raw if _et(e) == "GameFinished"]

    start_runs = [(_p(e).get("run_id") or _p(e).get("tick_id")) for e in starts]
    fin_runs = {(_p(e).get("run_id") or _p(e).get("tick_id")) for e in finishes}
    orphaned = sorted(r for r in start_runs if r and r not in fin_runs)
    ticks_started_eq_finished = (len(starts) == len(finishes)
                                 and not orphaned)

    # --- cadence from TickStarted timestamps ---------------------------------
    stimes = sorted(_ts(e) for e in starts if _ts(e) > 0)
    deltas = [b - a for a, b in zip(stimes, stimes[1:]) if b > a]
    cadence = {
        "n_ticks": len(starts),
        "first_tick_ts": stimes[0] if stimes else None,
        "last_tick_ts": stimes[-1] if stimes else None,
        "min_gap_s": round(min(deltas), 1) if deltas else None,
        "median_gap_s": round(statistics.median(deltas), 1) if deltas else None,
        "mean_gap_s": round(statistics.fmean(deltas), 1) if deltas else None,
        "max_gap_s": round(max(deltas), 1) if deltas else None,
        "nominal_interval_s": NOMINAL_INTERVAL_S,
    }
    staleness_s = round(now - stimes[-1], 1) if stimes else None
    # liveness: last tick within ~3x nominal interval (tolerant; audit can run
    # at any point in the cron cycle). Informational, not a hard gate.
    daemon_recent = bool(staleness_s is not None
                         and staleness_s <= 3 * NOMINAL_INTERVAL_S)
    # cadence regular: median gap within a tolerant band around nominal.
    med = cadence["median_gap_s"]
    cadence_regular = bool(med is not None
                           and 0.4 * NOMINAL_INTERVAL_S <= med <= 2.5
                           * NOMINAL_INTERVAL_S)

    # --- throughput & runtime health -----------------------------------------
    n_games = len(finished)
    outcomes = {"win": 0, "loss": 0, "draw": 0, "invalid_or_error": 0}
    timeouts = errors = 0
    no_upload_violations = 0
    for e in finished:
        p = _p(e)
        r = p.get("result")
        if r in ("win", "loss", "draw"):
            outcomes[r] += 1
        else:
            outcomes["invalid_or_error"] += 1
            if p.get("timeout"):
                timeouts += 1
            elif r == "error" or p.get("error"):
                errors += 1
        if p.get("no_upload") is not True:
            no_upload_violations += 1
    hardfail = outcomes["invalid_or_error"]
    hardfail_rate = round(hardfail / n_games, 4) if n_games else 0.0
    recent = finished[-RECENT_WINDOW:]
    recent_hf = sum(1 for e in recent
                    if _p(e).get("result") not in ("win", "loss", "draw"))
    recent_hf_rate = round(recent_hf / len(recent), 4) if recent else 0.0

    # tick-event no_upload (TickStarted/Finished payloads)
    for e in starts + finishes:
        if _p(e).get("no_upload") is not True:
            no_upload_violations += 1

    games_per_tick = [int(_p(e).get("games_played") or 0) for e in finishes]
    gpt_summary = {
        "min": min(games_per_tick) if games_per_tick else None,
        "median": (round(statistics.median(games_per_tick), 1)
                   if games_per_tick else None),
        "max": max(games_per_tick) if games_per_tick else None,
        "total_from_ticks": sum(games_per_tick),
    }

    # --- forbidden-event scan -------------------------------------------------
    forbidden_present = sorted({_et(e) for e in raw if _et(e) in FORBIDDEN})

    # --- manifest / ledger lockstep ------------------------------------------
    ledger_count = len(raw)
    manifest_count = (manifest or {}).get("event_count")
    manifest_matches = (manifest_count == ledger_count) if manifest else None

    # --- soak progress per probation target (since registration) -------------
    reg_ts = {}
    for e in raw:
        if _et(e) == "TournamentParticipantRegistered":
            cid = _p(e).get("candidate_id")
            if cid in TARGETS and cid not in reg_ts:
                reg_ts[cid] = _ts(e)
    per_target = {}
    for cid in TARGETS:
        invo = [e for e in finished
                if _p(e).get("candidate_a") == cid or _p(e).get("candidate_b") == cid]
        w = sum(1 for e in invo if _outcome_for(e, cid) == "win")
        ll = sum(1 for e in invo if _outcome_for(e, cid) == "loss")
        d = sum(1 for e in invo if _outcome_for(e, cid) == "draw")
        inv = sum(1 for e in invo
                  if _p(e).get("result") not in ("win", "loss", "draw"))
        rt = reg_ts.get(cid)
        since_reg = sum(1 for e in invo if rt is not None and _ts(e) >= rt)
        per_target[cid] = {
            "registered": rt is not None,
            "registration_ts": rt,
            "total_games": len(invo),
            "games_since_registration": since_reg,
            "wins": w, "losses": ll, "draws": d, "invalid_or_error": inv,
            "accruing_evidence": len(invo) > 0,
        }
    any_accruing = any(t["accruing_evidence"] for t in per_target.values())
    all_accruing = all(t["accruing_evidence"] for t in per_target.values())

    checks = {
        "ticks_started_equal_finished": ticks_started_eq_finished,
        "no_orphaned_ticks": not orphaned,
        "overall_hardfail_rate_within_budget": hardfail_rate <= MAX_HARDFAIL_RATE,
        "recent_hardfail_rate_within_budget": recent_hf_rate <= MAX_HARDFAIL_RATE,
        "all_events_no_upload": no_upload_violations == 0,
        "no_forbidden_events": not forbidden_present,
        "manifest_event_count_matches_ledger": bool(manifest_matches),
        "targets_accruing_evidence": any_accruing,
    }
    soak_healthy = all(checks.values())

    out = {
        "pass": "pass45_partB_scheduled_daemon_soak_audit",
        "read_only": True, "production_mutated": False, "tick_executed": False,
        "ledger_event_count": ledger_count,
        "engine_initialized":
            sum(1 for e in raw if _et(e) == "TournamentEngineInitialized"),
        "tick_lifecycle": {
            "ticks_started": len(starts),
            "ticks_finished": len(finishes),
            "orphaned_run_ids": orphaned,
            "all_finished": ticks_started_eq_finished,
        },
        "cadence": cadence,
        "staleness_s": staleness_s,
        "daemon_recent": daemon_recent,
        "cadence_regular": cadence_regular,
        "throughput": {
            "games_scheduled": len(scheduled),
            "games_started": len(started),
            "games_finished": n_games,
            "outcomes": outcomes,
            "timeouts": timeouts, "errors": errors,
            "games_per_tick": gpt_summary,
        },
        "runtime_health": {
            "hardfail": hardfail, "hardfail_rate": hardfail_rate,
            "recent_window": len(recent),
            "recent_hardfail": recent_hf, "recent_hardfail_rate": recent_hf_rate,
            "no_upload_violations": no_upload_violations,
            "max_hardfail_rate_budget": MAX_HARDFAIL_RATE,
        },
        "manifest": {"event_count": manifest_count,
                     "matches_ledger": manifest_matches,
                     "manifest_present": manifest is not None},
        "forbidden_events_present": forbidden_present,
        "probation_targets": per_target,
        "targets_any_accruing": any_accruing,
        "targets_all_accruing": all_accruing,
        "checks": checks,
        "soak_healthy": soak_healthy,
    }
    (EXP / "pass45_scheduled_daemon_soak_audit.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b else "no"

    def hhmm(s):
        return "n/a" if s is None else f"{s/60:.1f} min"

    md = [
        "# PASS 45 — Part B: scheduled daemon SOAK + tick-cadence audit", "",
        "> Read-only audit of the live Scheduled Deployment daemon from the production "
        "ledger only (no sidecar pulls, no tick execution, no mutation). Internal "
        "self-play diagnostics; NOT a Kaggle leaderboard.", "",
        f"- **soak healthy: {yn(soak_healthy)}**  · prod ledger events: "
        f"**{ledger_count}**",
        f"- ticks: **{len(starts)}** started / **{len(finishes)}** finished "
        f"(orphaned: `{orphaned or 'none'}`)",
        f"- cadence: median **{hhmm(cadence['median_gap_s'])}** "
        f"(min {hhmm(cadence['min_gap_s'])} / max {hhmm(cadence['max_gap_s'])}; "
        f"nominal {hhmm(NOMINAL_INTERVAL_S)})",
        f"- last tick staleness: **{hhmm(staleness_s)}**  · daemon recent: "
        f"**{yn(daemon_recent)}**  · cadence regular: **{yn(cadence_regular)}**",
        f"- games finished: **{n_games}**  · outcomes: `{json.dumps(outcomes)}`",
        f"- hard-fail rate: **{hardfail_rate}** (recent {recent_hf_rate}; budget "
        f"{MAX_HARDFAIL_RATE})",
        f"- manifest event_count == ledger: **{yn(manifest_matches)}** "
        f"({manifest_count} vs {ledger_count})",
        "", "## Checks", "", "| check | pass |", "|---|---|",
    ]
    for k, v in checks.items():
        md.append(f"| {k} | {yn(v)} |")
    md += ["", "## Probation soak progress (per target)", "",
           "| candidate | registered | total games | since reg | W | L | D | "
           "invalid | accruing |", "|---|---|---|---|---|---|---|---|---|"]
    for cid, t in per_target.items():
        md.append(
            f"| `{cid}` | {yn(t['registered'])} | {t['total_games']} | "
            f"{t['games_since_registration']} | {t['wins']} | {t['losses']} | "
            f"{t['draws']} | {t['invalid_or_error']} | {yn(t['accruing_evidence'])} |")
    md += ["", "> Cadence is derived from TournamentTickStarted timestamps, not "
           "lease-TTL spacing. Liveness/cadence-regularity are tolerant, "
           "informational signals (the audit can run at any point in the cron "
           "cycle); the hard soak gates are tick-lifecycle integrity, hard-fail "
           "budget, upload safety, forbidden-event absence, and manifest/ledger "
           "lockstep."]
    (EXP / "pass45_scheduled_daemon_soak_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass45 partB: soak_healthy={soak_healthy} ticks={len(starts)}/"
          f"{len(finishes)} games={n_games} hardfail_rate={hardfail_rate} "
          f"staleness_min={None if staleness_s is None else round(staleness_s/60,1)} "
          f"manifest_match={manifest_matches} targets_accruing={any_accruing}")
    return 0 if soak_healthy else 1


def _p(e: dict) -> dict:
    return e.get("payload") or {}


def _outcome_for(e: dict, cid: str) -> str | None:
    """Outcome from cid's perspective (payload 'result' is candidate_a's)."""
    p = _p(e)
    r = p.get("result")
    if r not in ("win", "loss", "draw"):
        return None
    if r == "draw":
        return "draw"
    if p.get("candidate_a") == cid:
        return r
    return "loss" if r == "win" else "win"


if __name__ == "__main__":
    raise SystemExit(main())
