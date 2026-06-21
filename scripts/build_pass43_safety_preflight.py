#!/usr/bin/env python3
"""Pass 43 (Part A) — production registration + promotion-gate safety preflight (STOP-GATE).

OPS / verify-only STOP-GATE. Re-confirms, WITHOUT mutating anything, the hard
invariants before the Pass 43 work (make the 3 Pass-42 internal *probation*
candidates real to the production scheduled daemon IF SAFE, and install the
internal Promotion Gate v1 in dry-run). This is NOT a Kaggle
upload/submission/promotion pass:

  1. root ``main.py``/``deck.csv`` byte-identical to the frozen v1 baseline
     (data/baselines/v1_kaggle_349_8), both before AND after a verify run;
  2. ``scripts/package_submission.py --verify-only`` passes and mutates nothing;
  3. auto-submit is OFF: config.auto_submit is False AND ``assert_no_auto_submit``
     does not raise for the live config — with a positive control proving a
     truthy config WOULD be refused;
  4. ``.replit [deployment]`` is the bounded *scheduled worker* pointing at
     scripts/tournament_deployment_tick.py --production (NOT root main.py);
  5. ``scripts/check_tournament_health.py --mode prod`` is HEALTHY (0 hard fails);
  6. the Pass 40 public-reference manifest exists and all five materialized
     reference agents still hash-match (tarball + main.py + deck.csv + cg/ SDK);
  7. references are benchmark-only and absent from candidate_pool.json, the main
     scheduler queue, and probation/promotion lineage (zero leakage);
  8. no forbidden upload/submit/queue/promotion events and no event with
     no_upload=false in the local main + benchmark ledgers;
  9. the 3 Pass-42 generated candidates are present and still ``probation``
     (informational expected state for this pass; never promoted).

Writes data/experiments/pass43_safety_preflight.{json,md} (and, via the health
checker, pass43_tournament_health.{json,md}). Exit nonzero if any hard check
fails. NO upload, NO submit, NO push, NO root/tarball mutation, NO registration,
NO promotion. Never starts the root 'Start application' workflow.
"""
from __future__ import annotations

import filecmp
import hashlib
import json
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament import benchmark as B  # noqa: E402
from ptcg_activegraph.tournament.config import (  # noqa: E402
    TournamentConfig,
    load_config,
)
from ptcg_activegraph.tournament.ledger import TournamentLedger  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402
from ptcg_activegraph.tournament.storage import (  # noqa: E402
    AutoSubmitRefusedError,
    assert_no_auto_submit,
)

BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"
MANIFEST = REPO / "data" / "reference_agents" / "reference_agent_manifest.json"
MAIN_EVENTS = REPO / "data" / "tournament" / "events.jsonl"
BENCH_EVENTS = REPO / "data" / "tournament" / "benchmark" / "benchmark_events.jsonl"
POOL_PATH = REPO / "data" / "tournament" / "candidate_pool.json"
SCHED_QUEUE = REPO / "data" / "tournament" / "projections" / "scheduler_queue.json"
GEN_MANIFEST = REPO / "data" / "experiments" / "pass42_generated_candidates_manifest.json"
EXTERNAL_REFERENCE_STATUS = "external_reference"
# Events this pass must NEVER produce (probation registration + promotion gate;
# no promotion unless strict gates pass, no submission-queue/upload mutation).
NEVER_EMIT_EVENT_TYPES = {"SubmissionUploaded", "KaggleScoreUpdated",
                          "CandidatePromoted", "SubmissionQueued"}
_SDK_MEMBERS = {"cg/__init__.py", "cg/api.py", "cg/game.py", "cg/sim.py",
                "cg/utils.py", "cg/libcg.so"}
PROBATION_STATUS = "probation"
PASS42_GENERATED_IDS = (
    "generated_diamond_diamondtoolbox_eratio_v1",
    "generated_dragapult_leaguedragapul_bdens_v1",
    "generated_lightning_monolightningm_dsratio_v1",
)


def _cmp(name: str) -> bool | None:
    root_f, base_f = REPO / name, BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return None
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return None


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _check_replit_deployment() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    dep = data.get("deployment", {}) or {}
    run = dep.get("run", []) or []
    run_str = " ".join(str(x) for x in run)
    checks = {
        "deployment_target_scheduled": dep.get("deploymentTarget") == "scheduled",
        "run_is_deployment_tick": "scripts/tournament_deployment_tick.py" in run_str,
        "run_not_root_main": "main.py" not in run,
        "run_has_production": "--production" in run,
    }
    return {"deploymentTarget": dep.get("deploymentTarget"), "run": run,
            "checks": checks, "all_ok": all(checks.values())}


def _check_start_application_workflow() -> dict:
    data = tomllib.loads((REPO / ".replit").read_text(encoding="utf-8"))
    found = None
    for wf in data.get("workflows", {}).get("workflow", []) or []:
        if wf.get("name") == "Start application":
            tasks = wf.get("tasks", []) or []
            found = " ".join(str(t.get("args", "")) for t in tasks)
    is_kaggle_entrypoint = found is not None and "main.py" in found
    return {"workflow_args": found,
            "is_frozen_kaggle_entrypoint": is_kaggle_entrypoint,
            "started_here": False, "not_started_is_expected": True,
            "all_ok": is_kaggle_entrypoint}


def _check_auto_submit() -> dict:
    """auto-submit OFF for live config + positive control that truthy is refused."""
    cfg = load_config()
    config_off = cfg.auto_submit is False
    live_ok = True
    live_err = None
    try:
        assert_no_auto_submit(cfg)
    except AutoSubmitRefusedError as exc:
        live_ok = False
        live_err = str(exc)
    # Positive control: a truthy config MUST be refused (proves the guard works).
    control_refused = False
    try:
        assert_no_auto_submit(TournamentConfig(auto_submit=True))
    except AutoSubmitRefusedError:
        control_refused = True
    checks = {
        "config_auto_submit_off": config_off,
        "live_config_not_refused": live_ok,
        "truthy_config_refused_control": control_refused,
    }
    return {"config_auto_submit": cfg.auto_submit, "live_refused_error": live_err,
            "checks": checks, "all_ok": all(checks.values())}


def _run_prod_health(reuse: bool = False) -> dict:
    """Run (or reuse) the ``--mode prod`` tournament health check.

    The prod check reads the production Object Storage snapshot and can take ~70s;
    ``reuse=True`` consumes an already-written pass43_tournament_health.json so the
    full preflight fits inside a single bounded run. Reuse is honest — the JSON is
    the real prod health artifact and the markdown notes it was reused.
    """
    out_json = EXP / "pass43_tournament_health.json"
    out_md = EXP / "pass43_tournament_health.md"
    rc = 0
    reused = False
    tail: list[str] = []
    if reuse and out_json.is_file():
        reused = True
        tail = ["(reused existing pass43_tournament_health.json)"]
    else:
        try:
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "check_tournament_health.py"),
                 "--mode", "prod", "--out-json", str(out_json),
                 "--out-md", str(out_md)],
                capture_output=True, text=True, cwd=str(REPO), timeout=240)
            rc = proc.returncode
            tail = proc.stdout.strip().splitlines()[-6:]
        except Exception as exc:  # noqa: BLE001
            rc, tail = -1, [f"health check raised: {exc!r}"]
    parsed = {}
    try:
        parsed = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        parsed = {}
    return {
        "returncode": rc,
        "reused": reused,
        "healthy": bool(parsed.get("healthy")),
        "source": parsed.get("mode"),
        "elapsed_s": parsed.get("elapsed_s"),
        "hard_failures": parsed.get("hard_failures", []),
        "warnings": parsed.get("warnings", []),
        "stdout_tail": tail,
        "out_json": str(out_json.relative_to(REPO)),
        "out_md": str(out_md.relative_to(REPO)),
    }


def _check_reference_manifest() -> dict:
    """Manifest exists and all five reference agents hash-match (immutable)."""
    if not MANIFEST.is_file():
        return {"manifest_exists": False, "all_match": False, "agents": []}
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    agents = raw.get("agents", [])
    out_agents = []
    all_match = True
    for a in agents:
        aid = a.get("agent_id")
        tb = REPO / a.get("tarball", "")
        rec = {"agent_id": aid, "tarball": a.get("tarball", ""),
               "tarball_exists": tb.is_file()}
        tar_ok = main_ok = deck_ok = sdk_ok = False
        if tb.is_file():
            tar_ok = _sha256_file(tb) == a.get("tarball_sha256")
            try:
                with tarfile.open(tb) as t:
                    names = set(t.getnames())
                    sdk_ok = _SDK_MEMBERS.issubset(names)
                    mf = t.extractfile("main.py")
                    df = t.extractfile("deck.csv")
                    if mf is not None:
                        main_ok = _sha256_bytes(mf.read()) == a.get("main_py_sha256")
                    if df is not None:
                        deck_ok = _sha256_bytes(df.read()) == a.get("deck_csv_sha256")
            except Exception as exc:  # noqa: BLE001
                rec["error"] = repr(exc)
        rec.update({"tarball_sha256_match": tar_ok, "main_py_sha256_match": main_ok,
                    "deck_csv_sha256_match": deck_ok, "cg_sdk_members_present": sdk_ok})
        agent_match = bool(rec["tarball_exists"] and tar_ok and main_ok and deck_ok
                           and sdk_ok)
        rec["hash_match"] = agent_match
        all_match = all_match and agent_match
        out_agents.append(rec)
    return {"manifest_exists": True,
            "agents_total": raw.get("agents_total"),
            "agents_built": raw.get("agents_built"),
            "all_built": bool(raw.get("all_built")),
            "all_match": bool(all_match and len(out_agents) == 5),
            "agents": out_agents}


def _check_reference_absence(ref_ids: set[str]) -> dict:
    """References benchmark-only: absent from pool, scheduler queue, and lineage."""
    pool = CandidatePool.load(POOL_PATH) if POOL_PATH.is_file() else CandidatePool()
    pool_ids = {c.candidate_id for c in pool.candidates}
    pool_statuses = {c.status for c in pool.candidates}
    # Scheduler queue: no reference id may appear as a scheduled participant.
    sched_ref_hits: list[str] = []
    if SCHED_QUEUE.is_file():
        try:
            qtext = SCHED_QUEUE.read_text(encoding="utf-8")
            for rid in ref_ids:
                if rid and rid in qtext:
                    sched_ref_hits.append(rid)
        except Exception:  # noqa: BLE001
            sched_ref_hits = []
    # Lineage: no candidate may have a public reference as parent.
    lineage_ref_parents = sorted(
        c.candidate_id for c in pool.candidates
        if getattr(c, "parent_candidate_id", "") in ref_ids
    )
    checks = {
        "no_reference_id_in_pool": not (ref_ids & pool_ids),
        "no_external_reference_status_in_pool":
            EXTERNAL_REFERENCE_STATUS not in pool_statuses,
        "no_reference_in_scheduler_queue": not sched_ref_hits,
        "no_reference_parent_in_lineage": not lineage_ref_parents,
    }
    leak = {}
    try:
        main_events = TournamentLedger(MAIN_EVENTS).load() if MAIN_EVENTS.is_file() else []
        opponents = B.load_opponents(include_optional=True)
        leak = B.assert_zero_leakage(pool, main_events, opponents)
    except Exception as exc:  # noqa: BLE001
        leak = {"zero_leakage": False, "error": repr(exc)}
    checks["main_ledger_zero_leakage"] = bool(leak.get("zero_leakage"))
    return {"checks": checks, "pool_candidate_count": len(pool_ids),
            "scheduler_reference_hits": sched_ref_hits,
            "lineage_reference_parents": lineage_ref_parents,
            "zero_leakage_detail": leak, "all_ok": all(checks.values())}


def _scan_ledger_events() -> dict:
    """No forbidden upload/submit/promote/queue events; none with no_upload=false."""
    forbidden = 0
    no_upload_false = 0
    scanned = 0
    per_file = {}
    for label, path in (("main", MAIN_EVENTS), ("benchmark", BENCH_EVENTS)):
        f_forbidden = f_nuf = f_count = 0
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                f_count += 1
                et = e.get("event_type") or e.get("type")
                if et in NEVER_EMIT_EVENT_TYPES:
                    f_forbidden += 1
                payload = e.get("payload") or {}
                if payload.get("no_upload") is False:
                    f_nuf += 1
        per_file[label] = {"events": f_count, "forbidden": f_forbidden,
                           "no_upload_false": f_nuf}
        forbidden += f_forbidden
        no_upload_false += f_nuf
        scanned += f_count
    checks = {"no_forbidden_events": forbidden == 0,
              "no_no_upload_false_events": no_upload_false == 0}
    return {"events_scanned": scanned, "forbidden_total": forbidden,
            "no_upload_false_total": no_upload_false, "per_file": per_file,
            "checks": checks, "all_ok": all(checks.values())}


def _check_pass42_probation_present() -> dict:
    """Confirm the 3 Pass-42 generated candidates exist and are still probation.

    Informational expected state for this pass (registration/promotion-gate).
    A generated candidate that is NOT probation here would mean an unexpected
    earlier promotion — surfaced as a hard fail.
    """
    pool = CandidatePool.load(POOL_PATH) if POOL_PATH.is_file() else CandidatePool()
    by_id = {c.candidate_id: c for c in pool.candidates}
    rows = []
    all_probation = True
    for cid in PASS42_GENERATED_IDS:
        c = by_id.get(cid)
        present = c is not None
        status = c.status if c is not None else None
        is_probation = status == PROBATION_STATUS
        all_probation = all_probation and present and is_probation
        rows.append({"candidate_id": cid, "present": present, "status": status,
                     "is_probation": is_probation,
                     "tarball_path": (c.tarball_path if c is not None else None),
                     "parent_candidate_id": (
                         getattr(c, "parent_candidate_id", None)
                         if c is not None else None)})
    return {"candidates": rows,
            "all_present_and_probation": all_probation,
            "expected_count": len(PASS42_GENERATED_IDS)}


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    reuse_health = "--reuse-health" in sys.argv[1:]

    main_ok = _cmp("main.py")
    deck_ok = _cmp("deck.csv")

    try:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "package_submission.py"),
             "--verify-only"],
            capture_output=True, text=True, cwd=str(REPO), timeout=120)
        verify_passed = proc.returncode == 0
        verify_rc = proc.returncode
        verify_tail = proc.stdout.strip().splitlines()[-10:]
    except Exception as exc:  # noqa: BLE001
        verify_passed, verify_rc, verify_tail = False, -1, [f"raised: {exc!r}"]

    main_ok_after = _cmp("main.py")
    deck_ok_after = _cmp("deck.csv")
    root_unchanged = (main_ok is True and deck_ok is True
                      and main_ok_after is True and deck_ok_after is True)

    deploy = _check_replit_deployment()
    start_wf = _check_start_application_workflow()
    auto_submit = _check_auto_submit()
    health = _run_prod_health(reuse=reuse_health)
    refman = _check_reference_manifest()
    ref_ids = {a.get("agent_id") for a in
               (json.loads(MANIFEST.read_text(encoding="utf-8")).get("agents", [])
                if MANIFEST.is_file() else [])}
    ref_absence = _check_reference_absence(ref_ids)
    ledger_scan = _scan_ledger_events()
    pass42 = _check_pass42_probation_present()

    config_ok = (deploy["all_ok"] and start_wf["all_ok"] and auto_submit["all_ok"])
    safe = (root_unchanged and verify_passed and config_ok and health["healthy"]
            and refman["all_match"] and ref_absence["all_ok"]
            and ledger_scan["all_ok"]
            and pass42["all_present_and_probation"])

    payload = {
        "pass": "43", "part": "A", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "production_registration_performed_here": False, "tarball_mutation": False,
        "promotion_performed": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_py_unchanged": main_ok, "root_deck_csv_unchanged": deck_ok,
        "root_main_py_unchanged_after_verify": main_ok_after,
        "root_deck_csv_unchanged_after_verify": deck_ok_after,
        "root_unchanged": root_unchanged,
        "package_verify_only_passed": verify_passed,
        "package_verify_returncode": verify_rc,
        "package_verify_stdout_tail": verify_tail,
        "deployment_config": deploy,
        "start_application_workflow": start_wf,
        "auto_submit_check": auto_submit,
        "prod_health": health,
        "reference_manifest": refman,
        "reference_absence": ref_absence,
        "ledger_event_scan": ledger_scan,
        "pass42_probation_present": pass42,
        "config_ok": config_ok,
        "preflight_safe": safe,
        "stop_required": not safe,
    }
    (EXP / "pass43_safety_preflight.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    dc = deploy["checks"]
    ac = auto_submit["checks"]
    rac = ref_absence["checks"]
    lsc = ledger_scan["checks"]
    md = [
        "# Pass 43 — Production registration + promotion-gate safety preflight (Part A)", "",
        "> OPS / verify-only STOP-GATE. Pass 43 makes the 3 Pass-42 internal "
        "`probation` candidates real to the production scheduled daemon IF SAFE, "
        "and installs Promotion Gate v1 (dry-run). NO upload, NO submit, NO "
        "auto-submit, NO push, NO root/tarball mutation, NO new candidate "
        "generation, NO promotion unless strict internal evidence gates pass. "
        "Public references are benchmark-only diagnostics — never our candidates, "
        "lineage parents, scheduler members, queued, or promoted. Internal "
        "diagnostics; NOT a Kaggle leaderboard or strength claim.", "",
        "## 1. Root immutability",
        f"- root main.py byte-identical to baseline: **{yn(main_ok)}**",
        f"- root deck.csv byte-identical to baseline: **{yn(deck_ok)}**",
        f"- package verify-only passed: **{yn(verify_passed)}** (rc {verify_rc})",
        f"- root unchanged AFTER verify-only: main=**{yn(main_ok_after)}** "
        f"deck=**{yn(deck_ok_after)}**", "",
        "## 2. Scheduled deployment config (.replit [deployment])",
        f"- deploymentTarget == scheduled: **{yn(dc['deployment_target_scheduled'])}**",
        f"- run is the deployment tick (not root main.py): "
        f"**{yn(dc['run_is_deployment_tick'] and dc['run_not_root_main'])}**",
        f"- run has --production: **{yn(dc['run_has_production'])}**", "",
        "## 3. Auto-submit OFF (with positive control)",
        f"- config.auto_submit is False: **{yn(ac['config_auto_submit_off'])}**",
        f"- live config not refused by assert_no_auto_submit: "
        f"**{yn(ac['live_config_not_refused'])}**",
        f"- positive control (truthy config IS refused): "
        f"**{yn(ac['truthy_config_refused_control'])}**", "",
        "## 4. Root 'Start application' workflow",
        f"- still the frozen Kaggle entrypoint (python3 main.py): "
        f"**{yn(start_wf['is_frozen_kaggle_entrypoint'])}**",
        "- not-started is EXPECTED (Kaggle agent entrypoint, not a server); "
        "**never** started by this pass.", "",
        "## 5. Production tournament health (--mode prod, read-only)",
        f"- source: `{health['source']}` (reused artifact: {yn(health['reused'])}; "
        f"elapsed {health.get('elapsed_s')}s)",
        f"- healthy (0 hard failures): **{yn(health['healthy'])}**",
        f"- hard failures: {health['hard_failures'] or 'none'}",
        f"- warnings: {health['warnings'] or 'none'}", "",
        "## 6. Pass 40 public-reference manifest hash-match",
        f"- manifest exists: **{yn(refman['manifest_exists'])}**  "
        f"all 5 hash-match: **{yn(refman['all_match'])}**",
    ]
    for a in refman.get("agents", []):
        md.append(
            f"  - `{a['agent_id']}`: tarball={yn(a.get('tarball_sha256_match'))} "
            f"main.py={yn(a.get('main_py_sha256_match'))} "
            f"deck.csv={yn(a.get('deck_csv_sha256_match'))} "
            f"cg/={yn(a.get('cg_sdk_members_present'))}")
    md += [
        "", "## 7. References benchmark-only (pool / scheduler / lineage absence)",
        f"- no reference id in pool: **{yn(rac['no_reference_id_in_pool'])}**",
        f"- no external_reference status in pool: "
        f"**{yn(rac['no_external_reference_status_in_pool'])}**",
        f"- no reference in scheduler queue: "
        f"**{yn(rac['no_reference_in_scheduler_queue'])}** "
        f"(hits: {ref_absence['scheduler_reference_hits'] or 'none'})",
        f"- no reference parent in lineage: "
        f"**{yn(rac['no_reference_parent_in_lineage'])}** "
        f"(hits: {ref_absence['lineage_reference_parents'] or 'none'})",
        f"- main-ledger zero leakage: **{yn(rac['main_ledger_zero_leakage'])}** "
        f"(pool candidates: {ref_absence['pool_candidate_count']})", "",
        "## 8. Forbidden / no_upload event audit (local ledgers)",
        f"- no upload/submit/promote/queue events: "
        f"**{yn(lsc['no_forbidden_events'])}** "
        f"(found {ledger_scan['forbidden_total']})",
        f"- no event with no_upload=false: **{yn(lsc['no_no_upload_false_events'])}** "
        f"(found {ledger_scan['no_upload_false_total']}; "
        f"scanned {ledger_scan['events_scanned']})", "",
        "## 9. Pass-42 probation candidates present (informational/expected)",
        f"- all 3 present and still probation: "
        f"**{yn(pass42['all_present_and_probation'])}**",
    ]
    for r in pass42["candidates"]:
        md.append(
            f"  - `{r['candidate_id']}`: present={yn(r['present'])} "
            f"status={r['status']} probation={yn(r['is_probation'])}")
    md += [
        "", "## Verdict",
        f"- preflight safe: **{yn(safe)}**",
        f"- **stop required: {yn(not safe)}**", "",
        "## package verify-only output (tail)", "```", *verify_tail, "```",
    ]
    (EXP / "pass43_safety_preflight.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass43 preflight: safe={safe} root_unchanged={root_unchanged} "
          f"verify={verify_passed} config_ok={config_ok} "
          f"auto_submit_off={auto_submit['all_ok']} healthy={health['healthy']} "
          f"refs_match={refman['all_match']} ref_absence={ref_absence['all_ok']} "
          f"ledger_clean={ledger_scan['all_ok']} "
          f"pass42_probation={pass42['all_present_and_probation']} "
          f"stop_required={not safe}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
