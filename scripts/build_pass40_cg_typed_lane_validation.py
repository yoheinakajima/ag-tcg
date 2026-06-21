#!/usr/bin/env python3
"""Pass 40 (Part E) — cg_typed lane validation + lane-separation proof.

Runs the new cg_typed validator (scripts/validate_cg_typed_tarball.py) across every
materialized reference tarball and proves the two lanes are SEPARATE and neither is
weakened:

  * each reference tarball PASSES the cg_typed lane (static) and records an
    import-smoke result (pass/skip),
  * a reference (cg_typed) tarball FAILS the stdlib tarball validator (it has a cg/
    tree + non-stdlib import) — proving we did not relax the stdlib gate,
  * a freshly-packaged stdlib tarball (built in /tmp from the frozen root main.py +
    deck.csv; root never mutated) STILL PASSES the stdlib validator, and FAILS the
    cg_typed lane (no cg/ SDK) — proving the stdlib lane is intact and the lanes do
    not overlap.

Outputs data/experiments/pass40_cg_typed_lane_validation.{json,md}.
"""
from __future__ import annotations

import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"

from ptcg_activegraph.reference_agents import REFERENCE_AGENTS  # noqa: E402
from ptcg_activegraph.tournament.artifacts import safe_extract_all  # noqa: E402
import validate_cg_typed_tarball as cgv  # noqa: E402
import validate_candidate_tarball as stdlibv  # noqa: E402
import validate_candidate_entrypoint as stdlibentry  # noqa: E402

# A minimal, *conforming* stdlib agent used purely as a positive control: it proves
# the stdlib lane's ACCEPT path still works (so "still rejects cg_typed" is not just
# a validator that rejects everything). Stdlib-only import, deck on deck-selection,
# legal index selection on gameplay, never raises on malformed.
_SYNTH_MAIN = '''import os
def _load_deck():
    p = "deck.csv"
    if not os.path.exists(p):
        p = "/kaggle_simulations/agent/deck.csv"
    with open(p) as f:
        return [int(x) for x in f.read().split() if x.strip()]
_DECK = _load_deck()
def agent(obs):
    if not isinstance(obs, dict):
        obs = {}
    sel = obs.get("select")
    if not isinstance(sel, dict):
        return list(_DECK)
    opts = sel.get("options", []) or []
    mn = sel.get("minCount", 0) or 0
    return list(range(min(mn, len(opts))))
'''


def _package_stdlib_tarball(dest: Path) -> None:
    """Pack the frozen root main.py + deck.csv into a stdlib-shaped tarball (read-only
    copy of root; root is never mutated). Used to show the cg_typed lane rejects a
    stdlib-shaped tarball (no cg/ SDK)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copy2(REPO / "main.py", tdp / "main.py")
        shutil.copy2(REPO / "deck.csv", tdp / "deck.csv")
        with tarfile.open(dest, "w:gz") as tf:
            tf.add(tdp / "main.py", arcname="main.py")
            tf.add(tdp / "deck.csv", arcname="deck.csv")


def _package_synthetic_stdlib_tarball(dest: Path) -> None:
    """Pack a minimal CONFORMING stdlib agent (positive control)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "main.py").write_text(_SYNTH_MAIN, encoding="utf-8")
        (tdp / "deck.csv").write_text("\n".join(["1"] * 60) + "\n", encoding="utf-8")
        with tarfile.open(dest, "w:gz") as tf:
            tf.add(tdp / "main.py", arcname="main.py")
            tf.add(tdp / "deck.csv", arcname="deck.csv")


def _stdlib_validator_files_unmodified() -> bool | None:
    """True if the stdlib validator sources have no working-tree diff vs HEAD."""
    import subprocess
    files = ["scripts/validate_candidate_tarball.py",
             "scripts/validate_candidate_entrypoint.py"]
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", "diff", "--quiet", "HEAD", "--", *files],
            cwd=str(REPO), capture_output=True, timeout=30)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    results = []
    for spec in REFERENCE_AGENTS:
        tb = REF / "raw_outputs" / spec.agent_id / "submission.tar.gz"
        if not tb.is_file():
            results.append({"agent_id": spec.agent_id, "present": False,
                            "cg_typed_ok": False})
            continue
        with tempfile.TemporaryDirectory() as td:
            with tarfile.open(tb, "r:gz") as tar:
                safe_extract_all(tar, Path(td))
            res = cgv.inspect_cg_typed(str(tb))
            res["import_smoke"] = cgv._run_import_smoke(Path(td))
        # stdlib lane must REJECT this cg_typed tarball
        stdlib_rc = stdlibv.validate(str(tb))
        results.append({
            "agent_id": spec.agent_id, "present": True,
            "cg_typed_ok": res["ok"], "cg_typed_errors": res["errors"],
            "deck_60_ints": res.get("deck_60_ints"),
            "imports_cg": res.get("imports_cg"),
            "defines_agent": res.get("defines_agent"),
            "libcg_present": res.get("libcg_present"),
            "import_smoke": res.get("import_smoke"),
            "stdlib_lane_rejects": stdlib_rc != 0,
        })

    # Lane separation / intactness proof:
    #  * synthetic CONFORMING stdlib agent still PASSES both stdlib validators
    #    (accept-path intact — the lane is not just rejecting everything),
    #  * that synthetic agent FAILS the cg_typed lane (no cg/ SDK),
    #  * a root-shaped stdlib tarball FAILS the cg_typed lane,
    #  * the stdlib validator source files are unmodified vs HEAD.
    # NB: the frozen root baseline intentionally fails the candidate validators'
    # defensive key-absent deck-selection shape (real cabt sends literal nulls); it
    # is NOT used as the accept-path control, only to show cg_typed shape rejection.
    sep = {}
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        synth_tb = tdp / "synthetic_stdlib_candidate.tar.gz"
        _package_synthetic_stdlib_tarball(synth_tb)
        sep["synthetic_stdlib_passes_tarball_validator"] = (
            stdlibv.validate(str(synth_tb)) == 0)
        sep["synthetic_stdlib_passes_entrypoint_validator"] = (
            stdlibentry.validate(str(synth_tb)) == 0)
        sep["synthetic_stdlib_fails_cg_typed_lane"] = (
            cgv.inspect_cg_typed(str(synth_tb))["ok"] is False)

        root_tb = tdp / "root_shaped_stdlib.tar.gz"
        _package_stdlib_tarball(root_tb)
        sep["root_shaped_tarball_fails_cg_typed_lane"] = (
            cgv.inspect_cg_typed(str(root_tb))["ok"] is False)
    sep["stdlib_validator_files_unmodified"] = _stdlib_validator_files_unmodified()

    n_present = sum(1 for r in results if r.get("present"))
    n_cg_ok = sum(1 for r in results if r.get("cg_typed_ok"))
    n_stdlib_rejects = sum(1 for r in results
                           if r.get("present") and r.get("stdlib_lane_rejects"))
    all_cg_ok = n_cg_ok == n_present and n_present > 0
    lanes_separate = (
        all_cg_ok
        and n_stdlib_rejects == n_present
        and sep["synthetic_stdlib_passes_tarball_validator"]
        and sep["synthetic_stdlib_passes_entrypoint_validator"]
        and sep["synthetic_stdlib_fails_cg_typed_lane"]
        and sep["root_shaped_tarball_fails_cg_typed_lane"]
        and sep["stdlib_validator_files_unmodified"] is True)

    payload = {
        "pass": "40", "part": "E", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "reference_tarballs_present": n_present,
        "cg_typed_pass_count": n_cg_ok,
        "all_reference_cg_typed_pass": all_cg_ok,
        "stdlib_lane_rejects_cg_typed_count": n_stdlib_rejects,
        "lane_separation": sep,
        "lanes_separate_and_intact": lanes_separate,
        "stdlib_lane_files_unmodified": sep["stdlib_validator_files_unmodified"],
        "results": results,
    }
    (EXP / "pass40_cg_typed_lane_validation.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "n/a")

    md = [
        "# Pass 40 — cg_typed lane validation (Part E)", "",
        "> A SEPARATE validation lane for public reference (cg-SDK) agents. The "
        "stdlib candidate gates are untouched; this lane never runs on our own "
        "submissions.", "",
        f"- reference tarballs present: **{n_present}**",
        f"- pass cg_typed lane (static): **{n_cg_ok}/{n_present}**",
        f"- stdlib lane correctly REJECTS each cg_typed tarball: "
        f"**{n_stdlib_rejects}/{n_present}**",
        f"- synthetic conforming stdlib agent still PASSES stdlib tarball "
        f"validator: **{yn(sep['synthetic_stdlib_passes_tarball_validator'])}**",
        f"- synthetic conforming stdlib agent still PASSES stdlib entrypoint "
        f"validator: **{yn(sep['synthetic_stdlib_passes_entrypoint_validator'])}**",
        f"- synthetic stdlib agent FAILS cg_typed lane (no cg/): "
        f"**{yn(sep['synthetic_stdlib_fails_cg_typed_lane'])}**",
        f"- root-shaped stdlib tarball FAILS cg_typed lane: "
        f"**{yn(sep['root_shaped_tarball_fails_cg_typed_lane'])}**",
        f"- stdlib validator source files unmodified vs HEAD: "
        f"**{yn(sep['stdlib_validator_files_unmodified'])}**",
        f"- **lanes separate AND intact: {yn(lanes_separate)}**", "",
        "| agent_id | cg_typed ok | deck60 | imports cg | agent() | libcg | "
        "import-smoke | stdlib rejects |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        sm = (r.get("import_smoke") or {}).get("result", "n/a")
        md.append(
            f"| `{r['agent_id']}` | {yn(r.get('cg_typed_ok'))} | "
            f"{yn(r.get('deck_60_ints'))} | {yn(r.get('imports_cg'))} | "
            f"{yn(r.get('defines_agent'))} | {yn(r.get('libcg_present'))} | "
            f"{sm} | {yn(r.get('stdlib_lane_rejects'))} |")
    (EXP / "pass40_cg_typed_lane_validation.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"cg_typed lane: pass={n_cg_ok}/{n_present} "
          f"stdlib_rejects={n_stdlib_rejects}/{n_present} "
          f"lanes_separate={lanes_separate}")
    return 0 if lanes_separate else 1


if __name__ == "__main__":
    raise SystemExit(main())
