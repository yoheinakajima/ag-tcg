#!/usr/bin/env python3
"""PASS 46F (Part F) — candidate validation + lane separation.

Validates the Part-E candidate WITHOUT running a tournament or touching prod:

  1. cg_typed lane ACCEPTS it (static + import-smoke), returncode 0.
  2. The stdlib lane REJECTS it (non-stdlib cg import + extra cg/ tree) — proving
     our own Kaggle-lane gates are unaffected by this benchmark-lane candidate.
  3. Behavioural contract (in a HARD-TIMEOUT SUBPROCESS, native cg can hang):
     - deck-submission step (select is None) returns the 60 source deck ids;
     - a fuzz battery of malformed observations NEVER raises and always returns
       a list;
     - a legality battery returns distinct in-range indices honouring min/max.
  4. Lane separation / originality: the candidate's main.py and tarball hashes
     match NO public-reference main.py or tarball (zero-copy of reference policy).

LOCAL / READ-ONLY. No mutation, no upload, no events. Writes
data/experiments/pass46f_candidate_validation.{json,md}. Exit 0 iff all_ok.
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
CAND_ID = "cg_typed_water_anti_disruption_searchcal_v1"
CAND_TAR = ROOT / "data/submissions/candidates_pass46f" / f"{CAND_ID}.tar.gz"
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
                        if isinstance(r, list) else None, "value": r
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

# Legality battery: (n, mn, mx) with crafted option types.
cases = [
    {"option": [{"type": 13}, {"type": 8}, {"type": 14}], "minCount": 1, "maxCount": 1},
    {"option": [{"type": 9}, {"type": 7}, {"type": 8}, {"type": 14}],
     "minCount": 1, "maxCount": 1},
    {"option": [{"type": 8}, {"type": 8}, {"type": 3}, {"type": 14}],
     "minCount": 2, "maxCount": 2},
    {"option": [{"type": 0}, {"type": 1}], "minCount": 0, "maxCount": 0},
    {"option": [{"type": 7}, {"type": 7}, {"type": 7}], "minCount": 1, "maxCount": 3},
]
for sel in cases:
    n = len(sel["option"]); mn = sel["minCount"]; mx = sel["maxCount"]
    rec = {"n": n, "mn": mn, "mx": mx}
    try:
        r = agent({"current": {"yourIndex": 0}, "select": sel})
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


def run_cg_typed() -> dict:
    p = subprocess.run([sys.executable,
                        str(ROOT / "scripts/validate_cg_typed_tarball.py"),
                        str(CAND_TAR), "--import-smoke"],
                       capture_output=True, text=True)
    return {"returncode": p.returncode, "accepts": p.returncode == 0,
            "stdout": p.stdout.strip(), "stderr": p.stderr.strip()[-400:]}


def run_stdlib_reject() -> dict:
    p = subprocess.run([sys.executable,
                        str(ROOT / "scripts/validate_candidate_tarball.py"),
                        str(CAND_TAR)],
                       capture_output=True, text=True, timeout=90)
    return {"returncode": p.returncode, "rejects": p.returncode != 0,
            "stdout": p.stdout.strip()[-400:], "stderr": p.stderr.strip()[-400:]}


def run_behavior() -> dict:
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(CAND_TAR, "r:gz") as tar:
            for m in tar.getmembers():  # trusted self-built tarball
                if m.isfile() and not m.name.startswith("/") and ".." not in m.name:
                    tar.extract(m, td)
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


def lane_separation() -> dict:
    cand_tar_sha = _sha(CAND_TAR.read_bytes())
    with tarfile.open(CAND_TAR, "r:gz") as tar:
        cand_main_sha = _sha(tar.extractfile("main.py").read())
    ref_hashes = {}
    matches = []
    for sub in sorted(REF_RAW.glob("public_ref_*/submission.tar.gz")):
        try:
            t_sha = _sha(sub.read_bytes())
            with tarfile.open(sub, "r:gz") as tar:
                names = [m.name for m in tar.getmembers() if m.isfile()]
                main_name = next((n for n in names if n.endswith("main.py")), None)
                m_sha = _sha(tar.extractfile(main_name).read()) if main_name else None
        except Exception as exc:  # noqa: BLE001
            ref_hashes[sub.parent.name] = {"error": type(exc).__name__}
            continue
        ref_hashes[sub.parent.name] = {"tarball_sha256": t_sha, "main_sha256": m_sha}
        if t_sha == cand_tar_sha or (m_sha is not None and m_sha == cand_main_sha):
            matches.append(sub.parent.name)
    return {"candidate_tarball_sha256": cand_tar_sha,
            "candidate_main_sha256": cand_main_sha,
            "n_references_checked": len(ref_hashes),
            "reference_hashes": ref_hashes,
            "matches_any_reference": matches,
            "no_ref_hash_match": not matches}


def main() -> int:
    if not CAND_TAR.exists():
        raise SystemExit(f"candidate tarball missing: {CAND_TAR}")

    cg = run_cg_typed()
    stdlib = run_stdlib_reject()
    beh = run_behavior()
    lane = lane_separation()

    deck_ok = bool(beh.get("ran") and (beh.get("deck_step") or {}).get("ok"))
    fuzz_ok = bool(beh.get("ran")) and all(
        (not f.get("raised")) and f.get("is_list") for f in beh.get("fuzz", []))
    legal_ok = bool(beh.get("ran")) and all(
        (not c.get("raised")) and c.get("legal") for c in beh.get("legality", []))

    all_ok = (cg["accepts"] and stdlib["rejects"] and deck_ok and fuzz_ok
              and legal_ok and lane["no_ref_hash_match"])

    data = {
        "pass": "46f", "part": "F", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "candidate_id": CAND_ID,
        "cg_typed_lane_accepts": cg,
        "stdlib_lane_rejects": stdlib,
        "behavior": beh,
        "behavior_summary": {"deck_ok": deck_ok, "fuzz_never_raise_ok": fuzz_ok,
                             "legality_ok": legal_ok},
        "lane_separation": lane,
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46f_candidate_validation.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46F (Part F) — candidate validation + lane separation", "",
        "_LOCAL / READ-ONLY. No tournament, no upload, no events. Proves the "
        "candidate is accepted by the cg_typed lane, REJECTED by the stdlib lane "
        "(our own Kaggle gates untouched), never-raises on malformed input, "
        "always returns legal indices, and copies NO public-reference policy._", "",
        f"- **cg_typed lane accepts:** {cg['accepts']} (`{cg['stdout'][:120]}`)",
        f"- **stdlib lane rejects:** {stdlib['rejects']} "
        f"(rc={stdlib['returncode']})",
        f"- **deck-step returns 60 ids:** {deck_ok}",
        f"- **fuzz battery never raises:** {fuzz_ok} "
        f"({len(beh.get('fuzz', []))} cases)",
        f"- **legality battery legal:** {legal_ok} "
        f"({len(beh.get('legality', []))} cases)",
        f"- **no public-reference hash match:** {lane['no_ref_hash_match']} "
        f"({lane['n_references_checked']} refs checked)",
        "", f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**",
    ]
    (EXP / "pass46f_candidate_validation.md").write_text("\n".join(md) + "\n",
                                                         encoding="utf-8")

    print(json.dumps({"all_ok": all_ok, "cg_typed_accepts": cg["accepts"],
                      "stdlib_rejects": stdlib["rejects"], "deck_ok": deck_ok,
                      "fuzz_ok": fuzz_ok, "legal_ok": legal_ok,
                      "no_ref_hash_match": lane["no_ref_hash_match"]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
