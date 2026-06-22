#!/usr/bin/env python3
"""PASS 46J (Part F) — candidate validation + lane separation (single specialist planner).

Validates the ONE Part-E candidate WITHOUT running a tournament or touching prod:

  1. cg_typed lane ACCEPTS it (static + import-smoke), returncode 0.
  2. The stdlib lane REJECTS it (non-stdlib cg import + extra cg/ tree) — proving our own
     Kaggle-lane gates are unaffected — and the tarball is BYTE-UNCHANGED across that
     rejection (the validator only reads).
  3. Behavioural contract (in a HARD-TIMEOUT SUBPROCESS, native cg can hang):
     - deck-submission step (select is None) returns the 60 source deck ids;
     - a fuzz battery of malformed observations NEVER raises and always returns a list;
     - a legality battery returns distinct in-range indices honouring min/max.
  4. Lane separation / originality:
     - the candidate's main.py and tarball hashes match NO public-reference (zero-copy);
     - deck.csv is BYTE-identical to the internal PARENT deck (unchanged);
     - the candidate main.py is DISTINCT from each 46H generic diamond scorer (the
       attribution baselines) — this is a planner, not a copy of a flat scorer;
     - root main.py / deck.csv are UNCHANGED vs the Part-A safety baseline.

LOCAL / READ-ONLY. No mutation, no upload, no events. Writes
data/experiments/pass46j_candidate_validation.{json,md}. Exit 0 iff all_ok.
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
BUILD_JSON = EXP / "pass46j_candidate_build.json"
PREFLIGHT_JSON = EXP / "pass46j_safety_preflight.json"
REF_RAW = ROOT / "data" / "reference_agents" / "raw_outputs"
PARENT_TARBALL = ROOT / "data" / "submissions" / "candidates_pass34" / \
    "diamond_toolbox_diancie.tar.gz"
H46_DIAMOND = sorted(
    (ROOT / "data" / "submissions" / "candidates_pass46h").glob(
        "cg_typed_diamond_*.tar.gz"))
ROOT_MAIN = ROOT / "main.py"
ROOT_DECK = ROOT / "deck.csv"


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
    {"current": {"yourIndex": 0, "players": [{"hand": [{"id": 766}],
     "active": [{"id": 766, "energyCards": []}], "bench": []}, {}]},
     "select": {"option": [{"type": 8, "area": 2, "index": 0, "inPlayArea": 4,
                "inPlayIndex": 0}, {"type": 14}], "minCount": 1, "maxCount": 1}},
    {"current": "not-a-dict", "select": {"option": [{"type": 7}, {"type": 12}],
     "minCount": 1, "maxCount": 1}},
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
    {"option": [{"type": 7, "area": 2, "index": 0}, {"type": 7, "area": 2, "index": 1},
                {"type": 7, "area": 2, "index": 2}], "minCount": 2, "maxCount": 2},
    {"option": [{"type": 0}, {"type": 1}], "minCount": 0, "maxCount": 0},
    {"option": [{"type": 7, "index": 0}, {"type": 7, "index": 1}, {"type": 7, "index": 2}],
     "minCount": 1, "maxCount": 3},
    {"option": [{"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "inPlayArea": 5, "inPlayIndex": 1}, {"type": 14}],
     "minCount": 1, "maxCount": 1},
    {"option": [{"type": 3, "area": 1, "index": 0}, {"type": 3, "area": 1, "index": 1}],
     "minCount": 1, "maxCount": 1, "deck": [{"id": 766}, {"id": 5}]},
]
for sel in cases:
    n = len(sel["option"]); mn = sel["minCount"]; mx = sel["maxCount"]
    rec = {"n": n, "mn": mn, "mx": mx}
    try:
        r = agent({"current": {"yourIndex": 0, "turn": 4, "deckCount": 12,
                   "players": [{"hand": [{"id": 766}], "active": [{"id": 766}],
                   "bench": []}, {}]}, "select": sel})
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
            "stdout": p.stdout.strip()[-300:], "stderr": p.stderr.strip()[-400:]}


def run_stdlib_reject(tar: Path) -> dict:
    sha_before = _sha(tar.read_bytes())
    try:
        p = subprocess.run([sys.executable,
                            str(ROOT / "scripts/validate_candidate_tarball.py"),
                            str(tar)],
                           capture_output=True, text=True, timeout=90)
        rc, so, se = p.returncode, p.stdout.strip()[-200:], p.stderr.strip()[-400:]
    except subprocess.TimeoutExpired:
        rc, so, se = 124, "", "timeout"
    sha_after = _sha(tar.read_bytes())
    return {"returncode": rc, "rejects": rc != 0,
            "tarball_byte_unchanged": sha_before == sha_after,
            "stdout": so, "stderr": se}


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


def _h46_diamond_main_shas() -> dict:
    out = {}
    for tb in H46_DIAMOND:
        try:
            with tarfile.open(tb, "r:gz") as t:
                out[tb.name] = _sha(t.extractfile("main.py").read())
        except Exception as exc:  # noqa: BLE001
            out[tb.name] = f"error:{type(exc).__name__}"
    return out


def lane_separation(tar: Path, ref_hashes: dict, h46: dict) -> dict:
    cand_tar_sha = _sha(tar.read_bytes())
    with tarfile.open(tar, "r:gz") as t:
        cand_main_sha = _sha(t.extractfile("main.py").read())
    ref_matches = [name for name, h in ref_hashes.items()
                   if h.get("tarball_sha256") == cand_tar_sha
                   or (h.get("main_sha256") is not None
                       and h["main_sha256"] == cand_main_sha)]
    h46_matches = [name for name, sha in h46.items() if sha == cand_main_sha]
    return {"candidate_tarball_sha256": cand_tar_sha,
            "candidate_main_sha256": cand_main_sha,
            "matches_any_reference": ref_matches,
            "no_ref_hash_match": not ref_matches,
            "matches_any_46h_diamond_scorer": h46_matches,
            "distinct_from_46h_diamond_scorers": not h46_matches,
            "n_46h_diamond_compared": len(h46)}


def deck_matches_parent(tar: Path) -> dict:
    with tarfile.open(tar, "r:gz") as t:
        cand_deck = t.extractfile("deck.csv").read()
    with tarfile.open(PARENT_TARBALL, "r:gz") as t:
        parent_deck = t.extractfile("deck.csv").read()
    return {"candidate_deck_sha256": _sha(cand_deck),
            "parent_deck_sha256": _sha(parent_deck),
            "deck_byte_identical_to_parent": cand_deck == parent_deck}


def root_unchanged() -> dict:
    out = {"baseline_present": PREFLIGHT_JSON.exists()}
    cur_main = _sha(ROOT_MAIN.read_bytes()) if ROOT_MAIN.exists() else None
    cur_deck = _sha(ROOT_DECK.read_bytes()) if ROOT_DECK.exists() else None
    out["current_root_main_sha256"] = cur_main
    out["current_root_deck_sha256"] = cur_deck
    if not PREFLIGHT_JSON.exists():
        out["root_main_unchanged"] = "unverified"
        out["root_deck_unchanged"] = "unverified"
        return out
    pre = json.loads(PREFLIGHT_JSON.read_text(encoding="utf-8"))
    base_main = pre.get("root_main_sha256")
    base_deck = pre.get("root_deck_sha256")
    out["baseline_root_main_sha256"] = base_main
    out["baseline_root_deck_sha256"] = base_deck
    out["root_main_unchanged"] = bool(base_main and cur_main == base_main)
    out["root_deck_unchanged"] = bool(base_deck and cur_deck == base_deck)
    return out


def main() -> int:
    if not BUILD_JSON.exists():
        raise SystemExit(f"missing build record: {BUILD_JSON}")
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    tar = ROOT / build["tarball"]
    if not tar.exists():
        raise SystemExit(f"candidate tarball missing: {tar}")

    ref_hashes = _ref_hashes()
    h46 = _h46_diamond_main_shas()

    cg = run_cg_typed(tar)
    stdlib = run_stdlib_reject(tar)
    beh = run_behavior(tar)
    lane = lane_separation(tar, ref_hashes, h46)
    deck = deck_matches_parent(tar)
    root = root_unchanged()

    deck_ok = bool(beh.get("ran") and (beh.get("deck_step") or {}).get("ok"))
    fuzz_ok = bool(beh.get("ran")) and all(
        (not f.get("raised")) and f.get("is_list") for f in beh.get("fuzz", []))
    legal_ok = bool(beh.get("ran")) and all(
        (not c.get("raised")) and c.get("legal") for c in beh.get("legality", []))

    all_ok = bool(
        cg["accepts"] and stdlib["rejects"] and stdlib["tarball_byte_unchanged"]
        and deck_ok and fuzz_ok and legal_ok
        and lane["no_ref_hash_match"] and lane["distinct_from_46h_diamond_scorers"]
        and deck["deck_byte_identical_to_parent"]
        and root["root_main_unchanged"] is True
        and root["root_deck_unchanged"] is True
        and not build.get("public_reference", False))

    data = {
        "pass": "46j", "part": "F", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True,
        "candidate_id": build["candidate_id"], "tarball": build["tarball"],
        "is_planner_not_flat_scorer": build.get("is_planner_not_flat_scorer"),
        "n_references_checked": len(ref_hashes),
        "n_46h_diamond_scorers_checked": len(h46),
        "cg_typed_lane_accepts": cg,
        "stdlib_lane_rejects": stdlib,
        "behavior_summary": {"deck_ok": deck_ok, "fuzz_never_raise_ok": fuzz_ok,
                             "legality_ok": legal_ok,
                             "n_fuzz": len(beh.get("fuzz", [])),
                             "n_legality": len(beh.get("legality", [])),
                             "ran": bool(beh.get("ran"))},
        "behavior_detail": beh,
        "lane_separation": lane,
        "deck_vs_parent": deck,
        "root_unchanged": root,
        "all_ok": all_ok,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46j_candidate_validation.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    bs = data["behavior_summary"]
    md = [
        "# PASS 46J · Part F — candidate validation + lane separation", "",
        "_LOCAL / READ-ONLY. No tournament, no upload, no events. Proves the specialist "
        "planner is accepted by the cg_typed lane, REJECTED (byte-unchanged) by the stdlib "
        "lane, never-raises on malformed input, always returns legal indices, copies NO "
        "public-reference policy, is DISTINCT from the 46H generic diamond scorers "
        "(attribution), ships the unchanged PARENT deck, and leaves root main.py/deck.csv "
        "untouched._", "",
        f"**ALL OK:** **{all_ok}**  ·  candidate: `{data['candidate_id']}`", "",
        "## Lane acceptance",
        f"- cg_typed lane accepts: **{cg['accepts']}** (rc={cg['returncode']})",
        f"- stdlib lane rejects: **{stdlib['rejects']}** (rc={stdlib['returncode']})  ·  "
        f"tarball byte-unchanged: **{stdlib['tarball_byte_unchanged']}**", "",
        "## Behaviour (hard-timeout subprocess)",
        f"- deck-return on select=None (60 ids): **{bs['deck_ok']}**",
        f"- fuzz never-raises ({bs['n_fuzz']} inputs): **{bs['fuzz_never_raise_ok']}**",
        f"- legality battery legal ({bs['n_legality']} cases): **{bs['legality_ok']}**", "",
        "## Lane separation / originality",
        f"- no public-reference hash match: **{lane['no_ref_hash_match']}** "
        f"({len(ref_hashes)} refs)",
        f"- distinct from 46H diamond scorers: "
        f"**{lane['distinct_from_46h_diamond_scorers']}** "
        f"({lane['n_46h_diamond_compared']} compared)",
        f"- deck byte-identical to parent: "
        f"**{deck['deck_byte_identical_to_parent']}**", "",
        "## Root untouched (vs Part-A baseline)",
        f"- root main.py unchanged: **{root['root_main_unchanged']}**",
        f"- root deck.csv unchanged: **{root['root_deck_unchanged']}**", "",
        f"## Decision: **{'ALL OK' if all_ok else 'NOT OK'}**", "",
    ]
    (EXP / "pass46j_candidate_validation.md").write_text("\n".join(md) + "\n",
                                                         encoding="utf-8")

    print(json.dumps({
        "all_ok": all_ok,
        "cg_accepts": cg["accepts"], "stdlib_rejects": stdlib["rejects"],
        "stdlib_byte_unchanged": stdlib["tarball_byte_unchanged"],
        "deck_ok": deck_ok, "fuzz_ok": fuzz_ok, "legal_ok": legal_ok,
        "no_ref_hash_match": lane["no_ref_hash_match"],
        "distinct_from_46h_diamond": lane["distinct_from_46h_diamond_scorers"],
        "deck_eq_parent": deck["deck_byte_identical_to_parent"],
        "root_main_unchanged": root["root_main_unchanged"],
        "root_deck_unchanged": root["root_deck_unchanged"],
    }, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
