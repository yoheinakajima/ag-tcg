#!/usr/bin/env python3
"""PASS 46I (Part F) — public-reference CONTEXT (benchmark-only, excluded from decisions).

Plays a small, seat-balanced benchmark panel of the option-value treatment
(`cg_typed_water_option_value_v1`) against two EXISTING public-reference agents, purely to
situate the candidate against outside policies. This is CONTEXT ONLY:

  * references are BENCHMARK-ONLY — never promoted, never registered, never uploaded;
  * NO parity / "beats the field" claim is made or implied;
  * these numbers are EXCLUDED from every gating panel and from the Part-G decision;
  * results live in their OWN no_upload ledger (data/experiments/pass46i_reference_games.jsonl)
    kept entirely separate from the gating ledger, so reference games can never leak into the
    attribution / practical statistics.

The external reference tarballs are UNTRUSTED, so every member is validated (regular files
only, no absolute paths, no parent-dir traversal, no symlinks/links/devices) BEFORE
extraction; a tarball that fails validation is skipped and reported, never extracted.

Reuses the same import-once batch worker as Part D. Resumable + hang-safe. Writes
data/experiments/pass46i_reference_context.{json,md}. Exit 0 iff it resolves (even with zero
safe refs — absence of context is itself a valid, reported outcome).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
PLAN_JSON = EXP / "pass46i_eval_plan.json"
REF_LEDGER = EXP / "pass46i_reference_games.jsonl"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46i_ref_work"
WORKER = ROOT / "scripts" / "_pass46i_batch_worker.py"
SUBJECT = "cg_typed_water_option_value_v1"
PER_OPP = 14          # hard cap of games per reference opponent
WILSON_Z = 1.96


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


def wilson(k: int, n: int, z: float = WILSON_Z) -> tuple:
    if n == 0:
        return (None, None, None)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(p, 4), round(center - half, 4), round(center + half, 4))


def read_ledger() -> tuple[list, set]:
    results, started = [], set()
    if REF_LEDGER.exists():
        for line in REF_LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("type") == "result":
                results.append(r)
            elif r.get("type") == "start":
                started.add(r.get("game_id"))
    done = {r["game_id"] for r in results}
    return results, started - done


def spawn_worker(todo: list, budget: float) -> None:
    spec = EXP / "_pass46i_ref_batch_spec.json"
    spec.write_text(json.dumps({"games": todo}), encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, str(WORKER), "--spec", str(spec),
             "--jsonl", str(REF_LEDGER), "--budget-seconds", str(budget)],
            capture_output=True, text=True, timeout=budget + 15)
    except subprocess.TimeoutExpired:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=55.0)
    a = ap.parse_args()

    if not PLAN_JSON.exists():
        raise SystemExit(f"missing eval plan: {PLAN_JSON}")
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))

    ctx_specs = plan.get("optional_reference_context") or []
    opponents = []
    for spec in ctx_specs:
        for opp in spec.get("opponents", []):
            if opp not in opponents:
                opponents.append(opp)
    refs_avail = {r["ref_id"]: r for r in plan.get("references_available", [])}

    # Subject: reuse the Part-D extraction if present, else extract into the ref work dir.
    subj_src = ROOT / "data" / "tournament" / "benchmark" / "_pass46i_work" / SUBJECT
    subj_dir = subj_src if (subj_src / "main.py").exists() else (REF_WORK / SUBJECT)
    if subj_dir == (REF_WORK / SUBJECT):
        safe_extract(ROOT / plan["participants"][SUBJECT]["tarball"], subj_dir)

    ref_status = {}
    safe_opponents = []
    for opp in opponents:
        meta = refs_avail.get(opp)
        if not meta or not (ROOT / meta["tarball"]).exists():
            ref_status[opp] = {"usable": False, "reason": "tarball_missing"}
            continue
        ok, reasons = validate_tar_members(ROOT / meta["tarball"])
        if not ok:
            ref_status[opp] = {"usable": False, "reason": "unsafe_members",
                               "detail": reasons[:5]}
            continue
        safe_extract(ROOT / meta["tarball"], REF_WORK / opp)
        ref_status[opp] = {"usable": True, "reason": "ok"}
        safe_opponents.append(opp)

    # Deterministic, resumable, seat-balanced plan.
    def rel(p: Path) -> str:
        return str(p.relative_to(ROOT))

    plan_games = []
    for opp in safe_opponents:
        for i in range(PER_OPP):
            plan_games.append({
                "game_id": f"ov_vs_refs#{opp}#g{i:03d}", "panel_id": "ov_vs_refs",
                "subject_id": SUBJECT, "opponent_id": opp,
                "subject_dir": rel(subj_dir), "opponent_dir": rel(REF_WORK / opp),
                "subject_seat": i % 2})
    plan_ids = {g["game_id"] for g in plan_games}

    t0 = time.time()
    no_progress = 0
    while plan_games:
        results, orphans = read_ledger()
        done = {r["game_id"] for r in results}
        todo = [g for g in plan_games
                if g["game_id"] not in done and g["game_id"] not in orphans]
        if not todo:
            break
        remaining = a.budget_seconds - (time.time() - t0)
        if remaining < 12:
            break
        before = len(results)
        spawn_worker(todo, min(45.0, remaining - 8))
        after, _ = read_ledger()
        if len(after) <= before:
            no_progress += 1
            if no_progress >= 2:
                break
        else:
            no_progress = 0

    # Summarise only THIS pass's planned reference games.
    results, _ = read_ledger()
    by_opp: dict[str, dict] = {}
    for r in results:
        if r.get("game_id") not in plan_ids or r.get("panel_id") != "ov_vs_refs":
            continue
        opp = r.get("opponent_id")
        d = by_opp.setdefault(opp, {"decisive": 0, "wins": 0, "invalid": 0, "total": 0})
        d["total"] += 1
        if r.get("invalid"):
            d["invalid"] += 1
        elif r.get("decisive"):
            d["decisive"] += 1
            if r.get("winner") == "subject":
                d["wins"] += 1

    per_opp = {}
    tot_dec = tot_win = tot_inv = 0
    for opp in safe_opponents:
        d = by_opp.get(opp, {"decisive": 0, "wins": 0, "invalid": 0, "total": 0})
        p, lo, hi = wilson(d["wins"], d["decisive"])
        per_opp[opp] = {"decisive": d["decisive"], "wins": d["wins"],
                        "invalid": d["invalid"], "total": d["total"],
                        "win_rate": p, "wilson_low": lo, "wilson_high": hi}
        tot_dec += d["decisive"]
        tot_win += d["wins"]
        tot_inv += d["invalid"]
    cp, clo, chi = wilson(tot_win, tot_dec)
    combined = {"decisive": tot_dec, "wins": tot_win, "invalid": tot_inv,
                "win_rate": cp, "wilson_low": clo, "wilson_high": chi}

    data = {
        "pass": "46i", "part": "F", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "benchmark_only": True, "parity_claim": False, "excluded_from_decisions": True,
        "subject": SUBJECT, "opponents_requested": opponents,
        "reference_status": ref_status, "safe_opponents": safe_opponents,
        "per_opponent": per_opp, "combined": combined,
        "caveat": ("Benchmark-only context vs public references with DIFFERENT decks; "
                   "cross-deck, small-n, NOT a parity claim; EXCLUDED from every decision."),
        "all_ok": True,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_reference_context.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46I (Part F) — public-reference context (benchmark-only)", "",
        "> **Benchmark-only. No parity claim. EXCLUDED from every decision.** Public "
        "references play their OWN decks (cross-deck), at small n. These numbers situate the "
        "candidate against outside policies for colour only; the attribution and practical "
        "verdicts come solely from Parts D/E/G.", "",
        f"- subject: `{SUBJECT}`",
        f"- references requested: {opponents}",
        f"- safe (validated + extracted): {safe_opponents}", "",
        "## Per-reference (decisive games)",
        "| reference | decisive | subj wins | win rate | Wilson 95% | invalid |",
        "|---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for opp in safe_opponents:
        o = per_opp[opp]
        md.append(f"| `{opp}` | {o['decisive']} | {o['wins']} | {o['win_rate']} | "
                  f"[{o['wilson_low']}, {o['wilson_high']}] | {o['invalid']} |")
    md += ["",
           f"**combined:** decisive {combined['decisive']}, win rate {combined['win_rate']} "
           f"(Wilson [{combined['wilson_low']}, {combined['wilson_high']}]), "
           f"invalid {combined['invalid']}", ""]
    skipped = {o: s for o, s in ref_status.items() if not s["usable"]}
    if skipped:
        md += ["## Skipped references (unsafe / missing)",
               *[f"- `{o}`: {s['reason']} {s.get('detail','')}" for o, s in skipped.items()],
               ""]
    md += [f"_{data['caveat']}_"]
    (EXP / "pass46i_reference_context.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": True, "safe_opponents": safe_opponents,
                      "combined_decisive": combined["decisive"],
                      "combined_win_rate": combined["win_rate"],
                      "combined_wilson": [combined["wilson_low"], combined["wilson_high"]],
                      "skipped": list(skipped)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
