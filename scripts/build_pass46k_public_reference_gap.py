#!/usr/bin/env python3
"""PASS 46K (Part F) — public-reference GAP audit (benchmark-only, EXCLUDED from decisions).

Plays a small, seat-balanced benchmark panel of the EXISTING Pass-46J candidate
`cg_typed_diamond_specialist_planner_v0` against the public-reference agents named in the
pre-registered eval plan, purely to situate the specialist against outside policies and to
measure how far it sits from public-reference parity. This is BENCHMARK-ONLY:

  * references are BENCHMARK-ONLY — never source / parent / candidate, never promoted, never
    registered, never uploaded;
  * NO parity / "beats the field" claim is made or implied — public references play their OWN
    (different) decks, so every number here is cross-deck colour, at small n;
  * these numbers are EXCLUDED from every gating panel and from the Part-H decision;
  * results live in their OWN no_upload ledger (data/experiments/pass46k_reference_games.jsonl)
    kept entirely separate from the gating/attribution ledger, so reference games can NEVER leak
    into the practical / attribution statistics.

The external reference tarballs are UNTRUSTED, so every member is validated (regular files /
dirs only, no absolute paths, no parent-dir traversal, no symlinks/links/devices) BEFORE
extraction; a tarball that fails validation is skipped and reported, never extracted.

Reuses the same import-once, hang-safe batch worker as Parts D/F of 46I. Resumable. Writes
data/experiments/pass46k_public_reference_gap.{json,md}. Exit 0 iff it resolves (even with zero
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
PLAN_JSON = EXP / "pass46k_eval_plan.json"
REF_LEDGER = EXP / "pass46k_reference_games.jsonl"
REF_WORK = ROOT / "data" / "tournament" / "benchmark" / "_pass46k_ref_work"
WORKER = ROOT / "scripts" / "_pass46i_batch_worker.py"
SUBJECT = "cg_typed_diamond_specialist_planner_v0"
WILSON_Z = 1.96

# Prior benchmark baselines (DIFFERENT candidates / earlier passes) — colour context only.
# These are NOT the specialist and are NOT a parity/delta claim; they show how earlier LOCAL
# candidates fared vs the SAME public references (historically ~0% decisive, cross-deck).
BASELINE_FILES = [
    ("46f", EXP / "pass46f_public_reference_eval.json"),
    ("41", EXP / "pass41_public_reference_eval.json"),
]


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
    spec = EXP / "_pass46k_ref_batch_spec.json"
    spec.write_text(json.dumps({"games": todo}), encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, str(WORKER), "--spec", str(spec),
             "--jsonl", str(REF_LEDGER), "--budget-seconds", str(budget)],
            capture_output=True, text=True, timeout=budget + 15)
    except subprocess.TimeoutExpired:
        pass


def _blank() -> dict:
    return {"total": 0, "wins": 0, "losses": 0, "draws": 0, "invalid": 0, "decisive": 0}


def _fold(d: dict, r: dict) -> None:
    d["total"] += 1
    if r.get("invalid"):
        d["invalid"] += 1
    elif r.get("decisive"):
        d["decisive"] += 1
        if r.get("winner") == "subject":
            d["wins"] += 1
        else:
            d["losses"] += 1
    else:
        d["draws"] += 1


def load_baselines(ref_ids: list[str]) -> dict:
    """Normalise prior reference-eval reports to ref_id -> [color-only baseline rows]."""
    out: dict[str, list] = {rid: [] for rid in ref_ids}
    for pass_tag, path in BASELINE_FILES:
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        cand = d.get("candidate_id") or d.get("subject") or "unknown"
        per = d.get("per_reference")
        rows: dict[str, dict] = {}
        if isinstance(per, dict):
            for k, v in per.items():
                rid = k.split("ref:", 1)[-1] if isinstance(k, str) else k
                rows[rid] = v
        elif isinstance(per, list):
            for v in per:
                rid = v.get("reference_id")
                rows[rid] = v.get("candidate", v)
        for rid in ref_ids:
            v = rows.get(rid)
            if not isinstance(v, dict):
                continue
            out[rid].append({
                "pass": pass_tag, "candidate_id": cand,
                "decisive": v.get("decisive"),
                "decisive_win_rate": v.get("decisive_win_rate"),
                "wilson95": v.get("wilson95"),
                "wins": v.get("wins"), "losses": v.get("losses"),
                "draws": v.get("draws"),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=90.0)
    a = ap.parse_args()

    if not PLAN_JSON.exists():
        raise SystemExit(f"missing eval plan: {PLAN_JSON}")
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))

    ctx_specs = plan.get("optional_reference_context") or []
    spec = next((s for s in ctx_specs if s.get("panel_id") == "spec_vs_public_refs"),
                ctx_specs[0] if ctx_specs else {})
    opponents = list(spec.get("opponents", []))
    target_dec = int(spec.get("target_decisive_per_ref", 4))
    min_per_seat = int(spec.get("min_games_per_seat_per_ref", 2))
    hard_cap = int(spec.get("hard_cap_games_per_ref", 12))
    refs_avail = {r["ref_id"]: r for r in plan.get("references_available", [])}

    # Subject (the EXISTING 46J candidate) — extract into the ref work dir (idempotent).
    subj_dir = REF_WORK / SUBJECT
    safe_extract(ROOT / plan["participants"][SUBJECT]["tarball"], subj_dir)

    ref_status: dict[str, dict] = {}
    safe_opponents: list[str] = []
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

    def rel(p: Path) -> str:
        return str(p.relative_to(ROOT))

    # Seat-balanced candidate game plan: hard_cap per safe ref, alternating seats.
    plan_games = []
    for opp in safe_opponents:
        for i in range(hard_cap):
            plan_games.append({
                "game_id": f"spec_vs_refs#{opp}#g{i:03d}", "panel_id": "spec_vs_public_refs",
                "subject_id": SUBJECT, "opponent_id": opp,
                "subject_dir": rel(subj_dir), "opponent_dir": rel(REF_WORK / opp),
                "subject_seat": i % 2})
    plan_ids = {g["game_id"] for g in plan_games}

    def ref_satisfied(results: list) -> dict:
        """Per-ref: stop scheduling once target decisive AND min per-seat games reached."""
        agg: dict[str, dict] = {}
        seat_tot: dict[tuple, int] = {}
        for r in results:
            if r.get("game_id") not in plan_ids:
                continue
            opp = r.get("opponent_id")
            agg.setdefault(opp, {"decisive": 0})
            if r.get("decisive"):
                agg[opp]["decisive"] += 1
            seat_tot[(opp, int(r.get("subject_seat", 0)))] = \
                seat_tot.get((opp, int(r.get("subject_seat", 0))), 0) + 1
        sat = {}
        for opp in safe_opponents:
            dec = agg.get(opp, {}).get("decisive", 0)
            s0 = seat_tot.get((opp, 0), 0)
            s1 = seat_tot.get((opp, 1), 0)
            sat[opp] = (dec >= target_dec and s0 >= min_per_seat and s1 >= min_per_seat)
        return sat

    t0 = time.time()
    no_progress = 0
    while plan_games:
        results, orphans = read_ledger()
        done = {r["game_id"] for r in results}
        sat = ref_satisfied(results)
        todo = [g for g in plan_games
                if g["game_id"] not in done and g["game_id"] not in orphans
                and not sat.get(g["opponent_id"], False)]
        if not todo:
            break
        remaining = a.budget_seconds - (time.time() - t0)
        if remaining < 14:
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
    per_opp: dict[str, dict] = {}
    pooled = _blank()
    for opp in safe_opponents:
        agg = _blank()
        seat = {0: _blank(), 1: _blank()}
        for r in results:
            if r.get("game_id") not in plan_ids or r.get("opponent_id") != opp:
                continue
            if r.get("panel_id") != "spec_vs_public_refs":
                continue
            _fold(agg, r)
            _fold(seat[int(r.get("subject_seat", 0))], r)
        p, lo, hi = wilson(agg["wins"], agg["decisive"])
        seat_out = {}
        for s in (0, 1):
            sp, slo, shi = wilson(seat[s]["wins"], seat[s]["decisive"])
            seat_out[f"seat{s}"] = {**seat[s], "win_rate": sp,
                                    "wilson_low": slo, "wilson_high": shi}
        per_opp[opp] = {**agg, "win_rate": p, "wilson_low": lo, "wilson_high": hi,
                        "by_seat": seat_out,
                        "target_decisive": target_dec,
                        "reached_target": agg["decisive"] >= target_dec}
        for kk in ("total", "wins", "losses", "draws", "invalid", "decisive"):
            pooled[kk] += agg[kk]
    pp, plo, phi = wilson(pooled["wins"], pooled["decisive"])
    pooled.update({"win_rate": pp, "wilson_low": plo, "wilson_high": phi})

    baselines = load_baselines(safe_opponents)

    # Parity is only assertable if a Wilson lower bound clears 0.5 — never expected cross-deck.
    parity_supported = any(
        per_opp[o]["wilson_low"] is not None and per_opp[o]["wilson_low"] > 0.5
        for o in safe_opponents)
    pooled_parity_supported = bool(
        pooled["wilson_low"] is not None and pooled["wilson_low"] > 0.5)

    all_ok = True  # resolving (even with zero safe refs) is a valid reported outcome
    data = {
        "pass": "46K", "part": "F", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "benchmark_only": True, "parity_claim": False, "excluded_from_decisions": True,
        "is_decision_gate": False,
        "subject": SUBJECT, "opponents_requested": opponents,
        "reference_status": ref_status, "safe_opponents": safe_opponents,
        "target_decisive_per_ref": target_dec, "min_games_per_seat_per_ref": min_per_seat,
        "hard_cap_games_per_ref": hard_cap,
        "per_reference": per_opp, "pooled": pooled,
        "parity_supported_any_ref": parity_supported,
        "pooled_parity_supported": pooled_parity_supported,
        "prior_benchmark_baselines": baselines,
        "baseline_note": ("Prior baselines are DIFFERENT candidates / earlier passes vs the SAME "
                          "public references; shown for historical colour only — NOT the "
                          "specialist, NOT a delta/parity claim, NEVER a gate."),
        "caveat": ("Benchmark-only gap audit vs public references with DIFFERENT decks; "
                   "cross-deck, small-n, NOT a parity claim; EXCLUDED from every decision and "
                   "from all gating/attribution statistics."),
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46k_public_reference_gap.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46K (Part F) — public-reference gap audit (benchmark-only)", "",
        "> **Benchmark-only. No parity claim. EXCLUDED from every decision and from all "
        "gating/attribution statistics.** Public references play their OWN decks (cross-deck), "
        "at small n. These numbers measure distance-from-parity for COLOUR only; the practical / "
        "attribution / decision verdicts come solely from Parts D / E / G / H.", "",
        f"- subject (existing 46J candidate): `{SUBJECT}`",
        f"- references requested: {opponents}",
        f"- safe (validated + extracted): {safe_opponents}",
        f"- per-ref target: {target_dec} decisive, \u2265{min_per_seat}/seat, cap {hard_cap}", "",
        "## Per-reference (decisive games)",
        "| reference | total | W | L | D | invalid | win rate | Wilson 95% | reached target |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for opp in safe_opponents:
        o = per_opp[opp]
        md.append(f"| `{opp}` | {o['total']} | {o['wins']} | {o['losses']} | {o['draws']} | "
                  f"{o['invalid']} | {o['win_rate']} | "
                  f"[{o['wilson_low']}, {o['wilson_high']}] | "
                  f"{'yes' if o['reached_target'] else 'no'} |")
    md += ["",
           f"**pooled (cross-deck, colour only):** decisive {pooled['decisive']} "
           f"(W{pooled['wins']}/L{pooled['losses']}/D{pooled['draws']}, "
           f"invalid {pooled['invalid']}), win rate {pooled['win_rate']} "
           f"(Wilson [{pooled['wilson_low']}, {pooled['wilson_high']}])",
           "",
           "## Seat split (per reference)",
           "| reference | seat | total | W | L | D | win rate | Wilson 95% |",
           "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
    for opp in safe_opponents:
        for s in (0, 1):
            so = per_opp[opp]["by_seat"][f"seat{s}"]
            md.append(f"| `{opp}` | {s} | {so['total']} | {so['wins']} | {so['losses']} | "
                      f"{so['draws']} | {so['win_rate']} | "
                      f"[{so['wilson_low']}, {so['wilson_high']}] |")
    md += ["",
           f"- parity supported by any ref (Wilson low > 0.5): "
           f"**{parity_supported}** | pooled parity supported: "
           f"**{pooled_parity_supported}** _(neither expected cross-deck)_", ""]

    any_baseline = any(baselines.get(o) for o in safe_opponents)
    if any_baseline:
        md += ["## Prior benchmark baselines (different candidates \u2014 colour only)",
               "| reference | pass | prior candidate | decisive | prior win rate |",
               "|---|:---:|---|:---:|:---:|"]
        for opp in safe_opponents:
            for b in baselines.get(opp, []):
                md.append(f"| `{opp}` | {b['pass']} | `{b['candidate_id']}` | "
                          f"{b['decisive']} | {b['decisive_win_rate']} |")
        md += ["", f"_{data['baseline_note']}_", ""]

    skipped = {o: s for o, s in ref_status.items() if not s["usable"]}
    if skipped:
        md += ["## Skipped references (unsafe / missing)",
               *[f"- `{o}`: {s['reason']} {s.get('detail','')}" for o, s in skipped.items()],
               ""]
    md += [f"_{data['caveat']}_"]
    (EXP / "pass46k_public_reference_gap.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "safe_opponents": safe_opponents,
                      "pooled_decisive": pooled["decisive"],
                      "pooled_win_rate": pooled["win_rate"],
                      "pooled_wilson": [pooled["wilson_low"], pooled["wilson_high"]],
                      "parity_supported_any_ref": parity_supported,
                      "pooled_parity_supported": pooled_parity_supported,
                      "skipped": list(skipped)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
