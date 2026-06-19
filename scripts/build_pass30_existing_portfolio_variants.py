#!/usr/bin/env python3
"""Pass 30 (Part E) — build/reuse the existing-portfolio hardening candidates.

LOCAL ONLY. No upload, no submit, no GitHub push, no invented ids, no opponent
clones. Reads experiments/pass30_existing_portfolio.yaml and produces a single
self-contained candidate set under data/submissions/candidates_pass30/:

  * REUSED candidates (kind: reused_prior_candidate) are copied VERBATIM from
    their prior-pass source tarball (the original artifact is never modified); the
    copy is verified to be top-level main.py + deck.csv only, exactly 60 cards.
  * BUILT candidates (kind: deck_skeleton, build: true) — the two Raging Bolt
    structural variants — are compiled from the proven Water v2 deck-safe base
    (the same chain Pass 27 used), swapping in THIS variant's 60-card deck. Only
    validated card ids from our own Raging Bolt / Ogerpon idea are used.

Every emitted deck is checked: exactly 60 cards, non-basic-energy <= 4 copies,
every id present in the card DB (no invented ids), tarball top-level only.

Writes experiments/runs_pass30/<cid>/, data/submissions/candidates_pass30/<cid>.tar.gz,
and data/experiments/pass30_candidate_manifest.{json,md}.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import _bootstrap  # noqa: F401,E402
import yaml  # type: ignore  # noqa: E402
from ptcg_activegraph.pilot.compiler import (  # noqa: E402
    compile_candidate_source, load_playbook, make_tarball)
from ptcg_activegraph.experiments.generator import (  # noqa: E402
    render_deck_safety_block, _DECK_SAFETY_MARKER)

REGISTRY = REPO / "experiments" / "pass30_existing_portfolio.yaml"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
V2_TARBALL = REPO / "data" / "submissions" / "candidates_pass14" / \
    "core_pilot_water_v2_runtime.tar.gz"
OUT_ROOT = REPO / "data" / "submissions" / "candidates_pass30"
RUNS_ROOT = REPO / "experiments" / "runs_pass30"
EXP = REPO / "data" / "experiments"
OVERRIDE_MARKER = "# === PASS14 CORE-PILOT OVERRIDE:"


def _load_card_ids() -> tuple[set[int], set[int]]:
    """Return (all_ids, basic_energy_ids) from the card DB."""
    all_ids: set[int] = set()
    basic_energy: set[int] = set()
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int(row["Card ID"].strip())
            except (KeyError, ValueError):
                continue
            all_ids.add(cid)
            stage = (row.get("Stage (Pokémon)/Type (Energy and Trainer)") or "").strip()
            if stage == "Basic Energy":
                basic_energy.add(cid)
    return all_ids, basic_energy


def _read_tar_member(tar_path: Path, name: str) -> str:
    with tarfile.open(tar_path, "r:gz") as tar:
        m = tar.extractfile(name)
        if m is None:
            raise FileNotFoundError(f"{name} not in {tar_path}")
        return m.read().decode("utf-8")


def _tar_names(tar_path: Path) -> list[str]:
    with tarfile.open(tar_path, "r:gz") as tar:
        return tar.getnames()


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


def _expand_and_check(cards: dict, all_ids: set[int], basic_energy: set[int],
                      cid: str) -> list[int]:
    ids: list[int] = []
    for raw_id, count in sorted(((int(k), int(v)) for k, v in cards.items())):
        if raw_id not in all_ids:
            raise ValueError(f"{cid}: card id {raw_id} not in card DB (invented id)")
        if raw_id not in basic_energy and count > 4:
            raise ValueError(
                f"{cid}: non-basic-energy card {raw_id} has {count} copies (>4)")
        ids.extend([raw_id] * count)
    if len(ids) != 60:
        raise ValueError(f"{cid}: deck expands to {len(ids)} cards, need 60")
    return ids


def _verify_reused_tarball(tar_path: Path, cid: str) -> int:
    names = _tar_names(tar_path)
    if sorted(names) != ["deck.csv", "main.py"]:
        raise ValueError(f"{cid}: reused tarball not top-level only: {names}")
    deck_csv = _read_tar_member(tar_path, "deck.csv")
    deck_ids = [x for x in deck_csv.splitlines() if x.strip()]
    if len(deck_ids) != 60:
        raise ValueError(f"{cid}: reused deck has {len(deck_ids)} cards")
    return len(deck_ids)


def reuse_one(cand: dict) -> dict:
    cid = cand["candidate_id"]
    src = REPO / cand["source_tarball"]
    if not src.exists():
        return {"candidate_id": cid, "kind": "reused_prior_candidate",
                "built": False, "blocked": True,
                "reason": f"source tarball missing: {cand['source_tarball']}"}
    deck_size = _verify_reused_tarball(src, cid)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    dst = OUT_ROOT / f"{cid}.tar.gz"
    shutil.copyfile(src, dst)
    return {
        "candidate_id": cid, "family": cand.get("_family"),
        "parent_id": cand.get("parent_id"), "role": cand.get("role"),
        "kind": "reused_prior_candidate", "built": True, "blocked": False,
        "source_tarball": cand["source_tarball"],
        "tarball": str(dst.relative_to(REPO)), "deck_size": deck_size,
        "playbook": cand.get("playbook"),
        "blocked_from_league": bool(cand.get("blocked_from_league")),
        "block_reason": (cand.get("block_reason") or "").strip() or None,
    }


def build_one(cand: dict, all_ids: set[int], basic_energy: set[int]) -> dict:
    cid = cand["candidate_id"]
    contexts = tuple(int(c) for c in cand.get("runtime_contexts", [7, 8]))
    playbook = load_playbook(REPO / cand["playbook"])
    deck_ids = _expand_and_check(cand["cards"], all_ids, basic_energy, cid)

    v2_main = _read_tar_member(V2_TARBALL, "main.py")
    base_main = swap_embedded_deck(extract_base_main(v2_main), deck_ids)
    deck_csv = "\n".join(str(c) for c in deck_ids) + "\n"
    src = compile_candidate_source(base_main, playbook, cid, runtime_contexts=contexts)

    out_dir = RUNS_ROOT / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main.py").write_text(src, encoding="utf-8")
    (out_dir / "deck.csv").write_text(deck_csv, encoding="utf-8")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    tar_path = OUT_ROOT / f"{cid}.tar.gz"
    make_tarball(out_dir, tar_path)
    if sorted(_tar_names(tar_path)) != ["deck.csv", "main.py"]:
        raise ValueError(f"{cid}: built tarball not top-level only")

    return {
        "candidate_id": cid, "family": cand.get("_family"),
        "parent_id": cand.get("parent_id"), "role": cand.get("role"),
        "kind": "deck_skeleton", "built": True, "blocked": False,
        "source_tarball": None, "run_dir": str(out_dir.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)), "deck_size": len(deck_ids),
        "runtime_contexts": list(contexts), "playbook": cand["playbook"],
        "hypothesis": (cand.get("hypothesis") or "").strip() or None,
        "diff_vs_parent": cand.get("diff_vs_parent"),
        "cards": {int(k): int(v) for k, v in cand["cards"].items()},
        "blocked_from_league": False, "block_reason": None, "main_bytes": len(src),
    }


def main() -> int:
    all_ids, basic_energy = _load_card_ids()
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    families = reg.get("families") or {}

    results: list[dict] = []
    for fam_key, fam in families.items():
        for cand in fam.get("candidates", []):
            cand = {**cand, "_family": fam.get("family_id", fam_key)}
            try:
                if cand.get("kind") == "deck_skeleton" and cand.get("build"):
                    info = build_one(cand, all_ids, basic_energy)
                else:
                    info = reuse_one(cand)
            except Exception as exc:  # noqa: BLE001
                info = {"candidate_id": cand["candidate_id"],
                        "family": fam.get("family_id", fam_key),
                        "kind": cand.get("kind"), "built": False, "blocked": True,
                        "reason": repr(exc)}
            results.append(info)
            tag = ("BUILT" if info.get("kind") == "deck_skeleton" else "reused") \
                if info.get("built") else "BLOCKED"
            extra = f" [{info.get('reason')}]" if info.get("blocked") else ""
            print(f"{tag:7} {info['candidate_id']}{extra}")

    built = [r for r in results if r.get("built")]
    blocked = [r for r in results if not r.get("built")]
    new_built = [r for r in built if r.get("kind") == "deck_skeleton"]
    reused = [r for r in built if r.get("kind") == "reused_prior_candidate"]
    manifest = {
        "pass": "30", "part": "E", "local_only": True, "no_upload": True,
        "upload_performed": False, "github_push_performed": False,
        "no_invented_ids": True, "no_opponent_clones": True,
        "root_main_py_untouched": True, "root_deck_csv_untouched": True,
        "base_from": str(V2_TARBALL.relative_to(REPO)),
        "candidates_reused": [r["candidate_id"] for r in reused],
        "candidates_built": [r["candidate_id"] for r in new_built],
        "candidates_blocked": [r["candidate_id"] for r in blocked],
        "league_blocked": [r["candidate_id"] for r in built
                           if r.get("blocked_from_league")],
        "results": results,
    }
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass30_candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    L = ["# Pass 30 — Candidate build/reuse manifest (Part E)", "",
         "> LOCAL ONLY. No upload, no GitHub push, no invented ids, no opponent "
         "clones. Root `main.py`/`deck.csv` untouched. Reused tarballs are copied "
         "verbatim from prior passes; only the two Raging Bolt structural variants "
         "are newly built.", "",
         f"- new structural variants built: **{manifest['candidates_built']}**",
         f"- prior candidates reused: **{len(reused)}**",
         f"- blocked from tournament (built but excluded): "
         f"**{manifest['league_blocked']}**",
         f"- failed to build/reuse: **{manifest['candidates_blocked']}**", "",
         "| candidate | family | kind | role | deck | parent | source/built |",
         "|---|---|---|---|---|---|---|"]
    for r in results:
        if not r.get("built"):
            L.append(f"| `{r['candidate_id']}` | {r.get('family')} | "
                     f"{r.get('kind')} | — | — | — | BLOCKED: {r.get('reason')} |")
            continue
        srcb = ("built from RB idea" if r["kind"] == "deck_skeleton"
                else f"`{r.get('source_tarball')}`")
        L.append(f"| `{r['candidate_id']}` | {r.get('family')} | {r['kind']} | "
                 f"{r.get('role')} | {r.get('deck_size')} | "
                 f"{r.get('parent_id') or '—'} | {srcb} |")
    for r in new_built:
        L += ["", f"### Built — `{r['candidate_id']}` ({r.get('role')})",
              f"- hypothesis: {r.get('hypothesis')}",
              f"- diff vs parent (`{r.get('parent_id')}`): `{r.get('diff_vs_parent')}`",
              f"- deck (60): `{r.get('cards')}`"]
    L.append("")
    (EXP / "pass30_candidate_manifest.md").write_text("\n".join(L), encoding="utf-8")

    print(f"\nbuilt={len(new_built)} reused={len(reused)} blocked={len(blocked)} "
          f"-> {(EXP / 'pass30_candidate_manifest.json').relative_to(REPO)}")
    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
