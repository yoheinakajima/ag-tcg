#!/usr/bin/env python3
"""Pass 40 (Part D) — provenance / attribution audit.

Consumes the Part C fetch record and, for every materialized public agent, writes
committed provenance next to the agent code:
  * materialized/<id>/source.json   — machine-readable provenance,
  * materialized/<id>/ATTRIBUTION.md — human-readable attribution,
then audits that every required provenance field is present and honest (public
kernel, content hashes recorded, benchmark-only usage declared).

NO Kaggle I/O here (reads the Part C JSON). NO upload/submit/push/mutation.
Outputs data/experiments/pass40_reference_attribution_audit.{json,md}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"
REF = REPO / "data" / "reference_agents"

from ptcg_activegraph.reference_agents import (  # noqa: E402
    EXTERNAL_REFERENCE_STATUS, REFERENCE_AGENTS, by_id,
)

LICENSE_NOTE = (
    "Public Kaggle kernel (is_private=false). Used here strictly as a benchmark "
    "opponent with attribution to the original author; not redistributed as our own "
    "work. The cg SDK / libcg.so / official card data are kept gitignored. See the "
    "kernel page for the author's stated license/terms.")

USAGE = "benchmark_opponent_only"
GUARDRAILS = [
    "never uploaded or submitted to Kaggle",
    "never entered in the submission queue / promoted / family-champion",
    "never mutated; not part of any mutation lineage",
    "never counted toward the active-candidate cap or 'our best' rankings",
    "excluded from the lifecycle manager",
]
REQUIRED_FIELDS = ["agent_id", "kaggle_ref", "author", "title", "source_kind",
                   "is_public", "kaggle_url", "tarball_sha256", "main_py_sha256",
                   "deck_csv_sha256", "cg_signature", "usage"]


def main() -> int:
    fetch = json.loads(
        (EXP / "pass40_reference_agent_fetch.json").read_text(encoding="utf-8"))
    frecs = {r["agent_id"]: r for r in fetch["agents"]}

    audits = []
    for spec in REFERENCE_AGENTS:
        fr = frecs.get(spec.agent_id, {})
        if not fr.get("ok"):
            audits.append({"agent_id": spec.agent_id, "materialized": False,
                           "complete": False, "missing": ["materialization"]})
            continue
        km = fr.get("kernel_metadata", {}) or {}
        mat = fr.get("materialized", {})
        source = {
            "agent_id": spec.agent_id, "label": spec.label,
            "kaggle_ref": spec.kaggle_ref, "owner": spec.owner, "slug": spec.slug,
            "author": spec.author, "author_display": spec.author_display,
            "source_kind": spec.source_kind, "deck_archetype": spec.deck_archetype,
            "title": km.get("title") or spec.title, "optional": spec.optional,
            "pool_status": EXTERNAL_REFERENCE_STATUS, "tags": list(spec.tags),
            "is_public": (km.get("is_private") is False) or (not km),
            "kaggle_url": f"https://www.kaggle.com/code/{spec.kaggle_ref}",
            "competition_sources": km.get("competition_sources", []),
            "dataset_sources": km.get("dataset_sources", []),
            "kernel_type": km.get("kernel_type"),
            "tarball_sha256": fr.get("tarball_sha256"),
            "tarball_bytes": fr.get("tarball_bytes"),
            "main_py_sha256": mat.get("main_py_sha256"),
            "deck_csv_sha256": mat.get("deck_csv_sha256"),
            "cg_signature": fr.get("cg_signature"),
            "usage": USAGE, "guardrails": GUARDRAILS, "license_note": LICENSE_NOTE,
        }
        mat_dir = REF / "materialized" / spec.agent_id
        mat_dir.mkdir(parents=True, exist_ok=True)
        (mat_dir / "source.json").write_text(
            json.dumps(source, indent=2), encoding="utf-8")

        att = [
            f"# Attribution — {source['title']}", "",
            f"- **Original author:** {spec.author_display} (`{spec.author}`) on Kaggle",
            f"- **Source kernel:** [{spec.kaggle_ref}]({source['kaggle_url']})",
            f"- **Source kind:** {spec.source_kind}",
            f"- **Deck archetype:** {spec.deck_archetype}",
            f"- **Competition:** {', '.join(source['competition_sources']) or 'n/a'}",
            f"- **Optional:** {'yes' if spec.optional else 'no'}", "",
            "## What this is", "",
            "A public Kaggle rule-based agent for the Pokémon-TCG AI Battle "
            "competition, materialized from the kernel's published `submission.tar.gz` "
            "output (the canonical cg_typed layout: `main.py` + `deck.csv` + the `cg` "
            "SDK).", "",
            "## How we use it", "",
            f"Registered in our tournament with pool status "
            f"**`{EXTERNAL_REFERENCE_STATUS}`** as a **benchmark opponent only**. It "
            "is:",
            *[f"- {g}" for g in GUARDRAILS],
            "", "Internal win-rates against it are LOCAL diagnostics, not Kaggle "
            "leaderboard scores.", "",
            "## Provenance (sha256)", "",
            f"- submission.tar.gz: `{source['tarball_sha256']}` "
            f"({source['tarball_bytes']} bytes)",
            f"- main.py: `{source['main_py_sha256']}`",
            f"- deck.csv: `{source['deck_csv_sha256']}`",
            f"- cg SDK signature: `{source['cg_signature']}`", "",
            "## License", "", LICENSE_NOTE, "",
        ]
        (mat_dir / "ATTRIBUTION.md").write_text("\n".join(att) + "\n", encoding="utf-8")

        missing = [f for f in REQUIRED_FIELDS if not source.get(f)]
        audits.append({
            "agent_id": spec.agent_id, "materialized": True,
            "is_public": source["is_public"],
            "source_json": str((mat_dir / "source.json").relative_to(REPO)),
            "attribution_md": str((mat_dir / "ATTRIBUTION.md").relative_to(REPO)),
            "missing": missing, "complete": not missing,
        })

    n_complete = sum(1 for a in audits if a.get("complete"))
    n_mat = sum(1 for a in audits if a.get("materialized"))
    all_attributed = n_complete == n_mat and n_mat > 0

    payload = {
        "pass": "40", "part": "D", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "materialized_count": n_mat, "fully_attributed_count": n_complete,
        "all_materialized_fully_attributed": all_attributed,
        "required_fields": REQUIRED_FIELDS, "usage": USAGE, "license_note": LICENSE_NOTE,
        "audits": audits,
    }
    (EXP / "pass40_reference_attribution_audit.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    def yn(v):
        return "yes" if v is True else ("no" if v is False else "n/a")

    md = [
        "# Pass 40 — Reference-agent provenance / attribution audit (Part D)", "",
        "> Every materialized public agent carries committed `source.json` + "
        "`ATTRIBUTION.md`. Benchmark opponents only; never uploaded/promoted/mutated.",
        "",
        f"- materialized: **{n_mat}**, fully attributed: **{n_complete}**",
        f"- all materialized fully attributed: **{yn(all_attributed)}**", "",
        "| agent_id | materialized | public | attribution complete | missing |",
        "|---|---|---|---|---|",
    ]
    for a in audits:
        md.append(f"| `{a['agent_id']}` | {yn(a.get('materialized'))} | "
                  f"{yn(a.get('is_public'))} | {yn(a.get('complete'))} | "
                  f"{a.get('missing') or 'none'} |")
    (EXP / "pass40_reference_attribution_audit.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"attribution: materialized={n_mat} complete={n_complete} "
          f"all_attributed={all_attributed}")
    return 0 if all_attributed else 1


if __name__ == "__main__":
    raise SystemExit(main())
