#!/usr/bin/env python3
"""Pass 27 (Part F) -- build the multi-archetype portfolio candidates.

LOCAL ONLY. Every candidate reuses the *exact* deck-safe base of the proven
``core_pilot_water_v2_runtime`` main.py (the Pass-8 effect-safety + deck-selection
wrapper, last-callable entrypoint). Per deck we:

  * build the 60-card deck.csv from experiments/pass27_portfolio_decks.yaml
    (validated ids only);
  * for non-Water decks, swap the embedded fallback deck (_EMBEDDED_DECK) so the
    deck-safety block reflects THIS candidate's own deck (render_deck_safety_block);
  * load the deck's pass17/pass27 playbook (card roles only);
  * compile the appended core-pilot override with the deck's runtime contexts;
  * write a candidate dir + tarball (top-level main.py + deck.csv ONLY).

The Water reference reuses v2's deck.csv byte-for-byte. Durant is BUILT (legality)
but marked blocked_from_league -- it is excluded from the league by the runner
(its deckout win condition needs special triggers the generic pilot lacks).

No upload, no submission, no GitHub push. stdlib-only runtime in the artifact.
Writes data/submissions/candidates_pass27/*.tar.gz + experiments/runs_pass27/ +
data/experiments/pass27_candidate_manifest.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.pilot.compiler import (
    compile_candidate_source, load_playbook, make_tarball)
from ptcg_activegraph.experiments.generator import (
    render_deck_safety_block, _DECK_SAFETY_MARKER)

import yaml  # type: ignore

REPO = Path(__file__).resolve().parents[1]
V2_TARBALL = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"
REGISTRY = REPO / "experiments" / "pass27_portfolio_decks.yaml"
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass27"
RUNS_ROOT = REPO / "experiments" / "runs_pass27"
EXP = REPO / "data" / "experiments"
OVERRIDE_MARKER = "# === PASS14 CORE-PILOT OVERRIDE:"

SOURCE_TARBALLS = {
    "core_pilot_water_v2_runtime": V2_TARBALL,
}


def _read_tar_member(tar_path: Path, name: str) -> str:
    with tarfile.open(tar_path, "r:gz") as tar:
        m = tar.extractfile(name)
        if m is None:
            raise FileNotFoundError(f"{name} not in {tar_path}")
        return m.read().decode("utf-8")


def extract_base_main(v2_main: str) -> str:
    idx = v2_main.find(OVERRIDE_MARKER)
    if idx < 0:
        raise RuntimeError("override marker not found in v2 main.py")
    line_start = v2_main.rfind("\n", 0, idx)
    base = v2_main[: line_start if line_start >= 0 else idx]
    return base.rstrip("\n") + "\n"


def swap_embedded_deck(base_main: str, deck_ids: list[int]) -> str:
    marker_idx = base_main.find(_DECK_SAFETY_MARKER)
    if marker_idx < 0:
        raise RuntimeError("deck-safety marker not found in base main.py")
    line_start = base_main.rfind("\n", 0, marker_idx)
    head = base_main[: line_start if line_start >= 0 else marker_idx]
    new_block = render_deck_safety_block(deck_ids)
    return head.rstrip("\n") + "\n" + new_block.lstrip("\n")


def expand_deck(cards: dict) -> list[int]:
    ids: list[int] = []
    for raw_id, count in sorted(((int(k), int(v)) for k, v in cards.items())):
        ids.extend([raw_id] * count)
    if len(ids) != 60:
        raise ValueError(f"deck expands to {len(ids)} cards, need 60")
    return ids


def build_one(key: str, spec: dict) -> dict:
    candidate_id = spec["candidate_id"]
    contexts = tuple(int(c) for c in spec.get("runtime_contexts", [7, 8]))
    playbook_path = REPO / spec["playbook"]
    playbook = load_playbook(playbook_path)

    v2_main = _read_tar_member(V2_TARBALL, "main.py")
    base_main = extract_base_main(v2_main)

    deck_source = spec.get("deck_source")
    if deck_source:
        src_tar = SOURCE_TARBALLS[deck_source]
        deck_csv = _read_tar_member(src_tar, "deck.csv")
        deck_ids = [int(x) for x in deck_csv.splitlines() if x.strip()]
    else:
        deck_ids = expand_deck(spec["cards"])
        base_main = swap_embedded_deck(base_main, deck_ids)
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
        "family": spec.get("family"),
        "archetype": spec.get("archetype"),
        "role": spec.get("role"),
        "run_dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)),
        "runtime_contexts": list(contexts),
        "playbook": spec["playbook"],
        "deck_source": deck_source,
        "deck_size": len(deck_ids),
        "blocked_from_league": bool(spec.get("blocked_from_league")),
        "block_reason": (spec.get("block_reason") or "").strip() or None,
        "main_bytes": len(src),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=None, help="build only this deck key")
    args = ap.parse_args()

    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    decks = reg.get("decks") or {}
    built: list[dict] = []
    blocked: list[dict] = []
    for key, spec in decks.items():
        if not spec.get("buildable"):
            blocked.append({"deck_key": key, "candidate_id": spec.get("candidate_id"),
                            "reason": "not buildable (legality/ids failed validation)"})
            continue
        if args.only and key != args.only:
            continue
        info = build_one(key, spec)
        built.append(info)
        flag = " [BLOCKED FROM LEAGUE]" if info["blocked_from_league"] else ""
        print(f"built {info['candidate_id']}{flag}: "
              f"contexts={info['runtime_contexts']} deck={info['deck_size']} "
              f"-> {info['tarball']}")

    manifest = {
        "pass": "27", "part": "F", "local_only": True, "no_upload": True,
        "upload_performed": False, "github_push_performed": False,
        "no_invented_ids": True,
        "root_main_py_untouched": True, "root_deck_csv_untouched": True,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "candidates_built": built,
        "candidates_not_built": blocked,
        "league_blocked": [b["candidate_id"] for b in built
                           if b["blocked_from_league"]],
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (EXP / "pass27_candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    L = ["# Pass 27 — Candidate build manifest (Part F)", "",
         "> LOCAL ONLY. No upload, no GitHub push, no invented ids. Root "
         "`main.py`/`deck.csv` untouched.", "",
         f"- base: `{manifest['base_from']}`",
         f"- candidates built: **{len(built)}**",
         f"- blocked from league (built but excluded): "
         f"**{manifest['league_blocked']}**", "",
         "| candidate | family | archetype | deck | contexts | blocked | tarball |",
         "|---|---|---|---|---|---|---|"]
    for b in built:
        L.append(f"| `{b['candidate_id']}` | {b['family']} | {b['archetype']} | "
                 f"{b['deck_size']} | {b['runtime_contexts']} | "
                 f"{b['blocked_from_league']} | `{b['tarball']}` |")
    for b in built:
        if b["blocked_from_league"]:
            L += ["", f"### League-blocked — `{b['candidate_id']}`", b["block_reason"] or ""]
    L.append("")
    (EXP / "pass27_candidate_manifest.md").write_text("\n".join(L), encoding="utf-8")

    print(f"\nmanifest: {len(built)} candidates -> "
          f"{(EXP / 'pass27_candidate_manifest.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
