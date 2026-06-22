#!/usr/bin/env python3
"""PASS 46K (Part A) — safety stop-gate for the Diamond specialist *larger-N confirmation*.

LOCAL / verify-only STOP-GATE. Pass 46K does NOT build a new candidate: it re-evaluates the
EXISTING Pass-46J candidate ``cg_typed_diamond_specialist_planner_v0`` at larger N against the
internal parent ``diamond_toolbox_diancie``, the Pass-46H generic diamond scorers (attribution
baselines), and the public references (benchmark-only opponents). Production keeps soaking — this
pass performs NO production tick / republish / candidate registration / lifecycle / status apply /
promotion, and NO Kaggle upload/submit/auto-submit. Public references stay benchmark-only
opponents (never source/parent/candidate, never a decision gate).

This preflight freshly re-confirms, WITHOUT mutating anything, the hard invariants:

  1. root ``main.py`` / ``deck.csv`` byte-identical to the frozen v1 baseline
     (data/baselines/v1_kaggle_349_8);
  2. ``.replit`` scheduled deployment still runs
     ``scripts/tournament_deployment_tick.py ... --production`` with the
     ``replit_app_storage`` backend (NOT root main.py);
  3. ``auto_submit`` falsy in tournament config;
  4. NO forbidden events in the prod + local ledgers
     (SubmissionQueued / SubmissionUploaded / KaggleScoreUpdated / CandidatePromoted);
  5. public references absent from the main candidate pool AND the scheduler worklist,
     and no never-schedule status (special_pilot_only / retired / quarantined / invalid)
     leaks into the worklist;
  6. the source parent ``diamond_toolbox_diancie`` tarball exists and is INTERNAL — it is
     NOT a public reference and NOT in a never-schedule status;
  7. the Pass-46J candidate tarball under evaluation is present (and is the only/expected
     tarball in candidates_pass46j — re-runnable, no foreign tarball to risk overwriting);
  8. the Pass-46J eval artifacts we may carry rows from / compare against are present
     (eval plan, eval panel, eval games JSONL, strategy decision);
  9. the comparison tarballs are present: the parent, the Pass-46H generic ``option_value``
     scorer (the strongest generic baseline / prior weak spot), and the Pass-46H
     ``family_only_floor`` scorer (attribution context); and the card DB CSV is present.

Writes data/experiments/pass46k_safety_preflight.{json,md}. Exit nonzero if unsafe.
NO upload / submit / push / tick / root or tarball mutation. Never starts the root
'Start application' workflow.
"""
from __future__ import annotations

import filecmp
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

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED,
         poolmod.INVALID}

# --- Pass-46K source / candidate-under-test / comparison artifacts -----------------------
DIAMOND_PARENT_ID = "diamond_toolbox_diancie"
DIAMOND_PARENT_TARBALL = (REPO / "data" / "submissions" / "candidates_pass34"
                          / "diamond_toolbox_diancie.tar.gz")
# Pass-46J candidate under evaluation (REUSED — NOT rebuilt this pass).
CAND_46J_DIR = REPO / "data" / "submissions" / "candidates_pass46j"
CAND_46J_ID = "cg_typed_diamond_specialist_planner_v0"
CAND_46J_TARBALL = CAND_46J_DIR / f"{CAND_46J_ID}.tar.gz"

# Pass-46H comparison scorers (the strongest generic baseline + the family-only floor).
CAND_46H_DIR = REPO / "data" / "submissions" / "candidates_pass46h"
DIAMOND_46H_COMPARISONS = [
    CAND_46H_DIR / "cg_typed_diamond_option_value_v1.tar.gz",
    CAND_46H_DIR / "cg_typed_diamond_family_only_floor_v1.tar.gz",
]

# Pass-46J eval artifacts we may carry rows from / compare against.
REQUIRED_46J_ARTIFACTS = [
    EXP / "pass46j_diamond_eval_plan.json",
    EXP / "pass46j_diamond_eval_panel.json",
    EXP / "pass46j_diamond_eval_games.jsonl",
    EXP / "pass46j_strategy_decision.json",
]
CARD_DB_CSV = REPO / "data" / "cards" / "EN_Card_Data.csv"
LOCAL_POOL_JSON = REPO / "data" / "tournament" / "candidate_pool.json"


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
           "never_in_wl": [], "ledger_len": 0, "diamond_parent_status": None,
           "diamond_parent_in_refs": None, "error": None}
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
        out["diamond_parent_status"] = status_of.get(DIAMOND_PARENT_ID)
        out["diamond_parent_in_refs"] = DIAMOND_PARENT_ID in ref_ids
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


def _local_pool_status(cand_id: str) -> str | None:
    try:
        data = json.loads(LOCAL_POOL_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    cands = data.get("candidates", data) if isinstance(data, dict) else data
    if isinstance(cands, dict):
        cands = cands.get("candidates", [])
    for c in cands if isinstance(cands, list) else []:
        if isinstance(c, dict) and c.get("candidate_id") == cand_id:
            return c.get("status")
    return None


def _diamond_source_check(prod: dict) -> dict:
    """Confirm the source parent is INTERNAL and safe to use (not ref / never-schedule)."""
    try:
        ref_ids = set(promotion.load_reference_ids())
    except Exception:  # noqa: BLE001
        ref_ids = set()
    in_refs = DIAMOND_PARENT_ID in ref_ids
    if prod.get("read_ok") and prod.get("diamond_parent_status") is not None:
        status, src = prod["diamond_parent_status"], "prod_pool"
    else:
        status, src = _local_pool_status(DIAMOND_PARENT_ID), "local_pool"
    return {
        "parent_id": DIAMOND_PARENT_ID,
        "parent_tarball": str(DIAMOND_PARENT_TARBALL.relative_to(REPO)),
        "parent_tarball_present": DIAMOND_PARENT_TARBALL.exists(),
        "parent_tarball_sha256": _sha(DIAMOND_PARENT_TARBALL),
        "parent_in_reference_ids": in_refs,
        "parent_status": status,
        "parent_status_source": src,
        "parent_status_not_never": status is not None and status not in NEVER,
    }


def _candidate_dir_safe() -> tuple[bool, list[str]]:
    """Re-runnable: only FOREIGN tarballs (not the 46J specialist) make the dir unsafe.

    Pass 46K writes NOTHING to candidates_pass46j; this only guards against an unexpected
    foreign artifact appearing next to the candidate we evaluate.
    """
    if not CAND_46J_DIR.exists():
        return False, []
    foreign = sorted(p.name for p in CAND_46J_DIR.glob("*.tar.gz")
                     if p.name != CAND_46J_TARBALL.name)
    return foreign == [], foreign


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
    diamond = _diamond_source_check(prod)
    cand_dir_safe, foreign_tarballs = _candidate_dir_safe()

    missing_46j = sorted(str(p.relative_to(REPO)) for p in REQUIRED_46J_ARTIFACTS
                         if not p.exists())
    missing_comparisons = sorted(str(p.relative_to(REPO)) for p in DIAMOND_46H_COMPARISONS
                                 if not p.exists())

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
        "diamond_parent_tarball_present": diamond["parent_tarball_present"],
        "diamond_parent_is_internal_not_reference": diamond["parent_in_reference_ids"] is False,
        "diamond_parent_status_not_never": diamond["parent_status_not_never"],
        "pass46j_candidate_tarball_present": CAND_46J_TARBALL.exists(),
        "candidates_pass46j_no_foreign_tarballs": cand_dir_safe,
        "pass46j_eval_artifacts_present": missing_46j == [],
        "pass46h_comparison_tarballs_present": missing_comparisons == [],
        "card_db_csv_present": CARD_DB_CSV.exists(),
    }
    all_ok = all(checks.values())

    data = {
        "pass": "46k", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False, "candidate_rebuilt": False,
        "republish_required": False, "registration_performed": False,
        "promotion_performed": False, "lifecycle_applied": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": _sha(REPO / "main.py"),
        "root_deck_sha256": _sha(REPO / "deck.csv"),
        "deployment_checks": dep,
        "start_application_workflow": start_wf,
        "auto_submit": auto_submit,
        "prod_ledger_scan": prod,
        "forbidden_events_in_local_ledger": local_forbidden,
        "diamond_source": diamond,
        "candidate_under_test_id": CAND_46J_ID,
        "candidate_under_test_tarball": str(CAND_46J_TARBALL.relative_to(REPO)),
        "candidate_under_test_sha256": _sha(CAND_46J_TARBALL),
        "candidates_pass46j_dir": str(CAND_46J_DIR.relative_to(REPO)),
        "candidates_pass46j_foreign_tarballs": foreign_tarballs,
        "missing_46j_eval_artifacts": missing_46j,
        "missing_46h_comparison_tarballs": missing_comparisons,
        "card_db_csv": str(CARD_DB_CSV.relative_to(REPO)),
        "checks": checks,
        "all_ok": all_ok,
        "stop_required": not all_ok,
    }
    (EXP / "pass46k_safety_preflight.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def yn(v):
        return "PASS" if v is True else ("FAIL" if v is False else "unverified")

    md = [
        "# Pass 46K — Part A: safety stop-gate", "",
        "> LOCAL larger-N confirmation pass: re-evaluate the EXISTING Pass-46J candidate "
        "`cg_typed_diamond_specialist_planner_v0` (NOT rebuilt) at larger N vs the internal "
        "parent `diamond_toolbox_diancie`, the Pass-46H generic diamond scorers (attribution "
        "baselines), and the public references (benchmark-only opponents, never a decision "
        "gate). Production keeps soaking. NO prod Object Storage mutation, no tick, no "
        "republish, no candidate registration, no lifecycle/status apply, no promotion, no "
        "Kaggle upload/submit, no auto-submit, no CandidatePromoted/SubmissionQueued/"
        "SubmissionUploaded/KaggleScoreUpdated, no public reference as source/parent/"
        "candidate, no root main.py/deck.csv mutation, no edit/delete/overwrite of existing "
        "tarballs, no invented card IDs. Root 'Start application' not-started is EXPECTED "
        "and never started here.", "",
        "## Stop-gate checks",
    ]
    for k, v in checks.items():
        md.append(f"- `{k}`: {yn(v)}")
    md += [
        "",
        f"- prod ledger length (read-only): {prod['ledger_len']}"
        + (f" | prod read error: `{prod['error']}`" if prod["error"] else ""),
        f"- diamond parent: `{diamond['parent_id']}` status="
        f"`{diamond['parent_status']}` (source: {diamond['parent_status_source']}), "
        f"in_reference_ids={diamond['parent_in_reference_ids']}",
        f"- candidate under test: `{CAND_46J_ID}` present={CAND_46J_TARBALL.exists()}",
        f"- candidates_pass46j foreign tarballs: {foreign_tarballs or 'none'}",
        f"- missing 46J eval artifacts: {missing_46j or 'none'}",
        f"- missing 46H comparison tarballs: {missing_comparisons or 'none'}", "",
        f"**all_ok = {all_ok}** — **stop_required = {not all_ok}**",
    ]
    (EXP / "pass46k_safety_preflight.md").write_text("\n".join(md) + "\n",
                                                     encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "stop_required": not all_ok,
                      "prod_read_ok": prod["read_ok"],
                      "diamond_parent_status": diamond["parent_status"],
                      "failing": sorted(k for k, v in checks.items() if not v)},
                     indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
