#!/usr/bin/env python3
"""PASS 46 — core tournament SOAK snapshot (root/deploy safety + daemon soak).

Read-only. Re-asserts root/deployment immutability (fresh filecmp + .replit deploy
config check) and re-runs a fast PRODUCTION ledger soak audit — reading ONLY the prod
``events.jsonl`` and ``storage_manifest.json`` (never the game sidecars):

  * event count, tick count (started==finished), game count;
  * last tick age, median inter-tick gap;
  * game hard-fail rate (invalid+timeout+error);
  * manifest event_count == ledger length;
  * forbidden events (CandidatePromoted / Submission* / KaggleScoreUpdated) absent;
  * every relevant tick/game event carries no_upload truthy.

NO mutation / upload / promotion / tick execution. The root "Start application"
workflow is NEVER started. Output:
  data/experiments/pass46_core_soak_snapshot.{json,md}
"""
from __future__ import annotations

import filecmp
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
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
DOTREPLIT = REPO / ".replit"
FORBIDDEN = {"CandidatePromoted", "SubmissionQueued",
             "SubmissionUploaded", "KaggleScoreUpdated"}
TARGETS = [
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
]
NOMINAL_INTERVAL_S = 1200.0
MAX_HARDFAIL_RATE = 0.05


def _p(e: dict) -> dict:
    return e.get("payload") or {}


def _et(e: dict) -> str:
    return e.get("event_type")


def _ts(e: dict) -> float:
    return float(e.get("timestamp") or 0.0)


def _load_prod():
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


def _root_safety() -> dict:
    main_ok = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_ok = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    return {"main_py_byte_identical": main_ok, "deck_csv_byte_identical": deck_ok,
            "root_unchanged": bool(main_ok and deck_ok), "filecmp_derived": True}


def _deploy_safety() -> dict:
    txt = DOTREPLIT.read_text(encoding="utf-8") if DOTREPLIT.is_file() else ""
    app_storage = "replit_app_storage" in txt
    tick = "tournament_deployment_tick.py" in txt
    production = "--production" in txt
    not_root_main = '\nrun = ["python", "main.py"]' not in txt
    return {"replit_app_storage": app_storage, "deployment_tick": tick,
            "production_flag": production, "deployment_not_root_main": not_root_main,
            "all_ok": app_storage and tick and production and not_root_main}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    raw, manifest = _load_prod()
    now = time.time()

    starts = [e for e in raw if _et(e) == "TournamentTickStarted"]
    finishes = [e for e in raw if _et(e) == "TournamentTickFinished"]
    scheduled = [e for e in raw if _et(e) == "GameScheduled"]
    started = [e for e in raw if _et(e) == "GameStarted"]
    finished = [e for e in raw if _et(e) == "GameFinished"]

    start_runs = [(_p(e).get("run_id") or _p(e).get("tick_id")) for e in starts]
    fin_runs = {(_p(e).get("run_id") or _p(e).get("tick_id")) for e in finishes}
    orphaned = sorted(r for r in start_runs if r and r not in fin_runs)
    ticks_balanced = len(starts) == len(finishes) and not orphaned

    stimes = sorted(_ts(e) for e in starts if _ts(e) > 0)
    deltas = [b - a for a, b in zip(stimes, stimes[1:]) if b > a]
    median_gap_s = round(statistics.median(deltas), 1) if deltas else None
    last_tick_age_s = round(now - stimes[-1], 1) if stimes else None
    cadence_regular = bool(median_gap_s is not None
                           and 0.4 * NOMINAL_INTERVAL_S <= median_gap_s
                           <= 2.5 * NOMINAL_INTERVAL_S)
    daemon_recent = bool(last_tick_age_s is not None
                         and last_tick_age_s <= 3 * NOMINAL_INTERVAL_S)

    outcomes = {"win": 0, "loss": 0, "draw": 0, "invalid_or_error": 0}
    timeouts = errors = no_upload_violations = 0
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
    for e in starts + finishes + scheduled + started:
        if _p(e).get("no_upload") is not True:
            no_upload_violations += 1
    n_games = len(finished)
    hardfail = outcomes["invalid_or_error"]
    hardfail_rate = round(hardfail / n_games, 4) if n_games else 0.0

    reg = {}
    for e in raw:
        if _et(e) == "TournamentParticipantRegistered":
            cid = _p(e).get("candidate_id")
            if cid in TARGETS and cid not in reg:
                reg[cid] = _ts(e)
    per_target = {}
    for cid in TARGETS:
        invo = [e for e in finished if _p(e).get("candidate_a") == cid
                or _p(e).get("candidate_b") == cid]
        per_target[cid] = {"registered": cid in reg, "games": len(invo),
                           "accruing_evidence": len(invo) > 0}
    any_accruing = any(t["accruing_evidence"] for t in per_target.values())

    forbidden_present = sorted({_et(e) for e in raw if _et(e) in FORBIDDEN})
    ledger_count = len(raw)
    manifest_count = (manifest or {}).get("event_count")
    manifest_matches = (manifest_count == ledger_count) if manifest else None

    root = _root_safety()
    deploy = _deploy_safety()

    checks = {
        "root_byte_identical": root["root_unchanged"],
        "deployment_config_unchanged": deploy["all_ok"],
        "ticks_started_equal_finished": ticks_balanced,
        "hardfail_rate_within_budget": hardfail_rate <= MAX_HARDFAIL_RATE,
        "all_events_no_upload": no_upload_violations == 0,
        "no_forbidden_events_in_scope": not forbidden_present,
        "manifest_event_count_matches_ledger": bool(manifest_matches),
        "targets_accruing_evidence": any_accruing,
    }
    soak_healthy = all(checks.values())
    daemon_attention_required = not soak_healthy

    out = {
        "pass": "pass46_core_soak_snapshot",
        "read_only": True, "production_mutated": False, "tick_executed": False,
        "upload_performed": False, "start_application_started": False,
        "root_safety": root,
        "deployment_safety": deploy,
        "ledger_event_count": ledger_count,
        "tick_count": {"started": len(starts), "finished": len(finishes),
                       "orphaned": orphaned},
        "game_count": {"scheduled": len(scheduled), "started": len(started),
                       "finished": n_games, "outcomes": outcomes,
                       "timeouts": timeouts, "errors": errors},
        "last_tick_age_s": last_tick_age_s,
        "median_inter_tick_gap_s": median_gap_s,
        "nominal_interval_s": NOMINAL_INTERVAL_S,
        "cadence_regular": cadence_regular,
        "daemon_recent": daemon_recent,
        "hardfail_rate": hardfail_rate,
        "max_hardfail_rate_budget": MAX_HARDFAIL_RATE,
        "no_upload_violations": no_upload_violations,
        "forbidden_events_present": forbidden_present,
        "manifest": {"event_count": manifest_count,
                     "matches_ledger": manifest_matches,
                     "manifest_present": manifest is not None},
        "probation_targets": per_target,
        "targets_any_accruing": any_accruing,
        "checks": checks,
        "soak_healthy": soak_healthy,
        "daemon_attention_required": daemon_attention_required,
    }
    (EXP / "pass46_core_soak_snapshot.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b is True else ("no" if b is False else "unverified")

    def hhmm(s):
        return "n/a" if s is None else f"{s/60:.1f} min"

    md = [
        "# PASS 46 — core tournament SOAK snapshot", "",
        "> Read-only audit of the live Scheduled Deployment daemon from the production "
        "ledger only (no sidecar pulls, no tick execution, no mutation). Internal "
        "self-play diagnostics; NOT a Kaggle leaderboard. The root 'Start application' "
        "workflow is never started.", "",
        f"- **soak healthy: {yn(soak_healthy)}**  · daemon attention required: "
        f"**{yn(daemon_attention_required)}**",
        f"- root byte-identical: **{yn(root['root_unchanged'])}** (filecmp-derived)  · "
        f"deploy config unchanged: **{yn(deploy['all_ok'])}**",
        f"- ledger events: **{ledger_count}**  · ticks: **{len(starts)}** started / "
        f"**{len(finishes)}** finished (orphaned: `{orphaned or 'none'}`)",
        f"- games finished: **{n_games}**  · outcomes: `{json.dumps(outcomes)}`",
        f"- last tick age: **{hhmm(last_tick_age_s)}**  · median inter-tick gap: "
        f"**{hhmm(median_gap_s)}** (nominal {hhmm(NOMINAL_INTERVAL_S)})",
        f"- hard-fail rate: **{hardfail_rate}** (budget {MAX_HARDFAIL_RATE})  · "
        f"no_upload violations: **{no_upload_violations}**",
        f"- manifest event_count == ledger: **{yn(manifest_matches)}** "
        f"({manifest_count} vs {ledger_count})",
        f"- forbidden events present: `{forbidden_present or 'none'}`",
        "", "## Checks", "", "| check | pass |", "|---|---|",
    ]
    for k, v in checks.items():
        md.append(f"| {k} | {yn(v)} |")
    md += ["", "## Probation targets accruing evidence", "",
           "| candidate | registered | games | accruing |",
           "|---|---|---|---|"]
    for cid, t in per_target.items():
        md.append(f"| `{cid}` | {yn(t['registered'])} | {t['games']} | "
                  f"{yn(t['accruing_evidence'])} |")
    md += ["", "> Cadence is derived from TournamentTickStarted timestamps. Liveness "
           "and cadence-regularity are tolerant informational signals; the hard soak "
           "gates are tick-lifecycle integrity, hard-fail budget, upload safety, "
           "forbidden-event absence, manifest/ledger lockstep, and root/deploy "
           "immutability."]
    (EXP / "pass46_core_soak_snapshot.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass46 core_soak: soak_healthy={soak_healthy} events={ledger_count} "
          f"ticks={len(starts)}/{len(finishes)} games={n_games} "
          f"hardfail_rate={hardfail_rate} last_tick_min="
          f"{None if last_tick_age_s is None else round(last_tick_age_s/60,1)} "
          f"manifest_match={manifest_matches} root_ok={root['root_unchanged']}")
    return 0 if soak_healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
