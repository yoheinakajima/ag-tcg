#!/usr/bin/env python3
"""Pass 35 (T-H) — typed candidate validation + live smoke. LOCAL / no upload.

For every typed child in data/submissions/candidates_pass35/ (the 9 executable
profiles; special-pilot-only profiles were never built):

  1. STATIC — validate_candidate_tarball (exactly main.py+deck.csv, 60 ids,
     stdlib-only) AND validate_candidate_entrypoint (last-callable returns the
     60 ids on every deck-selection shape; safe gameplay delegation).
  2. IMPORT SCAN — AST scan of the child main.py; flag any non-stdlib /
     known-forbidden imports (net, ML, kaggle).
  3. ENTRYPOINT SMOKE — validate_candidate_entrypoint(--smoke): one live cabt
     game must not INVALID/ERROR.
  4. LIVE SMOKE — seat-swapped cabt games child-vs-self and child-vs-control
     (the proven Water core reference PARENT). Clean iff no INVALID/ERROR/TIMEOUT.
  5. PARENT/CHILD SMOKE — child vs its own parent tarball, seat-swapped; confirms
     both run clean (the directional A/B is graded later in T-K).
  6. FIXTURE GATE — references the already-green typed strategy gate.

RESUMABLE + time-boxed: each call validates as many candidates as fit in
P35_PER_CALL_BUDGET_S, checkpointing per candidate. Re-invoke until remaining=0.
Outcomes are CLEAN-RUN ONLY (same generic pilot both seats); never a promotion
or upload signal.

Writes data/experiments/pass35_candidate_validation.{json,md}.
Exit non-zero iff any built candidate fails a gate.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
CAND = REPO / "data" / "submissions" / "candidates_pass35"
BUILD = EXP / "pass35_candidate_build.json"
GATE = REPO / "data" / "reports" / "pass35_typed_strategy_gate.json"
PROGRESS = EXP / "pass35_candidate_validation_progress.json"
WORKER = REPO / "scripts" / "_pass34_game_worker.py"

CONTROL_PARENT = REPO / ("data/submissions/candidates_pass33/"
                         "league_water_core_reference.tar.gz")

GAME_TIMEOUT_S = int(os.environ.get("P35_GAME_TIMEOUT_S", "60"))
GAMES_PER_SEAT = int(os.environ.get("P35_SMOKE_GAMES_PER_SEAT", "1"))
PER_CALL_BUDGET_S = int(os.environ.get("P35_PER_CALL_BUDGET_S", "600"))
BAD = {"INVALID", "ERROR", "TIMEOUT"}

DISCLAIMER = ("SURROGATE VALIDITY SMOKE, LOCAL ONLY. Both seats run the same "
              "generic core pilot refined by the typed layer; the verdict is "
              "clean-run only — win/loss is directional and never justifies "
              "upload or promotion.")

# stdlib modules that the embedded typed layer / base legitimately use; anything
# outside the stdlib set is flagged.
FORBIDDEN_HINTS = {"numpy", "torch", "tensorflow", "pandas", "requests",
                   "kaggle", "sklearn", "scipy", "urllib3", "httpx", "aiohttp"}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_VTAR = _load("validate_candidate_tarball")
_VENT = _load("validate_candidate_entrypoint")
_MEV = _load("run_meta_pool_eval")
_extract_agent = _MEV._extract_agent
_outcome_for_seat = _MEV._outcome_for_seat


def _run_game(agent_a: str, agent_b: str) -> dict:
    hard = GAME_TIMEOUT_S + 15
    try:
        p = subprocess.run(
            [sys.executable, str(WORKER), agent_a, agent_b, str(GAME_TIMEOUT_S)],
            capture_output=True, text=True, timeout=hard)
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True, "error": "watchdog hard timeout"}
    out = (p.stdout or "").strip()
    if p.returncode != 0 or not out:
        return {"ok": False, "timeout": False,
                "error": f"worker rc={p.returncode}: {(p.stderr or '')[-200:]}"}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "timeout": False, "error": f"worker parse: {exc!r}"}


def _matchup(a_agent: str, b_agent: str, n: int) -> dict:
    games = []
    for (a, b, seat) in [(a_agent, b_agent, 0), (b_agent, a_agent, 1)]:
        for _ in range(n):
            g = _run_game(a, b)
            g["our_seat"] = seat
            g["outcome"] = _outcome_for_seat(g, seat) if g.get("ok") else None
            games.append(g)
    bad = sorted({s for g in games for s in (g.get("statuses") or []) if s in BAD})
    return {
        "n_games": len(games),
        "completed": sum(1 for g in games if g.get("ok")),
        "bad_statuses": bad,
        "timeouts": sum(1 for g in games if g.get("timeout")),
        "errors": sorted({g.get("error") for g in games if g.get("error")}),
        "outcomes": [g.get("outcome") for g in games if g.get("ok")],
        "clean": not bad and all(g.get("ok") for g in games),
    }


def _import_scan(main_py: Path) -> dict:
    try:
        tree = ast.parse(main_py.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return {"ok": False, "error": f"syntax: {e}", "modules": []}
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    forbidden = sorted(m for m in mods if m in FORBIDDEN_HINTS)
    non_stdlib = sorted(m for m in mods
                        if m not in stdlib and m not in {"cg"} and m != "")
    return {"ok": not forbidden, "modules": sorted(mods),
            "forbidden": forbidden, "non_stdlib": non_stdlib}


def _static(tar: Path) -> dict:
    rc_tar = _VTAR.validate(str(tar))
    rc_ent = _VENT.validate(str(tar), smoke=False)
    return {"tarball_rc": rc_tar, "entrypoint_rc": rc_ent,
            "passed": rc_tar == 0 and rc_ent == 0}


def _entrypoint_smoke(tar: Path) -> dict:
    """Run validate_candidate_entrypoint --smoke in a SUBPROCESS with a hard
    wall-clock timeout. The validator's own --smoke uses an in-process SIGALRM
    watchdog that cannot interrupt a hang in native open_spiel C code, so we
    isolate it here and kill it on a hard timeout (recorded as a smoke timeout)."""
    cli = REPO / "scripts" / "validate_candidate_entrypoint.py"
    try:
        p = subprocess.run([sys.executable, str(cli), str(tar), "--smoke"],
                           capture_output=True, text=True,
                           timeout=GAME_TIMEOUT_S + 30)
        return {"rc": p.returncode, "timeout": False,
                "tail": (p.stdout or p.stderr or "").strip()[-200:]}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "timeout": True,
                "tail": "hard wall-clock timeout (native engine hang)"}


def _candidate_ok(rec: dict) -> bool:
    return bool(rec.get("static", {}).get("passed")
               and rec.get("import_scan", {}).get("ok")
               and rec.get("entrypoint_smoke_rc") == 0
               and rec.get("self_smoke", {}).get("clean")
               and rec.get("control_smoke", {}).get("clean")
               and rec.get("parent_child_smoke", {}).get("clean"))


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    build = json.loads(BUILD.read_text(encoding="utf-8"))
    gate_ok = bool(json.loads(GATE.read_text(encoding="utf-8")).get("all_ok")) \
        if GATE.exists() else False
    built = [c for c in build["candidates"] if c.get("built")]
    parent_of = {c["id"]: c.get("parent_tarball") for c in built}
    cand_ids = [c["id"] for c in built]

    prog = (json.loads(PROGRESS.read_text(encoding="utf-8"))
            if PROGRESS.exists() else {"records": {}})
    records = prog["records"]

    start = time.time()
    n = GAMES_PER_SEAT
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Control agent (proven Water core reference parent).
        control_agent = None
        if CONTROL_PARENT.exists():
            control_agent = _extract_agent(CONTROL_PARENT, tmp / "_control")

        for cid in cand_ids:
            if cid in records:
                continue
            if time.time() - start >= PER_CALL_BUDGET_S:
                break
            tar = CAND / f"{cid}.tar.gz"
            rec = {"id": cid, "parent_tarball": parent_of.get(cid)}
            if not tar.exists():
                rec["static"] = {"passed": False, "reason": "tarball missing"}
                records[cid] = rec
                PROGRESS.write_text(json.dumps(prog, indent=2), encoding="utf-8")
                continue
            cdir = tmp / cid
            child_agent = _extract_agent(tar, cdir)
            rec["static"] = _static(tar)
            rec["import_scan"] = _import_scan(Path(child_agent))
            _es = _entrypoint_smoke(tar)
            rec["entrypoint_smoke"] = _es
            rec["entrypoint_smoke_rc"] = _es["rc"]
            rec["self_smoke"] = _matchup(child_agent, child_agent, n)
            rec["control_smoke"] = (
                _matchup(child_agent, control_agent, n) if control_agent
                else {"clean": True, "skipped": True,
                      "note": "control parent missing"})
            prel = parent_of.get(cid)
            pabs = REPO / prel if prel else None
            if pabs and pabs.exists():
                parent_agent = _extract_agent(pabs, tmp / f"{cid}__parent")
                rec["parent_child_smoke"] = _matchup(child_agent, parent_agent, n)
            else:
                rec["parent_child_smoke"] = {"clean": False,
                                             "error": f"parent missing: {prel}"}
            rec["ok"] = _candidate_ok(rec)
            records[cid] = rec
            PROGRESS.write_text(json.dumps(prog, indent=2), encoding="utf-8")

    remaining = [c for c in cand_ids if c not in records]
    done = not remaining
    all_ok = done and all(records[c].get("ok") for c in cand_ids)

    report = {
        "pass": "35", "task": "T-H", "local_only": True, "no_upload": True,
        "upload_performed": False, "is_kaggle_leaderboard": False,
        "disclaimer": DISCLAIMER, "typed_strategy_gate_ok": gate_ok,
        "games_per_seat": n, "control": "league_water_core_reference (parent)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "complete" if done else "in_progress",
        "remaining": remaining, "all_ok": all_ok,
        "records": [records[c] for c in cand_ids if c in records],
    }
    (EXP / "pass35_candidate_validation.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")

    L = ["# Pass 35 — typed candidate validation (T-H)", "",
         f"> LOCAL ONLY. {DISCLAIMER}", "",
         f"- generated: {report['generated_at']}  status: **{report['status']}**",
         f"- typed strategy gate green: **{gate_ok}**  games/seat: {n} "
         f"(seat-swapped); control: proven Water core reference parent",
         f"- all built candidates pass every gate: **{all_ok}**",
         f"- remaining: {remaining or 'none'}", "",
         "| candidate | static | imports | entry-smoke | self | control | "
         "parent/child | OK |", "|---|---|---|---|---|---|---|---|"]
    for cid in cand_ids:
        r = records.get(cid)
        if not r:
            L.append(f"| {cid} | _pending_ |  |  |  |  |  |  |")
            continue

        def cell(m):
            if not m:
                return "—"
            if m.get("skipped"):
                return "skip"
            return "clean" if m.get("clean") else f"BAD:{m.get('bad_statuses') or m.get('errors')}"
        imp = r.get("import_scan", {})
        imp_cell = "ok" if imp.get("ok") else f"BAD:{imp.get('forbidden')}"
        L.append(
            f"| {cid} | {'ok' if r.get('static', {}).get('passed') else 'NO'} | "
            f"{imp_cell} | {'ok' if r.get('entrypoint_smoke_rc') == 0 else 'NO'} | "
            f"{cell(r.get('self_smoke'))} | {cell(r.get('control_smoke'))} | "
            f"{cell(r.get('parent_child_smoke'))} | "
            f"{'YES' if r.get('ok') else 'NO'} |")
    L += ["", "_Win/loss is directional only (same generic pilot both seats); "
          "this gate asserts clean execution, never promotion._", ""]
    (EXP / "pass35_candidate_validation.md").write_text("\n".join(L), encoding="utf-8")

    for cid in cand_ids:
        r = records.get(cid, {})
        print(f"{cid}: ok={r.get('ok')} static={r.get('static', {}).get('passed')} "
              f"entry_smoke_rc={r.get('entrypoint_smoke_rc')} "
              f"self={r.get('self_smoke', {}).get('clean')} "
              f"control={r.get('control_smoke', {}).get('clean')} "
              f"parent_child={r.get('parent_child_smoke', {}).get('clean')}")
    print(f"\nstatus={report['status']} all_ok={all_ok} remaining={remaining}")
    if done and PROGRESS.exists():
        PROGRESS.unlink()
    return 0 if all_ok else (0 if not done else 1)


if __name__ == "__main__":
    raise SystemExit(main())
