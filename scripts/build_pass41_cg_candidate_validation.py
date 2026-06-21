#!/usr/bin/env python3
"""Part F — validate the owned cg_typed candidate across BOTH lanes.

Asserts the two validation lanes stay separate for the PASS-41 candidate:

  1. cg_typed lane (``validate_cg_typed_tarball.py``) ACCEPTS the candidate
     (static PASS; import-smoke recorded separately, never gating).
  2. The stdlib lanes (``validate_candidate_tarball.py`` +
     ``validate_candidate_entrypoint.py``) REJECT it (it ships ``cg/`` and
     ``import cg`` — correctly out-of-bounds for our Kaggle submission lane).
  3. The stdlib validators are BYTE-UNCHANGED (sha256 + git-clean), so the
     cg_typed work never weakened our submission gates.

Read-only on the candidate; never mutates root, tarballs, or the validators.
Writes data/experiments/pass41_cg_candidate_validation.{json,md}.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "data/submissions/candidates_pass41/cg_typed_mono_lightning_miraidon_policy_v1.tar.gz"
V_CG = ROOT / "scripts/validate_cg_typed_tarball.py"
V_STD_TAR = ROOT / "scripts/validate_candidate_tarball.py"
V_STD_ENTRY = ROOT / "scripts/validate_candidate_entrypoint.py"


def _run(args: list[str]) -> dict:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return {"returncode": proc.returncode,
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_clean(p: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain", str(p)],
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
        return out == ""
    except Exception:
        return False


def main() -> int:
    if not CAND.exists():
        raise SystemExit(f"candidate tarball not found: {CAND}")

    cg_static = _run([sys.executable, str(V_CG), str(CAND)])
    cg_smoke = _run([sys.executable, str(V_CG), str(CAND), "--import-smoke"])
    std_tar = _run([sys.executable, str(V_STD_TAR), str(CAND)])
    std_entry = _run([sys.executable, str(V_STD_ENTRY), str(CAND)])

    import_smoke_line = next(
        (ln.strip() for ln in cg_smoke["stdout"].splitlines()
         if "import-smoke" in ln), "")

    rec = {
        "pass": 41, "part": "F",
        "candidate": str(CAND.relative_to(ROOT)),
        "candidate_sha256": _sha(CAND),
        "cg_typed_lane": {
            "static_returncode": cg_static["returncode"],
            "static_pass": cg_static["returncode"] == 0,
            "static_stdout": cg_static["stdout"],
            "import_smoke_stdout": import_smoke_line,
        },
        "stdlib_lane_rejects": {
            "validate_candidate_tarball": {
                "returncode": std_tar["returncode"],
                "rejected": std_tar["returncode"] != 0,
                "stdout": std_tar["stdout"],
            },
            "validate_candidate_entrypoint": {
                "returncode": std_entry["returncode"],
                "rejected": std_entry["returncode"] != 0,
                "stdout": std_entry["stdout"],
            },
        },
        "validators_unchanged": {
            "validate_cg_typed_tarball.py": {
                "sha256": _sha(V_CG), "git_clean": _git_clean(V_CG)},
            "validate_candidate_tarball.py": {
                "sha256": _sha(V_STD_TAR), "git_clean": _git_clean(V_STD_TAR)},
            "validate_candidate_entrypoint.py": {
                "sha256": _sha(V_STD_ENTRY), "git_clean": _git_clean(V_STD_ENTRY)},
        },
    }
    rec["lanes_separated"] = bool(
        rec["cg_typed_lane"]["static_pass"]
        and rec["stdlib_lane_rejects"]["validate_candidate_tarball"]["rejected"]
        and rec["stdlib_lane_rejects"]["validate_candidate_entrypoint"]["rejected"])
    rec["stdlib_validators_byte_unchanged"] = all(
        v["git_clean"] for v in rec["validators_unchanged"].values())
    rec["ok"] = rec["lanes_separated"] and rec["stdlib_validators_byte_unchanged"]

    (ROOT / "data/experiments/pass41_cg_candidate_validation.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")

    md = [
        "# Pass 41 (Part F) — cg_typed Candidate Validation (two-lane separation)",
        "",
        "_The cg_typed lane is a benchmark-only lane. It NEVER gates, relaxes, or",
        "touches our strict stdlib Kaggle-submission lane._",
        "",
        f"- **candidate:** `{rec['candidate']}` (sha256 `{rec['candidate_sha256']}`)",
        "",
        "## cg_typed lane — ACCEPTS",
        f"- static: {'PASS' if rec['cg_typed_lane']['static_pass'] else 'FAIL'} — "
        f"`{rec['cg_typed_lane']['static_stdout']}`",
        f"- {rec['cg_typed_lane']['import_smoke_stdout'] or 'import-smoke: (n/a)'}",
        "",
        "## stdlib lanes — correctly REJECT (out-of-bounds for our submissions)",
        f"- validate_candidate_tarball: "
        f"{'REJECTED' if rec['stdlib_lane_rejects']['validate_candidate_tarball']['rejected'] else 'ACCEPTED?!'}"
        f" — `{rec['stdlib_lane_rejects']['validate_candidate_tarball']['stdout']}`",
        f"- validate_candidate_entrypoint: "
        f"{'REJECTED' if rec['stdlib_lane_rejects']['validate_candidate_entrypoint']['rejected'] else 'ACCEPTED?!'}"
        f" — `{rec['stdlib_lane_rejects']['validate_candidate_entrypoint']['stdout']}`",
        "",
        "## stdlib validators byte-unchanged",
    ]
    for name, v in rec["validators_unchanged"].items():
        md.append(f"- `{name}`: git_clean={v['git_clean']} sha256=`{v['sha256']}`")
    md += [
        "",
        f"**lanes_separated:** {rec['lanes_separated']}  ·  "
        f"**stdlib_validators_byte_unchanged:** {rec['stdlib_validators_byte_unchanged']}"
        f"  ·  **ok:** {rec['ok']}",
        "",
    ]
    (ROOT / "data/experiments/pass41_cg_candidate_validation.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"lanes_separated": rec["lanes_separated"],
                      "stdlib_validators_byte_unchanged": rec["stdlib_validators_byte_unchanged"],
                      "ok": rec["ok"]}, indent=2))
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
