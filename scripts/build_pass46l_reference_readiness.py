#!/usr/bin/env python3
"""PASS 46L (Part B0) — public-reference READINESS ping (benchmark-only, EXCLUDED from decisions).

A small FEASIBILITY probe run BEFORE committing to the full Part-H reference panel: confirm each
of the 5 public references (1) resolves to a present tarball, (2) passes the untrusted-tarball
member gate (regular files/dirs only, no abs paths, no '..', no links/devices), (3) extracts
cleanly, and (4) is RUNNABLE in-budget — a single hang-safe smoke game vs the EXISTING Pass-46J
candidate ``cg_typed_diamond_specialist_planner_v0`` completes without hanging the engine.

This is BENCHMARK-ONLY and EXCLUDED from every decision: references are NEVER source / parent /
candidate, never promoted / registered / uploaded, never a decision gate. The smoke games live
in their OWN no_upload ledger (data/experiments/pass46l_reference_readiness_games.jsonl), kept
entirely separate from any gating/attribution ledger. The smoke OUTCOME (win/loss/draw) is NOT
recorded as a result claim — only whether the reference RAN cleanly in budget. If a reference
cannot run, it is recorded and the pass proceeds with the runnable subset.

Reuses the import-once, hang-safe batch worker (HARD subprocess timeout reaps a native-C hang;
each game's result row is fsync'd, so a kill never loses a finished game). Writes
data/experiments/pass46l_reference_readiness.{json,md}. Exit 0 iff it resolves.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
SMOKE_LEDGER = EXP / "pass46l_reference_readiness_games.jsonl"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46l_ref_work"
WORKER = ROOT / "scripts" / "_pass46i_batch_worker.py"

SUBJECT_ID = "cg_typed_diamond_specialist_planner_v0"
SUBJECT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass46j"
                   / f"{SUBJECT_ID}.tar.gz")

# The 5 public references (benchmark-only). Resolved directly so this probe is independent
# of any not-yet-written 46L eval plan.
REF_IDS = [
    "public_ref_kiyotah_dragapult",
    "public_ref_kiyotah_iono",
    "public_ref_kiyotah_mega_abomasnow",
    "public_ref_kiyotah_mega_lucario",
    "public_ref_ryotasueyoshi_alakazam",
]


def ref_tarball(ref_id: str) -> Path:
    return ROOT / "data" / "reference_agents" / "raw_outputs" / ref_id / "submission.tar.gz"


def validate_tar_members(tarball: Path) -> tuple[bool, list]:
    """Untrusted-tarball gate: only regular files / dirs, no abs paths, no '..', no links."""
    reasons: list[str] = []
    try:
        with tarfile.open(tarball, "r:gz") as t:
            for m in t.getmembers():
                nm = m.name
                if nm.startswith("/") or ".." in Path(nm).parts:
                    reasons.append(f"path-traversal: {nm}")
                if m.issym() or m.islnk():
                    reasons.append(f"link member: {nm}")
                if m.ischr() or m.isblk() or m.isfifo() or m.isdev():
                    reasons.append(f"device/special member: {nm}")
                if not (m.isfile() or m.isdir()):
                    reasons.append(f"non-regular member: {nm}")
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"open_error: {exc}")
    return (len(reasons) == 0, reasons)


def safe_extract(tarball: Path, dest: Path) -> None:
    if (dest / "main.py").exists() and (dest / "deck.csv").exists():
        return  # idempotent
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                continue
            t.extract(m, dest)


def read_ledger() -> dict:
    """game_id -> result row (last one wins)."""
    out: dict[str, dict] = {}
    if SMOKE_LEDGER.exists():
        for line in SMOKE_LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("type") == "result":
                out[r.get("game_id")] = r
    return out


def spawn_worker(todo: list, budget: float) -> None:
    """HARD subprocess timeout reaps a native-C hang; finished games already fsync'd."""
    spec = EXP / "_pass46l_readiness_batch_spec.json"
    spec.write_text(json.dumps({"games": todo}), encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, str(WORKER), "--spec", str(spec),
             "--jsonl", str(SMOKE_LEDGER), "--budget-seconds", str(budget)],
            capture_output=True, text=True, timeout=budget + 20)
    except subprocess.TimeoutExpired:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=180.0)
    a = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)

    # Subject (owned candidate) — validate + extract (idempotent).
    subj_present = SUBJECT_TARBALL.exists()
    subj_ok, subj_reasons = (validate_tar_members(SUBJECT_TARBALL) if subj_present
                             else (False, ["tarball_missing"]))
    subj_dir = REF_WORK / SUBJECT_ID
    if subj_present and subj_ok:
        safe_extract(SUBJECT_TARBALL, subj_dir)
    subj_extracted = (subj_dir / "main.py").exists() and (subj_dir / "deck.csv").exists()

    # References — resolve, validate, extract.
    ref_status: dict[str, dict] = {}
    runnable_candidates: list[str] = []
    for rid in REF_IDS:
        tb = ref_tarball(rid)
        if not tb.exists():
            ref_status[rid] = {"present": False, "validated": False, "extracted": False,
                               "reason": "tarball_missing"}
            continue
        ok, reasons = validate_tar_members(tb)
        if not ok:
            ref_status[rid] = {"present": True, "validated": False, "extracted": False,
                               "reason": "unsafe_members", "detail": reasons[:5]}
            continue
        safe_extract(tb, REF_WORK / rid)
        extracted = (REF_WORK / rid / "main.py").exists() and (REF_WORK / rid / "deck.csv").exists()
        ref_status[rid] = {"present": True, "validated": True, "extracted": extracted,
                           "reason": "ok" if extracted else "extract_incomplete",
                           "tarball": str(tb.relative_to(ROOT))}
        if extracted:
            runnable_candidates.append(rid)

    def rel(p: Path) -> str:
        return str(p.relative_to(ROOT))

    # One hang-safe smoke game per extractable reference vs v0 (seats varied across refs).
    smoke_games = []
    if subj_extracted:
        for i, rid in enumerate(runnable_candidates):
            smoke_games.append({
                "game_id": f"readiness_smoke#{rid}", "panel_id": "readiness_smoke",
                "subject_id": SUBJECT_ID, "opponent_id": rid,
                "subject_dir": rel(subj_dir), "opponent_dir": rel(REF_WORK / rid),
                "subject_seat": i % 2})
    smoke_ids = {g["game_id"] for g in smoke_games}

    t0 = time.time()
    no_progress = 0
    while smoke_games:
        done = set(read_ledger())
        todo = [g for g in smoke_games if g["game_id"] not in done]
        if not todo:
            break
        remaining = a.budget_seconds - (time.time() - t0)
        if remaining < 15:
            break
        before = len(done)
        spawn_worker(todo, min(120.0, remaining - 10))
        after = len(read_ledger())
        if after <= before:
            no_progress += 1
            if no_progress >= 2:
                break
        else:
            no_progress = 0

    results = read_ledger()

    # Decide readiness per ref: extracted AND a result row exists AND the engine did not hang
    # (no soft_timeout / worker error). The win/loss OUTCOME is intentionally NOT a claim here.
    ready: list[str] = []
    not_ready: dict[str, str] = {}
    per_ref: dict[str, dict] = {}
    for rid in REF_IDS:
        st = ref_status[rid]
        gid = f"readiness_smoke#{rid}"
        r = results.get(gid)
        ran_clean = bool(r is not None and not r.get("error")
                         and r.get("subject_status") not in ("TIMEOUT", "ERROR")
                         and r.get("opponent_status") not in ("TIMEOUT", "ERROR"))
        per_ref[rid] = {
            "present": st.get("present"), "validated": st.get("validated"),
            "extracted": st.get("extracted"), "smoke_ran": r is not None,
            "smoke_clean": ran_clean,
            "wall_s": (r or {}).get("wall_s"), "steps": (r or {}).get("steps"),
            "invalid": (r or {}).get("invalid"), "error": (r or {}).get("error"),
            "reason": st.get("reason"),
        }
        if st.get("validated") and st.get("extracted") and ran_clean:
            ready.append(rid)
        else:
            not_ready[rid] = (st.get("reason") if not st.get("extracted")
                              else ("no_result_in_budget" if r is None
                                    else (r.get("error") or "engine_unclean")))

    all_present = all(ref_status[r].get("present") for r in REF_IDS)
    all_ready = ready == REF_IDS
    # Resolving is a valid outcome even with a partial runnable subset (charter: proceed with
    # the runnable subset and record the rest). The pass only STOPS if the subject itself or
    # ALL references are unusable, leaving nothing to benchmark.
    resolved_ok = subj_extracted and len(ready) >= 1

    data = {
        "pass": "46l", "part": "B0", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "benchmark_only": True, "is_decision_gate": False, "excluded_from_decisions": True,
        "outcome_is_a_claim": False,
        "subject": SUBJECT_ID,
        "subject_tarball": str(SUBJECT_TARBALL.relative_to(ROOT)),
        "subject_present": subj_present, "subject_validated": subj_ok,
        "subject_validation_reasons": subj_reasons if not subj_ok else [],
        "subject_extracted": subj_extracted,
        "references_requested": REF_IDS,
        "reference_status": ref_status,
        "per_reference": per_ref,
        "ready_opponents": ready,
        "not_ready": not_ready,
        "all_references_present": all_present,
        "all_references_ready": all_ready,
        "smoke_ledger": str(SMOKE_LEDGER.relative_to(ROOT)),
        "work_dir": str(REF_WORK.relative_to(ROOT)),
        "caveat": ("Feasibility probe only. References are benchmark-only opponents with "
                   "DIFFERENT decks — never source/parent/candidate, never a decision gate. "
                   "The smoke OUTCOME is NOT a result claim; only whether each reference RAN "
                   "cleanly in budget. The full Part-H reference panel uses ready_opponents."),
        "resolved_ok": resolved_ok,
        "all_ok": resolved_ok,
    }
    (EXP / "pass46l_reference_readiness.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46L (Part B0) — public-reference readiness ping (benchmark-only)", "",
        "> **Feasibility probe. Benchmark-only. EXCLUDED from every decision.** Confirms each "
        "public reference resolves, passes the untrusted-tarball member gate, extracts, and "
        "RUNS one hang-safe smoke game vs the existing v0 in budget. References are NEVER "
        "source/parent/candidate and NEVER a decision gate; the smoke OUTCOME is NOT a result "
        "claim — only whether the reference ran cleanly. The full Part-H reference panel uses "
        "`ready_opponents`.", "",
        f"- subject (v0): `{SUBJECT_ID}` present={subj_present}, validated={subj_ok}, "
        f"extracted={subj_extracted}",
        f"- references requested: {REF_IDS}",
        f"- **ready_opponents:** {ready or 'none'}",
        f"- not ready: {not_ready or 'none'}", "",
        "## Per-reference readiness",
        "| reference | present | validated | extracted | smoke ran | clean | wall_s | steps | reason |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|",
    ]
    for rid in REF_IDS:
        p = per_ref[rid]
        md.append(f"| `{rid}` | {p['present']} | {p['validated']} | {p['extracted']} | "
                  f"{p['smoke_ran']} | {p['smoke_clean']} | {p['wall_s']} | {p['steps']} | "
                  f"{p['reason']} |")
    md += ["",
           f"- all references present: **{all_present}** | all references ready: "
           f"**{all_ready}**",
           f"- resolved_ok (subject extracted AND \u22651 ready ref): **{resolved_ok}**", "",
           f"_{data['caveat']}_"]
    (EXP / "pass46l_reference_readiness.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": resolved_ok, "ready_opponents": ready,
                      "not_ready": not_ready, "all_references_ready": all_ready,
                      "subject_extracted": subj_extracted}, indent=2))
    return 0 if resolved_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
