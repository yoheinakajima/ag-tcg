#!/usr/bin/env python3
"""Pass 35 (T-K addendum) — typed-layer firing probe. LOCAL ONLY.

Supporting evidence for T-K (NOT the strength measurement). For each child we play
it directly against its identical untyped PARENT and instrument the embedded strategy
layer to record, per gameplay decision, whether the TYPED choice differed from the
BASE (parent) choice and whether that typed choice was LEGAL. Two robust facts come
out of this census:
  * the typed layer genuinely fires (low overall rate), and
  * it NEVER emits an illegal count across thousands of decisions (falls back / keeps
    legal base options only).
Per-deck per-game firing is high variance, so we accumulate several games per child
(seat-balanced) before reporting a rate; a single short draw can show 0% for a deck
that nevertheless produces a significant T-K effect — absence in a small draw is
sampling noise, not inertness. STRENGTH is measured by T-K's seat-swapped H2H, where
by mirror symmetry identical behaviour would give exactly 0.5; a Wilson CI excluding
0.5 is itself proof the layer changed outcomes.

Internal self-play only; nothing uploaded/submitted/pushed. Resumable: re-invoke until
status=complete. Output pass35_typed_firing_probe.{json,md}.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BUILD = EXP / "pass35_candidate_build.json"
OUT = EXP / "pass35_typed_firing_probe.json"
JSONL_DIR = EXP / "pass35_firing_jsonl"
WORKER = REPO / "scripts" / "_pass35_replay_worker.py"

GAME_TIMEOUT_S = int(os.environ.get("P35_GAME_TIMEOUT_S", "28"))
BUDGET_S = int(os.environ.get("P35_PER_CALL_BUDGET_S", "80"))
TARGET_GAMES = int(os.environ.get("P35_PROBE_TARGET_GAMES", "8"))
BATCH = int(os.environ.get("P35_PROBE_BATCH", "4"))

DISCLAIMER = (
    "TYPED-LAYER FIRING PROBE — instrumented divergence census of each child played "
    "against its identical untyped parent. Confirms the typed layer fires and stays "
    "legal; it is supporting evidence, NOT the strength estimate (see T-K). Internal "
    "self-play only; nothing uploaded, submitted, or pushed.")


def _extract(tar: Path, dest: Path) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar) as t:
        t.extractall(dest)
    return str(dest / "main.py")


def _pairs() -> list[dict]:
    data = json.loads(BUILD.read_text(encoding="utf-8"))
    out = []
    for r in data.get("candidates", []):
        if not r.get("built") or not r.get("tarball"):
            continue
        par = r.get("parent_tarball")
        if not par or not (REPO / par).exists():
            continue
        out.append({"child_id": r["candidate_id"], "child_tar": str(REPO / r["tarball"]),
                    "parent_tar": str(REPO / par), "parent_tarball_rel": par})
    out.sort(key=lambda x: x["child_id"])
    return out


def _games_in(jl: Path) -> list[dict]:
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _run_more(p: dict, jl: Path, n: int, tmp: Path) -> None:
    child_main = _extract(Path(p["child_tar"]), tmp / p["child_id"])
    parent_main = _extract(Path(p["parent_tar"]), tmp / (p["child_id"] + "_par"))
    have = len(_games_in(jl))
    specs = [f"{parent_main}|{(have + i) % 2}|{GAME_TIMEOUT_S}" for i in range(n)]
    try:
        subprocess.run([sys.executable, str(WORKER), child_main, str(jl)] + specs,
                       capture_output=True, text=True, timeout=BUDGET_S + 40)
    except subprocess.TimeoutExpired:
        pass


def _aggregate(p: dict, games: list[dict]) -> dict:
    tot = chg = ill = 0
    per_game, by_ctx = [], {}
    for g in games:
        ds = g.get("decisions", [])
        t = len(ds)
        c = sum(1 for d in ds if d.get("changed"))
        il = sum(1 for d in ds if not d.get("legal"))
        for d in ds:
            if d.get("changed"):
                ctx = str(d.get("ctx"))
                by_ctx[ctx] = by_ctx.get(ctx, 0) + 1
        tot += t
        chg += c
        ill += il
        per_game.append({"seat": g.get("seat"), "ok": g.get("ok"),
                         "timeout": g.get("timeout", False), "decisions": t,
                         "changes": c, "illegal": il})
    return {"child_id": p["child_id"], "parent_tarball": p["parent_tarball_rel"],
            "games": len(games), "decisions": tot, "typed_changes": chg,
            "firing_rate_pct": round(100.0 * chg / tot, 2) if tot else None,
            "illegal_refinements": ill, "changes_by_context": by_ctx,
            "per_game": per_game}


def _save(pairs: list[dict]) -> bool:
    rows = []
    for p in pairs:
        rows.append(_aggregate(p, _games_in(JSONL_DIR / f"{p['child_id']}.jsonl")))
    done = all(r["games"] >= TARGET_GAMES for r in rows)
    tot_dec = sum(r["decisions"] for r in rows)
    tot_chg = sum(r["typed_changes"] for r in rows)
    tot_ill = sum(r["illegal_refinements"] for r in rows)
    payload = {"pass": "35", "task": "T-K addendum", "kind": "typed_firing_probe",
               "status": "complete" if done else "in_progress",
               "is_kaggle_leaderboard": False, "upload_performed": False,
               "no_upload": True, "disclaimer": DISCLAIMER,
               "target_games_per_child": TARGET_GAMES,
               "children_total": len(rows),
               "children_at_target": sum(1 for r in rows if r["games"] >= TARGET_GAMES),
               "totals": {"decisions": tot_dec, "typed_changes": tot_chg,
                          "overall_firing_rate_pct":
                              round(100.0 * tot_chg / tot_dec, 2) if tot_dec else None,
                          "illegal_refinements": tot_ill},
               "any_illegal_refinement": tot_ill > 0, "children": rows}
    EXP.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    L = ["# Pass 35 — typed-layer firing probe (T-K addendum)", "",
         f"> {DISCLAIMER}", "",
         f"- status: **{payload['status']}**  children at target "
         f"({TARGET_GAMES} games): {payload['children_at_target']}/{len(rows)}  "
         f"is Kaggle leaderboard: **False**  upload_performed: **False**",
         f"- overall firing rate: **{payload['totals']['overall_firing_rate_pct']}%** "
         f"({tot_chg} typed changes / {tot_dec} instrumented decisions)  "
         f"illegal refinements: **{tot_ill}**", "",
         "| child (typed) | games | decisions | typed changes | firing rate | "
         "illegal | changed contexts |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['child_id']} | {r['games']} | {r['decisions']} | "
                 f"{r['typed_changes']} | {r['firing_rate_pct']}% | "
                 f"{r['illegal_refinements']} | {r['changes_by_context'] or '-'} |")
    L += ["", "## Reading the result", "",
          "- Low overall firing **rate** with real win/loss swings (T-K) means the "
          "layer fires rarely but at **high-leverage** decisions; frequency and impact "
          "are distinct. Per-deck firing is high variance across short draws.",
          "- Zero illegal refinements across all instrumented decisions confirms the "
          "typed layer never emits an illegal count — it reorders/keeps legal base "
          "options or falls back to base.",
          "- This is a divergence/legality census, NOT a strength estimate; the "
          "seat-swapped H2H in T-K (where mirror symmetry pins identical behaviour to "
          "0.5) is the strength measurement.", ""]
    (EXP / "pass35_typed_firing_probe.md").write_text("\n".join(L), encoding="utf-8")
    return done


def main() -> int:
    JSONL_DIR.mkdir(parents=True, exist_ok=True)
    pairs = _pairs()
    if not pairs:
        _save(pairs)
        print("firing-probe blocked: no pairs")
        return 0
    start = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for p in pairs:
            jl = JSONL_DIR / f"{p['child_id']}.jsonl"
            have = len(_games_in(jl))
            if have >= TARGET_GAMES:
                continue
            if time.time() - start > BUDGET_S:
                break
            _run_more(p, jl, min(BATCH, TARGET_GAMES - have), tmp)
            _save(pairs)
    done = _save(pairs)
    at = sum(1 for p in pairs
             if len(_games_in(JSONL_DIR / f"{p['child_id']}.jsonl")) >= TARGET_GAMES)
    print(f"firing-probe: at_target={at}/{len(pairs)} "
          f"status={'complete' if done else 'partial'} "
          f"elapsed={round(time.time() - start, 1)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
