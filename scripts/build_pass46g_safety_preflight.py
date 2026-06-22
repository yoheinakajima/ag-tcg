#!/usr/bin/env python3
"""PASS 46G (Part A) — safety stop-gate for the multi-profile turn-planner sprint.

LOCAL / verify-only STOP-GATE. Pass 46G is a LOCAL gameplay-improvement sprint that
builds a SMALL BATCH of owned cg_typed turn-planner candidates (<=6) from internal
source families. It is NOT a Kaggle upload/submission/promotion/registration pass and
performs NO production tick / republish. This preflight freshly re-confirms, WITHOUT
mutating anything, the hard invariants before any candidate is built:

  1. root ``main.py`` / ``deck.csv`` byte-identical to the frozen v1 baseline
     (data/baselines/v1_kaggle_349_8);
  2. ``.replit`` scheduled deployment still points at
     ``scripts/tournament_deployment_tick.py ... --production`` (NOT root main.py);
  3. ``auto_submit`` falsy in tournament config;
  4. production is not mutated by this pass (read-only flags asserted);
  5. NO forbidden events in the prod + local ledgers
     (SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated / CandidatePromoted);
  6. public references absent from the main candidate pool AND the scheduler worklist,
     and no never-schedule status (special_pilot_only / retired / quarantined / invalid)
     leaks into the worklist;
  7. the Pass 46D primitives + Pass 46E oracle/calibration artifacts are present
     (the inputs this sprint depends on).

Writes data/experiments/pass46g_safety_preflight.{json,md}. Exit nonzero if unsafe.
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
TRACES = EXP / "pass46c_traces"
LOCAL_EVENTS = REPO / "data" / "tournament" / "events.jsonl"

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED,
         poolmod.INVALID}

# Inputs this sprint strictly depends on.
REQUIRED_46D = [REPO / "src/ptcg_activegraph/analysis/turn_primitives.py"]
REQUIRED_46E = [
    REPO / "src/ptcg_activegraph/analysis/search_oracle.py",
    REPO / "src/ptcg_activegraph/analysis/_search_worker.py",
    EXP / "pass46e_search_oracle_calibration.json",
    EXP / "pass46e_strategy_decision.json",
]
# 46F label/profile reused as a calibration input where possible (Part D).
REQUIRED_46F = [
    REPO / "src/ptcg_activegraph/analysis/turn_scorer.py",
    EXP / "pass46f_turn_label_dataset.json",
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

    missing_46d = sorted(str(p.relative_to(REPO)) for p in REQUIRED_46D if not p.exists())
    missing_46e = sorted(str(p.relative_to(REPO)) for p in REQUIRED_46E if not p.exists())
    missing_46f = sorted(str(p.relative_to(REPO)) for p in REQUIRED_46F if not p.exists())
    traces_present = sorted(Path(p).name for p in glob.glob(str(TRACES / "*.json.gz")))

    checks = {
        "root_main_unchanged": main_ok,
        "root_deck_unchanged": deck_ok,
        "deployment_target_scheduled": dep["deployment_target_scheduled"],
        "deployment_points_to_tick_not_root": (dep["run_is_deployment_tick"]
                                               and dep["run_not_root_main"]),
        "deployment_has_production": dep["run_has_production"],
        "start_application_frozen_entrypoint": start_wf["is_frozen_kaggle_entrypoint"],
        "auto_submit_falsy": auto_submit is False,
        "prod_ledger_read_ok": prod["read_ok"],
        "no_forbidden_events_in_prod_ledger": prod["read_ok"] and prod["forbidden"] == [],
        "no_forbidden_events_in_local_ledger": local_forbidden == [],
        "references_absent_from_pool": prod["read_ok"] and prod["refs_in_pool"] == [],
        "references_absent_from_worklist": prod["read_ok"] and prod["refs_in_wl"] == [],
        "no_never_schedule_in_worklist": prod["read_ok"] and prod["never_in_wl"] == [],
        "pass46d_artifacts_present": missing_46d == [],
        "pass46e_artifacts_present": missing_46e == [],
        "pass46f_inputs_present": missing_46f == [],
        "pass46c_traces_present": len(traces_present) > 0,
    }
    all_ok = all(checks.values())

    data = {
        "pass": "46g", "part": "A", "read_only": True, "production_mutated": False,
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
        "missing_46d_artifacts": missing_46d,
        "missing_46e_artifacts": missing_46e,
        "missing_46f_inputs": missing_46f,
        "n_traces_present": len(traces_present),
        "checks": checks,
        "all_ok": all_ok,
        "stop_required": not all_ok,
    }
    (EXP / "pass46g_safety_preflight.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def yn(v):
        return "PASS" if v is True else ("FAIL" if v is False else "unverified")

    md = [
        "# Pass 46G — Part A: safety stop-gate", "",
        "> LOCAL gameplay-improvement sprint (multi-profile turn-planner candidates). "
        "NOT a Kaggle upload/submission/promotion/registration pass. No prod Object "
        "Storage mutation, no tick, no republish, no upload/submit, no auto-submit, no "
        "CandidatePromoted/SubmissionQueued/SubmissionUploaded/KaggleScoreUpdated, no "
        "public reference as source/parent/candidate, no root main.py/deck.csv "
        "mutation, no edit/delete of existing tarballs. Root 'Start application' "
        "not-started is EXPECTED and never started here.", "",
        "## Stop-gate checks",
    ]
    for k, v in checks.items():
        md.append(f"- `{k}`: {yn(v)}")
    md += [
        "",
        f"- prod ledger length (read-only): {prod['ledger_len']}"
        + (f" | prod read error: `{prod['error']}`" if prod["error"] else ""),
        f"- traces present: {len(traces_present)}",
        f"- missing 46D artifacts: {missing_46d or 'none'}",
        f"- missing 46E artifacts: {missing_46e or 'none'}",
        f"- missing 46F inputs: {missing_46f or 'none'}", "",
        f"**all_ok = {all_ok}** — **stop_required = {not all_ok}**",
    ]
    (EXP / "pass46g_safety_preflight.md").write_text("\n".join(md) + "\n",
                                                     encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "stop_required": not all_ok,
                      "prod_read_ok": prod["read_ok"],
                      "failing": sorted(k for k, v in checks.items() if not v)},
                     indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
