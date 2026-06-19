#!/usr/bin/env python3
"""Pass 25 (Part G) — aggregate candidate validation / eligibility. LOCAL ONLY.

Composes the single eligibility verdict per candidate from the independent gates,
re-running the cheap stdlib validators in-process and reading the previously
written gate reports:

  * tarball validator      (scripts/validate_candidate_tarball.py)
  * entrypoint validator   (scripts/validate_candidate_entrypoint.py)
  * core-competency gate    (data/reports/pass25/<id>_core_competency.json)
  * board-safety gate       (data/reports/pass25/<id>_pass22_water_board_safety.json)
  * pass25 hardening gate   (data/experiments/pass25_hardening_gate.json)
  * live cabt smoke         (data/experiments/pass25_live_smoke.json)

ELIGIBILITY (for the Part-J decision; eligibility != promotion):
    tarball_valid AND entrypoint_valid AND core_gate_ok AND board_safety_ok
    AND hardening_gate_ok AND smoke_clean.

Run the prerequisite gates/smoke first (run_core_competency_gate.py x2,
run_pass25_hardening_gate.py, run_pass25_live_smoke.py). Writes
data/experiments/pass25_candidate_validation.{json,md}. Exit non-zero iff any
candidate is ineligible. No upload, no root edits.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

EXP = REPO / "data" / "experiments"
REPORTS = REPO / "data" / "reports" / "pass25"

CANDIDATES = [
    ("deckout_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25" / "deckout_guard_v1.tar.gz"),
    ("prize_liability_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25"
     / "prize_liability_guard_v1.tar.gz"),
    ("hybrid_guard_v1",
     REPO / "data" / "submissions" / "candidates_pass25" / "hybrid_guard_v1.tar.gz"),
]


def _load_validator(fname: str):
    spec = importlib.util.spec_from_file_location(
        fname.replace(".py", ""), REPO / "scripts" / fname)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    tarball_v = _load_validator("validate_candidate_tarball.py")
    entry_v = _load_validator("validate_candidate_entrypoint.py")

    hardening = _read_json(EXP / "pass25_hardening_gate.json") or {}
    smoke = _read_json(EXP / "pass25_live_smoke.json") or {}
    hard_cands = hardening.get("candidates", {})
    smoke_cands = (smoke.get("results") or {})

    rows = []
    for cid, tar in CANDIDATES:
        tb_ok = tar.exists() and tarball_v.validate(str(tar)) == 0
        ep_ok = tar.exists() and entry_v.validate(str(tar)) == 0

        core = _read_json(REPORTS / f"{cid}_core_competency.json") or {}
        board = _read_json(REPORTS / f"{cid}_pass22_water_board_safety.json") or {}
        core_ok = bool(core.get("ok"))
        board_ok = bool(board.get("ok"))

        hard = hard_cands.get(cid, {})
        hard_ok = bool(hard.get("ok"))
        hard_hf = hard.get("applicable_hard_failures")

        sm = smoke_cands.get(cid, {})
        smoke_clean = bool(sm.get("clean"))
        smoke_bad = sm.get("all_bad_statuses") or []

        eligible = (tb_ok and ep_ok and core_ok and board_ok and hard_ok
                    and smoke_clean)
        rows.append({
            "candidate_id": cid,
            "tarball": str(tar.relative_to(REPO)),
            "tarball_valid": tb_ok,
            "entrypoint_valid": ep_ok,
            "core_gate_ok": core_ok,
            "core_hard_failures": core.get("hard_failures"),
            "board_safety_ok": board_ok,
            "board_hard_failures": board.get("hard_failures"),
            "hardening_gate_ok": hard_ok,
            "hardening_applicable_hard_failures": hard_hf,
            "smoke_clean": smoke_clean,
            "smoke_bad_statuses": smoke_bad,
            "eligible": eligible,
        })

    all_eligible = all(r["eligible"] for r in rows)
    report = {
        "pass": "25", "part": "G", "local_only": True, "no_upload": True,
        "upload_performed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eligibility_rule": ("tarball_valid AND entrypoint_valid AND core_gate_ok "
                             "AND board_safety_ok AND hardening_gate_ok AND smoke_clean"),
        "note": ("Eligibility is a SAFETY/VALIDITY bar for inclusion in the Part-I "
                 "eval, NOT a promotion or upload decision. All numbers local/"
                 "surrogate; never equal Kaggle."),
        "all_eligible": all_eligible,
        "candidates": rows,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass25_candidate_validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    cols = ["tarball_valid", "entrypoint_valid", "core_gate_ok", "board_safety_ok",
            "hardening_gate_ok", "smoke_clean", "eligible"]
    L = ["# Pass 25 — Candidate validation / eligibility (Part G)", "",
         "> LOCAL ONLY — eligibility is a validity/safety bar, NOT promotion.", "",
         f"- generated: {report['generated_at']}",
         f"- rule: `{report['eligibility_rule']}`",
         f"- all eligible: **{all_eligible}**", "",
         "| candidate | " + " | ".join(c.replace('_', ' ') for c in cols) + " |",
         "|---|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        L.append("| " + r["candidate_id"] + " | "
                 + " | ".join(("yes" if r[c] else "NO") for c in cols) + " |")
    L += ["", report["note"], ""]
    (EXP / "pass25_candidate_validation.md").write_text("\n".join(L), encoding="utf-8")

    for r in rows:
        print(f"{r['candidate_id']:28} eligible={r['eligible']} "
              f"(tb={r['tarball_valid']} ep={r['entrypoint_valid']} "
              f"core={r['core_gate_ok']} board={r['board_safety_ok']} "
              f"hard={r['hardening_gate_ok']} smoke={r['smoke_clean']})")
    print(f"\nall_eligible={all_eligible}\n"
          f"wrote {EXP / 'pass25_candidate_validation.json'}")
    return 0 if all_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
