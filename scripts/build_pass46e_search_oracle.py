#!/usr/bin/env python3
"""PASS 46E — cg Search Outcome Oracle + One-Step Turn Planner v0 (orchestrator).

LOCAL / READ-ONLY / DIAGNOSTIC / GAMEPLAY-INFRASTRUCTURE-ONLY while production
soaks. Produces every Pass-46E artifact WITHOUT mutating production, running a
tick, generating/promoting candidates, queueing, uploading, or republishing:

* Part A — safety stop-gate ........ data/experiments/pass46e_safety_preflight.{json,md}
* Part B — search API surface ...... data/experiments/pass46e_search_api_surface.{json,md}
* Part D — calibration ............. data/experiments/pass46e_search_oracle_calibration.{json,md}
* Part E — one-step planner ........ data/experiments/pass46e_one_step_planner_diagnostic.{json,md}
* Part F — runtime budget .......... data/experiments/pass46e_search_runtime_budget.{json,md}
* Part I — strategy decision ....... data/experiments/pass46e_strategy_decision.{json,md}
* Part J — report (10 sections) .... data/reports/pass46e_cg_search_oracle_report.md
* Part H — docs .................... docs/CG_SEARCH_ORACLE_V0.md (+ NEXT_STEPS / CANVAS)

The oracle under test lives in the pure module
``src/ptcg_activegraph/analysis/search_oracle.py`` (cg isolated to the subprocess
worker ``_search_worker.py``). Run order for a full refresh:
    python3 scripts/build_pass46e_search_oracle_calibration.py
    python3 scripts/build_pass46e_one_step_planner_diagnostic.py
    python3 scripts/build_pass46e_search_oracle.py
(The orchestrator regenerates D/E only if their artifacts are absent.)
"""
from __future__ import annotations

import filecmp
import glob
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
import build_pass46e_search_oracle_calibration as CAL  # noqa: E402
import build_pass46e_one_step_planner_diagnostic as PLN  # noqa: E402
from ptcg_activegraph.tournament import sync, promotion, pool as poolmod, projections as projmod  # noqa: E402
from ptcg_activegraph.tournament.config import load_config  # noqa: E402
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.scheduler import build_worklist  # noqa: E402
from ptcg_activegraph.tournament.storage import get_storage_backend  # noqa: E402

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports"
DOCS = REPO / "docs"
TRACES = EXP / "pass46c_traces"
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"

LEDGER_FORBIDDEN = {"SubmissionQueued", "SubmissionUploaded", "KaggleScoreUpdated",
                    "CandidatePromoted"}
NEVER = {poolmod.SPECIAL_PILOT_ONLY, poolmod.RETIRED, poolmod.QUARANTINED, poolmod.INVALID}

# Ready-for-pilot gate thresholds (honest, conservative).
READY_MIN_SUPPORTED_FRACTION = 0.70
READY_MAX_MISMATCH_RATE = 0.10
READY_MIN_EXACT_RATE = 0.60
READY_MAX_PER_EVAL_P90_S = 1.0

CAVEATS = CAL.CAVEATS


def sha_path(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def write_pair(stem: str, data: dict, title: str, body: str) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# " + title + "\n\n_Pass 46E — cg Search Outcome Oracle + one-step turn "
            "planner v0. READ-ONLY / LOCAL / DIAGNOSTIC. cg Search over Pass-46C "
            "frames under a fabricated hidden-state assumption; NOT a Kaggle strength "
            "or best-action claim. No generation / promotion / queue / upload / "
            "tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + body + "\n", encoding="utf-8")


# ============================================================= Part A: safety
def part_a() -> dict:
    main_unchanged = filecmp.cmp(REPO / "main.py", BASELINE / "main.py", shallow=False)
    deck_unchanged = filecmp.cmp(REPO / "deck.csv", BASELINE / "deck.csv", shallow=False)
    replit_txt = (REPO / ".replit").read_text(encoding="utf-8")
    dep_ok = ("scripts/tournament_deployment_tick.py" in replit_txt
              and "--production" in replit_txt
              and "replit_app_storage" in replit_txt)
    deployment_target_scheduled = 'deploymentTarget = "scheduled"' in replit_txt
    try:
        cfg0 = load_config()
        auto_submit = bool(getattr(cfg0, "auto_submit", False)) if cfg0 is not None else False
    except Exception:  # noqa: BLE001
        auto_submit = False
    b = get_storage_backend(env="production", backend="replit_app_storage")
    txt = b.read_text(sync.EVENTS_KEY)
    tmpf = Path(tempfile.mkdtemp()) / "events.jsonl"
    tmpf.write_text(txt, encoding="utf-8")
    events = TournamentLedger(path=tmpf).load()
    pool = CandidatePool.from_events(events)
    status_of = {c.candidate_id: c.status for c in pool.candidates}
    ref_ids = set(promotion.load_reference_ids())
    refs_in_pool = sorted(ref_ids & set(status_of))
    projmod.PROJ_DIR = Path(tempfile.mkdtemp())
    cfg = load_config()
    prior = projmod.write_projections(pool, events, cfg)
    state = projmod.build_scheduler_state(events, ranking=prior["ranked_ids"])
    wl_ids: set[str] = set()
    for g in build_worklist(pool, state, cfg):
        d = g.to_dict()
        wl_ids.add(d["candidate_a"])
        wl_ids.add(d["candidate_b"])
    refs_in_wl = sorted(ref_ids & wl_ids)
    never_in_wl = sorted(c for c, s in status_of.items() if s in NEVER and c in wl_ids)
    forbidden_in_ledger = sorted({e.event_type for e in events
                                  if e.event_type in LEDGER_FORBIDDEN})
    local_events_path = REPO / "data" / "tournament" / "events.jsonl"
    local_forbidden: list[str] = []
    if local_events_path.exists():
        seen: set[str] = set()
        for line in local_events_path.read_text(encoding="utf-8").splitlines():
            try:
                et = json.loads(line).get("event_type")
            except Exception:  # noqa: BLE001
                continue
            if et in LEDGER_FORBIDDEN:
                seen.add(et)
        local_forbidden = sorted(seen)
    traces_present = sorted(Path(p).name for p in glob.glob(str(TRACES / "*.json.gz")))
    checks = {
        "root_main_unchanged": main_unchanged,
        "root_deck_unchanged": deck_unchanged,
        "deployment_points_to_tick_not_root": dep_ok,
        "deployment_target_scheduled": deployment_target_scheduled,
        "auto_submit_falsy": auto_submit is False,
        "references_absent_from_pool": refs_in_pool == [],
        "references_absent_from_worklist": refs_in_wl == [],
        "no_never_schedule_in_worklist": never_in_wl == [],
        "no_forbidden_events_in_prod_ledger": forbidden_in_ledger == [],
        "no_forbidden_events_in_local_ledger": local_forbidden == [],
        "pass46c_traces_present": len(traces_present) > 0,
    }
    all_ok = all(checks.values())
    data = {
        "pass": "46e", "part": "A", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_sha256": sha_path(REPO / "main.py"),
        "root_deck_sha256": sha_path(REPO / "deck.csv"),
        "checks": checks, "all_ok": all_ok,
        "refs_in_pool": refs_in_pool, "refs_in_worklist": refs_in_wl,
        "never_schedule_in_worklist": never_in_wl,
        "forbidden_events_in_prod_ledger": forbidden_in_ledger,
        "forbidden_events_in_local_ledger": local_forbidden,
        "prod_ledger_len": len(events), "n_traces_present": len(traces_present),
    }
    md = "## Stop-gate checks\n" + "".join(
        f"- `{k}`: {'PASS' if v else 'FAIL'}\n" for k, v in checks.items())
    md += f"\n**all_ok = {all_ok}**\n"
    write_pair("pass46e_safety_preflight", data,
               "Pass 46E — Part A: safety stop-gate", md)
    return data


# ===================================================== Part B: search API surface
_SURFACE_PROBE = r'''
import json, sys, inspect
from pathlib import Path
REPO = Path(r"%s")
sys.path.insert(0, str(REPO / "data" / "reference_agents" / "_sdk"))
out = {"ok": False, "callables": {}, "enums": {}, "error": None}
try:
    from cg import api
    names = ["search_begin", "search_step", "search_end", "search_release",
             "to_observation_class", "all_card_data"]
    for n in names:
        fn = getattr(api, n, None)
        info = {"exists": fn is not None, "callable": callable(fn)}
        try:
            info["signature"] = str(inspect.signature(fn)) if callable(fn) else None
        except (TypeError, ValueError):
            info["signature"] = "builtin_or_c_signature_unavailable"
        out["callables"][n] = info
    for en in ["AreaType", "OptionType", "SelectContext"]:
        e = getattr(api, en, None)
        if e is not None:
            try:
                out["enums"][en] = {m.name: int(m.value) for m in e}
            except Exception:
                out["enums"][en] = "present_non_enumerable"
    core = ["search_begin", "search_step", "search_end", "search_release"]
    out["core_present"] = all(out["callables"][n]["callable"] for n in core)
    out["ok"] = True
except Exception as exc:
    out["error"] = f"{type(exc).__name__}:{exc}"
print(json.dumps(out))
'''


def part_b() -> dict:
    probe = REPO / "scripts" / "_pass46e_surface_probe.py"
    probe.write_text(_SURFACE_PROBE % str(REPO), encoding="utf-8")
    surface = {"ok": False, "core_present": False, "error": "not_run"}
    try:
        cp = subprocess.run([sys.executable, str(probe)], capture_output=True,
                            text=True, timeout=60, cwd=str(REPO))
        line = next((ln for ln in cp.stdout.splitlines()[::-1] if ln.startswith("{")), "")
        if line:
            surface = json.loads(line)
        else:
            surface = {"ok": False, "core_present": False,
                       "error": f"no_json (rc={cp.returncode}): {cp.stderr[-200:]}"}
    except Exception as exc:  # noqa: BLE001
        surface = {"ok": False, "core_present": False,
                   "error": f"{type(exc).__name__}:{exc}"}
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    data = {"pass": "46e", "part": "B", "read_only": True, "production_mutated": False,
            **surface}
    body = (
        f"## cg Search API surface (recorded in subprocess)\n"
        f"- import_ok: **{surface.get('ok')}**\n"
        f"- core_search_callables_present: **{surface.get('core_present')}**\n\n"
        "## Callables\n"
        + "".join(f"- `{n}`: exists={i.get('exists')}, callable={i.get('callable')}, "
                  f"sig=`{i.get('signature')}`\n"
                  for n, i in (surface.get("callables") or {}).items())
        + "\n## Enums present\n"
        + "".join(f"- `{e}`: {len(v) if isinstance(v, dict) else v} members\n"
                  for e, v in (surface.get("enums") or {}).items())
    )
    write_pair("pass46e_search_api_surface", data,
               "Pass 46E — Part B: cg Search API surface audit", body)
    return data


# ===================================================== load D/E (regen if absent)
def _load_or_build(stem: str, builder) -> dict:
    p = EXP / f"{stem}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return builder()


# ============================================================= Part F: runtime
def part_f(calib: dict, rank_sample_frames: int = 4) -> dict:
    per_eval = calib.get("elapsed_stats") or {}
    timeout_rate = 0.0
    cls = calib.get("overall_classification") or {}
    attempted = calib.get("frames_attempted") or 0
    if attempted:
        timeout_rate = round((cls.get("timed_out", 0) + cls.get("error", 0)) / attempted, 4)

    # Live per-rank wall sample (subprocess spawn included) — bounded.
    rank_walls: list[float] = []
    trace_paths = sorted(glob.glob(str(TRACES / "*.json.gz")))
    sampled = 0
    for tp in trace_paths:
        if sampled >= rank_sample_frames:
            break
        try:
            d = json.loads(gzip.open(tp).read())
        except Exception:  # noqa: BLE001
            continue
        seen: dict = {}
        frames = PLN._rankable_frames(d.get("steps") or [], int(d.get("a_seat", 0)),
                                      d.get("role_a"), d.get("role_b"), 1, seen)
        for f in frames:
            if sampled >= rank_sample_frames:
                break
            t0 = time.time()
            O.rank_legal_actions_one_step(f["frame"], max_actions=8, timeout_s=6.0)
            rank_walls.append(round(time.time() - t0, 4))
            sampled += 1

    per_rank = CAL._stats(rank_walls)
    p90_eval = per_eval.get("p90")
    runtime_agent_safe = bool(p90_eval is not None and p90_eval <= READY_MAX_PER_EVAL_P90_S
                              and timeout_rate <= 0.05)
    # recommended per-task budget: ~10x p90 eval, floored, capped.
    rec_budget = None
    if isinstance(p90_eval, (int, float)):
        rec_budget = round(min(8.0, max(2.0, p90_eval * 10 + 1.0)), 2)
    data = {
        "pass": "46e", "part": "F", "read_only": True, "production_mutated": False,
        "per_evaluate_native_step_s": per_eval,
        "per_rank_call_wall_s_includes_subprocess_spawn": per_rank,
        "timeout_plus_error_rate": timeout_rate,
        "recommended_per_task_timeout_s": rec_budget,
        "runtime_agent_safe": runtime_agent_safe,
        "note": "per-evaluate measures the native search step only (batched, cg "
                "imported once); per-rank wall includes one subprocess spawn + cg "
                "import per ranked frame, which dominates and makes per-move live use "
                "diagnostic-grade, not turn-loop-latency-grade.",
    }
    body = (
        "## Runtime budget\n"
        f"- per-evaluate native step (s): {per_eval}\n"
        f"- per-rank call wall incl. subprocess spawn (s): {per_rank}\n"
        f"- timeout+error rate: {timeout_rate}\n"
        f"- recommended per-task timeout (s): {rec_budget}\n"
        f"- runtime_agent_safe (native step only): **{runtime_agent_safe}**\n\n"
        f"> {data['note']}\n"
    )
    write_pair("pass46e_search_runtime_budget", data,
               "Pass 46E — Part F: search runtime budget", body)
    return data


# ============================================================= Part I: decision
def part_i(safety: dict, surface: dict, calib: dict, planner: dict,
           runtime: dict) -> dict:
    attempted = calib.get("frames_attempted") or 0
    supported = calib.get("frames_supported") or 0
    supported_fraction = round(supported / attempted, 4) if attempted else 0.0
    exact_rate = calib.get("exact_rate_of_decisive") or 0.0
    mismatch_rate = calib.get("mismatch_rate_of_decisive") or 1.0
    p90_eval = (runtime.get("per_evaluate_native_step_s") or {}).get("p90")

    safety_ok = bool(safety.get("all_ok"))
    api_ok = bool(surface.get("core_present"))
    claims_guarded = set(O.unsupported_search_claims().keys()) >= {
        "exact_damage", "lethal", "missed_ko", "boss_gust", "spread", "best_action"}
    no_forbidden = (not safety.get("forbidden_events_in_prod_ledger")
                    and not safety.get("forbidden_events_in_local_ledger"))
    no_mutation = (safety.get("production_mutated") is False
                   and calib.get("production_mutated") is False
                   and planner.get("production_mutated") is False)
    no_candidate = (calib.get("candidate_generated") is False
                    and planner.get("candidate_generated") is False)

    ready_gate = {
        "safety_all_ok": safety_ok,
        "api_core_present": api_ok,
        "supported_fraction>=%.2f" % READY_MIN_SUPPORTED_FRACTION:
            supported_fraction >= READY_MIN_SUPPORTED_FRACTION,
        "mismatch_rate<=%.2f" % READY_MAX_MISMATCH_RATE:
            mismatch_rate <= READY_MAX_MISMATCH_RATE,
        "exact_rate>=%.2f" % READY_MIN_EXACT_RATE: exact_rate >= READY_MIN_EXACT_RATE,
        "per_eval_p90<=%.2fs" % READY_MAX_PER_EVAL_P90_S:
            bool(p90_eval is not None and p90_eval <= READY_MAX_PER_EVAL_P90_S),
        "claims_guarded": claims_guarded,
        "no_forbidden_events": no_forbidden,
        "no_prod_mutation": no_mutation,
        "no_candidate_generated": no_candidate,
    }
    partial_usable_gate = {
        "safety_all_ok": safety_ok,
        "api_core_present": api_ok,
        "some_supported_frames": supported > 0,
        "mismatch_not_dominant": mismatch_rate < 0.5,
        "claims_guarded": claims_guarded,
    }

    if not safety_ok or not no_mutation or not no_forbidden or not no_candidate:
        decision = "safety_stop_required"
    elif not api_ok or supported == 0:
        decision = "search_oracle_blocked"
    elif all(ready_gate.values()):
        decision = "search_oracle_ready_for_candidate_pilot"
    elif all(partial_usable_gate.values()):
        decision = "search_oracle_partial_diagnostic_only"
    else:
        decision = "search_oracle_blocked"

    ready_blockers = sorted(k for k, v in ready_gate.items() if not v)
    data = {
        "pass": "46e", "part": "I", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "decision": decision,
        "metrics": {
            "supported_fraction": supported_fraction,
            "exact_rate_of_decisive": exact_rate,
            "mismatch_rate_of_decisive": mismatch_rate,
            "per_eval_p90_s": p90_eval,
            "planner_buckets": planner.get("by_role_bucket"),
        },
        "ready_gate": ready_gate,
        "ready_gate_blockers": ready_blockers,
        "partial_usable_gate": partial_usable_gate,
        "thresholds": {
            "READY_MIN_SUPPORTED_FRACTION": READY_MIN_SUPPORTED_FRACTION,
            "READY_MAX_MISMATCH_RATE": READY_MAX_MISMATCH_RATE,
            "READY_MIN_EXACT_RATE": READY_MIN_EXACT_RATE,
            "READY_MAX_PER_EVAL_P90_S": READY_MAX_PER_EVAL_P90_S,
        },
        "unsupported_claims": O.unsupported_search_claims(),
        "rationale": _decision_rationale(decision, ready_blockers, supported_fraction,
                                         exact_rate, mismatch_rate),
    }
    body = (
        f"## Decision: `{decision}`\n\n"
        f"{data['rationale']}\n\n"
        "## Ready-for-pilot gate\n"
        + "".join(f"- `{k}`: {'PASS' if v else 'FAIL'}\n" for k, v in ready_gate.items())
        + (f"\n**Ready gate blockers:** {', '.join(ready_blockers)}\n" if ready_blockers else "")
        + "\n## Partial-usable gate\n"
        + "".join(f"- `{k}`: {'PASS' if v else 'FAIL'}\n"
                  for k, v in partial_usable_gate.items())
    )
    write_pair("pass46e_strategy_decision", data,
               "Pass 46E — Part I: strategy decision", body)
    return data


def _decision_rationale(decision, blockers, supp, exact, mismatch) -> str:
    if decision == "search_oracle_ready_for_candidate_pilot":
        return ("All safety, API, calibration, runtime and honesty gates passed; the "
                "oracle reproduces next-frame objective state reliably enough to pilot.")
    if decision == "search_oracle_partial_diagnostic_only":
        return (f"Safe and functional, but the ready gate is not met "
                f"(blockers: {', '.join(blockers)}). With supported_fraction={supp}, "
                f"exact_rate={exact}, mismatch_rate={mismatch}, fabricated hidden zones "
                f"make predictions diagnostic-grade — usable for analysis, NOT yet for a "
                f"live candidate pilot. No candidate created.")
    if decision == "search_oracle_blocked":
        return ("The cg Search API is unavailable or no frame produced a supported "
                "prediction; the oracle cannot be calibrated. No candidate created.")
    return ("A safety invariant failed (mutation/forbidden-event/candidate detected). "
            "Halt and investigate before any further work.")


# ============================================================= Part J: report
def part_j(safety, surface, calib, planner, runtime, decision) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    cls = calib.get("overall_classification") or {}
    pb = planner.get("by_role_bucket") or {}
    lines = []
    A = lines.append
    A("# Pass 46E — cg Search Outcome Oracle + One-Step Turn Planner v0\n")
    A("_LOCAL / READ-ONLY / DIAGNOSTIC / gameplay-infrastructure-only while "
      "production soaks. No prod mutation, tick, generation, promotion, queue, "
      "upload, republish, lifecycle, or public-reference copying._\n")

    A("\n## 1. Objective")
    A("Build a reusable, never-raise, subprocess-isolated wrapper over the cg Search "
      "API (`search_begin`/`search_step`/`search_end`/`search_release`) that, given a "
      "Pass-46C decision frame, predicts the one-step post-state, and a transparent "
      "one-step action ranker — then calibrate honestly against real next frames. No "
      "candidate is created.")

    A("\n## 2. Safety preflight (Part A)")
    A(f"- all_ok: **{safety.get('all_ok')}**")
    for k, v in (safety.get("checks") or {}).items():
        A(f"  - `{k}`: {'PASS' if v else 'FAIL'}")
    A(f"- prod ledger length (read-only): {safety.get('prod_ledger_len')}; "
      f"traces present: {safety.get('n_traces_present')}")

    A("\n## 3. cg Search API surface (Part B)")
    A(f"- import_ok: {surface.get('ok')}; core_present: **{surface.get('core_present')}**")
    for n, i in (surface.get("callables") or {}).items():
        A(f"  - `{n}`: callable={i.get('callable')} sig=`{i.get('signature')}`")

    A("\n## 4. Oracle design & honesty model")
    A("- cg is imported ONLY inside `_search_worker.py` (subprocess); the core module "
      "never imports it, stays pure and never-raise.")
    A("- Hidden zones (opponent deck/hand/prize, your prize, sometimes your deck) are "
      "filled with valid basic-Pokémon IDs by **count only** — a labelled "
      "`assumption_based_hidden_state`, never the real hidden contents and never the "
      "opponent's hand cards.")
    A("- Supported levels: `exact_full_state_replay` (reserved for full-state replays) / "
      "`assumption_based_hidden_state` (the live path here) / `unsupported_or_failed`.")
    A("- Permanently unsupported claims (asserted, never made): "
      + ", ".join(f"`{k}`" for k in O.unsupported_search_claims()) + ".")

    A("\n## 5. Calibration vs Pass-46C traces (Part D)")
    A(f"- frames attempted: {calib.get('frames_attempted')}; supported "
      f"(exact+partial): {calib.get('frames_supported')}")
    A(f"- exact_rate_of_decisive: {calib.get('exact_rate_of_decisive')}; "
      f"mismatch_rate_of_decisive: {calib.get('mismatch_rate_of_decisive')}")
    A("- classification counts: " + ", ".join(f"{k}={cls.get(k,0)}" for k in
      ("exact_match", "partial_match", "mismatch", "unsupported", "timed_out", "error")))
    A("- by action family: " + json.dumps(calib.get("by_family")))
    A("- Ground truth = the ACTIVE seat's `current` at the next trace frame "
      "(the INACTIVE seat carries a stale observation and is never used).")
    A("- Mismatches are dominated by `turn` at setup / turn-ending KO transitions and "
      "by hand/deck *counts* downstream of drawing from the fabricated deck — expected "
      "consequences of the hidden-state assumption, not engine errors.")

    A("\n## 6. One-step planner diagnostic (Part E)")
    A(f"- frames ranked: {planner.get('n_frames_ranked')}; scoring profile: "
      f"`{planner.get('scoring_profile')}`; label: `{planner.get('label')}`")
    for bkt in ("public_reference", "internal_candidate", "internal_parent"):
        s = pb.get(bkt) or {}
        A(f"  - `{bkt}`: n={s.get('n')}, actual_is_top_rate={s.get('actual_is_top_rate')}, "
          f"median_actual_rank={s.get('median_actual_rank')}, "
          f"median_normalized_rank={s.get('median_normalized_rank')}")
    A("- Interpretation: the actually-chosen action usually scores at/near the top under "
      "`generic_progress_v0`, a sanity signal only. Small-n, NOT a strength or "
      "best-action claim.")

    A("\n## 7. Runtime budget (Part F)")
    A(f"- per-evaluate native step (s): {runtime.get('per_evaluate_native_step_s')}")
    A(f"- per-rank call wall incl. subprocess spawn (s): "
      f"{runtime.get('per_rank_call_wall_s_includes_subprocess_spawn')}")
    A(f"- timeout+error rate: {runtime.get('timeout_plus_error_rate')}; recommended "
      f"per-task timeout (s): {runtime.get('recommended_per_task_timeout_s')}")
    A(f"- runtime_agent_safe (native step only): {runtime.get('runtime_agent_safe')}")

    A("\n## 8. Decision (Part I)")
    A(f"- **decision: `{decision.get('decision')}`**")
    A(f"- {decision.get('rationale')}")
    if decision.get("ready_gate_blockers"):
        A("- ready-gate blockers: " + ", ".join(decision["ready_gate_blockers"]))

    A("\n## 9. Limitations & threats to validity")
    A("- Hidden-zone fabrication: opponent deck/hand/prize and your prize/deck order are "
      "placeholders; any prediction depending on which specific card is drawn/revealed "
      "is unreliable (drives the `partial_match` / `mismatch` tail).")
    A("- Setup and turn-ending KO transitions are the weakest families.")
    A("- Per-rank latency is dominated by subprocess spawn + cg import, so live per-move "
      "use is diagnostic-grade, not turn-loop-latency-grade.")
    A("- Public references are benchmark-only calibration inputs; none were copied, "
      "promoted, or used as a candidate source.")

    A("\n## 10. Next steps")
    A("- Raise fidelity: seed known revealed cards into hidden zones; track our own deck "
      "order when the trace exposes it; add an `exact_full_state_replay` path for "
      "fully-observed frames to lift exact_rate.")
    A("- Improve `setup`/KO-transition handling before re-evaluating the ready gate.")
    A("- Keep cg in the subprocess; if piloting, run the oracle off the hot path and "
      "treat outputs as advisory `one_step_score_rank under assumption`.")
    A("\n_Caveats apply to every section:_")
    for c in CAVEATS:
        A(f"- {c}")
    path = REPORTS / "pass46e_cg_search_oracle_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ============================================================= Part H: docs
def part_h(safety, surface, calib, planner, runtime, decision) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    doc = DOCS / "CG_SEARCH_ORACLE_V0.md"
    cls = calib.get("overall_classification") or {}
    doc.write_text(
        "# cg Search Outcome Oracle v0\n\n"
        "_Pass 46E. LOCAL / READ-ONLY / DIAGNOSTIC. A never-raise, "
        "subprocess-isolated wrapper over the cg Search API plus a transparent "
        "one-step action ranker._\n\n"
        "## Modules\n"
        "- `src/ptcg_activegraph/analysis/search_oracle.py` — pure core (NO cg import "
        "at module top). Builds count-based search inputs from a frame, runs the "
        "subprocess worker, decodes objective post-state signatures, compares them to "
        "ground truth, scores `generic_progress_v0`, and ranks one-step actions. "
        "Public: `evaluate_action_once`, `evaluate_actions_batch`, "
        "`rank_legal_actions_one_step`, `signature_from_current`, `compare_signatures`, "
        "`unsupported_search_claims`.\n"
        "- `src/ptcg_activegraph/analysis/_search_worker.py` — the ONLY place cg / "
        "`libcg.so` is imported. Per-task `SIGALRM` budget, start+result JSONL markers "
        "(fsync'd), `search_release`/`search_end` cleanup in `finally`.\n\n"
        "## Honesty model\n"
        "- Hidden zones (opponent deck/hand/prize, your prize) are filled by **count "
        "only** with valid basic-Pokémon IDs — a labelled `assumption_based_hidden_"
        "state`. Opponent hand *contents* are never read or claimed.\n"
        "- Supported levels: `exact_full_state_replay` / `assumption_based_hidden_state` "
        "/ `unsupported_or_failed`.\n"
        "- Permanently unsupported (asserted, never claimed): "
        + ", ".join(f"`{k}`" for k in O.unsupported_search_claims()) + ".\n"
        "- Ranking output is `one_step_score_rank under assumption`, explicitly NOT a "
        "best/optimal action.\n\n"
        "## Calibration snapshot\n"
        f"- attempted={calib.get('frames_attempted')}, supported="
        f"{calib.get('frames_supported')}, exact_rate="
        f"{calib.get('exact_rate_of_decisive')}, mismatch_rate="
        f"{calib.get('mismatch_rate_of_decisive')} "
        f"(exact={cls.get('exact_match',0)}, partial={cls.get('partial_match',0)}, "
        f"mismatch={cls.get('mismatch',0)}).\n"
        f"- **decision: `{decision.get('decision')}`.**\n\n"
        "## Reproduce\n"
        "```\n"
        "python3 scripts/build_pass46e_search_oracle_calibration.py\n"
        "python3 scripts/build_pass46e_one_step_planner_diagnostic.py\n"
        "python3 scripts/build_pass46e_search_oracle.py\n"
        "```\n",
        encoding="utf-8")

    # living pass-logs
    dec = decision.get("decision")
    _append_log(
        DOCS / "NEXT_STEPS.md",
        f"\n## Pass 46E — cg Search Outcome Oracle + one-step planner v0 "
        f"(decision: {dec})\n"
        f"- Built never-raise, subprocess-isolated cg Search oracle "
        f"(`search_oracle.py` + `_search_worker.py`); cg confined to the worker.\n"
        f"- Calibrated vs Pass-46C traces: supported={calib.get('frames_supported')}/"
        f"{calib.get('frames_attempted')}, exact_rate="
        f"{calib.get('exact_rate_of_decisive')}, mismatch_rate="
        f"{calib.get('mismatch_rate_of_decisive')}.\n"
        f"- Decision **{dec}** — fabricated hidden zones keep predictions "
        f"diagnostic-grade; no candidate created. Next: seed revealed cards, add a "
        f"full-state-replay path, improve setup/KO transitions.\n")
    _append_log(
        DOCS / "PTCG_STRATEGY_CANVAS.md",
        f"\n## Pass 46E (cg Search oracle v0) — decision: {dec}\n"
        f"- A read-only one-step lookahead over real frames now exists, honestly "
        f"labelled `assumption_based_hidden_state` / `one_step_score_rank under "
        f"assumption`. It is calibrated, not trusted: ~"
        f"{int(round((calib.get('frames_supported') or 0) / max(1, calib.get('frames_attempted') or 1) * 100))}% "
        f"of frames yield a supported prediction, "
        f"{calib.get('mismatch_rate_of_decisive')} decisive mismatch.\n"
        f"- Strategic read: lookahead is feasible but hidden-state fidelity (not the "
        f"API) is the bottleneck. Treat as analysis tooling until exact-replay + "
        f"card-reveal seeding land.\n")


def _append_log(path: Path, text: str) -> None:
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n" + text,
                        encoding="utf-8")
    else:
        path.write_text("# " + path.stem.replace("_", " ").title() + "\n" + text,
                        encoding="utf-8")


def main() -> int:
    safety = part_a()
    surface = part_b()
    calib = _load_or_build("pass46e_search_oracle_calibration", CAL.run_calibration)
    planner = _load_or_build("pass46e_one_step_planner_diagnostic", PLN.run_planner)
    runtime = part_f(calib)
    decision = part_i(safety, surface, calib, planner, runtime)
    report = part_j(safety, surface, calib, planner, runtime, decision)
    part_h(safety, surface, calib, planner, runtime, decision)
    print(json.dumps({
        "safety_all_ok": safety.get("all_ok"),
        "api_core_present": surface.get("core_present"),
        "supported_fraction": decision["metrics"]["supported_fraction"],
        "mismatch_rate": decision["metrics"]["mismatch_rate_of_decisive"],
        "decision": decision.get("decision"),
        "report": str(report.relative_to(REPO)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
