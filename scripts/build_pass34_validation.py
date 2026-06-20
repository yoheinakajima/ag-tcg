#!/usr/bin/env python3
"""Pass 34 (Part G) — candidate validation + live smoke. LOCAL / no upload.

For every Part-E candidate tarball this runs, honestly:
  * validate_candidate_tarball.py        (structure + legal 60-card deck);
  * validate_candidate_entrypoint.py     (last-callable invariant, no --smoke);
  * one live cabt game (both seats = the candidate) capturing per-seat status.

The live smoke is the lane-split EVIDENCE: normal-lane decks complete cleanly
under the generic pilot; special-lane decks have a legal deck (a seat can reach
DONE with it) but the generic pilot emits an illegal gameplay action piloting the
special win condition, so a seat goes INVALID. That deck-legal / pilot-illegal
split is reported verbatim, not asserted.

Writes data/experiments/pass34_candidate_validation.{json,md} and
pass34_live_smoke.{json,md}.
"""
from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
CAND_DIR = REPO / "data" / "submissions" / "candidates_pass34"
MANIFEST = EXP / "pass34_candidate_manifest.json"
VAL_JSON = EXP / "pass34_candidate_validation.json"
VAL_MD = EXP / "pass34_candidate_validation.md"
SMOKE_JSON = EXP / "pass34_live_smoke.json"
SMOKE_MD = EXP / "pass34_live_smoke.md"

TARBALL_VALIDATOR = REPO / "scripts" / "validate_candidate_tarball.py"
ENTRY_VALIDATOR = REPO / "scripts" / "validate_candidate_entrypoint.py"


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()


def _live_game(tar_path: Path) -> dict:
    """Run one cabt game (both seats = candidate); record per-seat status."""
    try:
        from kaggle_environments import make  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "skip": f"kaggle_environments unavailable: {exc!r}"}
    d = tempfile.mkdtemp()
    with tarfile.open(tar_path) as t:
        t.extractall(d)
    mp = str(Path(d) / "main.py")
    try:
        env = None
        for cfg in ({}, {"actTimeout": 30}):
            try:
                env = make("cabt", configuration=cfg)
                break
            except Exception:
                continue
        if env is None:
            return {"ran": False, "skip": "make('cabt') failed"}
        env.run([mp, mp])
        seats = []
        for i, a in enumerate(env.state):
            seats.append({"seat": i, "status": a.get("status"),
                          "reward": a.get("reward")})
        statuses = {s["status"] for s in seats}
        any_done = any(s["status"] == "DONE" for s in seats)
        any_invalid = any(s["status"] == "INVALID" for s in seats)
        clean = statuses <= {"ACTIVE", "INACTIVE", "DONE"}
        return {"ran": True, "seats": seats, "clean": clean,
                "deck_is_legal_evidence": any_done,
                "pilot_emitted_illegal_action": any_invalid}
    except Exception as exc:  # noqa: BLE001
        return {"ran": False, "error": repr(exc)}


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    built = [r for r in manifest["results"] if r.get("built")]

    val_results, smoke_results = [], []
    for r in built:
        cid = r["candidate_id"]
        tar = CAND_DIR / f"{cid}.tar.gz"
        t_rc, t_out = _run(["python3", str(TARBALL_VALIDATOR), str(tar)])
        e_rc, e_out = _run(["python3", str(ENTRY_VALIDATOR), str(tar)])
        val_results.append({
            "candidate_id": cid, "lane": r["lane"],
            "blocked_from_league": r.get("blocked_from_league", False),
            "tarball_valid": t_rc == 0, "tarball_out": t_out.splitlines()[-1:],
            "entrypoint_valid": e_rc == 0, "entrypoint_out": e_out.splitlines()[-1:],
        })

        game = _live_game(tar)
        smoke_results.append({
            "candidate_id": cid, "lane": r["lane"],
            "special_pilot_required": r.get("special_pilot_required", False),
            "blocked_from_league": r.get("blocked_from_league", False),
            **game,
        })

    val_doc = {"pass": "34", "part": "G", "no_upload": True,
               "results": val_results}
    VAL_JSON.write_text(json.dumps(val_doc, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    smoke_doc = {
        "pass": "34", "part": "G", "no_upload": True,
        "interpretation": (
            "A seat reaching DONE proves the deck is LEGAL/constructible. A seat "
            "going INVALID with that same legal deck means the GENERIC PILOT "
            "emitted an illegal gameplay action piloting the deck's win condition "
            "— i.e. a pilot mis-fit, not a deck-construction fault. Normal-lane "
            "decks complete cleanly; special-lane decks show the deck-legal / "
            "pilot-illegal split that justifies the special-pilot lane."),
        "results": smoke_results,
    }
    SMOKE_JSON.write_text(json.dumps(smoke_doc, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    L = ["# Pass 34 — Candidate Validation (Part G)", "",
         "> LOCAL / no upload. Structure + legal-deck + entrypoint-invariant "
         "checks per candidate.", "",
         "| candidate | lane | blocked_league | tarball_valid | entrypoint_valid |",
         "|---|---|---|---|---|"]
    for r in val_results:
        L.append(f"| {r['candidate_id']} | {r['lane']} | "
                 f"{r['blocked_from_league']} | {r['tarball_valid']} | "
                 f"{r['entrypoint_valid']} |")
    VAL_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    S = ["# Pass 34 — Live Smoke (Part G)", "",
         f"> {smoke_doc['interpretation']}", "",
         "| candidate | lane | special_pilot | deck_legal(DONE seen) | "
         "pilot_illegal(INVALID seen) | clean | seats |",
         "|---|---|---|---|---|---|---|"]
    for r in smoke_results:
        if not r.get("ran"):
            S.append(f"| {r['candidate_id']} | {r['lane']} | "
                     f"{r['special_pilot_required']} | - | - | - | "
                     f"{r.get('skip') or r.get('error')} |")
            continue
        seats = ", ".join(f"s{s['seat']}={s['status']}" for s in r["seats"])
        S.append(f"| {r['candidate_id']} | {r['lane']} | "
                 f"{r['special_pilot_required']} | "
                 f"{r['deck_is_legal_evidence']} | "
                 f"{r['pilot_emitted_illegal_action']} | {r['clean']} | {seats} |")
    SMOKE_MD.write_text("\n".join(S) + "\n", encoding="utf-8")

    for r in smoke_results:
        if r.get("ran"):
            print(f"{r['candidate_id']}: clean={r['clean']} "
                  f"deck_legal={r['deck_is_legal_evidence']} "
                  f"pilot_illegal={r['pilot_emitted_illegal_action']}")
        else:
            print(f"{r['candidate_id']}: smoke not run "
                  f"({r.get('skip') or r.get('error')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
