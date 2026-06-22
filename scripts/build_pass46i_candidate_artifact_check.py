#!/usr/bin/env python3
"""PASS 46I (Part B) — candidate artifact verification (EXISTING 46H water tarballs).

Verifies the THREE existing Pass-46H water tarballs this confirmation pass replays —
``cg_typed_water_option_value_v1`` (treatment), ``cg_typed_water_family_only_floor_v1``
(floor control), ``cg_typed_water_conservative_option_value_v1`` (conservative sibling) —
WITHOUT rebuilding, overwriting, uploading, or running a tournament:

  1. tarball EXISTS and its sha256 is BYTE-IDENTICAL to the value Pass 46H recorded
     (proves no overwrite/regeneration — Pass 46I generates no candidates);
  2. top-level members are exactly ``main.py`` + ``deck.csv`` + a ``cg/`` SDK tree
     (with the native ``cg/libcg.so``);
  3. the candidate ``deck.csv`` is BYTE-IDENTICAL to the real parent
     ``league_water_anti_disruption_pivot_v1`` deck (same 60-card list — the only
     difference vs the parent is the policy, never the deck);
  4. NO public-reference hash/code match (the candidate copies no reference policy);
  5. the cg_typed lane ACCEPTS it (static + import-smoke), the stdlib lane REJECTS it
     (our own Kaggle-lane gates untouched), and both validator scripts are recorded
     byte-for-byte so any tampering that manufactured the reject is detectable;
  6. behavioural contract in a HARD-TIMEOUT SUBPROCESS (native cg can hang): deck step
     returns 60 ids, a fuzz battery never raises, a legality battery returns legal
     in-range indices.

Reuses the proven Pass-46H validation helpers. LOCAL / READ-ONLY: no mutation, no
upload, no events, no tarball write. Writes
data/experiments/pass46i_candidate_artifact_check.{json,md}. Exit 0 iff all_ok.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
BUILD_JSON = EXP / "pass46h_candidate_build.json"
VALIDATION_46H = EXP / "pass46h_candidate_validation.json"
PARENT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass33"
                  / "league_water_anti_disruption_pivot_v1.tar.gz")
STDLIB_VALIDATOR = ROOT / "scripts" / "validate_candidate_tarball.py"
CG_TYPED_VALIDATOR = ROOT / "scripts" / "validate_cg_typed_tarball.py"
WATER_FAMILY = "water"


def _load_46h_helpers():
    spec = importlib.util.spec_from_file_location(
        "_p46h_val", ROOT / "scripts" / "build_pass46h_candidate_validation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load_46h_helpers()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: Path) -> str | None:
    return _sha_bytes(p.read_bytes()) if p.exists() else None


def _recorded_46h_tarball_shas() -> dict:
    out: dict[str, str] = {}
    if VALIDATION_46H.exists():
        v = json.loads(VALIDATION_46H.read_text(encoding="utf-8"))
        for r in v.get("per_candidate", []):
            ls = r.get("lane_separation") or {}
            if ls.get("candidate_tarball_sha256"):
                out[r["candidate_id"]] = ls["candidate_tarball_sha256"]
    return out


def _tarball_members(tar: Path) -> dict:
    with tarfile.open(tar, "r:gz") as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
    top = {n.split("/", 1)[0] for n in names}
    return {
        "names": names,
        "has_main_py": "main.py" in names,
        "has_deck_csv": "deck.csv" in names,
        "has_cg_tree": "cg" in top,
        "has_libcg_so": "cg/libcg.so" in names,
        "top_level_ok": {"main.py", "deck.csv", "cg"} <= top,
    }


def _deck_bytes(tar: Path) -> bytes:
    with tarfile.open(tar, "r:gz") as t:
        return t.extractfile("deck.csv").read()


def verify_candidate(cand: dict, ref_hashes: dict, recorded: dict,
                     parent_deck_sha: str) -> dict:
    tar = ROOT / cand["tarball"]
    cid = cand["candidate_id"]
    if not tar.exists():
        return {"candidate_id": cid, "tarball_present": False, "candidate_ok": False}

    tar_sha = _sha_file(tar)
    recorded_sha = recorded.get(cid)
    no_overwrite = bool(recorded_sha) and tar_sha == recorded_sha

    members = _tarball_members(tar)
    members_ok = bool(members["top_level_ok"] and members["has_libcg_so"])

    cand_deck_sha = _sha_bytes(_deck_bytes(tar))
    deck_equals_parent = cand_deck_sha == parent_deck_sha

    cg = H.run_cg_typed(tar)
    stdlib = H.run_stdlib_reject(tar)
    beh = H.run_behavior(tar)
    lane = H.lane_separation(tar, ref_hashes)

    deck_ok = bool(beh.get("ran") and (beh.get("deck_step") or {}).get("ok"))
    fuzz_ok = bool(beh.get("ran")) and all(
        (not f.get("raised")) and f.get("is_list") for f in beh.get("fuzz", []))
    legal_ok = bool(beh.get("ran")) and all(
        (not c.get("raised")) and c.get("legal") for c in beh.get("legality", []))

    candidate_ok = bool(
        no_overwrite and members_ok and deck_equals_parent
        and lane["no_ref_hash_match"] and cg["accepts"] and stdlib["rejects"]
        and deck_ok and fuzz_ok and legal_ok
        and not cand.get("public_reference", False))
    return {
        "candidate_id": cid, "tarball_present": True,
        "parent_candidate_id": cand.get("parent_candidate_id"),
        "parent_family": cand.get("parent_family"),
        "profile_id": cand.get("profile_id"),
        "public_reference": cand.get("public_reference", False),
        "tarball_sha256": tar_sha, "recorded_46h_sha256": recorded_sha,
        "no_overwrite": no_overwrite,
        "members": members, "members_ok": members_ok,
        "candidate_deck_sha256": cand_deck_sha,
        "deck_equals_parent": deck_equals_parent,
        "cg_typed_lane_accepts": cg, "stdlib_lane_rejects": stdlib,
        "behavior_summary": {"deck_ok": deck_ok, "fuzz_never_raise_ok": fuzz_ok,
                             "legality_ok": legal_ok,
                             "n_fuzz": len(beh.get("fuzz", [])),
                             "n_legality": len(beh.get("legality", [])),
                             "ran": bool(beh.get("ran"))},
        "lane_separation": lane,
        "candidate_ok": candidate_ok,
    }


def main() -> int:
    if not BUILD_JSON.exists():
        raise SystemExit(f"missing 46H build record: {BUILD_JSON}")
    if not PARENT_TARBALL.exists():
        raise SystemExit(f"missing parent tarball: {PARENT_TARBALL}")
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    water = [c for c in build["candidates"] if c.get("parent_family") == WATER_FAMILY]
    ref_hashes = H._ref_hashes()
    recorded = _recorded_46h_tarball_shas()
    parent_deck_sha = _sha_bytes(_deck_bytes(PARENT_TARBALL))

    results = [verify_candidate(c, ref_hashes, recorded, parent_deck_sha) for c in water]

    tar_shas = [r["tarball_sha256"] for r in results if r.get("tarball_present")]
    distinct_tarballs = len(set(tar_shas)) == len(tar_shas)
    # The treatment must be present (decision hinges on it).
    has_treatment = any(r["candidate_id"] == "cg_typed_water_option_value_v1"
                        and r["candidate_ok"] for r in results)
    has_floor = any(r["candidate_id"] == "cg_typed_water_family_only_floor_v1"
                    and r["candidate_ok"] for r in results)

    all_ok = (bool(results) and all(r["candidate_ok"] for r in results)
              and distinct_tarballs and has_treatment and has_floor)

    data = {
        "pass": "46i", "part": "B", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tarballs_regenerated": False,
        "n_candidates": len(results), "family": WATER_FAMILY,
        "parent_candidate_id": "league_water_anti_disruption_pivot_v1",
        "parent_deck_sha256": parent_deck_sha,
        "n_references_checked": len(ref_hashes),
        "stdlib_validator_sha256": _sha_file(STDLIB_VALIDATOR),
        "cg_typed_validator_sha256": _sha_file(CG_TYPED_VALIDATOR),
        "per_candidate": results,
        "cross_candidate": {"distinct_tarballs": distinct_tarballs,
                            "n_distinct_tarballs": len(set(tar_shas)),
                            "treatment_present_ok": has_treatment,
                            "floor_present_ok": has_floor},
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_candidate_artifact_check.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46I (Part B) — candidate artifact verification", "",
        "_LOCAL / READ-ONLY. Verifies the EXISTING Pass-46H water tarballs (no rebuild, "
        "no overwrite, no upload, no tournament): each tarball's sha256 matches the value "
        "46H recorded (no overwrite), top-level members are `main.py` + `deck.csv` + "
        "`cg/`, the deck is byte-identical to the real parent, no public-reference policy "
        "is copied, the cg_typed lane accepts while the stdlib lane rejects, and the "
        "runtime never raises / always returns legal indices._", "",
        f"- **candidates verified:** {len(results)} (family={WATER_FAMILY})",
        f"- **parent deck sha256:** `{parent_deck_sha[:16]}…`",
        f"- **public references checked:** {len(ref_hashes)}",
        f"- **distinct tarballs:** {distinct_tarballs}",
        f"- **ALL OK:** **{all_ok}**", "",
        "| candidate | profile | no-overwrite | members | deck==parent | no-ref-match | "
        "cg accepts | stdlib rejects | deck | fuzz | legal | ok |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        bs = r.get("behavior_summary", {})
        md.append(
            f"| `{r['candidate_id']}` | `{r.get('profile_id')}` | {r['no_overwrite']} | "
            f"{r['members_ok']} | {r['deck_equals_parent']} | "
            f"{r['lane_separation']['no_ref_hash_match']} | "
            f"{r['cg_typed_lane_accepts']['accepts']} | "
            f"{r['stdlib_lane_rejects']['rejects']} | {bs.get('deck_ok')} | "
            f"{bs.get('fuzz_never_raise_ok')} | {bs.get('legality_ok')} | "
            f"{r['candidate_ok']} |")
    md += ["", f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**"]
    (EXP / "pass46i_candidate_artifact_check.md").write_text("\n".join(md) + "\n",
                                                             encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "n_candidates": len(results),
                      "distinct_tarballs": distinct_tarballs,
                      "per_candidate": [{"id": r["candidate_id"],
                                         "ok": r["candidate_ok"],
                                         "no_overwrite": r.get("no_overwrite"),
                                         "deck_eq_parent": r.get("deck_equals_parent")}
                                        for r in results]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
