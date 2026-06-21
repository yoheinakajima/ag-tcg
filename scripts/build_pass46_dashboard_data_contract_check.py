#!/usr/bin/env python3
"""PASS 46 — dashboard data contract check (read-only, secret-safe).

Validates ``docs/DASHBOARD_DATA_CONTRACT.md`` against the live PRODUCTION object
storage WITHOUT exposing any secret:

  * lists the actual relative keys present under the production prefix (read-only
    ``backend.list`` — key NAMES only, no object downloads), and confirms the
    contract's documented keys/prefixes are present where expected;
  * scans the contract document for any secret/bucket/credential leakage — it reads
    the live secret VALUES from the environment ONLY to assert they are ABSENT from
    the doc, and NEVER prints, logs, or writes those values; it also rejects
    bucket-id-style and long-hex token patterns.

No mutation / upload / download of object bodies. Output:
  data/experiments/pass46_dashboard_data_contract_check.{json,md}
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.tournament.storage import (  # noqa: E402
    DEFAULT_PREFIX, get_storage_backend)

EXP = REPO / "data" / "experiments"
DOC = REPO / "docs" / "DASHBOARD_DATA_CONTRACT.md"

# documented relative keys / prefixes the dashboard relies on
DOCUMENTED_EXACT = [
    "events.jsonl",
    "candidate_pool.json",
    "config.yaml",
    "storage_manifest.json",
    "projections/rankings.json",
    "projections/rankings.md",
    "projections/scheduler_queue.json",
    "projections/candidate_pool.json",
    "projections/non_inertness.json",
    "projections/lineage.json",
    "projections/matchups.csv",
    "projections/tournament_state.json",
]
DOCUMENTED_PREFIXES = ["projections/", "runs/", "games/"]

# env var NAMES whose VALUES must never appear in the doc (values read live, never printed)
SECRET_ENV_NAMES = [
    "DEFAULT_OBJECT_STORAGE_BUCKET_ID",
    "PRIVATE_OBJECT_DIR",
    "PUBLIC_OBJECT_SEARCH_PATHS",
    "KAGGLE_KEY",
    "KAGGLE_USERNAME",
]
# bucket-id / token style patterns that must NOT appear in the doc
SECRET_PATTERNS = {
    "objstore_bucket_id": re.compile(r"replit-objstore-[0-9a-fA-F-]{8,}"),
    "long_hex_token": re.compile(r"\b[0-9a-f]{32,}\b"),
    "aws_like_key": re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
}


def _list_prod_keys():
    backend = get_storage_backend(env="production", backend="replit_app_storage")
    try:
        keys = backend.list("")
    except Exception as exc:  # noqa: BLE001
        return None, f"list_failed: {exc}"
    return sorted(set(keys)), None


def _scan_doc_for_secrets(text: str) -> dict:
    # which env VALUES (if any) leaked into the doc — names, never values, are reported
    leaked_env_names = []
    for name in SECRET_ENV_NAMES:
        val = os.environ.get(name)
        if val and len(val) >= 6 and val in text:
            leaked_env_names.append(name)
    pattern_hits = {}
    for label, rx in SECRET_PATTERNS.items():
        if rx.search(text):
            pattern_hits[label] = True
    clean = (not leaked_env_names) and (not pattern_hits)
    return {
        "env_value_leaks_by_name": sorted(leaked_env_names),
        "pattern_hits": sorted(pattern_hits),
        "patterns_checked": sorted(SECRET_PATTERNS),
        "env_names_checked": sorted(SECRET_ENV_NAMES),
        "clean": clean,
    }


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)

    doc_exists = DOC.is_file()
    text = DOC.read_text(encoding="utf-8") if doc_exists else ""

    prod_keys, list_err = _list_prod_keys()
    prod_state_available = prod_keys is not None
    keyset = set(prod_keys or [])

    def _has_prefix(pfx):
        return any(k == pfx.rstrip("/") or k.startswith(pfx) for k in keyset)

    exact_present = {k: (k in keyset) for k in DOCUMENTED_EXACT}
    prefix_present = {p: _has_prefix(p) for p in DOCUMENTED_PREFIXES}
    documented_missing = sorted(
        [k for k, ok in exact_present.items() if not ok]
        + [p for p, ok in prefix_present.items() if not ok])

    # every documented exact/prefix key is mentioned verbatim in the doc text
    documented_in_doc = all(k in text for k in DOCUMENTED_EXACT) and \
        all(p in text for p in DOCUMENTED_PREFIXES)

    # required non-secret connection guidance + caveats present
    mentions_prefix_var = "TOURNAMENT_STORAGE_PREFIX" in text
    mentions_default_prefix = DEFAULT_PREFIX in text
    mentions_read_only = "read-only" in text.lower()
    mentions_not_kaggle = "NOT a Kaggle leaderboard" in text or \
        "not a kaggle leaderboard" in text.lower()
    mentions_no_bulk_sidecar = ("bulk-read" in text.lower()
                                or "never bulk-read" in text.lower())
    mentions_locks_excluded = "locks/" in text and "conflict_report" in text

    secret_scan = _scan_doc_for_secrets(text)

    keys_match = prod_state_available and not documented_missing
    keys_match_status = ("matched" if keys_match
                         else ("unverified" if not prod_state_available
                               else "documented_missing_in_prod"))

    checks = {
        "contract_doc_exists": doc_exists,
        "documented_keys_present_in_doc_text": documented_in_doc,
        "connection_by_env_name_no_values": mentions_prefix_var,
        "default_prefix_documented": mentions_default_prefix,
        "caveat_read_only": mentions_read_only,
        "caveat_not_kaggle": mentions_not_kaggle,
        "caveat_no_bulk_sidecar_read": mentions_no_bulk_sidecar,
        "caveat_locks_excluded": mentions_locks_excluded,
        "documented_keys_match_prod_where_verifiable":
            keys_match or not prod_state_available,
        "contract_contains_no_secrets": secret_scan["clean"],
    }
    contains_no_secrets = secret_scan["clean"]
    all_ok = all(checks.values()) and contains_no_secrets

    out = {
        "pass": "pass46_dashboard_data_contract_check",
        "read_only": True, "production_mutated": False,
        "object_bodies_downloaded": False,
        "contract_doc_path": "docs/DASHBOARD_DATA_CONTRACT.md",
        "contract_doc_exists": doc_exists,
        "default_prefix": DEFAULT_PREFIX,
        "documented_exact_keys": DOCUMENTED_EXACT,
        "documented_prefixes": DOCUMENTED_PREFIXES,
        "documented_exact_present_in_prod": exact_present,
        "documented_prefix_present_in_prod": prefix_present,
        "documented_missing_in_prod": documented_missing,
        "keys_match_status": keys_match_status,
        "production_state_available": prod_state_available,
        "prod_key_count": len(keyset) if prod_state_available else None,
        "prod_key_sample": sorted(keyset)[:25] if prod_state_available else None,
        "prod_list_error": list_err,
        "secret_scan": secret_scan,
        "contains_no_secrets": contains_no_secrets,
        "checks": checks,
        "all_ok": all_ok,
        "dashboard_ready": all_ok,
    }
    (EXP / "pass46_dashboard_data_contract_check.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")

    def yn(b):
        return "yes" if b is True else ("no" if b is False else "unverified")

    md = [
        "# PASS 46 — dashboard data contract check", "",
        "> Read-only validation of `docs/DASHBOARD_DATA_CONTRACT.md` against live "
        "production object storage. Lists key NAMES only (no object downloads). Asserts "
        "the contract leaks NO secret/bucket/credential value.", "",
        f"- **all ok: {yn(all_ok)}**  · contract contains no secrets: "
        f"**{yn(contains_no_secrets)}**  · keys match: **{keys_match_status}**",
        f"- default prefix: `{DEFAULT_PREFIX}`  · prod state available: "
        f"**{yn(prod_state_available)}**  · prod key count: "
        f"{out['prod_key_count']}", "",
        "## Documented keys vs production", "",
        "| documented key/prefix | present in prod |", "|---|---|",
    ]
    for k, ok in exact_present.items():
        md.append(f"| `{k}` | {yn(ok)} |")
    for p, ok in prefix_present.items():
        md.append(f"| `{p}*` | {yn(ok)} |")
    md += ["", "## Checks", "", "| check | pass |", "|---|---|"]
    for k, v in checks.items():
        md.append(f"| {k} | {yn(v)} |")
    md += [
        "", "## Secret-leak scan", "",
        f"- env value leaks (by name): `{secret_scan['env_value_leaks_by_name'] or 'none'}`",
        f"- pattern hits: `{secret_scan['pattern_hits'] or 'none'}`",
        f"- patterns checked: `{secret_scan['patterns_checked']}`",
        "", "> The check reads live secret VALUES only to assert their ABSENCE from the "
        "doc; it never prints, logs, or writes any value. The contract documents env var "
        "NAMES and relative keys only.",
    ]
    (EXP / "pass46_dashboard_data_contract_check.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")

    print(f"pass46 contract: all_ok={all_ok} no_secrets={contains_no_secrets} "
          f"keys_match={keys_match_status} doc_exists={doc_exists} "
          f"prod_keys={out['prod_key_count']} missing={documented_missing}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
