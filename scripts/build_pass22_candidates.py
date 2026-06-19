#!/usr/bin/env python3
"""Pass 22 (Part G) — build the ONE water anti-disruption candidate.

LOCAL ONLY. NO Kaggle upload, NO GitHub push. ONE candidate is built:

  * ``league_water_anti_disruption_pivot_v1`` — the proven deck-safe base of
    ``core_pilot_water_v2_runtime`` (deck reused BYTE-IDENTICAL) plus three narrow,
    flag-gated runtime hooks compiled over it:
        - emergency_backup_bench         (Main / ctx0)
        - anti_disruption_search_pivot   (ctx7)
        - preserve_backup_basic_on_discard (ctx8)

Each hook only refines WHICH option is chosen (never whether/how-many), bails to
the base on any mismatch, and is off unless its flag is set in the embedded
playbook AND its context is emitted in ``_CP_RUNTIME_CONTEXTS``. No invented ids;
no deck change (deck.csv is copied verbatim from the v2 tarball). Tarballs hold
top-level main.py + deck.csv ONLY.
"""
from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.pilot.compiler import (  # noqa: F401
    compile_candidate_source, load_playbook, make_tarball)

_p17_spec = _ilu.spec_from_file_location(
    "build_pass17_candidates",
    Path(__file__).resolve().parent / "build_pass17_candidates.py")
_p17 = _ilu.module_from_spec(_p17_spec)
_p17_spec.loader.exec_module(_p17)  # type: ignore[union-attr]

REPO = Path(__file__).resolve().parents[1]
V2_TARBALL = _p17.V2_TARBALL
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass22"
RUNS_ROOT = REPO / "experiments" / "runs_pass22"

CANDIDATE_ID = "league_water_anti_disruption_pivot_v1"
PLAYBOOK = "playbooks/pass22_water_anti_disruption_pivot.yaml"
# EXACTLY the three Pass-22 hooks: ctx0 Main emergency backup bench, ctx7 ToHand
# anti-disruption search pivot, ctx8 discard preservation. The proven water v2 base
# refines only (7, 8); Pass 22 adds the narrow ctx0 hook. Contexts 1/2/38 are NOT
# in scope -- leaving them out makes those decisions fall through to the proven base
# policy (the compiler gates every context branch on _CP_RUNTIME_CONTEXTS membership).
RUNTIME_CONTEXTS = (0, 7, 8)


def build() -> dict:
    playbook = load_playbook(REPO / PLAYBOOK)

    # Reuse the proven deck-safe base AND its deck BYTE-IDENTICAL (no deck change).
    v2_main = _p17._read_tar_member(V2_TARBALL, "main.py")
    base_main = _p17.extract_base_main(v2_main)
    deck_csv = _p17._read_tar_member(V2_TARBALL, "deck.csv")
    deck_ids = [l for l in deck_csv.splitlines() if l.strip()]
    if len(deck_ids) != 60:
        raise ValueError(f"{CANDIDATE_ID}: deck has {len(deck_ids)} cards, expected 60")

    src = compile_candidate_source(base_main, playbook, CANDIDATE_ID,
                                   runtime_contexts=RUNTIME_CONTEXTS)

    out_dir = RUNS_ROOT / CANDIDATE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    tar_path = OUT_ROOT / (CANDIDATE_ID + ".tar.gz")
    make_tarball(out_dir, tar_path)

    return {
        "candidate_id": CANDIDATE_ID,
        "based_on": "core_pilot_water_v2_runtime",
        "playbook": PLAYBOOK,
        "runtime_contexts": list(RUNTIME_CONTEXTS),
        "flags": dict(playbook.get("flags") or {}),
        "run_dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "deck_size": len(deck_ids),
        "deck_byte_identical_to": str(V2_TARBALL.relative_to(REPO)),
        "main_bytes": len(src),
        "upload_performed": False,
        "github_push_performed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    info = build()
    print(f"built {info['candidate_id']}: contexts={info['runtime_contexts']} "
          f"flags={info['flags']} deck={info['deck_size']} -> {info['tarball']}")

    manifest = {
        "pass": "22", "part": "G", "local_only": True,
        "upload_performed": False, "github_push_performed": False, "no_upload": True,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "justified_by": [
            "data/experiments/pass22_no_pokemon_loss_analysis.json",
            "data/experiments/pass22_energy_denial_analysis.json",
        ],
        "candidate": info,
        "guardrails": {
            "deck_changed": False,
            "invented_ids": False,
            "broad_main_override": False,
            "narrow_hooks_only": ["emergency_backup_bench (ctx0)",
                                  "anti_disruption_search_pivot (ctx7)",
                                  "preserve_backup_basic_on_discard (ctx8)"],
        },
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest -> {(RUNS_ROOT / 'build_manifest.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
