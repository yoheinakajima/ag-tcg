#!/usr/bin/env python3
"""Pass 35 — build typed candidates (T-G).

LOCAL ONLY. No Kaggle upload/submit, no GitHub push. NEVER touches the repo-root
main.py/deck.csv. No invented card ids (decks come verbatim from each parent's
existing tarball; we only READ those tarballs, never mutate them). The card CSV
is read locally to inline a minimal derived metadata table and is never shipped
or committed.

For every EXECUTABLE, gate-passing StrategyProfile we build a TYPED CHILD:
    child main.py = parent's extracted main.py  +  PASS35 typed override
    child deck.csv = parent's deck.csv  (byte-identical; deck is never changed)
The parent is the deck's latest existing tarball; the child differs ONLY by the
appended typed override, so T-K's parent-vs-child A/B isolates the typed layer.

Special-pilot-only profiles (executable=false) are intentionally NOT built.

Outputs:
    data/submissions/candidates_pass35/<id>/{main.py,deck.csv}
    data/submissions/candidates_pass35/<id>.tar.gz
    data/experiments/pass35_meta_audit/<id>.json   (derived metadata only)
    data/experiments/pass35_candidate_build.{json,md}
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import yaml  # noqa: E402

from ptcg_activegraph.pilot_typed.compiler import (  # noqa: E402
    build_metadata_table, build_profile_literal, compile_candidate_source,
    make_tarball, write_metadata_audit, _profile_card_ids,
)

REGISTRY = os.path.join(ROOT, "experiments", "strategy_profiles.yaml")
CARD_CSV = os.path.join(ROOT, "data", "cards", "EN_Card_Data.csv")
GATE_JSON = os.path.join(ROOT, "data", "reports", "pass35_typed_strategy_gate.json")
OUT_DIR = os.path.join(ROOT, "data", "submissions", "candidates_pass35")
AUDIT_DIR = os.path.join(ROOT, "data", "experiments", "pass35_meta_audit")
OUT_JSON = os.path.join(ROOT, "data", "experiments", "pass35_candidate_build.json")
OUT_MD = os.path.join(ROOT, "data", "experiments", "pass35_candidate_build.md")

ROOT_MAIN = os.path.join(ROOT, "main.py")
ROOT_DECK = os.path.join(ROOT, "deck.csv")

# Each typed child is built on its deck's latest existing tarball (the parent).
PARENT_TARBALL = {
    "water_core_reference":
        "data/submissions/candidates_pass33/league_water_core_reference.tar.gz",
    "water_basic_density_v1":
        "data/submissions/candidates_pass33/water_basic_density_v1.tar.gz",
    "dragapult_spread_control":
        "data/submissions/candidates_pass33/league_dragapult_spread.tar.gz",
    "mono_lightning_miraidon_easy":
        "data/submissions/candidates_pass34/mono_lightning_miraidon_easy.tar.gz",
    "diamond_toolbox_diancie":
        "data/submissions/candidates_pass34/diamond_toolbox_diancie.tar.gz",
    "mega_charizard_x_burst":
        "data/submissions/candidates_pass33/league_mega_charizard_x_burst.tar.gz",
    "mega_venusaur_tank":
        "data/submissions/candidates_pass33/league_mega_venusaur_tank.tar.gz",
    "mega_gardevoir_psychic_ramp":
        "data/submissions/candidates_pass33/league_mega_gardevoir_psychic_ramp.tar.gz",
    "raging_bolt_ogerpon_basic_aggro":
        "data/submissions/candidates_pass33/league_raging_bolt_ogerpon.tar.gz",
}


def sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_parent(tar_rel: str, dest: str) -> tuple:
    """Extract parent main.py + deck.csv into dest. Returns (main_path, deck_path)."""
    tar_abs = os.path.join(ROOT, tar_rel)
    with tarfile.open(tar_abs) as t:
        members = {m.name for m in t.getmembers()}
        if members != {"main.py", "deck.csv"}:
            raise RuntimeError(f"{tar_rel}: unexpected members {sorted(members)}")
        for name in ("main.py", "deck.csv"):
            t.extract(name, dest)
    return os.path.join(dest, "main.py"), os.path.join(dest, "deck.csv")


def deck_rows(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.isdigit():
                rows.append(int(s))
    return rows


def quick_entry_check(cand_dir: str) -> dict:
    """py_compile + import the child main.py in a subprocess; confirm the LAST
    callable returns 60 ids on a deck-selection obs and never raises on a
    minimal gameplay obs. Full validation is T-H; this just rejects broken builds."""
    code = r'''
import importlib.util, sys, os
d = sys.argv[1]
os.chdir(d)
spec = importlib.util.spec_from_file_location("cand_main", os.path.join(d, "main.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ns = vars(m)
last = [v for v in ns.values() if callable(v)][-1]
shapes = [
    {"current": None, "select": None, "logs": [], "step": 0},
    {"logs": [], "step": 0},
]
for s in shapes:
    r = last(s)
    assert isinstance(r, list) and len(r) == 60, ("deck", len(r) if isinstance(r, list) else r)
# minimal gameplay obs must not raise
gp = {"current": {"players": [], "yourIndex": 0},
      "select": {"context": 99, "options": [], "minCount": 0, "maxCount": 0},
      "step": 1}
_ = last(gp)
print("OK")
'''
    try:
        p = subprocess.run([sys.executable, "-c", code, cand_dir],
                           capture_output=True, text=True, timeout=120)
        ok = p.returncode == 0 and "OK" in p.stdout
        return {"ok": ok, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()[-800:]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stdout": "", "stderr": f"{type(e).__name__}: {e}"}


def main() -> int:
    # Root-safety re-assert: we must never have touched root main.py/deck.csv.
    base_main_sha = sha1(os.path.join(ROOT, "data", "baselines",
                                      "v1_kaggle_349_8", "main.py"))
    base_deck_sha = sha1(os.path.join(ROOT, "data", "baselines",
                                      "v1_kaggle_349_8", "deck.csv"))
    root_safe = (sha1(ROOT_MAIN) == base_main_sha and
                 sha1(ROOT_DECK) == base_deck_sha)

    with open(REGISTRY, encoding="utf-8") as f:
        reg = yaml.safe_load(f)
    profiles = {p["id"]: p for p in (reg.get("profiles") or [])}

    gate_ok = False
    if os.path.exists(GATE_JSON):
        with open(GATE_JSON, encoding="utf-8") as f:
            gate_ok = bool(json.load(f).get("all_ok"))

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(AUDIT_DIR, exist_ok=True)

    results = []
    for pid, profile in profiles.items():
        executable = bool(profile.get("executable"))
        if not executable:
            results.append({"id": pid, "executable": False, "built": False,
                            "reason": "special-pilot-only (executable=false)",
                            "skipped": True})
            continue
        if not gate_ok:
            results.append({"id": pid, "executable": True, "built": False,
                            "reason": "typed strategy gate not all_ok"})
            continue
        parent_rel = PARENT_TARBALL.get(pid)
        if not parent_rel or not os.path.exists(os.path.join(ROOT, parent_rel)):
            results.append({"id": pid, "executable": True, "built": False,
                            "reason": f"parent tarball missing: {parent_rel}"})
            continue

        with tempfile.TemporaryDirectory() as tmp:
            try:
                pmain, pdeck = extract_parent(parent_rel, tmp)
            except Exception as e:  # noqa: BLE001
                results.append({"id": pid, "built": False,
                                "reason": f"extract failed: {e}"})
                continue
            parent_deck = deck_rows(pdeck)
            if len(parent_deck) != 60:
                results.append({"id": pid, "built": False,
                                "reason": f"parent deck not 60 rows ({len(parent_deck)})"})
                continue

            literal = build_profile_literal(profile)
            card_ids = _profile_card_ids(literal)
            meta_table = build_metadata_table(CARD_CSV, card_ids)
            base_main_src = open(pmain, encoding="utf-8").read()
            candidate_id = f"{pid}_typed35"
            src = compile_candidate_source(base_main_src, profile, meta_table,
                                           candidate_id)

            cand_dir = os.path.join(OUT_DIR, pid)
            os.makedirs(cand_dir, exist_ok=True)
            with open(os.path.join(cand_dir, "main.py"), "w", encoding="utf-8") as f:
                f.write(src)
            # deck.csv byte-identical to the parent's deck (no deck mutation).
            with open(pdeck, encoding="utf-8") as src_f, \
                    open(os.path.join(cand_dir, "deck.csv"), "w",
                         encoding="utf-8") as dst_f:
                dst_f.write(src_f.read())

        child_deck = deck_rows(os.path.join(cand_dir, "deck.csv"))
        deck_identical = child_deck == parent_deck
        tar_path = os.path.join(OUT_DIR, f"{pid}.tar.gz")
        make_tarball(cand_dir, tar_path)
        write_metadata_audit(CARD_CSV, card_ids,
                             os.path.join(AUDIT_DIR, f"{pid}.json"))
        entry = quick_entry_check(cand_dir)

        built = deck_identical and len(child_deck) == 60 and entry["ok"]
        results.append({
            "id": pid, "candidate_id": candidate_id, "executable": True,
            "parent_tarball": parent_rel,
            "implemented_contexts": list(literal.get("implemented_contexts") or []),
            "meta_card_count": len(meta_table),
            "deck_unique": len(set(child_deck)),
            "deck_count": len(child_deck),
            "deck_identical_to_parent": deck_identical,
            "tarball": os.path.relpath(tar_path, ROOT),
            "tarball_sha1": sha1(tar_path),
            "entry_check": entry,
            "built": built,
            "reason": "ok" if built else "entry/deck check failed",
        })

    n_built = sum(1 for r in results if r.get("built"))
    n_exec = sum(1 for r in results if r.get("executable"))
    n_skipped = sum(1 for r in results if r.get("skipped"))
    all_built = all(r.get("built") for r in results if r.get("executable"))

    summary = {
        "no_upload": True, "upload_performed": False,
        "card_csv_committed": False, "root_safe": root_safe,
        "typed_strategy_gate_ok": gate_ok,
        "executable_profiles": n_exec, "built": n_built,
        "special_pilot_only_skipped": n_skipped,
        "all_executable_built": all_built,
        "candidates": results,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    lines = ["# Pass 35 — typed candidate build", "",
             "> LOCAL ONLY. No Kaggle upload/submit, no GitHub push. Root "
             "main.py/deck.csv untouched. Decks copied byte-identical from each "
             "parent's existing tarball (no invented ids).", "",
             f"- root_safe: **{root_safe}**  typed_gate_ok: **{gate_ok}**",
             f"- executable profiles: **{n_exec}**  built: **{n_built}**  "
             f"special-pilot-only skipped: **{n_skipped}**",
             f"- all executable built: **{all_built}**", "",
             "| id | built | contexts | deck (uniq/total) | deck==parent | meta | tarball |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("skipped"):
            lines.append(f"| {r['id']} | SKIP (special-pilot-only) | - | - | - | - | - |")
            continue
        if not r.get("built") and "deck_count" not in r:
            lines.append(f"| {r['id']} | FAIL ({r.get('reason')}) | - | - | - | - | - |")
            continue
        lines.append(
            f"| {r['id']} | {'OK' if r['built'] else 'FAIL'} | "
            f"{r.get('implemented_contexts')} | "
            f"{r.get('deck_unique')}/{r.get('deck_count')} | "
            f"{r.get('deck_identical_to_parent')} | {r.get('meta_card_count')} | "
            f"`{r.get('tarball')}` |")
    lines.append("")
    fails = [r for r in results if r.get("executable") and not r.get("built")]
    if fails:
        lines.append("## Build failures")
        lines.append("")
        for r in fails:
            ec = r.get("entry_check") or {}
            lines.append(f"- **{r['id']}**: {r.get('reason')} {ec.get('stderr','')}")
        lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"built {n_built}/{n_exec} executable (skipped {n_skipped} special-pilot-only); "
          f"root_safe={root_safe} gate_ok={gate_ok} all_built={all_built}")
    for r in results:
        if r.get("executable") and not r.get("built"):
            ec = r.get("entry_check") or {}
            print(f"  FAIL {r['id']}: {r.get('reason')} :: {ec.get('stderr','')[:300]}")
    print(f"wrote {os.path.relpath(OUT_JSON, ROOT)} and {os.path.relpath(OUT_MD, ROOT)}")
    return 0 if (root_safe and all_built) else 1


if __name__ == "__main__":
    raise SystemExit(main())
