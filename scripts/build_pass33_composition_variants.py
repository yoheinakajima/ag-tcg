#!/usr/bin/env python3
"""Pass 33 (Part E) — assemble the stress-test candidate set. LOCAL / no upload.

Consumes data/experiments/pass33_stress_test_plan.json and populates
data/submissions/candidates_pass33/ with one top-level tarball (main.py +
deck.csv only) per selected candidate:

  * existing_reuse / blocked : the canonical source tarball is copied verbatim
    (deck + pilot unchanged). Durant is copied so Part F can smoke it; it stays
    blocked_from_league.
  * build_variant            : the PARENT tarball's main.py is reused unchanged
    except for its embedded deck list, and deck.csv is rewritten. Only the deck
    composition changes — the pilot is byte-identical to the parent's outside the
    `_EMBEDDED_DECK` block.

Honesty / safety gates enforced here:
  * every card id must exist in the local card DB (no invented ids);
  * non-basic-energy cards capped at 4 copies;
  * every deck expands to exactly 60 ids;
  * core Water cards (Kyogre 721, Snover 722, Mega Abomasnow ex 723, Ultra Ball
    1121) must survive the delta unchanged;
  * built tarball is top-level (main.py + deck.csv) only.

No upload, no GitHub push, card DB is never committed.

Writes data/experiments/pass33_composition_variants_manifest.{json,md}.
"""
from __future__ import annotations

import csv
import collections
import io
import json
import re
import shutil
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
PLAN = EXP / "pass33_stress_test_plan.json"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
OUT_DIR = REPO / "data" / "submissions" / "candidates_pass33"
RUNS = REPO / "data" / "runs" / "pass33"

OUT_JSON = EXP / "pass33_composition_variants_manifest.json"
OUT_MD = EXP / "pass33_composition_variants_manifest.md"

STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"
CORE_PRESERVE = {721: 4, 722: 4, 723: 4, 1121: 4}
EMBED_RE = re.compile(r"_EMBEDDED_DECK = \[.*?\]", re.DOTALL)


def _load_card_db():
    all_ids, basic_energy = set(), set()
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                cid = int((row.get("Card ID") or "").strip())
            except ValueError:
                continue
            all_ids.add(cid)
            if (row.get(STAGE_COL) or "").strip() == "Basic Energy":
                basic_energy.add(cid)
    return all_ids, basic_energy


def _tar_names(tp):
    with tarfile.open(tp, "r:gz") as t:
        return sorted(t.getnames())


def _read_member(tp, name):
    with tarfile.open(tp, "r:gz") as t:
        m = t.extractfile(name)
        return m.read().decode("utf-8") if m else None


def _deck_from_csv(text):
    return [int(x) for x in text.splitlines() if x.strip()]


def _render_embedded(deck_ids):
    lines = ["_EMBEDDED_DECK = ["]
    for i in range(0, len(deck_ids), 10):
        chunk = deck_ids[i:i + 10]
        lines.append("    " + ", ".join(str(c) for c in chunk) + ",")
    lines.append("]")
    return "\n".join(lines)


def _make_tarball(main_src, deck_csv, tar_path):
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"main.py": main_src.encode("utf-8"),
            "deck.csv": deck_csv.encode("utf-8")}
    with tarfile.open(tar_path, "w:gz") as t:
        for name in ("main.py", "deck.csv"):
            info = tarfile.TarInfo(name)
            info.size = len(data[name])
            info.mtime = 0
            t.addfile(info, io.BytesIO(data[name]))


def reuse_one(entry):
    cid = entry["candidate_id"]
    src = REPO / (entry.get("source_tarball") or "")
    if not entry.get("source_tarball") or not src.exists():
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"source tarball missing: {entry.get('source_tarball')}"}
    if _tar_names(src) != ["deck.csv", "main.py"]:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": "source not top-level (main.py+deck.csv) only"}
    deck = _deck_from_csv(_read_member(src, "deck.csv"))
    if len(deck) != 60:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"source deck has {len(deck)} cards"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"{cid}.tar.gz"
    shutil.copyfile(src, dst)
    return {"candidate_id": cid, "family": entry.get("family"),
            "disposition": entry["disposition"], "kind": "reused", "built": True,
            "blocked": False, "blocked_from_league": entry.get("blocked_from_league", False),
            "source_tarball": entry["source_tarball"],
            "tarball": str(dst.relative_to(REPO)), "deck_size": len(deck)}


def build_variant(entry, all_ids, basic_energy):
    cid = entry["candidate_id"]
    parent_tar = REPO / (entry.get("parent_tarball") or "")
    if not parent_tar.exists():
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"parent tarball missing: {entry.get('parent_tarball')}"}
    parent_main = _read_member(parent_tar, "main.py")
    parent_deck = _deck_from_csv(_read_member(parent_tar, "deck.csv"))
    counts = collections.Counter(parent_deck)
    delta = entry["deck_delta"]
    for raw, k in delta["remove"].items():
        cidn = int(raw)
        if counts[cidn] < k:
            return {"candidate_id": cid, "built": False, "blocked": True,
                    "reason": f"cannot remove {k}x{cidn}; only {counts[cidn]} present"}
        counts[cidn] -= k
    for raw, k in delta["add"].items():
        counts[int(raw)] += k
    new_deck = []
    for c in sorted(counts):
        new_deck.extend([c] * counts[c])
    # gates
    if len(new_deck) != 60:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"deck expands to {len(new_deck)} (need 60)"}
    invented = sorted(set(new_deck) - all_ids)
    if invented:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"invented card ids not in DB: {invented}"}
    overcap = {c: n for c, n in counts.items()
               if n > 4 and c not in basic_energy}
    if overcap:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": f"non-basic-energy over 4 copies: {overcap}"}
    for c, need in CORE_PRESERVE.items():
        if counts.get(c, 0) != need:
            return {"candidate_id": cid, "built": False, "blocked": True,
                    "reason": f"core card {c} not preserved ({counts.get(c,0)}!={need})"}
    # swap embedded deck only
    if not EMBED_RE.search(parent_main):
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": "_EMBEDDED_DECK block not found in parent main.py"}
    new_main = EMBED_RE.sub(_render_embedded(new_deck), parent_main, count=1)
    # assert only the embedded-deck block changed (pilot byte-identical elsewhere)
    if EMBED_RE.sub("<DECK>", parent_main) != EMBED_RE.sub("<DECK>", new_main):
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": "main.py changed outside the embedded-deck block"}
    deck_csv = "\n".join(str(c) for c in new_deck) + "\n"
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{cid}.main.py").write_text(new_main, encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tar_path = OUT_DIR / f"{cid}.tar.gz"
    _make_tarball(new_main, deck_csv, tar_path)
    if _tar_names(tar_path) != ["deck.csv", "main.py"]:
        return {"candidate_id": cid, "built": False, "blocked": True,
                "reason": "built tarball not top-level only"}
    return {
        "candidate_id": cid, "family": entry.get("family"),
        "disposition": "build_variant", "kind": "built", "built": True,
        "blocked": False, "blocked_from_league": False,
        "parent_id": entry.get("parent_id"),
        "parent_tarball": entry["parent_tarball"],
        "tarball": str(tar_path.relative_to(REPO)), "deck_size": len(new_deck),
        "deck_delta": delta,
        "pilot_identical_to_parent_outside_deck": True,
        "card_counts": {int(c): int(n) for c, n in sorted(counts.items()) if n},
        "basic_pokemon_parent_vs_variant": entry.get("projected_basic_pokemon"),
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    all_ids, basic_energy = _load_card_db()
    results = []
    for entry in plan["candidates"]:
        disp = entry["disposition"]
        if disp == "build_variant":
            results.append(build_variant(entry, all_ids, basic_energy))
        else:  # existing_reuse or blocked -> copy verbatim
            results.append(reuse_one(entry))

    built = [r for r in results if r.get("built")]
    failed = [r for r in results if not r.get("built")]
    manifest = {
        "pass": "33", "part": "E", "no_upload": True, "upload_performed": False,
        "candidates_dir": str(OUT_DIR.relative_to(REPO)),
        "built_count": len(built), "failed_count": len(failed),
        "variants_built": [r["candidate_id"] for r in built
                           if r.get("kind") == "built"],
        "reused_count": sum(1 for r in built if r.get("kind") == "reused"),
        "core_preserved": CORE_PRESERVE,
        "results": results,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    L = ["# Pass 33 — Composition Variant Build Manifest (Part E)", "",
         "> LOCAL / no upload. Built tarballs are top-level (main.py + deck.csv) "
         "only. Variants change ONLY the deck; the pilot is byte-identical to the "
         "parent outside the embedded-deck block.", "",
         f"- built/copied: **{len(built)}** "
         f"({manifest['reused_count']} reused, {len(manifest['variants_built'])} "
         f"new variants); failed: **{len(failed)}**",
         f"- variants built: {manifest['variants_built']}", "",
         "| candidate | kind | disposition | deck | blocked_league | note |",
         "|---|---|---|---|---|---|"]
    for r in results:
        note = r.get("reason", "")
        if r.get("kind") == "built":
            note = f"delta {r.get('deck_delta')}"
        L.append(f"| {r['candidate_id']} | {r.get('kind','-')} | "
                 f"{r.get('disposition','-')} | {r.get('deck_size','-')} | "
                 f"{r.get('blocked_from_league','-')} | {str(note)[:70]} |")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"built/copied {len(built)} ({manifest['reused_count']} reused, "
          f"{len(manifest['variants_built'])} variants); failed {len(failed)}")
    for r in failed:
        print("  FAILED", r["candidate_id"], "-", r.get("reason"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
