#!/usr/bin/env python3
"""Pass 35 — StrategyProfile registry builder / validator.

LOCAL ONLY. No Kaggle upload/submit, no GitHub push. Reads
``experiments/strategy_profiles.yaml``, validates each profile against
``src/ptcg_activegraph/pilot_typed/profiles.py`` and re-checks every referenced
card id against ``data/cards/EN_Card_Data.csv`` (gitignored, never committed; no
invented ids). Renders ``data/experiments/pass35_strategy_profiles.{json,md}``.

Honesty guards enforced here (fail the build):
  * every card id (card_ids + roles + priority + discard_*) exists in the CSV;
  * executable profiles only claim contexts in {0,1,2,7,8,38};
  * profiles only list known unsupported mechanics;
  * special-pilot-only profiles are executable:false with empty
    implemented_contexts;
  * profile-level validate_profile() reports no errors.
"""
from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import yaml  # noqa: E402

from ptcg_activegraph.pilot_typed import profiles as P  # noqa: E402

REGISTRY = os.path.join(ROOT, "experiments", "strategy_profiles.yaml")
CARD_CSV = os.path.join(ROOT, "data", "cards", "EN_Card_Data.csv")
OUT_JSON = os.path.join(ROOT, "data", "experiments", "pass35_strategy_profiles.json")
OUT_MD = os.path.join(ROOT, "data", "experiments", "pass35_strategy_profiles.md")

VALID_CONTEXTS = {0, 1, 2, 7, 8, 38}


def load_card_ids(path: str) -> set:
    ids = set()
    if not os.path.exists(path):
        raise SystemExit(f"FATAL: card CSV not found at {path} (required for id validation)")
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = (row.get("Card ID") or "").strip()
            if cid.isdigit():
                ids.add(int(cid))
    return ids


def referenced_ids(profile: dict) -> set:
    ids = set()
    for cid in profile.get("card_ids", []) or []:
        if isinstance(cid, int):
            ids.add(cid)
    for role_ids in (profile.get("roles") or {}).values():
        for cid in role_ids or []:
            if isinstance(cid, int):
                ids.add(cid)
    for key in ("priority", "discard_keep", "discard_prefer"):
        for cid in profile.get(key, []) or []:
            if isinstance(cid, int):
                ids.add(cid)
    return ids


def check_profile(profile: dict, known_ids: set) -> dict:
    errors: list = []
    warnings: list = []

    base = P.validate_profile(profile)
    errors.extend(base["errors"])
    warnings.extend(base["warnings"])

    # 1. every referenced id must exist in the CSV (no invented ids).
    missing = sorted(referenced_ids(profile) - known_ids)
    if missing:
        errors.append(f"unknown/invented card ids (not in CSV): {missing}")

    pid = profile.get("id")
    executable = bool(profile.get("executable"))
    contexts = list(P.implemented_contexts(profile))
    special = bool(profile.get("special_pilot_required"))

    # 2. contexts must be within the supported observable set.
    bad_ctx = [c for c in contexts if c not in VALID_CONTEXTS]
    if bad_ctx:
        errors.append(f"contexts outside supported set {sorted(VALID_CONTEXTS)}: {bad_ctx}")

    # 3. unsupported mechanics must be known (else the honesty list is bogus).
    for m in P.unsupported_mechanics(profile):
        if m not in P.KNOWN_UNSUPPORTED:
            errors.append(f"unknown unsupported mechanic {m!r}")

    # 4. special-pilot-only must be executable:false with no claimed contexts.
    if special and executable:
        errors.append("special_pilot_required profile must be executable:false")
    if not executable and contexts:
        errors.append("non-executable profile must not claim implemented_contexts")

    # 5. executable profiles must declare a primary attacker.
    if executable and not P.role_ids(profile, "primary_attacker"):
        errors.append("executable profile has no primary_attacker role")

    return {
        "id": pid,
        "executable": executable,
        "special_pilot_required": special,
        "lane": profile.get("lane"),
        "role": profile.get("role"),
        "parent": profile.get("parent"),
        "implemented_contexts": contexts,
        "unsupported_mechanics": P.unsupported_mechanics(profile),
        "energy_types": P.energy_types(profile),
        "n_card_ids": len(profile.get("card_ids", []) or []),
        "refuted": bool(profile.get("refuted")),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main() -> int:
    with open(REGISTRY, encoding="utf-8") as f:
        reg = yaml.safe_load(f)
    profiles = reg.get("profiles") or []
    known_ids = load_card_ids(CARD_CSV)

    results = [check_profile(p, known_ids) for p in profiles]
    n_ok = sum(1 for r in results if r["ok"])
    n_exec = sum(1 for r in results if r["executable"])
    n_special = sum(1 for r in results if r["special_pilot_required"])
    all_ok = all(r["ok"] for r in results)

    summary = {
        "schema": reg.get("schema"),
        "pass": reg.get("pass"),
        "lane": reg.get("lane"),
        "no_upload": True,
        "upload_performed": False,
        "card_csv_committed": False,
        "total_profiles": len(results),
        "ok_profiles": n_ok,
        "executable_profiles": n_exec,
        "special_pilot_only_profiles": n_special,
        "all_ok": all_ok,
        "profiles": results,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    lines = []
    lines.append("# Pass 35 — StrategyProfile registry validation")
    lines.append("")
    lines.append("> LOCAL ONLY. No Kaggle upload/submit, no GitHub push. Card CSV is "
                 "gitignored and never committed; all ids validated against it.")
    lines.append("")
    lines.append(f"- total profiles: **{len(results)}**  ok: **{n_ok}**  "
                 f"executable: **{n_exec}**  special-pilot-only: **{n_special}**")
    lines.append(f"- all_ok: **{all_ok}**  lane: `{reg.get('lane')}`")
    lines.append("")
    lines.append("| id | exec | role | parent | contexts | energy | unsupported | refuted | ok |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r['id']} | {r['executable']} | {r['role']} | {r['parent']} | "
            f"{r['implemented_contexts']} | {','.join(r['energy_types'])} | "
            f"{len(r['unsupported_mechanics'])} | {r['refuted']} | "
            f"{'OK' if r['ok'] else 'FAIL'} |")
    lines.append("")
    problems = [r for r in results if r["errors"] or r["warnings"]]
    if problems:
        lines.append("## Issues")
        lines.append("")
        for r in problems:
            for e in r["errors"]:
                lines.append(f"- **ERROR** [{r['id']}] {e}")
            for w in r["warnings"]:
                lines.append(f"- warning [{r['id']}] {w}")
        lines.append("")
    lines.append("## Honesty note")
    lines.append("")
    lines.append("Every executable profile lists the same unsupported-mechanic set "
                 "(attack damage, lethal, KO targeting, spread, Boss/gust, opponent "
                 "hand). The typed lane never acts on these; it refines only "
                 "observable board contexts and otherwise falls back to the proven "
                 "base policy. Raging Bolt is marked `refuted` and carries NO "
                 "color-match / attack-damage fix (Pass 28 refuted that hypothesis).")
    lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"profiles: {len(results)}  ok: {n_ok}  executable: {n_exec}  "
          f"special-pilot-only: {n_special}  all_ok: {all_ok}")
    print(f"wrote {os.path.relpath(OUT_JSON, ROOT)} and {os.path.relpath(OUT_MD, ROOT)}")
    if not all_ok:
        for r in results:
            for e in r["errors"]:
                print(f"  ERROR [{r['id']}] {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
