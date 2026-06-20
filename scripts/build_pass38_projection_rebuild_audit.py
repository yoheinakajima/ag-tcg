#!/usr/bin/env python3
"""Pass 38 (Part G) — projection rebuild audit (idempotent, ledger-sourced).

OPS / read-only over the ledger. Rebuilds ALL projections from
``data/tournament/events.jsonl`` ALONE via the existing
``scripts/build_tournament_projections.py``, then proves:

  * every expected projection file is produced,
  * the candidate registry is reconstructed from the ledger (registry_source ==
    "ledger") — i.e. event-sourcing works without reading candidate_pool.json,
  * the rebuild is **idempotent**: running it twice yields byte-identical
    projections once the volatile ``generated_at`` timestamps are normalised.

Writes data/experiments/pass38_projection_rebuild_audit.{json,md}. NO upload, NO
submit, NO push, NO root mutation, NO candidate generation.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PROJ = REPO / "data" / "tournament" / "projections"

_EXPECTED = [
    "tournament_state.json", "rankings.json", "rankings.md", "matchups.csv",
    "candidate_pool.json", "candidate_pool.md", "lineage.json", "lineage.md",
    "non_inertness.json", "non_inertness.md", "scheduler_queue.json",
    "scheduler_queue.md",
]
_TS_LINE = re.compile(r"generated[: ].*", re.IGNORECASE)


def _rebuild() -> dict:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_tournament_projections.py")],
        capture_output=True, text=True, cwd=str(REPO), timeout=180)
    out = {}
    try:
        out = json.loads(proc.stdout)
    except Exception:
        out = {"_raw": proc.stdout.strip().splitlines()[-5:]}
    out["_returncode"] = proc.returncode
    return out


def _normalize(name: str) -> str:
    """Content fingerprint with volatile timestamps removed."""
    p = PROJ / name
    if not p.is_file():
        return "<absent>"
    if name.endswith(".json"):
        obj = json.loads(p.read_text(encoding="utf-8"))

        def strip(o):
            if isinstance(o, dict):
                return {k: strip(v) for k, v in o.items() if k != "generated_at"}
            if isinstance(o, list):
                return [strip(x) for x in o]
            return o

        return json.dumps(strip(obj), sort_keys=True)
    if name.endswith(".md"):
        return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines()
                         if not _TS_LINE.search(l))
    return p.read_text(encoding="utf-8")  # csv (no timestamp)


def _fingerprints() -> dict:
    return {n: hashlib.sha256(_normalize(n).encode()).hexdigest() for n in _EXPECTED}


def main() -> int:
    run1 = _rebuild()
    present_1 = {n: (PROJ / n).is_file() for n in _EXPECTED}
    fp1 = _fingerprints()

    run2 = _rebuild()
    present_2 = {n: (PROJ / n).is_file() for n in _EXPECTED}
    fp2 = _fingerprints()

    all_present = all(present_1.values()) and all(present_2.values())
    idempotent_files = {n: (fp1[n] == fp2[n]) for n in _EXPECTED}
    idempotent = all(idempotent_files.values())
    registry_from_ledger = run1.get("registry_source") == "ledger"
    registered = run1.get("registered_candidates")

    ok = (all_present and idempotent and registry_from_ledger
          and run1.get("_returncode") == 0 and run2.get("_returncode") == 0)

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "38", "part": "G", "read_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "run1": run1, "run2": run2,
        "all_projections_present": all_present,
        "present": present_1,
        "registry_source": run1.get("registry_source"),
        "registry_from_ledger": registry_from_ledger,
        "registered_candidates": registered,
        "idempotent": idempotent,
        "idempotent_files": idempotent_files,
        "audit_ok": ok,
    }
    (EXP / "pass38_projection_rebuild_audit.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")

    md = [
        "# Pass 38 — Projection rebuild audit (Part G)", "",
        "> OPS / read-only. Projections are a pure fold over the event ledger; this "
        "audit rebuilds them twice and confirms they are complete, ledger-sourced, "
        "and idempotent. Internal diagnostics; NOT a Kaggle leaderboard.", "",
        f"- registry source: **{run1.get('registry_source')}** "
        f"(rebuilt from the ledger alone: **{yn(registry_from_ledger)}**)",
        f"- registered candidates: **{registered}**",
        f"- all expected projections present: **{yn(all_present)}**",
        f"- rebuild idempotent (timestamps normalised): **{yn(idempotent)}**",
        f"- totals: {run1.get('totals')}", "",
        "## Projection files",
        "| file | present | idempotent |", "|---|---|---|",
        *[f"| `{n}` | {yn(present_1[n])} | {yn(idempotent_files[n])} |"
          for n in _EXPECTED],
        "",
        f"## Verdict: audit_ok = **{yn(ok)}**",
    ]
    (EXP / "pass38_projection_rebuild_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"projection rebuild: ok={ok} present={all_present} idempotent={idempotent} "
          f"registry={run1.get('registry_source')} registered={registered}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
