#!/usr/bin/env python3
"""PASS 46I (Part A) — safety stop-gate for the Water option-value CONFIRMATION pass.

LOCAL / verify-only STOP-GATE. Pass 46I is a LOCAL confirmation pass: it replays the
EXISTING Pass-46H water tarballs (treatment ``cg_typed_water_option_value_v1``, floor
control ``cg_typed_water_family_only_floor_v1``, conservative sibling
``cg_typed_water_conservative_option_value_v1``) against each other and against the real
internal parent ``league_water_anti_disruption_pivot_v1`` to decide whether the
option-value treatment clears BOTH (1) attribution vs the family-only floor AND (2) a
practical edge vs the real parent. It is NOT a Kaggle upload/submission/promotion/
registration pass and performs NO production tick / republish / candidate generation.
This preflight freshly re-confirms, WITHOUT mutating anything, the hard invariants:

  1. root ``main.py`` / ``deck.csv`` byte-identical to the frozen v1 baseline
     (data/baselines/v1_kaggle_349_8);
  2. ``.replit`` scheduled deployment still runs
     ``scripts/tournament_deployment_tick.py ... --production`` with the
     ``replit_app_storage`` backend (NOT root main.py);
  3. ``auto_submit`` falsy in tournament config;
  4. production is not mutated by this pass (read-only flags asserted);
  5. NO forbidden events in the prod + local ledgers
     (SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated / CandidatePromoted);
  6. public references absent from the main candidate pool AND the scheduler worklist,
     and no never-schedule status (special_pilot_only / retired / quarantined / invalid)
     leaks into the worklist;
  7. the Pass-46H water candidate tarballs + the real parent tarball this pass replays
     are present (existing artifacts only — Pass 46I generates NO new candidates);
  8. the Pass-46H eval artifacts this confirmation extends are present
     (candidate build record, eval panel, smoke non-inertness, strategy decision).

Writes data/experiments/pass46i_safety_preflight.{json,md}. Exit nonzero if unsafe.
NO upload / submit / push / tick / root or tarball mutation. Never starts the root
'Start application' workflow.
"""
from __future__ import annotations

import filecmp
import glob
import hashlib
import json
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import sync, promotion, pool as poolmod, projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
LOCAL_EVENTS = REPO / "data" / "tournament" / "events.jsonl"
CAND_46H_DIR = REPO / "data" / "submissions" / "candidates_pass46h"

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED,
         poolmod.INVALID}

# The EXISTING Pass-46H water artifacts this confirmation pass replays (no new builds).
WATER_CANDIDATE_TARBALLS = [
    CAND_46H_DIR / "cg_typed_water_family_only_floor_v1.tar.gz",
    CAND_46H_DIR / "cg_typed_water_option_value_v1.tar.gz",
    CAND_46H_DIR / "cg_typed_water_conservative_option_value_v1.tar.gz",
]
PARENT_TARBALL = (REPO / "data" / "submissions" / "candidates_pass33"
                  / "league_water_anti_disruption_pivot_v1.tar.gz")
REQUIRED_46H_EVAL = [
    EXP / "pass46h_candidate_build.json",
    EXP / "pass46h_eval_panel.json",
    EXP / "pass46h_smoke_non_inertness.json",
    EXP / "pass46h_strategy_decision.json",
]


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _cmp(name: str) -> bool:
    root_f, base_f = REPO / name, BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return False
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return False


def _scan_local_forbidden() -> list[str]:
    if not LOCAL_EVENTS.exists():
        return []
    seen: set[str] = set()
    for line in LOCAL_EVENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            et = json.loads(line).get("event_type")
        except Exception:  # noqa: BLE001
            continue
        if et in LEDGER_FORBIDDEN:
            seen.add(et)
    return sorted(seen)


def _prod_ledger_scan() -> dict:
    """Read-only prod ledger scan. Fails CLOSED: any read error => unverified."""
    out = {"read_ok": False, "forbidden": [], "refs_in_pool": [], "refs_in_wl": [],
           "never_in_wl": [], "ledger_len": 0, "error": None}
    try:
        b = get_storage_backend(env="production", backend="replit_app_storage")
        txt = b.read_text(sync.EVENTS_KEY)
        tmpf = Path(tempfile.mkdtemp()) / "events.jsonl"
        tmpf.write_text(txt, encoding="utf-8")
        events = TournamentLedger(path=tmpf).load()
        pool = CandidatePool.from_events(events)
        status_of = {c.candidate_id: c.status for c in pool.candidates}
        ref_ids = set(promotion.load_reference_ids())
        out["refs_in_pool"] = sorted(ref_ids & set(status_of))
        projmod.PROJ_DIR = Path(tempfile.mkdtemp())
        cfg = load_config()
        prior = projmod.write_projections(pool, events, cfg)
        state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
        wl_ids: set[str] = set()
        for g in build_worklist(pool, state, cfg):
            d = g.to_dict()
            wl_ids.add(d["candidate_a"])
            wl_ids.add(d["candidate_b"])
        out["refs_in_wl"] = sorted(ref_ids & wl_ids)
        out["never_in_wl"] = sorted(c for c, s in status_of.items()
                                    if s in NEVER and c in wl_ids)
        out["forbidden"] = sorted({e.event_type for e in events
                                   if e.event_type in LEDGER_FORBIDDEN})
        out["ledger_len"] = len(events)
        out["read_ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}:{exc}"
    return out


def _check_auto_submit() -> bool:
    try:
        cfg = load_config()
        return bool(getattr(cfg, "auto_submit", False)) if cfg is not None else False
    except Exception:  # noqa: BLE001
        return False


def _deployment_checks() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = data.get("deployment", {}) or {}
    run = dep.get("run", []) or []
    run_str = " ".join(str(x) for x in run)
    return {
        "deployment_target_scheduled": dep.get("deploymentTarget") == "scheduled",
        "run_is_deployment_tick": "scripts/tournament_deployment_tick.py" in run_str,
        "run_not_root_main": "main.py" not in run,
        "run_has_production": "--production" in run_str,
        "run_uses_replit_app_storage": "replit_app_storage" in run_str,
    }


def _start_workflow_check() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    found = None
    for wf in data.get("workflows", {}).get("workflow", []) or []:
        if wf.get("name") == "Start application":
            tasks = wf.get("tasks", []) or []
            found = " ".join(str(t.get("args", "")) for t in tasks)
    return {"workflow_args": found,
            "is_frozen_kaggle_entrypoint": found is not None and "main.py" in found,
            "started_here": False, "not_started_is_expected": True}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    main_ok = _cmp("main.py")
    deck_ok = _cmp("deck.csv")
    dep = _deployment_checks()
    start_wf = _start_workflow_check()
    auto_submit = _check_auto_submit()
    local_forbidden = _scan_local_forbidden()
    prod = _prod_ledger_scan()

    missing_water_tarballs = sorted(str(p.relative_to(REPO))
                                    for p in WATER_CANDIDATE_TARBALLS if not p.exists())
    parent_present = PARENT_TARBALL.exists()
    missing_46h_eval = sorted(str(p.relative_to(REPO))
                              for p in REQUIRED_46H_EVAL if not p.exists())
    water_tarballs = sorted(Path(p).name for p in WATER_CANDIDATE_TARBALLS if p.exists())

    checks = {
        "root_main_unchanged": main_ok,
        "root_deck_unchanged": deck_ok,
        "deployment_target_scheduled": dep["deployment_target_scheduled"],
        "deployment_points_to_tick_not_root": (dep["run_is_deployment_tick"]
                                               and dep["run_not_root_main"]),
        "deployment_has_production": dep["run_has_production"],
        "deployment_uses_replit_app_storage": dep["run_uses_replit_app_storage"],
        "start_application_frozen_entrypoint": start_wf["is_frozen_kaggle_entrypoint"],
        "auto_submit_falsy": auto_submit is False,
        "prod_ledger_read_ok": prod["read_ok"],
        "no_forbidden_events_in_prod_ledger": prod["read_ok"] and prod["forbidden"] == [],
        "no_forbidden_events_in_local_ledger": local_forbidden == [],
        "references_absent_from_pool": prod["read_ok"] and prod["refs_in_pool"] == [],
        "references_absent_from_worklist": prod["read_ok"] and prod["refs_in_wl"] == [],
        "no_never_schedule_in_worklist": prod["read_ok"] and prod["never_in_wl"] == [],
        "pass46h_water_tarballs_present": missing_water_tarballs == [],
        "pass46h_parent_tarball_present": parent_present,
        "pass46h_eval_artifacts_present": missing_46h_eval == [],
    }
    all_ok = all(checks.values())

    data = {
        "pass": "46i", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False, "republish_required": False,
        "registration_performed": False, "promotion_performed": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": _sha(REPO / "main.py"),
        "root_deck_sha256": _sha(REPO / "deck.csv"),
        "deployment_checks": dep,
        "start_application_workflow": start_wf,
        "auto_submit": auto_submit,
        "prod_ledger_scan": prod,
        "forbidden_events_in_local_ledger": local_forbidden,
        "water_candidate_tarballs": water_tarballs,
        "missing_water_candidate_tarballs": missing_water_tarballs,
        "parent_tarball_present": parent_present,
        "parent_tarball": str(PARENT_TARBALL.relative_to(REPO)),
        "missing_46h_eval_artifacts": missing_46h_eval,
        "checks": checks,
        "all_ok": all_ok,
        "stop_required": not all_ok,
    }
    (EXP / "pass46i_safety_preflight.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def yn(v):
        return "PASS" if v is True else ("FAIL" if v is False else "unverified")

    md = [
        "# Pass 46I — Part A: safety stop-gate", "",
        "> LOCAL confirmation pass (replays the EXISTING Pass-46H water tarballs to "
        "confirm whether `cg_typed_water_option_value_v1` clears BOTH attribution vs the "
        "family-only floor AND a practical edge vs the real parent). NOT a Kaggle "
        "upload/submission/promotion/registration pass. No prod Object Storage mutation, "
        "no tick, no republish, no candidate generation, no upload/submit, no "
        "auto-submit, no CandidatePromoted/SubmissionQueued/SubmissionUploaded/"
        "KaggleScoreUpdated, no public reference as source/parent/candidate, no root "
        "main.py/deck.csv mutation, no edit/delete of existing tarballs. Root 'Start "
        "application' not-started is EXPECTED and never started here.", "",
        "## Stop-gate checks",
    ]
    for k, v in checks.items():
        md.append(f"- `{k}`: {yn(v)}")
    md += [
        "",
        f"- prod ledger length (read-only): {prod['ledger_len']}"
        + (f" | prod read error: `{prod['error']}`" if prod["error"] else ""),
        f"- water candidate tarballs present: {water_tarballs}",
        f"- parent tarball present: {parent_present}",
        f"- missing water tarballs: {missing_water_tarballs or 'none'}",
        f"- missing 46H eval artifacts: {missing_46h_eval or 'none'}", "",
        f"**all_ok = {all_ok}** — **stop_required = {not all_ok}**",
    ]
    (EXP / "pass46i_safety_preflight.md").write_text("\n".join(md) + "\n",
                                                     encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "stop_required": not all_ok,
                      "prod_read_ok": prod["read_ok"],
                      "failing": sorted(k for k, v in checks.items() if not v)},
                     indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
