#!/usr/bin/env python3
"""Pass 35 — typed strategy gate.

LOCAL ONLY. No Kaggle upload/submit, no GitHub push. Replays every fixture in
``data/fixtures/pass35_typed_strategy/`` through the SAME public entry the
compiled runtime calls (``decisions.decide``), grading each decision against an
explicit expectation. Builds per-fixture ``meta`` exactly like the compiler does
(``build_metadata_table`` over the profile's card ids; the CSV is never shipped
or committed).

Honesty sweep: for every executable profile, the unsupported decision kinds
(attack, lethal, ko_target, spread, boss, gust) MUST report ``unsupported`` — the
typed layer never fabricates attack damage / lethal / spread / Boss-gust targets.

Coverage gate: every executable profile needs >= 1 graded case, and the named
required scenarios (keep-backup-Basic, no-spread-claim, attach-to-attacker,
loop-guard, no-fake-fix) must each appear at least once.

Outputs ``data/reports/pass35_typed_strategy_gate.{json,md}``. Exit non-zero if
any case fails, the honesty sweep fails, or coverage is incomplete.
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import yaml  # noqa: E402

from ptcg_activegraph.pilot_typed import decisions as D  # noqa: E402
from ptcg_activegraph.pilot_typed import profiles as P  # noqa: E402
from ptcg_activegraph.pilot_typed.compiler import build_metadata_table  # noqa: E402

REGISTRY = os.path.join(ROOT, "experiments", "strategy_profiles.yaml")
CARD_CSV = os.path.join(ROOT, "data", "cards", "EN_Card_Data.csv")
FIX_DIR = os.path.join(ROOT, "data", "fixtures", "pass35_typed_strategy")
OUT_JSON = os.path.join(ROOT, "data", "reports", "pass35_typed_strategy_gate.json")
OUT_MD = os.path.join(ROOT, "data", "reports", "pass35_typed_strategy_gate.md")

# Decision kinds the typed layer must always refuse to fabricate.
HONESTY_KINDS = ["attack", "lethal", "ko_target", "spread", "boss", "gust"]

# Required scenario tags, each must appear in >= 1 graded case across fixtures.
REQUIRED_TAGS = [
    "keep_backup_basic",        # Water family keeps a backup Basic
    "no_spread_claim",          # Dragapult never claims a spread target
    "attach_to_attacker",       # energy goes to the intended attacker
    "loop_guard",               # Venusaur loop / deckout guard preserved
    "no_fake_fix",              # Raging Bolt: no fabricated attack/color fix
]


def load_profiles() -> dict:
    with open(REGISTRY, encoding="utf-8") as f:
        reg = yaml.safe_load(f)
    return {p["id"]: p for p in (reg.get("profiles") or [])}


def grade_expect(result: dict, expect: dict) -> tuple:
    """Return (ok, detail) comparing a decide() result to an expectation."""
    if not isinstance(result, dict):
        return False, f"result not a dict: {result!r}"
    for key, want in expect.items():
        if key == "chosen_card_id":
            got = result.get("chosen_card_id")
            if got != want:
                return False, f"chosen_card_id={got} != {want}"
        elif key == "chosen_target_id":
            got = result.get("chosen_target_id")
            if got != want:
                return False, f"chosen_target_id={got} != {want}"
        elif key == "chosen_number":
            got = result.get("chosen_number")
            if got != want:
                return False, f"chosen_number={got} != {want}"
        elif key == "chosen_card_ids":
            got = result.get("chosen_card_ids")
            if got != want:
                return False, f"chosen_card_ids={got} != {want}"
        elif key == "chosen_card_ids_contains":
            got = result.get("chosen_card_ids") or []
            miss = [c for c in want if c not in got]
            if miss:
                return False, f"chosen_card_ids={got} missing {miss}"
        elif key == "chosen_card_ids_excludes":
            got = result.get("chosen_card_ids") or []
            bad = [c for c in want if c in got]
            if bad:
                return False, f"chosen_card_ids={got} must exclude {bad}"
        elif key == "unsupported":
            got = result.get("unsupported") is True
            if got != bool(want):
                return False, f"unsupported={got} != {want} (result={result})"
        elif key == "defer_to_base":
            is_empty = result == {}
            if is_empty != bool(want):
                return False, f"defer_to_base expected {want}, result={result}"
        else:
            return False, f"unknown expect key {key!r}"
    return True, "ok"


def check_profile_assertions(profile: dict, asserts: dict) -> list:
    errs = []
    for key, want in (asserts or {}).items():
        if key == "executable":
            got = bool(profile.get("executable"))
            if got != bool(want):
                errs.append(f"executable={got} != {want}")
        elif key == "special_pilot_required":
            got = bool(profile.get("special_pilot_required"))
            if got != bool(want):
                errs.append(f"special_pilot_required={got} != {want}")
        elif key == "refuted":
            got = bool(profile.get("refuted"))
            if got != bool(want):
                errs.append(f"refuted={got} != {want}")
        elif key == "implemented_contexts":
            got = list(P.implemented_contexts(profile))
            if got != list(want):
                errs.append(f"implemented_contexts={got} != {want}")
    return errs


def main() -> int:
    profiles = load_profiles()
    fixture_paths = sorted(glob.glob(os.path.join(FIX_DIR, "*.json")))

    fixtures = []
    seen_tags = set()
    total_cases = passed_cases = 0
    profile_errors = []

    for path in fixture_paths:
        with open(path, encoding="utf-8") as f:
            fx = json.load(f)
        pid = fx.get("profile_id")
        profile = profiles.get(pid)
        rel = os.path.relpath(path, ROOT)
        if profile is None:
            profile_errors.append(f"{rel}: profile {pid!r} not in registry")
            fixtures.append({"profile_id": pid, "path": rel, "ok": False,
                             "assertion_errors": [f"unknown profile {pid!r}"],
                             "cases": []})
            continue

        meta = build_metadata_table(CARD_CSV, profile.get("card_ids") or [])
        a_errs = check_profile_assertions(profile, fx.get("profile_assertions"))

        case_results = []
        for case in fx.get("cases") or []:
            total_cases += 1
            result = D.decide(case.get("kind"), case.get("board"),
                              case.get("options"), profile, meta)
            ok, detail = grade_expect(result, case.get("expect") or {})
            if ok:
                passed_cases += 1
                if case.get("tag"):
                    seen_tags.add(case["tag"])
            case_results.append({
                "name": case.get("name"), "tag": case.get("tag"),
                "kind": case.get("kind"), "result": result,
                "expect": case.get("expect"), "ok": ok, "detail": detail,
            })

        fixtures.append({
            "profile_id": pid, "path": rel,
            "executable": bool(profile.get("executable")),
            "assertion_errors": a_errs,
            "n_cases": len(case_results),
            "n_passed": sum(1 for c in case_results if c["ok"]),
            "cases": case_results,
            "ok": not a_errs and all(c["ok"] for c in case_results),
        })
        if a_errs:
            profile_errors.extend(f"{pid}: {e}" for e in a_errs)

    # Honesty sweep: every executable profile must refuse fabricated mechanics.
    honesty = []
    for pid, profile in profiles.items():
        if not profile.get("executable"):
            continue
        meta = build_metadata_table(CARD_CSV, profile.get("card_ids") or [])
        for kind in HONESTY_KINDS:
            res = D.decide(kind, {}, [], profile, meta)
            ok = res.get("unsupported") is True
            honesty.append({"profile_id": pid, "kind": kind,
                            "unsupported": bool(ok), "ok": ok})
    honesty_ok = all(h["ok"] for h in honesty)

    # Coverage: every executable profile has >= 1 graded case; required tags hit.
    exec_ids = [pid for pid, p in profiles.items() if p.get("executable")]
    covered = {fx["profile_id"] for fx in fixtures if (fx.get("n_cases") or 0) > 0}
    missing_cov = [pid for pid in exec_ids if pid not in covered]
    missing_tags = [t for t in REQUIRED_TAGS if t not in seen_tags]
    coverage_ok = not missing_cov and not missing_tags

    cases_ok = passed_cases == total_cases
    asserts_ok = not profile_errors
    all_ok = cases_ok and asserts_ok and honesty_ok and coverage_ok

    summary = {
        "no_upload": True,
        "upload_performed": False,
        "card_csv_committed": False,
        "lane": "stdlib_typed_lite",
        "total_fixtures": len(fixtures),
        "executable_profiles": len(exec_ids),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "cases_ok": cases_ok,
        "assertions_ok": asserts_ok,
        "honesty_sweep_ok": honesty_ok,
        "coverage_ok": coverage_ok,
        "missing_coverage_profiles": missing_cov,
        "missing_required_tags": missing_tags,
        "seen_tags": sorted(seen_tags),
        "all_ok": all_ok,
        "profile_errors": profile_errors,
        "honesty": honesty,
        "fixtures": fixtures,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    lines = ["# Pass 35 — typed strategy gate", "",
             "> LOCAL ONLY. No Kaggle upload/submit, no GitHub push. Decisions "
             "graded through the same `decide()` the compiled runtime calls; "
             "metadata built from the gitignored card CSV (never committed).", "",
             f"- result: **{'PASS' if all_ok else 'FAIL'}**  "
             f"(cases {passed_cases}/{total_cases})",
             f"- assertions_ok: **{asserts_ok}**  honesty_sweep_ok: "
             f"**{honesty_ok}**  coverage_ok: **{coverage_ok}**",
             f"- executable profiles: **{len(exec_ids)}**  fixtures: "
             f"**{len(fixtures)}**", ""]
    if missing_cov:
        lines.append(f"- MISSING coverage for: {missing_cov}")
    if missing_tags:
        lines.append(f"- MISSING required tags: {missing_tags}")
    lines.append("")
    lines.append("## Fixtures")
    lines.append("")
    lines.append("| profile | exec | cases | passed | assertions | ok |")
    lines.append("|---|---|---|---|---|---|")
    for fx in fixtures:
        lines.append(
            f"| {fx['profile_id']} | {fx.get('executable')} | "
            f"{fx.get('n_cases', 0)} | {fx.get('n_passed', 0)} | "
            f"{'ok' if not fx.get('assertion_errors') else fx['assertion_errors']} | "
            f"{'OK' if fx.get('ok') else 'FAIL'} |")
    lines.append("")
    fails = [(fx["profile_id"], c) for fx in fixtures for c in fx["cases"]
             if not c["ok"]]
    if fails:
        lines.append("## Failing cases")
        lines.append("")
        for pid, c in fails:
            lines.append(f"- **{pid}** / {c['name']}: {c['detail']}")
        lines.append("")
    lines.append("## Honesty sweep (executable profiles)")
    lines.append("")
    lines.append("Every executable profile refuses to fabricate attack / lethal / "
                 "ko_target / spread / boss / gust. "
                 f"All unsupported: **{honesty_ok}** "
                 f"({sum(1 for h in honesty if h['ok'])}/{len(honesty)} checks).")
    lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"gate: {'PASS' if all_ok else 'FAIL'}  cases {passed_cases}/{total_cases}  "
          f"honesty_ok={honesty_ok}  coverage_ok={coverage_ok}")
    if not all_ok:
        for pid, c in fails:
            print(f"  CASE FAIL [{pid}] {c['name']}: {c['detail']}")
        for e in profile_errors:
            print(f"  ASSERT FAIL {e}")
        if missing_cov:
            print(f"  MISSING COVERAGE {missing_cov}")
        if missing_tags:
            print(f"  MISSING TAGS {missing_tags}")
        for h in honesty:
            if not h["ok"]:
                print(f"  HONESTY FAIL [{h['profile_id']}] {h['kind']} not unsupported")
    print(f"wrote {os.path.relpath(OUT_JSON, ROOT)} and {os.path.relpath(OUT_MD, ROOT)}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
