#!/usr/bin/env python3
"""PASS 46H (Part G) — candidate validation + lane separation (all candidates).

Validates EVERY Part-F candidate WITHOUT running a tournament or touching prod:

  1. cg_typed lane ACCEPTS it (static + import-smoke), returncode 0.
  2. The stdlib lane REJECTS it (non-stdlib cg import + extra cg/ tree) — proving our
     own Kaggle-lane gates are unaffected by these benchmark-lane candidates.
  3. Behavioural contract (in a HARD-TIMEOUT SUBPROCESS, native cg can hang):
     - deck-submission step (select is None) returns the 60 source deck ids;
     - a fuzz battery of malformed observations NEVER raises and always returns a list;
     - a legality battery returns distinct in-range indices honouring min/max.
  4. Lane separation / originality: each candidate's main.py and tarball hashes match NO
     public-reference main.py or tarball (zero-copy of reference policy), and the
     candidates are mutually distinct (distinct tarballs/decks/profiles).

LOCAL / READ-ONLY. No mutation, no upload, no events. Writes
data/experiments/pass46h_candidate_validation.{json,md}. Exit 0 iff all_ok.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
BUILD_JSON = EXP / "pass46h_candidate_build.json"
REF_RAW = ROOT / "data" / "reference_agents" / "raw_outputs"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_BEHAVIOR_SNIPPET = r'''
import importlib.util, json, os, sys
d = sys.argv[1]
os.chdir(d)
sys.path.insert(0, d)
spec = importlib.util.spec_from_file_location("cand_under_test",
                                              os.path.join(d, "main.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
agent = getattr(m, "agent")

out = {"import_ok": True, "deck_step": None, "fuzz": [], "legality": []}

# Deck-submission step: select present but None -> 60 ids.
try:
    r = agent({"select": None})
    out["deck_step"] = {"ok": isinstance(r, list) and len(r) == 60
                        and all(isinstance(x, int) for x in r), "len": len(r)
                        if isinstance(r, list) else None}
except Exception as e:
    out["deck_step"] = {"ok": False, "raised": type(e).__name__}

fuzz_inputs = [
    None, {}, {"select": None}, {"select": {}}, {"select": {"option": []}},
    {"select": {"option": [{"type": "x"}], "minCount": "a", "maxCount": None}},
    "string", 12345, [1, 2, 3],
    {"select": {"option": [{"type": 13}], "minCount": 5, "maxCount": 2}},
    {"current": {"yourIndex": 0}, "select": {"option": [{"type": 8}, {"type": 14}],
     "minCount": 1, "maxCount": 1}},
    {"select": {"option": [{}, {}], "minCount": -1, "maxCount": 99}},
    {"current": {"yourIndex": 0, "players": [{"hand": [{"id": 3}],
     "active": [{"id": 700, "energies": []}], "bench": []}, {}]},
     "select": {"option": [{"type": 8, "area": 2, "index": 0, "inPlayArea": 4,
                "inPlayIndex": 0}, {"type": 14}], "minCount": 1, "maxCount": 1}},
]
for fi in fuzz_inputs:
    rec = {"repr": repr(fi)[:60]}
    try:
        r = agent(fi)
        rec["raised"] = False
        rec["is_list"] = isinstance(r, list)
        rec["all_int"] = isinstance(r, list) and all(isinstance(x, int) for x in r)
    except Exception as e:
        rec["raised"] = True
        rec["err"] = type(e).__name__
    out["fuzz"].append(rec)

# Legality battery: (n, mn, mx) with crafted option types + board context.
cases = [
    {"option": [{"type": 13}, {"type": 8}, {"type": 14}], "minCount": 1, "maxCount": 1},
    {"option": [{"type": 9}, {"type": 7}, {"type": 8}, {"type": 14}],
     "minCount": 1, "maxCount": 1},
    {"option": [{"type": 8}, {"type": 8}, {"type": 3}, {"type": 14}],
     "minCount": 2, "maxCount": 2},
    {"option": [{"type": 0}, {"type": 1}], "minCount": 0, "maxCount": 0},
    {"option": [{"type": 7, "index": 0}, {"type": 7, "index": 1}, {"type": 7, "index": 2}],
     "minCount": 1, "maxCount": 3},
    {"option": [{"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "inPlayArea": 5, "inPlayIndex": 1}, {"type": 14}],
     "minCount": 1, "maxCount": 1},
]
for sel in cases:
    n = len(sel["option"]); mn = sel["minCount"]; mx = sel["maxCount"]
    rec = {"n": n, "mn": mn, "mx": mx}
    try:
        r = agent({"current": {"yourIndex": 0, "turn": 4, "deckCount": 12,
                   "players": [{"hand": [], "active": [{"id": 700}], "bench": []}, {}]},
                   "select": sel})
        in_range = all(isinstance(x, int) and 0 <= x < n for x in r)
        distinct = len(set(r)) == len(r)
        len_ok = len(r) <= mx and (len(r) >= min(mn, n) if mn > 0 else True)
        rec.update({"raised": False, "returned": r, "legal":
                    bool(in_range and distinct and len_ok)})
    except Exception as e:
        rec.update({"raised": True, "err": type(e).__name__, "legal": False})
    out["legality"].append(rec)

print("BEHAVIOR_JSON_BEGIN")
print(json.dumps(out))
print("BEHAVIOR_JSON_END")
'''


def run_cg_typed(tar: Path) -> dict:
    p = subprocess.run([sys.executable,
                        str(ROOT / "scripts/validate_cg_typed_tarball.py"),
                        str(tar), "--import-smoke"],
                       capture_output=True, text=True)
    return {"returncode": p.returncode, "accepts": p.returncode == 0,
            "stdout": p.stdout.strip()[-200:], "stderr": p.stderr.strip()[-400:]}


def run_stdlib_reject(tar: Path) -> dict:
    p = subprocess.run([sys.executable,
                        str(ROOT / "scripts/validate_candidate_tarball.py"),
                        str(tar)],
                       capture_output=True, text=True, timeout=90)
    return {"returncode": p.returncode, "rejects": p.returncode != 0,
            "stdout": p.stdout.strip()[-200:], "stderr": p.stderr.strip()[-400:]}


def run_behavior(tar: Path) -> dict:
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(tar, "r:gz") as t:
            for m in t.getmembers():  # trusted self-built tarball
                if m.isfile() and not m.name.startswith("/") and ".." not in m.name:
                    t.extract(m, td)
        snippet = Path(td) / "_behavior.py"
        snippet.write_text(_BEHAVIOR_SNIPPET, encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, str(snippet), td],
                               capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            return {"ran": False, "timed_out": True}
    txt = p.stdout
    try:
        body = txt.split("BEHAVIOR_JSON_BEGIN", 1)[1].split(
            "BEHAVIOR_JSON_END", 1)[0].strip()
        data = json.loads(body)
        data["ran"] = True
        return data
    except Exception:
        return {"ran": False, "stdout": txt[-600:], "stderr": p.stderr[-400:]}


def _ref_hashes() -> dict:
    refs = {}
    for sub in sorted(REF_RAW.glob("public_ref_*/submission.tar.gz")):
        try:
            t_sha = _sha(sub.read_bytes())
            with tarfile.open(sub, "r:gz") as tar:
                names = [m.name for m in tar.getmembers() if m.isfile()]
                main_name = next((n for n in names if n.endswith("main.py")), None)
                m_sha = _sha(tar.extractfile(main_name).read()) if main_name else None
        except Exception as exc:  # noqa: BLE001
            refs[sub.parent.name] = {"error": type(exc).__name__}
            continue
        refs[sub.parent.name] = {"tarball_sha256": t_sha, "main_sha256": m_sha}
    return refs


def lane_separation(tar: Path, ref_hashes: dict) -> dict:
    cand_tar_sha = _sha(tar.read_bytes())
    with tarfile.open(tar, "r:gz") as t:
        cand_main_sha = _sha(t.extractfile("main.py").read())
    matches = [name for name, h in ref_hashes.items()
               if h.get("tarball_sha256") == cand_tar_sha
               or (h.get("main_sha256") is not None
                   and h["main_sha256"] == cand_main_sha)]
    return {"candidate_tarball_sha256": cand_tar_sha,
            "candidate_main_sha256": cand_main_sha,
            "matches_any_reference": matches,
            "no_ref_hash_match": not matches}


def validate_candidate(cand: dict, ref_hashes: dict) -> dict:
    tar = ROOT / cand["tarball"]
    if not tar.exists():
        return {"candidate_id": cand["candidate_id"], "tarball_present": False,
                "candidate_ok": False}
    cg = run_cg_typed(tar)
    stdlib = run_stdlib_reject(tar)
    beh = run_behavior(tar)
    lane = lane_separation(tar, ref_hashes)

    deck_ok = bool(beh.get("ran") and (beh.get("deck_step") or {}).get("ok"))
    fuzz_ok = bool(beh.get("ran")) and all(
        (not f.get("raised")) and f.get("is_list") for f in beh.get("fuzz", []))
    legal_ok = bool(beh.get("ran")) and all(
        (not c.get("raised")) and c.get("legal") for c in beh.get("legality", []))
    candidate_ok = bool(cg["accepts"] and stdlib["rejects"] and deck_ok and fuzz_ok
                        and legal_ok and lane["no_ref_hash_match"]
                        and not cand.get("public_reference", False))
    return {
        "candidate_id": cand["candidate_id"], "tarball_present": True,
        "parent_candidate_id": cand.get("parent_candidate_id"),
        "parent_family": cand.get("parent_family"),
        "profile_id": cand.get("profile_id"),
        "scoring_mode": cand.get("scoring_mode"),
        "public_reference": cand.get("public_reference", False),
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
        raise SystemExit(f"missing build record: {BUILD_JSON}")
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    cands = build["candidates"]
    ref_hashes = _ref_hashes()

    results = [validate_candidate(c, ref_hashes) for c in cands]

    tar_shas = [r["lane_separation"]["candidate_tarball_sha256"]
                for r in results if r.get("tarball_present")]
    main_shas = [r["lane_separation"]["candidate_main_sha256"]
                 for r in results if r.get("tarball_present")]
    distinct_tarballs = len(set(tar_shas)) == len(tar_shas)
    distinct_mains = len(set(main_shas)) == len(main_shas)

    all_ok = (bool(results) and all(r["candidate_ok"] for r in results)
              and distinct_tarballs and distinct_mains)

    data = {
        "pass": "46H", "part": "G", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "n_candidates": len(results),
        "n_references_checked": len(ref_hashes),
        "per_candidate": results,
        "cross_candidate": {"distinct_tarballs": distinct_tarballs,
                            "distinct_main_py": distinct_mains,
                            "n_distinct_tarballs": len(set(tar_shas)),
                            "n_distinct_main_py": len(set(main_shas))},
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46h_candidate_validation.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46H (Part G) — candidate validation + lane separation", "",
        "_LOCAL / READ-ONLY. No tournament, no upload, no events. Proves every candidate "
        "is accepted by the cg_typed lane, REJECTED by the stdlib lane (our own Kaggle "
        "gates untouched), never-raises on malformed input, always returns legal indices, "
        "copies NO public-reference policy, and that the candidates are mutually "
        "distinct._", "",
        f"- **candidates validated:** {len(results)}",
        f"- **public references checked:** {len(ref_hashes)}",
        f"- **distinct tarballs:** {distinct_tarballs} / distinct main.py: "
        f"{distinct_mains}",
        f"- **ALL OK:** **{all_ok}**", "",
        "| candidate | family | profile | cg accepts | stdlib rejects | deck | fuzz | "
        "legal | no-ref-match | ok |",
        "|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in results:
        bs = r.get("behavior_summary", {})
        md.append(
            f"| `{r['candidate_id']}` | {r.get('parent_family')} | "
            f"`{r.get('profile_id')}` | {r['cg_typed_lane_accepts']['accepts']} | "
            f"{r['stdlib_lane_rejects']['rejects']} | {bs.get('deck_ok')} | "
            f"{bs.get('fuzz_never_raise_ok')} | {bs.get('legality_ok')} | "
            f"{r['lane_separation']['no_ref_hash_match']} | {r['candidate_ok']} |")
    md += ["", f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**"]
    (EXP / "pass46h_candidate_validation.md").write_text("\n".join(md) + "\n",
                                                         encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "n_candidates": len(results),
                      "distinct_tarballs": distinct_tarballs,
                      "distinct_main_py": distinct_mains,
                      "per_candidate": [{"id": r["candidate_id"],
                                         "ok": r["candidate_ok"]}
                                        for r in results]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
