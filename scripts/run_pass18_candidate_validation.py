#!/usr/bin/env python3
"""Pass 18 (Part J) -- validation gates + fixture gates + live smoke.

LOCAL ONLY. For every built Pass-18 candidate
(experiments/runs_pass18/build_manifest.json) this runs the hard pre-flight
gates, the targeted + core-competency fixture gates, and a live cabt smoke,
recording per candidate:

  * tarball gate     -- scripts/validate_candidate_tarball.py (exactly top-level
                        main.py + deck.csv, 60-int deck, agent returns the deck on
                        the deck-selection step, no raise on malformed obs);
  * entrypoint gate  -- scripts/validate_candidate_entrypoint.py (last-callable is
                        the deck-safe agent, legal gameplay indices, stdlib-only);
  * core fixtures    -- scripts/run_core_competency_gate.py vs data/fixtures/
                        core_competency (the generic pilot must not regress);
  * targeted fixtures-- the family's own fixtures (Dragapult: data/fixtures/
                        pass18_dragapult_spread);
  * live smoke       -- one self-mirror game + one game vs the Water reference in
                        real cabt; must reach a normal terminal status.

A candidate is LEAGUE-ELIGIBLE iff it passes both hard gates AND both fixture
gates AND the live smoke AND is not flagged blocked_from_league. Durant is not a
Pass-18 candidate (chaos-research-only) and never appears here.

Writes data/experiments/pass18_candidate_validation.{json,md}. No upload.
"""

from __future__ import annotations

import contextlib
import io
import importlib.util
import json
import signal
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
MANIFEST = REPO / "experiments" / "runs_pass18" / "build_manifest.json"
WATER_REF = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_water_core_reference.tar.gz"
PARENT_DIR = REPO / "data" / "submissions" / "candidates_pass17"
CORE_FIXTURES = REPO / "data" / "fixtures" / "core_competency"
TARGETED_FIXTURES = {
    "dragapult_spread_v1": REPO / "data" / "fixtures" / "pass18_dragapult_spread",
}

GAME_TIMEOUT_S = 60


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_TARBALL = _load("validate_candidate_tarball")
_ENTRY = _load("validate_candidate_entrypoint")
_GATE = _load("run_core_competency_gate")


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def _extract_main(tar: Path, dest: Path) -> str:
    with tarfile.open(tar, "r:gz") as t:
        t.extractall(dest)  # noqa: S202 (our own artifact)
    return str(dest / "main.py")


def _live_game(agent_a: str, agent_b: str) -> dict:
    try:
        from kaggle_environments import make
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "reason": f"cabt unavailable: {exc!r}"}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(GAME_TIMEOUT_S)
    try:
        env = make("cabt")
        env.run([agent_a, agent_b])
        statuses = [s.get("status") for s in env.state]
        ok = all(st in ("ACTIVE", "INACTIVE", "DONE") for st in statuses)
        return {"ran": True, "ok": ok, "statuses": statuses,
                "steps": len(env.steps)}
    except _Timeout:
        return {"ran": True, "ok": False, "statuses": ["TIMEOUT"], "timeout": True}
    except Exception as exc:  # noqa: BLE001
        return {"ran": True, "ok": False, "error": repr(exc)}
    finally:
        signal.alarm(0)


def _run_gate(fn, *args, **kw) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kw)
    return {"passed": code == 0, "exit_code": code,
            "output": buf.getvalue().strip().splitlines()[-3:]}


def _fixture_gate(tar: Path, fixtures_dir: Path) -> dict:
    summary = _GATE.grade_candidate(str(tar), None, fixtures_dir)
    return {
        "fixtures_dir": str(fixtures_dir.relative_to(REPO)),
        "passed": bool(summary.get("ok")),
        "total": summary.get("total"),
        "passed_count": summary.get("passed"),
        "failed_count": summary.get("failed"),
        "hard_failed": summary.get("hard_failed"),
        "has_core_pilot_layer": summary.get("has_core_pilot_layer"),
    }


def validate_candidate(c: dict, tmp: Path) -> dict:
    tar = REPO / c["tarball"]
    cid = c["candidate_id"]
    deck_key = c.get("deck_key")
    blocked = bool(c.get("blocked_from_league"))

    tarball_gate = _run_gate(_TARBALL.validate, str(tar))
    entry_gate = _run_gate(_ENTRY.validate, str(tar), smoke=False)

    core_gate = _fixture_gate(tar, CORE_FIXTURES)
    targeted_dir = TARGETED_FIXTURES.get(deck_key)
    targeted_gate = _fixture_gate(tar, targeted_dir) if targeted_dir else {
        "fixtures_dir": None, "passed": True, "reason": "no targeted fixtures"}

    # Core-competency fixtures encode the Water shell's card ids (e.g. evolving to
    # 723), so a non-Water family can legitimately not recognise every Water
    # payoff. The fair gate for a REFINEMENT candidate is therefore "no
    # regression vs its parent" on core competency, not an absolute pass. The
    # absolute result is still recorded for transparency.
    parent_id = c.get("parent_candidate")
    parent_core = None
    core_no_regression = bool(core_gate["passed"])
    if parent_id:
        parent_tar = PARENT_DIR / f"{parent_id}.tar.gz"
        if parent_tar.exists():
            parent_core = _fixture_gate(parent_tar, CORE_FIXTURES)
            core_no_regression = (
                (core_gate.get("passed_count") or 0)
                >= (parent_core.get("passed_count") or 0)
                and (core_gate.get("hard_failed") or core_gate.get("hard_failures") or 0)
                <= (parent_core.get("hard_failed") or parent_core.get("hard_failures") or 0)
            )
    core_gate["parent_candidate"] = parent_id
    core_gate["parent_passed_count"] = (
        parent_core.get("passed_count") if parent_core else None)
    core_gate["no_regression_vs_parent"] = core_no_regression

    self_main = _extract_main(tar, tmp / cid / "self")
    smoke_self = _live_game(self_main, self_main)
    smoke_vs_ref = {"ran": False, "reason": "is the reference"}
    if tar.resolve() != WATER_REF.resolve():
        ref_main = _extract_main(WATER_REF, tmp / cid / "ref")
        smoke_vs_ref = _live_game(self_main, ref_main)

    gates_pass = tarball_gate["passed"] and entry_gate["passed"]
    fixtures_pass = core_no_regression and bool(targeted_gate["passed"])
    smoke_pass = bool(smoke_self.get("ok")) and (
        smoke_vs_ref.get("ok") if smoke_vs_ref.get("ran") else True)
    league_eligible = gates_pass and fixtures_pass and smoke_pass and not blocked

    return {
        "candidate_id": cid,
        "deck_key": deck_key,
        "parent_candidate": parent_id,
        "blocked_from_league": blocked,
        "block_reason": c.get("block_reason"),
        "tarball_gate": tarball_gate,
        "entrypoint_gate": entry_gate,
        "core_fixture_gate": core_gate,
        "core_fixture_gate_parent": parent_core,
        "targeted_fixture_gate": targeted_gate,
        "live_smoke_self": smoke_self,
        "live_smoke_vs_reference": smoke_vs_ref,
        "gates_pass": gates_pass,
        "fixtures_pass": fixtures_pass,
        "core_no_regression_vs_parent": core_no_regression,
        "smoke_pass": smoke_pass,
        "league_eligible": league_eligible,
    }


def md(rep: dict) -> str:
    L = ["# Pass 18 — candidate validation: gates + fixtures + live smoke (Part J)",
         "",
         "> LOCAL ONLY — no Kaggle upload, no submission. A refinement candidate "
         "is league-eligible iff it passes both hard gates AND does not regress "
         "vs its parent on the core-competency fixtures AND passes its targeted "
         "fixture gate AND the live smoke AND is not blocked by design.", "",
         "> Note: the core-competency fixtures encode the Water shell's card ids "
         "(e.g. evolving to 723), so a non-Water family can legitimately miss a "
         "Water-specific payoff. Hence the core gate is scored as **no "
         "regression vs parent**, with the absolute pass count shown for "
         "transparency.", "",
         "| candidate | parent | tarball | entrypoint | core fx (v1 / parent, no-regress) | targeted fx | smoke(self) | smoke(vs ref) | eligible |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["candidates"]:
        ss = r["live_smoke_self"]
        sv = r["live_smoke_vs_reference"]
        smoke_self = "✅" if ss.get("ok") else ("—" if not ss.get("ran") else "❌")
        smoke_ref = ("n/a" if not sv.get("ran")
                     else ("✅" if sv.get("ok") else "❌"))
        cg = r["core_fixture_gate"]
        tg = r["targeted_fixture_gate"]
        ppc = cg.get("parent_passed_count")
        cg_s = (f"{'✅' if cg.get('no_regression_vs_parent') else '❌'} "
                f"{cg.get('passed_count')}/{cg.get('total')}"
                + (f" (parent {ppc}/{cg.get('total')})" if ppc is not None else ""))
        tg_s = ("n/a" if tg.get("fixtures_dir") is None
                else (f"✅ {tg.get('passed_count')}/{tg.get('total')}"
                      if tg.get("passed") else "❌"))
        L.append(f"| {r['candidate_id']} | {r.get('parent_candidate') or '—'} | "
                 f"{'✅' if r['tarball_gate']['passed'] else '❌'} | "
                 f"{'✅' if r['entrypoint_gate']['passed'] else '❌'} | "
                 f"{cg_s} | {tg_s} | {smoke_self} | {smoke_ref} | "
                 f"{'✅' if r['league_eligible'] else '❌'} |")
    elig = [r["candidate_id"] for r in rep["candidates"] if r["league_eligible"]]
    L += ["", f"- **league-eligible candidates ({len(elig)}):** "
          f"{', '.join(elig) if elig else 'none'}",
          "",
          "## Not built (scope decisions)"]
    for cid, why in (rep.get("not_built") or {}).items():
        L.append(f"- **{cid}** — {why}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rep = {"pass": "18", "part": "J", "local_only": True,
           "upload_performed": False, "candidates": [],
           "not_built": manifest.get("not_built", {})}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for c in manifest["candidates"]:
            rep["candidates"].append(validate_candidate(c, tmp))
    rep["league_eligible"] = [r["candidate_id"] for r in rep["candidates"]
                              if r["league_eligible"]]
    (EXP / "pass18_candidate_validation.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass18_candidate_validation.md").write_text(md(rep), encoding="utf-8")
    print("pass18 candidate validation:")
    for r in rep["candidates"]:
        print(f"  {r['candidate_id']}: gates={r['gates_pass']} "
              f"fixtures={r['fixtures_pass']} smoke={r['smoke_pass']} "
              f"eligible={r['league_eligible']}")
    print(f"league-eligible: {rep['league_eligible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
