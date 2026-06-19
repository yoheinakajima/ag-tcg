#!/usr/bin/env python3
"""Pass 17 (Part F) -- validation gates + live smoke for league candidates.

LOCAL ONLY. For every built candidate (experiments/runs_pass17/build_manifest.json)
this runs the two hard pre-flight gates plus a live cabt smoke and records, per
candidate:

  * tarball gate     -- scripts/validate_candidate_tarball.py (exactly top-level
                        main.py + deck.csv, 60-int deck, agent returns the deck on
                        the deck-selection step, no raise on malformed obs);
  * entrypoint gate  -- scripts/validate_candidate_entrypoint.py (last-callable is
                        the deck-safe agent, legal gameplay indices, stdlib-only);
  * live smoke       -- one self-mirror game + one game vs the Water reference in
                        real cabt; must reach a normal terminal status.

A candidate is LEAGUE-ELIGIBLE iff it passes both gates AND the live smoke AND is
not flagged blocked_from_league in deck_ideas.yaml. Durant is blocked by design;
its results are still recorded (and its live smoke INVALID is expected evidence
that the generic pilot cannot pilot a mill deck).

Writes data/experiments/pass17_candidate_validation.{json,md}. No upload.
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
EXP = REPO / "data" / "experiments"
MANIFEST = REPO / "experiments" / "runs_pass17" / "build_manifest.json"
WATER_REF = REPO / "data" / "submissions" / "candidates_pass17" / \
    "league_water_core_reference.tar.gz"

GAME_TIMEOUT_S = 60


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_TARBALL = _load("validate_candidate_tarball")
_ENTRY = _load("validate_candidate_entrypoint")


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


def validate_candidate(c: dict, tmp: Path) -> dict:
    tar = REPO / c["tarball"]
    cid = c["candidate_id"]
    blocked = bool(c.get("blocked_from_league"))

    tarball_gate = _run_gate(_TARBALL.validate, str(tar))
    entry_gate = _run_gate(_ENTRY.validate, str(tar), smoke=False)

    self_main = _extract_main(tar, tmp / cid / "self")
    smoke_self = _live_game(self_main, self_main)

    smoke_vs_ref = {"ran": False, "reason": "is the reference"}
    if tar.resolve() != WATER_REF.resolve():
        ref_main = _extract_main(WATER_REF, tmp / cid / "ref")
        smoke_vs_ref = _live_game(self_main, ref_main)

    gates_pass = tarball_gate["passed"] and entry_gate["passed"]
    smoke_pass = bool(smoke_self.get("ok")) and (
        smoke_vs_ref.get("ok") if smoke_vs_ref.get("ran") else True)
    league_eligible = gates_pass and smoke_pass and not blocked

    return {
        "candidate_id": cid,
        "deck_key": c.get("deck_key"),
        "blocked_from_league": blocked,
        "block_reason": c.get("block_reason"),
        "tarball_gate": tarball_gate,
        "entrypoint_gate": entry_gate,
        "live_smoke_self": smoke_self,
        "live_smoke_vs_reference": smoke_vs_ref,
        "gates_pass": gates_pass,
        "smoke_pass": smoke_pass,
        "league_eligible": league_eligible,
    }


def md(rep: dict) -> str:
    L = ["# Pass 17 — candidate validation gates + live smoke (Part F)", "",
         "> LOCAL ONLY. A candidate is league-eligible iff it passes both hard "
         "gates AND the live smoke AND is not blocked by design.", "",
         "| candidate | tarball | entrypoint | smoke(self) | smoke(vs ref) | blocked | league-eligible |",
         "|---|---|---|---|---|---|---|"]
    for r in rep["candidates"]:
        ss = r["live_smoke_self"]
        sv = r["live_smoke_vs_reference"]
        smoke_self = "✅" if ss.get("ok") else ("—" if not ss.get("ran") else "❌")
        smoke_ref = ("n/a" if not sv.get("ran")
                     else ("✅" if sv.get("ok") else "❌"))
        L.append(f"| {r['candidate_id']} | "
                 f"{'✅' if r['tarball_gate']['passed'] else '❌'} | "
                 f"{'✅' if r['entrypoint_gate']['passed'] else '❌'} | "
                 f"{smoke_self} | {smoke_ref} | "
                 f"{'yes' if r['blocked_from_league'] else 'no'} | "
                 f"{'✅' if r['league_eligible'] else '❌'} |")
    elig = [r["candidate_id"] for r in rep["candidates"] if r["league_eligible"]]
    L += ["", f"- **league-eligible candidates ({len(elig)}):** "
          f"{', '.join(elig) if elig else 'none'}"]
    blocked = [r for r in rep["candidates"] if r["blocked_from_league"]]
    if blocked:
        L += ["", "## Blocked candidates"]
        for r in blocked:
            ss = r["live_smoke_self"]
            L.append(f"- **{r['candidate_id']}** — {r.get('block_reason','').strip()}")
            L.append(f"  - live self-smoke: ran={ss.get('ran')} ok={ss.get('ok')} "
                     f"statuses={ss.get('statuses')} (illegal play under the generic "
                     f"pilot reinforces the block)")
    L.append("")
    return "\n".join(L)


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rep = {"pass": "17", "part": "F", "local_only": True, "candidates": []}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for c in manifest["candidates"]:
            rep["candidates"].append(validate_candidate(c, tmp))
    rep["league_eligible"] = [r["candidate_id"] for r in rep["candidates"]
                              if r["league_eligible"]]
    (EXP / "pass17_candidate_validation.json").write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    (EXP / "pass17_candidate_validation.md").write_text(md(rep), encoding="utf-8")
    print("candidate validation:")
    for r in rep["candidates"]:
        print(f"  {r['candidate_id']}: gates={r['gates_pass']} "
              f"smoke={r['smoke_pass']} eligible={r['league_eligible']}")
    print(f"league-eligible: {rep['league_eligible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
