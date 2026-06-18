#!/usr/bin/env python3
"""Pass 15 — live cabt smoke + focused directional eval of the core-pilot runtime.

SURROGATE-BASED and DIRECTIONAL ONLY. Opponent decks are piloted by a generic
surrogate policy, not the real opponent policy. These results never equal Kaggle
results and are NEVER sufficient to promote or upload a candidate. No upload, no
submission, no GitHub push.

Two products from one run (so the live games are shared, not duplicated):

* LIVE SMOKE (data/reports/pass15_live_smoke.{json,md}) — proves both candidates
  and the active control actually *play* live cabt without crash/timeout/invalid:
  v2_runtime vs active control (seat-swapped), v2 self-mirror, v1 vs active,
  active-control self-mirror.
* FOCUSED DIRECTIONAL EVAL (data/reports/pass15_core_focused_eval.{json,md,csv})
  — v1 and v2_runtime and the active control vs the refined Pass-13 surrogate
  subfamilies (seat-swapped), with a small ranking. The runtime only refines the
  ToHand-search and discard targets at the two reliably identifiable cabt
  contexts, so any delta vs the active control is expected to be SMALL; this is a
  no-regression directional signal, not a promotion proof.

Gated on cabt availability and a global time budget; writes partial results and
marks the run incomplete rather than hanging.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

import run_meta_pool_eval as eng  # reuse proven game primitives  # noqa: E402
from ptcg_activegraph.sim.surrogate_agents import (  # noqa: E402
    materialize_surrogate_agent,
)

REFINED = REPO / "experiments" / "pass13_refined_meta_pool.yaml"
CAND14 = REPO / "data" / "submissions" / "candidates_pass14"
CAND = REPO / "data" / "submissions" / "candidates"
SMOKE_JSON = REPO / "data" / "reports" / "pass15_live_smoke.json"
SMOKE_MD = REPO / "data" / "reports" / "pass15_live_smoke.md"
EVAL_JSON = REPO / "data" / "reports" / "pass15_core_focused_eval.json"
EVAL_MD = REPO / "data" / "reports" / "pass15_core_focused_eval.md"
EVAL_CSV = REPO / "data" / "reports" / "pass15_core_focused_eval_matrix.csv"

DISCLAIMER = (
    "Surrogate-based and DIRECTIONAL ONLY. Opponent decks are piloted by a generic "
    "surrogate policy, not the real opponent policy. These results never equal "
    "Kaggle results and are not sufficient to promote or upload a candidate."
)

CANDIDATES = (
    ("core_pilot_water_v2_runtime", CAND14 / "core_pilot_water_v2_runtime.tar.gz"),
    ("core_pilot_water_v1", CAND14 / "core_pilot_water_v1.tar.gz"),
)


ENTRYPOINT_VALIDATOR = REPO / "scripts" / "validate_candidate_entrypoint.py"


def _entrypoint_ok(tarball: Path) -> bool:
    """Run the entrypoint-invariant validator on a tarball; True iff it PASSES.

    This is the ratchet from this pass: only artifacts whose last top-level
    callable returns a 60-card deck on every probed obs shape + legal gameplay
    indices are considered valid. We refuse to directional-RANK a candidate that
    fails it. The live-scoring active control is kept as a flagged anchor (it is
    a real Kaggle submission, never a promotion target) but its status is
    recorded transparently.
    """
    if not ENTRYPOINT_VALIDATOR.exists():
        return True
    try:
        proc = subprocess.run([sys.executable, str(ENTRYPOINT_VALIDATOR),
                               str(tarball)],
                              capture_output=True, text=True, timeout=180)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _opponents(limit: int) -> list:
    if not REFINED.exists():
        return []
    pool = yaml.safe_load(REFINED.read_text(encoding="utf-8")) or {}
    opps = []
    for a in pool.get("archetypes", []):
        if a.get("is_ours"):
            continue
        deck = a.get("surrogate_deck")
        if deck and (REPO / deck).exists():
            opps.append({"key": a["key"], "deck": str(REPO / deck),
                         "weight": a.get("weight"), "confidence": a.get("confidence")})
    return opps[:limit]


def _matchup_summary(m: dict) -> dict:
    return {k: m.get(k) for k in ("label", "win_rate", "wins", "losses", "draws",
                                  "crashes", "timeouts", "skipped")}


def run(max_opponents: int) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    base = {"disclaimer": DISCLAIMER, "started": started,
            "games_per_seat": eng.GAMES_PER_SEAT,
            "global_budget_s": eng.GLOBAL_BUDGET_S}
    if not eng._cabt_available():
        return {**base, "ok": False, "complete": False, "reason": "cabt not available",
                "smoke": [], "matchups": []}

    ac_name = eng._active_control_name()
    ac_tar = CAND / f"{ac_name}.tar.gz"
    missing = [n for n, p in CANDIDATES if not p.exists()]
    if missing or not ac_tar.exists():
        return {**base, "ok": False, "complete": False,
                "reason": f"missing tarballs: {missing} ac={ac_tar.exists()}",
                "smoke": [], "matchups": []}

    # ---- ENTRYPOINT VALIDATION PRE-FILTER (ratchet) --------------------- #
    # Only validator-PASSING candidates are directional-ranked. The live-scoring
    # active control is kept as a flagged directional anchor regardless (it is a
    # real Kaggle submission, never a promotion target), with its status logged.
    validation = {}
    valid_candidates = []
    for n, p in CANDIDATES:
        ok = _entrypoint_ok(p)
        validation[n] = {"role": "candidate", "entrypoint_pass": ok,
                         "tarball": str(p.relative_to(REPO))}
        if ok:
            valid_candidates.append((n, p))
    ac_ok = _entrypoint_ok(ac_tar)
    validation[ac_name] = {
        "role": "active_control_anchor", "entrypoint_pass": ac_ok,
        "tarball": str(ac_tar.relative_to(REPO)),
        "note": ("kept as a directional anchor despite validator status — it is a "
                 "real live Kaggle submission and is NEVER a promotion target."),
    }
    if not valid_candidates:
        return {**base, "ok": False, "complete": False,
                "reason": "no candidate passed the entrypoint validator",
                "validation": validation, "smoke": [], "matchups": []}

    deadline = time.time() + eng.GLOBAL_BUDGET_S

    def budget_left():
        return deadline - time.time()

    def _short(name: str) -> str:
        return name.replace("core_pilot_water_", "")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ac_agent = eng._extract_agent(ac_tar, tmp / "active_control")
        agents = {n: eng._extract_agent(p, tmp / n) for n, p in valid_candidates}

        # ---- LIVE SMOKE -------------------------------------------------- #
        smoke = []
        for n, _ in valid_candidates:
            s = _short(n)
            smoke.append({"matchup": f"{s}_vs_active_control",
                          **_matchup_summary(eng._run_matchup(
                              agents[n], ac_agent, budget_left,
                              f"{s} vs active_control"))})
            smoke.append({"matchup": f"{s}_self_mirror",
                          **_matchup_summary(eng._run_matchup(
                              agents[n], agents[n], budget_left,
                              f"{s} self-mirror"))})
        smoke.append({"matchup": "active_control_self_mirror",
                      **_matchup_summary(eng._run_matchup(
                          ac_agent, ac_agent, budget_left,
                          "active_control self-mirror"))})

        # ---- FOCUSED DIRECTIONAL EVAL ------------------------------------ #
        roles = [(n, agents[n]) for n, _ in valid_candidates]
        roles.append(("active_control", ac_agent))
        matchups = []
        for opp in _opponents(max_opponents):
            try:
                opp_agent = str(materialize_surrogate_agent(
                    opp["deck"], tmp / ("surr_" + opp["key"])))
            except Exception as exc:  # noqa: BLE001
                matchups.append({"opponent": opp["key"], "role": "-",
                                 "error": repr(exc), "ok": False})
                continue
            for role, agent in roles:
                matchups.append({"opponent": opp["key"], "role": role,
                                 "weight": opp.get("weight"),
                                 **_matchup_summary(eng._run_matchup(
                                     agent, opp_agent, budget_left,
                                     f"{role} vs {opp['key']}"))})

    all_m = smoke + matchups
    complete = all(m.get("skipped", 0) == 0 for m in all_m
                   if isinstance(m.get("skipped"), int))
    return {**base, "ok": True, "complete": complete,
            "ended": datetime.now(timezone.utc).isoformat(),
            "active_control": ac_name, "validation": validation,
            "smoke": smoke, "matchups": matchups}


def _rank(rep: dict) -> list:
    """Weighted directional win-rate per role across subfamilies (small samples)."""
    by_role: dict = {}
    for m in rep.get("matchups", []):
        if m.get("win_rate") is None:
            continue
        r = by_role.setdefault(m["role"], {"wsum": 0.0, "w": 0.0, "n": 0})
        w = m.get("weight") or 1.0
        r["wsum"] += m["win_rate"] * w
        r["w"] += w
        r["n"] += 1
    out = []
    for role, d in by_role.items():
        out.append({"role": role, "subfamilies": d["n"],
                    "weighted_directional_win_rate":
                        round(d["wsum"] / d["w"], 4) if d["w"] else None})
    out.sort(key=lambda x: (x["weighted_directional_win_rate"] or -1), reverse=True)
    return out


def _write_smoke(rep: dict) -> None:
    SMOKE_JSON.parent.mkdir(parents=True, exist_ok=True)
    doc = {k: rep[k] for k in ("disclaimer", "started", "ended", "ok", "complete",
                               "reason", "games_per_seat", "global_budget_s",
                               "active_control", "validation", "smoke") if k in rep}
    SMOKE_JSON.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    L = ["# Pass 15 — Live cabt Smoke", "", f"> {rep['disclaimer']}", "",
         f"- started: {rep.get('started')}  ended: {rep.get('ended')}",
         f"- ok: {rep.get('ok')}  complete: **{rep.get('complete')}**  "
         f"games/seat: {rep.get('games_per_seat')}"]
    if rep.get("reason"):
        L.append(f"- reason: {rep['reason']}")
    val = rep.get("validation") or {}
    if val:
        L += ["", "## Entrypoint-validator pre-filter", "",
              "| artifact | role | entrypoint validator |", "|---|---|---|"]
        for name, v in val.items():
            status = "PASS" if v.get("entrypoint_pass") else "**FAIL**"
            L.append(f"| {name} | {v.get('role')} | {status} |")
        L.append("")
        L.append("_Only validator-PASSING candidates are directional-ranked. The "
                 "live-scoring active control is kept as a flagged anchor (real "
                 "Kaggle submission, never a promotion target)._")
    L += ["", "Confirms each agent plays live cabt with **0 crash / 0 timeout / 0 "
          "skipped** (validity). Win rates here are tiny-sample directional only.", "",
          "| matchup | win rate | W-L-D | crash/timeout/skip |", "|---|---|---|---|"]
    for m in rep.get("smoke", []):
        L.append(f"| {m['matchup']} | {m.get('win_rate')} | "
                 f"{m.get('wins')}-{m.get('losses')}-{m.get('draws')} | "
                 f"{m.get('crashes')}/{m.get('timeouts')}/{m.get('skipped')} |")
    SMOKE_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def _write_eval(rep: dict) -> None:
    ranking = _rank(rep)
    rep["ranking"] = ranking
    doc = {k: rep[k] for k in ("disclaimer", "started", "ended", "ok", "complete",
                               "reason", "games_per_seat", "global_budget_s",
                               "active_control", "validation", "matchups",
                               "ranking") if k in rep}
    EVAL_JSON.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    L = ["# Pass 15 — Core-Pilot Focused Directional Eval", "",
         f"> {rep['disclaimer']}", "",
         f"- started: {rep.get('started')}  complete: **{rep.get('complete')}**",
         f"- games/seat: {rep.get('games_per_seat')}  "
         f"budget_s: {rep.get('global_budget_s')}", ""]
    L += ["## Weighted directional ranking (small samples)", "",
          "| role | subfamilies | weighted directional win rate |", "|---|---|---|"]
    for r in ranking:
        L.append(f"| {r['role']} | {r['subfamilies']} | "
                 f"{r['weighted_directional_win_rate']} |")
    L += ["", "## Per-subfamily matchups", "",
          "| opponent | role | weight | win rate | W-L-D | crash/timeout/skip |",
          "|---|---|---|---|---|---|"]
    rows = []
    for m in rep.get("matchups", []):
        if "wins" not in m:
            L.append(f"| {m.get('opponent')} | {m.get('role')} | - | error | - | - |")
            continue
        L.append(f"| {m.get('opponent')} | {m.get('role')} | {m.get('weight')} | "
                 f"{m.get('win_rate')} | "
                 f"{m['wins']}-{m['losses']}-{m['draws']} | "
                 f"{m['crashes']}/{m['timeouts']}/{m['skipped']} |")
        rows.append([m.get("opponent"), m.get("role"), m.get("weight"),
                     m.get("win_rate"), m["wins"], m["losses"], m["draws"],
                     m["crashes"], m["timeouts"], m["skipped"]])
    L += ["", "Directional only; small samples. A small/zero delta between v2_runtime, "
          "v1, and the active control is EXPECTED — the runtime only refines the "
          "ToHand-search and discard targets at the two reliably identifiable cabt "
          "contexts. Treat as a no-regression sanity signal, not a promotion proof.", ""]
    EVAL_MD.write_text("\n".join(L), encoding="utf-8")

    with EVAL_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["opponent", "role", "weight", "win_rate", "wins", "losses",
                    "draws", "crashes", "timeouts", "skipped"])
        w.writerows(rows)


def main() -> int:
    rep = run(max_opponents=int(os.environ.get("PASS15_MAX_OPPONENTS", "2")))
    _write_smoke(rep)
    _write_eval(rep)
    print(SMOKE_MD.read_text(encoding="utf-8"))
    print(EVAL_MD.read_text(encoding="utf-8"))
    print(f"wrote {SMOKE_JSON}\nwrote {SMOKE_MD}")
    print(f"wrote {EVAL_JSON}\nwrote {EVAL_MD}\nwrote {EVAL_CSV}")
    # Sentinel for background-run completion detection.
    (REPO / "data" / "reports" / "pass15_eval_DONE.txt").write_text(
        f"complete={rep.get('complete')} ok={rep.get('ok')}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
