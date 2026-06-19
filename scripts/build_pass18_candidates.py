#!/usr/bin/env python3
"""Pass 18 (Part I) — build the Pass-18 deck candidates.

LOCAL ONLY. Scope is deliberately narrow:

  * ``league_dragapult_spread_v1`` — the SAME Dragapult deck as Pass 17, recompiled
    against the light-refinement playbook (playbooks/pass18_dragapult_spread_v1.yaml).
    Deck cards are byte-identical to Pass 17; only the embedded playbook roles differ.

NOT built (by design, justified upstream):
  * ``league_raging_bolt_aggro_v1`` — the Part-D diagnosis showed the failure is
    deck/structural, NOT an energy/tempo pilot gap (the pilot already attaches the
    correct energy and attacks). Parts E/F are skipped, so no aggro candidate exists.
  * ``water_core_reference_v1`` — Part H confirmed no Water change; the Pass-17
    reference is carried forward unchanged.

Every candidate reuses the exact deck-safe base of the proven
``core_pilot_water_v2_runtime`` main.py and the proven build path
(extract base -> swap embedded deck -> compile override with runtime contexts).
Tarballs hold top-level main.py + deck.csv ONLY. No upload, no GitHub push.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.pilot.compiler import (
    compile_candidate_source, load_playbook, make_tarball)

# Reuse the Pass-17 builder's proven helpers verbatim.
import importlib.util as _ilu
_p17_spec = _ilu.spec_from_file_location(
    "build_pass17_candidates",
    Path(__file__).resolve().parent / "build_pass17_candidates.py")
_p17 = _ilu.module_from_spec(_p17_spec)
_p17_spec.loader.exec_module(_p17)  # type: ignore[union-attr]

REPO = Path(__file__).resolve().parents[1]
V2_TARBALL = _p17.V2_TARBALL
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass18"
RUNS_ROOT = REPO / "experiments" / "runs_pass18"

# Pass-18 candidates. Dragapult deck cards are identical to Pass 17.
CANDIDATES = {
    "dragapult_spread_v1": {
        "candidate_id": "league_dragapult_spread_v1",
        "parent_candidate": "league_dragapult_spread",
        "playbook": "playbooks/pass18_dragapult_spread_v1.yaml",
        "runtime_contexts": [1, 2, 7, 8, 38],
        "cards": {119: 4, 120: 3, 121: 4, 131: 2, 133: 2, 1079: 4, 1231: 4,
                  1224: 4, 1121: 4, 1086: 4, 1182: 4, 1097: 4, 5: 11, 2: 6},
    },
}


def build_one(key: str, spec: dict) -> dict:
    candidate_id = spec["candidate_id"]
    contexts = tuple(int(c) for c in spec.get("runtime_contexts", [7, 8]))
    playbook = load_playbook(REPO / spec["playbook"])

    v2_main = _p17._read_tar_member(V2_TARBALL, "main.py")
    base_main = _p17.extract_base_main(v2_main)

    deck_ids = _p17.expand_deck(spec["cards"])
    base_main = _p17.swap_embedded_deck(base_main, deck_ids)
    deck_csv = "\n".join(str(c) for c in deck_ids) + "\n"
    if len(deck_ids) != 60:
        raise ValueError(f"{candidate_id}: deck has {len(deck_ids)} cards")

    src = compile_candidate_source(base_main, playbook, candidate_id,
                                   runtime_contexts=contexts)

    out_dir = RUNS_ROOT / candidate_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    tar_path = OUT_ROOT / (candidate_id + ".tar.gz")
    make_tarball(out_dir, tar_path)

    return {
        "deck_key": key,
        "candidate_id": candidate_id,
        "parent_candidate": spec.get("parent_candidate"),
        "run_dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "runtime_contexts": list(contexts),
        "playbook": spec["playbook"],
        "deck_size": len(deck_ids),
        "main_bytes": len(src),
        "upload_performed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=None, help="build only this deck key")
    args = ap.parse_args()

    built = []
    for key, spec in CANDIDATES.items():
        if args.only and key != args.only:
            continue
        info = build_one(key, spec)
        built.append(info)
        print(f"built {info['candidate_id']}: contexts={info['runtime_contexts']} "
              f"deck={info['deck_size']} -> {info['tarball']}")

    manifest = {
        "pass": "18", "part": "I", "local_only": True, "upload_performed": False,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "candidates": built,
        "not_built": {
            "league_raging_bolt_aggro_v1": "Part-D diagnosis: failure is deck/structural, not energy/tempo; Parts E/F skipped.",
            "water_core_reference_v1": "Part-H: no Water change; Pass-17 reference carried forward unchanged.",
        },
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest: {len(built)} candidate(s) -> "
          f"{(RUNS_ROOT / 'build_manifest.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
