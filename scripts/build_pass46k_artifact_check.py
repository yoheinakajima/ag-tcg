#!/usr/bin/env python3
"""PASS 46K (Part B) — candidate artifact verification (EXISTING tarballs, no rebuild).

Pass 46K evaluates the EXISTING Pass-46J specialist candidate at larger N. It builds NOTHING.
This part verifies — WITHOUT rebuilding, overwriting, uploading, or running a tournament — the
four tarballs the confirmation panel needs:

  * ``cg_typed_diamond_specialist_planner_v0`` (the candidate under test, cg_typed lane);
  * ``diamond_toolbox_diancie``               (the internal parent, stdlib lane / deck source);
  * ``cg_typed_diamond_option_value_v1``      (strongest generic baseline, cg_typed lane);
  * ``cg_typed_diamond_family_only_floor_v1`` (family-only floor, cg_typed lane).

For every tarball:
  1. it EXISTS and its current sha256 is BYTE-IDENTICAL to the value a prior pass recorded
     (specialist: 46J build record; 46H scorers: 46H validation record; parent: 46J preflight)
     — proving no overwrite/regeneration this pass;
  2. top-level members match the lane: cg_typed = ``main.py`` + ``deck.csv`` + ``cg/`` (with
     ``cg/libcg.so``); stdlib parent = ``main.py`` + ``deck.csv`` and NO ``cg/`` tree;
  3. deck.csv is byte-comparable to the parent deck (the specialist MUST be byte-identical —
     same 60-card list, the only difference vs the parent is the policy).

For the SPECIALIST additionally (the decision hinges on it):
  4. NO public-reference hash/code match (copies no reference policy);
  5. the cg_typed lane ACCEPTS it; the stdlib lane REJECTS it and the tarball is BYTE-UNCHANGED
     across that rejection (the validator only reads); both validator scripts are sha-recorded;
  6. behavioural contract in a HARD-TIMEOUT SUBPROCESS (native cg can hang): deck step returns
     60 ids, a fuzz battery never raises, a legality battery returns legal in-range indices.

The cg_typed generic baselines additionally get the cg_typed-accept + no-ref-match checks.

Reuses the proven Pass-46J validation helpers. LOCAL / READ-ONLY: no mutation, no upload,
no events, no tarball write. Writes data/experiments/pass46k_artifact_check.{json,md}.
Exit 0 iff all_ok.
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

SPECIALIST_BUILD_JSON = EXP / "pass46j_candidate_build.json"
H46_VALIDATION_JSON = EXP / "pass46h_candidate_validation.json"
PREFLIGHT_46J_JSON = EXP / "pass46j_safety_preflight.json"
PREFLIGHT_46K_JSON = EXP / "pass46k_safety_preflight.json"

PARENT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass34"
                  / "diamond_toolbox_diancie.tar.gz")
CAND_46J_DIR = ROOT / "data" / "submissions" / "candidates_pass46j"
SPECIALIST_TARBALL = CAND_46J_DIR / "cg_typed_diamond_specialist_planner_v0.tar.gz"
CAND_46H_DIR = ROOT / "data" / "submissions" / "candidates_pass46h"
OV_TARBALL = CAND_46H_DIR / "cg_typed_diamond_option_value_v1.tar.gz"
FLOOR_TARBALL = CAND_46H_DIR / "cg_typed_diamond_family_only_floor_v1.tar.gz"

STDLIB_VALIDATOR = ROOT / "scripts" / "validate_candidate_tarball.py"
CG_TYPED_VALIDATOR = ROOT / "scripts" / "validate_cg_typed_tarball.py"


def _load_46j_helpers():
    spec = importlib.util.spec_from_file_location(
        "_p46j_val", ROOT / "scripts" / "build_pass46j_candidate_validation.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p46j_val"] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load_46j_helpers()


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: Path) -> str | None:
    return _sha_bytes(p.read_bytes()) if p.exists() else None


def _recorded_shas() -> dict:
    """Recorded sha256 per id from prior-pass artifacts (proves no overwrite this pass)."""
    out: dict[str, dict] = {}
    if SPECIALIST_BUILD_JSON.exists():
        b = json.loads(SPECIALIST_BUILD_JSON.read_text(encoding="utf-8"))
        out[b["candidate_id"]] = {"sha256": b.get("tarball_sha256"),
                                  "source": "pass46j_candidate_build.json"}
    if H46_VALIDATION_JSON.exists():
        v = json.loads(H46_VALIDATION_JSON.read_text(encoding="utf-8"))
        for r in v.get("per_candidate", []):
            ls = r.get("lane_separation") or {}
            if ls.get("candidate_tarball_sha256"):
                out[r["candidate_id"]] = {"sha256": ls["candidate_tarball_sha256"],
                                          "source": "pass46h_candidate_validation.json"}
    if PREFLIGHT_46J_JSON.exists():
        p = json.loads(PREFLIGHT_46J_JSON.read_text(encoding="utf-8"))
        ds = p.get("diamond_source") or {}
        if ds.get("parent_id") and ds.get("parent_tarball_sha256"):
            out[ds["parent_id"]] = {"sha256": ds["parent_tarball_sha256"],
                                    "source": "pass46j_safety_preflight.json"}
    return out


def _tarball_members(tar: Path) -> dict:
    with tarfile.open(tar, "r:gz") as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
    top = {n.split("/", 1)[0] for n in names}
    return {
        "n_files": len(names),
        "has_main_py": "main.py" in names,
        "has_deck_csv": "deck.csv" in names,
        "has_cg_tree": "cg" in top,
        "has_libcg_so": "cg/libcg.so" in names,
        "top_level": sorted(top),
    }


def _deck_bytes(tar: Path) -> bytes:
    with tarfile.open(tar, "r:gz") as t:
        return t.extractfile("deck.csv").read()


def _members_ok(members: dict, lane: str) -> bool:
    if lane == "cg_typed":
        return bool(members["has_main_py"] and members["has_deck_csv"]
                    and members["has_cg_tree"] and members["has_libcg_so"])
    # stdlib parent: main.py + deck.csv, and NO cg/ tree.
    return bool(members["has_main_py"] and members["has_deck_csv"]
                and not members["has_cg_tree"])


def verify(target: dict, ref_hashes: dict, h46: dict, recorded: dict,
           parent_deck_sha: str) -> dict:
    tar, cid, lane = target["tar"], target["id"], target["lane"]
    out = {"candidate_id": cid, "lane": lane, "role": target["role"],
           "tarball": str(tar.relative_to(ROOT)), "tarball_present": tar.exists()}
    if not tar.exists():
        out["ok"] = False
        return out

    tar_sha = _sha_file(tar)
    rec = recorded.get(cid, {})
    rec_sha = rec.get("sha256")
    no_overwrite = bool(rec_sha) and tar_sha == rec_sha

    members = _tarball_members(tar)
    members_ok = _members_ok(members, lane)

    deck_sha = _sha_bytes(_deck_bytes(tar))
    deck_equals_parent = deck_sha == parent_deck_sha

    out.update({
        "tarball_sha256": tar_sha, "recorded_sha256": rec_sha,
        "recorded_sha_source": rec.get("source"), "no_overwrite": no_overwrite,
        "members": members, "members_ok": members_ok,
        "deck_sha256": deck_sha, "deck_equals_parent": deck_equals_parent,
    })

    # cg_typed candidates: acceptance + originality.
    if lane == "cg_typed":
        cg = H.run_cg_typed(tar)
        lane_sep = H.lane_separation(tar, ref_hashes, h46)
        out["cg_typed_lane_accepts"] = cg
        out["lane_separation"] = lane_sep
        cg_ok = cg["accepts"]
        no_ref = lane_sep["no_ref_hash_match"]
    else:
        cg_ok, no_ref = True, True  # not applicable to the stdlib parent

    # The specialist (candidate under test) gets the FULL behavioural battery + stdlib reject.
    if target.get("full"):
        stdlib = H.run_stdlib_reject(tar)
        beh = H.run_behavior(tar)
        deck_ok = bool(beh.get("ran") and (beh.get("deck_step") or {}).get("ok"))
        fuzz_ok = bool(beh.get("ran")) and all(
            (not f.get("raised")) and f.get("is_list") for f in beh.get("fuzz", []))
        legal_ok = bool(beh.get("ran")) and all(
            (not c.get("raised")) and c.get("legal") for c in beh.get("legality", []))
        out["stdlib_lane_rejects"] = stdlib
        out["behavior_summary"] = {"deck_ok": deck_ok, "fuzz_never_raise_ok": fuzz_ok,
                                   "legality_ok": legal_ok, "n_fuzz": len(beh.get("fuzz", [])),
                                   "n_legality": len(beh.get("legality", [])),
                                   "ran": bool(beh.get("ran"))}
        full_ok = (stdlib["rejects"] and stdlib["tarball_byte_unchanged"]
                   and deck_ok and fuzz_ok and legal_ok and deck_equals_parent)
    else:
        full_ok = True

    out["ok"] = bool(no_overwrite and members_ok and cg_ok and no_ref and full_ok)
    return out


def main() -> int:
    if not PARENT_TARBALL.exists():
        raise SystemExit(f"missing parent tarball: {PARENT_TARBALL}")

    ref_hashes = H._ref_hashes()
    h46 = H._h46_diamond_main_shas()
    recorded = _recorded_shas()
    parent_deck_sha = _sha_bytes(_deck_bytes(PARENT_TARBALL))

    targets = [
        {"id": "cg_typed_diamond_specialist_planner_v0", "tar": SPECIALIST_TARBALL,
         "lane": "cg_typed", "role": "candidate_under_test", "full": True},
        {"id": "diamond_toolbox_diancie", "tar": PARENT_TARBALL,
         "lane": "stdlib", "role": "parent", "full": False},
        {"id": "cg_typed_diamond_option_value_v1", "tar": OV_TARBALL,
         "lane": "cg_typed", "role": "generic_baseline_strongest", "full": False},
        {"id": "cg_typed_diamond_family_only_floor_v1", "tar": FLOOR_TARBALL,
         "lane": "cg_typed", "role": "generic_baseline_floor", "full": False},
    ]
    results = [verify(t, ref_hashes, h46, recorded, parent_deck_sha) for t in targets]

    tar_shas = [r["tarball_sha256"] for r in results if r.get("tarball_present")]
    distinct_tarballs = len(set(tar_shas)) == len(tar_shas)
    specialist = next(r for r in results if r["role"] == "candidate_under_test")
    specialist_deck_eq_parent = specialist.get("deck_equals_parent") is True

    all_ok = (all(r["ok"] for r in results) and distinct_tarballs
              and specialist_deck_eq_parent)

    data = {
        "pass": "46k", "part": "B", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tarballs_regenerated": False,
        "n_targets": len(results),
        "parent_id": "diamond_toolbox_diancie", "parent_deck_sha256": parent_deck_sha,
        "n_references_checked": len(ref_hashes),
        "stdlib_validator_sha256": _sha_file(STDLIB_VALIDATOR),
        "cg_typed_validator_sha256": _sha_file(CG_TYPED_VALIDATOR),
        "per_target": results,
        "cross_target": {"distinct_tarballs": distinct_tarballs,
                         "n_distinct_tarballs": len(set(tar_shas)),
                         "specialist_deck_equals_parent": specialist_deck_eq_parent},
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46k_artifact_check.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46K (Part B) — candidate artifact verification (existing tarballs)", "",
        "_LOCAL / READ-ONLY. Pass 46K rebuilds NOTHING. Verifies the 4 existing tarballs the "
        "confirmation panel needs: each sha256 matches the value a prior pass recorded (no "
        "overwrite), lane-correct top-level members, the specialist deck is byte-identical to "
        "the parent, the specialist copies no public-reference policy, the cg_typed lane "
        "accepts the cg_typed tarballs while the stdlib lane rejects the specialist "
        "(byte-unchanged), and the specialist runtime never raises / returns legal indices._",
        "",
        f"- **targets verified:** {len(results)}",
        f"- **parent deck sha256:** `{parent_deck_sha[:16]}…`",
        f"- **public references checked:** {len(ref_hashes)}",
        f"- **distinct tarballs:** {distinct_tarballs}",
        f"- **specialist deck == parent:** {specialist_deck_eq_parent}",
        f"- **ALL OK:** **{all_ok}**", "",
        "| target | role | lane | no-overwrite | members | deck==parent | cg accepts | "
        "stdlib rejects | behaviour | ok |",
        "|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        cg = r.get("cg_typed_lane_accepts", {})
        st = r.get("stdlib_lane_rejects", {})
        bs = r.get("behavior_summary", {})
        beh_cell = ("-" if not r.get("behavior_summary") else
                    f"{bs.get('deck_ok')}/{bs.get('fuzz_never_raise_ok')}/"
                    f"{bs.get('legality_ok')}")
        md.append(
            f"| `{r['candidate_id']}` | {r['role']} | {r['lane']} | "
            f"{r.get('no_overwrite')} | {r.get('members_ok')} | "
            f"{r.get('deck_equals_parent')} | "
            f"{cg.get('accepts', '-') if cg else '-'} | "
            f"{st.get('rejects', '-') if st else '-'} | {beh_cell} | {r['ok']} |")
    md += ["", f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**"]
    (EXP / "pass46k_artifact_check.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "distinct_tarballs": distinct_tarballs,
                      "per_target": [{"id": r["candidate_id"], "ok": r["ok"],
                                      "no_overwrite": r.get("no_overwrite"),
                                      "deck_eq_parent": r.get("deck_equals_parent")}
                                     for r in results]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
