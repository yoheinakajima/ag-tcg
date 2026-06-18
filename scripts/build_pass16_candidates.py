#!/usr/bin/env python3
"""Pass 16 -- build the core_pilot_water_v3_context candidate.

v3 reuses the *exact* deck-safe base of the Pass 14 ``core_pilot_water_v2_runtime``
candidate (same deck.csv, same Pass-8 effect-safety + deck-selection wrapper, same
last-callable entrypoint), and only swaps the appended PASS14 core-pilot override
block for a freshly compiled one that wires the Pass 16 cross-source-confirmed
contexts:

    _CP_RUNTIME_CONTEXTS = (1, 2, 7, 8, 38)
      1  = setup place active  (Kyogre > Snover; count fixed at 1)
      2  = setup place bench   (count preserved from base; reorder which)
      7  = ToHand search       (already wired in v2)
      8  = discard             (already wired in v2)
      38 = numeric draw-count  (low-deck draw-avoid safety guard)

The base is recovered by splitting v2's ``main.py`` at the override marker, so the
deck-selection-safe entrypoint and deck list are byte-identical to the proven v2
artifact; only the override (and the embedded, now-extended decision layer) change.

LOCAL ONLY: writes a candidate dir + tarball under data/submissions/candidates_pass16/.
No upload, no submission, no GitHub push. Tarball = top-level main.py + deck.csv only.
"""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.pilot.compiler import (
    compile_candidate_source, load_playbook, make_tarball)

REPO = Path(__file__).resolve().parents[1]
V2_TARBALL = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"
COMBO_TARBALL = REPO / "data" / "submissions" / "candidates" / \
    "combo_full_safety_v3_fixed.tar.gz"
PLAYBOOK = REPO / "playbooks" / "v2_kyogre_abomasnow_core_pilot.yaml"
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass16"
OVERRIDE_MARKER = "# === PASS14 CORE-PILOT OVERRIDE:"

V3_ID = "core_pilot_water_v3_context"
V3_CONTEXTS = (1, 2, 7, 8, 38)
CLONE_ID = "combo_full_safety_v3_entrypoint_safe_local"

# Appended block that makes a FRESH-named callable the last top-level callable, so
# kaggle_environments.agent.get_last_callable selects the deck-safety ``agent``
# (re-binding ``agent`` does NOT move it to the end of the module namespace, which
# is why the original combo anchor leaks ``_PRE_DECK_SAFETY_AGENT`` as the
# entrypoint and is INVALID at deck selection).
_CLONE_BLOCK = '''

# === PASS16 ENTRYPOINT-SAFE ANCHOR CLONE: {clone_id} ===
# Same deck + same combo_full_safety strategy as combo_full_safety_v3_fixed. The
# only change is this trailing block: it binds the proven deck-safe ``agent`` to a
# fresh name and exposes it as the LAST top-level callable so the cabt runner picks
# the correct entrypoint (the original re-bound ``agent`` left a pre-deck-safety
# callable as last, which returned [] at deck selection -> INVALID).
_ANCHOR_DECK_SAFE_AGENT = agent


def anchor_safe_agent(obs_dict):
    return _ANCHOR_DECK_SAFE_AGENT(obs_dict)
# === END PASS16 ENTRYPOINT-SAFE ANCHOR CLONE ===
'''


def _read_tar_member(tar_path: Path, name: str) -> str:
    with tarfile.open(tar_path, "r:gz") as tar:
        m = tar.extractfile(name)
        if m is None:
            raise FileNotFoundError("%s not in %s" % (name, tar_path))
        return m.read().decode("utf-8")


def extract_base_main(v2_main: str) -> str:
    """Return v2's deck-safe base main.py (everything before the override block)."""
    idx = v2_main.find(OVERRIDE_MARKER)
    if idx < 0:
        raise RuntimeError("override marker not found in v2 main.py")
    # back up to the start of the marker's own comment line
    line_start = v2_main.rfind("\n", 0, idx)
    base = v2_main[: line_start if line_start >= 0 else idx]
    return base.rstrip("\n") + "\n"


def build(candidate_id: str, contexts: tuple) -> dict:
    v2_main = _read_tar_member(V2_TARBALL, "main.py")
    deck_csv = _read_tar_member(V2_TARBALL, "deck.csv")
    base_main = extract_base_main(v2_main)
    playbook = load_playbook(PLAYBOOK)
    src = compile_candidate_source(base_main, playbook, candidate_id,
                                   runtime_contexts=contexts)
    out_dir = OUT_ROOT / candidate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")
    tar_path = OUT_ROOT / (candidate_id + ".tar.gz")
    make_tarball(out_dir, tar_path)
    return {
        "candidate_id": candidate_id,
        "dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "runtime_contexts": list(contexts),
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "main_bytes": len(src),
        "deck_unchanged_vs_v2": deck_csv == _read_tar_member(V2_TARBALL, "deck.csv"),
    }


def build_anchor_clone(candidate_id: str) -> dict:
    """Build an entrypoint-safe clone of combo_full_safety_v3_fixed."""
    combo_main = _read_tar_member(COMBO_TARBALL, "main.py")
    deck_csv = _read_tar_member(COMBO_TARBALL, "deck.csv")
    src = combo_main.rstrip("\n") + "\n" + _CLONE_BLOCK.format(clone_id=candidate_id)
    out_dir = OUT_ROOT / candidate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")
    tar_path = OUT_ROOT / (candidate_id + ".tar.gz")
    make_tarball(out_dir, tar_path)
    return {
        "candidate_id": candidate_id,
        "dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "base_from": str(COMBO_TARBALL.relative_to(REPO)),
        "main_bytes": len(src),
        "deck_unchanged_vs_combo": deck_csv == _read_tar_member(COMBO_TARBALL, "deck.csv"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate-id", default=V3_ID)
    ap.add_argument("--contexts", default=",".join(str(c) for c in V3_CONTEXTS),
                    help="comma-separated runtime contexts")
    ap.add_argument("--mode", choices=("v3", "clone", "both"), default="v3")
    args = ap.parse_args()
    contexts = tuple(int(x) for x in args.contexts.split(",") if x.strip())
    if args.mode in ("v3", "both"):
        info = build(args.candidate_id, contexts)
        print("[v3]")
        for k, v in info.items():
            print(f"  {k}: {v}")
    if args.mode in ("clone", "both"):
        cinfo = build_anchor_clone(CLONE_ID)
        print("[anchor clone]")
        for k, v in cinfo.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
