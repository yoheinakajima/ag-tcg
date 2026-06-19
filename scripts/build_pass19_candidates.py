#!/usr/bin/env python3
"""Pass 19 (Part F) — build the evidence-justified Dragapult ablations.

LOCAL ONLY. NO upload, NO GitHub push. These two candidates are built ONLY because the
Pass-19 forensic trace + decision-delta justify them (see data/experiments/
pass19_dragapult_parent_child_trace and pass19_dragapult_decision_delta):

  * ``league_dragapult_v1_search_only`` — drops the ``draw_support`` role alias, keeps
    ``search_cards``. This is the TARGETED REVERT of the diagnosed parent-H2H regression
    cause (the discard self-harm). Expected to recover the parent head-to-head.
  * ``league_dragapult_v1_draw_only``   — drops the ``search_cards`` role alias, keeps
    ``draw_support``. DIAGNOSTIC isolation; expected to reproduce the regression.

A dedicated ``H2H-guard``/`#4` variant is intentionally NOT built: it would be redundant
with ``search_only`` (both remove the draw_support discard bias), and Pass 19 forbids
broad Main overrides. This is documented in the manifest's ``not_built`` block.

Every candidate reuses the EXACT deck-safe base of ``core_pilot_water_v2_runtime`` and the
proven build path (extract base -> swap embedded deck -> compile override with runtime
contexts). Deck cards are byte-identical to league_dragapult_spread_v1. Tarballs hold
top-level main.py + deck.csv ONLY. No invented ids. No deck change.
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
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass19"
RUNS_ROOT = REPO / "experiments" / "runs_pass19"

# Deck cards identical to league_dragapult_spread_v1 (and the byte-identical parent).
_DRAGAPULT_DECK = {119: 4, 120: 3, 121: 4, 131: 2, 133: 2, 1079: 4, 1231: 4,
                   1224: 4, 1121: 4, 1086: 4, 1182: 4, 1097: 4, 5: 11, 2: 6}

CANDIDATES = {
    "dragapult_v1_search_only": {
        "candidate_id": "league_dragapult_v1_search_only",
        "parent_candidate": "league_dragapult_spread_v1",
        "playbook": "playbooks/pass19_dragapult_v1_search_only.yaml",
        "runtime_contexts": [1, 2, 7, 8, 38],
        "cards": dict(_DRAGAPULT_DECK),
        "role": "targeted_revert",
    },
    "dragapult_v1_draw_only": {
        "candidate_id": "league_dragapult_v1_draw_only",
        "parent_candidate": "league_dragapult_spread_v1",
        "playbook": "playbooks/pass19_dragapult_v1_draw_only.yaml",
        "runtime_contexts": [1, 2, 7, 8, 38],
        "cards": dict(_DRAGAPULT_DECK),
        "role": "diagnostic",
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
        "role": spec.get("role"),
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
        print(f"built {info['candidate_id']} ({info['role']}): "
              f"contexts={info['runtime_contexts']} deck={info['deck_size']} "
              f"-> {info['tarball']}")

    manifest = {
        "pass": "19", "part": "F", "local_only": True, "upload_performed": False,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "justified_by": [
            "data/experiments/pass19_dragapult_parent_child_trace.json",
            "data/experiments/pass19_dragapult_decision_delta.json",
        ],
        "candidates": built,
        "not_built": {
            "league_dragapult_v1_h2h_guard": (
                "Redundant with search_only: both remove the draw_support discard "
                "bias that the decision-replay isolated as the sole behavioral delta. "
                "A bespoke H2H guard would also require a broad Main override, which "
                "Pass 19 forbids."),
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
