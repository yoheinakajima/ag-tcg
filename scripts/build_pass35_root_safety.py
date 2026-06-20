#!/usr/bin/env python3
"""Pass 35 (Part A) — root safety.

Verifies that root ``main.py`` and ``deck.csv`` are byte-identical to the frozen
v1 baseline and that ``package_submission.py --verify-only`` passes WITHOUT
mutating any root file. Writes evidence-derived artifacts:
- data/experiments/pass35_root_safety.json
- data/experiments/pass35_root_safety.md

Local-only, read/verify-only: no upload, no submit, no push, no root mutation.
"""
from __future__ import annotations

import filecmp
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "data" / "baselines" / "v1_kaggle_349_8"
EXP = REPO / "data" / "experiments"


def _cmp(name: str) -> bool | None:
    root_f, base_f = REPO / name, BASELINE / name
    if not root_f.exists() or not base_f.exists():
        return None
    try:
        return filecmp.cmp(root_f, base_f, shallow=False)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    main_ok = _cmp("main.py")
    deck_ok = _cmp("deck.csv")

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "package_submission.py"),
         "--verify-only"],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    verify_passed = proc.returncode == 0

    # Re-cmp AFTER the verify-only run to prove it did not mutate root files.
    main_ok_after = _cmp("main.py")
    deck_ok_after = _cmp("deck.csv")

    root_unchanged = (main_ok is True and deck_ok is True
                      and main_ok_after is True and deck_ok_after is True)
    safe = root_unchanged and verify_passed

    EXP.mkdir(parents=True, exist_ok=True)
    payload = {
        "pass": "35", "part": "A", "local_only": True, "no_upload": True,
        "upload_performed": False, "github_push": False,
        "baseline": str(BASELINE.relative_to(REPO)),
        "root_main_py_unchanged": main_ok,
        "root_deck_csv_unchanged": deck_ok,
        "root_main_py_unchanged_after_verify": main_ok_after,
        "root_deck_csv_unchanged_after_verify": deck_ok_after,
        "package_verify_only_passed": verify_passed,
        "package_verify_returncode": proc.returncode,
        "package_verify_stdout_tail": proc.stdout.strip().splitlines()[-12:],
        "root_unchanged": root_unchanged,
        "root_safe": safe,
        "stop_required": not safe,
    }
    (EXP / "pass35_root_safety.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "unverified")
    md = [
        "# Pass 35 — Root safety (Part A)", "",
        "> LOCAL ONLY — verify-only, no upload, no submit, no push, no root "
        "mutation. Internal/surrogate evidence; NOT the Kaggle leaderboard.", "",
        f"- root main.py byte-identical to baseline: **{yn(main_ok)}**",
        f"- root deck.csv byte-identical to baseline: **{yn(deck_ok)}**",
        f"- package verify-only passed: **{yn(verify_passed)}** "
        f"(returncode {proc.returncode})",
        f"- root unchanged AFTER verify-only: "
        f"main=**{yn(main_ok_after)}** deck=**{yn(deck_ok_after)}**",
        f"- overall root safe: **{yn(safe)}**",
        f"- stop required: **{yn(not safe)}**", "",
        "## package verify-only output (tail)", "```",
        *payload["package_verify_stdout_tail"], "```",
    ]
    (EXP / "pass35_root_safety.md").write_text("\n".join(md) + "\n",
                                               encoding="utf-8")
    print(f"root safety: safe={safe} main_ok={main_ok} deck_ok={deck_ok} "
          f"verify={verify_passed} stop_required={not safe}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
