#!/usr/bin/env python3
"""Pass 34 (Part E) — assemble new-deck candidate tarballs. LOCAL / no upload.

Each Part-D 60-card decklist is embedded into the shared DECK-AGNOSTIC generic
pilot main.py (the pilot is byte-identical across candidates outside the
`_EMBEDDED_DECK` block). Built tarballs are top-level (main.py + deck.csv) only.

Lane policy:
  * normal lane (Miraidon, Diamond): league-eligible candidates, generic pilot is
    a reasonable fit.
  * special lane (Toxic, Durant): built so the internal tournament can MEASURE the
    generic pilot's mis-fit, but flagged blocked_from_league=true until a real
    special pilot exists (Part F is plan-first; no special pilot is wired here).

Honesty gates: 60 ids, every id in DB, non-basic-energy <= 4 copies, top-level
tarball only, pilot byte-identical to the source outside the embedded-deck block.
No invented ids, no upload, card DB never committed.
Writes data/experiments/pass34_candidate_manifest.{json,md}.
"""
from __future__ import annotations

import csv
import collections
import io
import json
import re
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
BUILDS = EXP / "pass34_decklist_builds.json"
CARD_DB = REPO / "data" / "cards" / "EN_Card_Data.csv"
OUT_DIR = REPO / "data" / "submissions" / "candidates_pass34"
RUNS = REPO / "data" / "runs" / "pass34"
OUT_JSON = EXP / "pass34_candidate_manifest.json"
OUT_MD = EXP / "pass34_candidate_manifest.md"

# Shared deck-agnostic generic pilot source (confirmed to load _EMBEDDED_DECK and
# play generically; pilot identical across candidates outside the deck block).
GENERIC_PILOT_TAR = (REPO / "data" / "submissions" / "candidates_pass30" /
                     "league_water_anti_disruption_pivot_v1.tar.gz")

STAGE_COL = "Stage (Pokémon)/Type (Energy and Trainer)"
EMBED_RE = re.compile(r"_EMBEDDED_DECK = \[.*?\]", re.DOTALL)


def _load_db():
    all_ids, basic_energy = set(), set()
    with CARD_DB.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("Card ID") or "").strip()
            if not cid.isdigit():
                continue
            all_ids.add(int(cid))
            if (row.get(STAGE_COL) or "").strip() == "Basic Energy":
                basic_energy.add(int(cid))
    return all_ids, basic_energy


def _read_member(tp, name):
    with tarfile.open(tp, "r:gz") as t:
        m = t.extractfile(name)
        return m.read().decode("utf-8") if m else None


def _tar_names(tp):
    with tarfile.open(tp, "r:gz") as t:
        return sorted(t.getnames())


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


def build_one(rec, pilot_main, all_ids, basic_energy):
    deck_id = rec["deck_id"]
    deck_csv_path = REPO / rec["deck_csv"]
    deck_ids = [int(x) for x in deck_csv_path.read_text().split() if x.strip()]
    counts = collections.Counter(deck_ids)

    if len(deck_ids) != 60:
        return {"candidate_id": deck_id, "built": False,
                "reason": f"deck size {len(deck_ids)} != 60"}
    invented = sorted(set(deck_ids) - all_ids)
    if invented:
        return {"candidate_id": deck_id, "built": False,
                "reason": f"invented ids: {invented}"}
    overcap = {c: n for c, n in counts.items() if n > 4 and c not in basic_energy}
    if overcap:
        return {"candidate_id": deck_id, "built": False,
                "reason": f"non-basic-energy over 4 copies: {overcap}"}
    if not EMBED_RE.search(pilot_main):
        return {"candidate_id": deck_id, "built": False,
                "reason": "_EMBEDDED_DECK block not found in generic pilot"}

    new_main = EMBED_RE.sub(_render_embedded(deck_ids), pilot_main, count=1)
    if EMBED_RE.sub("<DECK>", pilot_main) != EMBED_RE.sub("<DECK>", new_main):
        return {"candidate_id": deck_id, "built": False,
                "reason": "pilot changed outside the embedded-deck block"}

    deck_csv = "\n".join(str(c) for c in deck_ids) + "\n"
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{deck_id}.main.py").write_text(new_main, encoding="utf-8")
    tar_path = OUT_DIR / f"{deck_id}.tar.gz"
    _make_tarball(new_main, deck_csv, tar_path)
    if _tar_names(tar_path) != ["deck.csv", "main.py"]:
        return {"candidate_id": deck_id, "built": False,
                "reason": "built tarball not top-level only"}

    special = rec["special_pilot_required"]
    return {
        "candidate_id": deck_id, "display_name": rec["display_name"],
        "lane": rec["lane"], "built": True,
        "special_pilot_required": special,
        "blocked_from_league": bool(special),
        "blocked_reason": ("special-pilot lane: generic pilot cannot pilot this "
                           "deck's win condition; built for internal measurement "
                           "only until a real special pilot exists (Part F is "
                           "plan-first)") if special else None,
        "pilot_identical_to_source_outside_deck": True,
        "generic_pilot_source": str(GENERIC_PILOT_TAR.relative_to(REPO)),
        "tarball": str(tar_path.relative_to(REPO)), "deck_size": 60,
        "card_counts": {int(c): int(n) for c, n in sorted(counts.items())},
    }


def main() -> int:
    builds = json.loads(BUILDS.read_text(encoding="utf-8"))
    all_ids, basic_energy = _load_db()
    if not GENERIC_PILOT_TAR.exists():
        print(f"FATAL: generic pilot source missing: {GENERIC_PILOT_TAR}")
        return 2
    pilot_main = _read_member(GENERIC_PILOT_TAR, "main.py")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for rec in builds["results"]:
        if not rec.get("built"):
            results.append({"candidate_id": rec["deck_id"], "built": False,
                            "reason": f"Part D did not build: {rec.get('reason')}"})
            continue
        results.append(build_one(rec, pilot_main, all_ids, basic_energy))

    built = [r for r in results if r.get("built")]
    league = [r for r in built if not r.get("blocked_from_league")]
    blocked = [r for r in built if r.get("blocked_from_league")]
    failed = [r for r in results if not r.get("built")]

    manifest = {
        "pass": "34", "part": "E", "local_only": True, "no_upload": True,
        "upload_performed": False,
        "candidates_dir": str(OUT_DIR.relative_to(REPO)),
        "generic_pilot_source": str(GENERIC_PILOT_TAR.relative_to(REPO)),
        "built_count": len(built),
        "league_eligible": [r["candidate_id"] for r in league],
        "blocked_from_league": [r["candidate_id"] for r in blocked],
        "failed_count": len(failed),
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    L = ["# Pass 34 — New Deck Candidate Manifest (Part E)", "",
         "> LOCAL / no upload. Tarballs are top-level (main.py + deck.csv) only. "
         "Every deck is embedded into the shared deck-agnostic generic pilot; the "
         "pilot is byte-identical across candidates outside the embedded-deck "
         "block. Special-lane decks are built for internal measurement only and "
         "are blocked_from_league until a real special pilot exists.", "",
         f"- built: **{len(built)}**  (league-eligible: {len(league)}, "
         f"blocked_from_league: {len(blocked)})  failed: **{len(failed)}**",
         f"- league-eligible: {manifest['league_eligible']}",
         f"- blocked_from_league: {manifest['blocked_from_league']}", "",
         "| candidate | lane | built | league_eligible | note |",
         "|---|---|---|---|---|"]
    for r in results:
        note = r.get("reason") or r.get("blocked_reason") or "generic-pilot fit ok"
        L.append(f"| {r['candidate_id']} | {r.get('lane','-')} | "
                 f"{r.get('built')} | "
                 f"{(not r.get('blocked_from_league')) if r.get('built') else '-'} | "
                 f"{str(note)[:80]} |")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    for r in results:
        if r.get("built"):
            print(f"{r['candidate_id']}: built (league="
                  f"{not r.get('blocked_from_league')})")
        else:
            print(f"{r['candidate_id']}: FAILED — {r.get('reason')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
