#!/usr/bin/env python3
"""Pass 40 (Part B) — public reference-agent source / intake manifest.

Declarative, pre-fetch intake plan: which public Kaggle agents we will materialize
as **benchmark opponents only**, where they come from, who authored them, what role
they are allowed to play, and exactly which guardrails bound their use. Writes no
agent code; performs no Kaggle I/O (importing the registry is pure metadata).

Outputs data/experiments/pass40_reference_source_manifest.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
EXP = REPO / "data" / "experiments"

from ptcg_activegraph.reference_agents import (  # noqa: E402
    COMPETITIONS, EXTERNAL_REFERENCE_STATUS, OPTIONAL_AGENTS, REFERENCE_AGENTS,
    REQUIRED_AGENTS,
)

REF_ROOT = "data/reference_agents"

LAYOUT = {
    "committed": {
        f"{REF_ROOT}/materialized/<agent_id>/main.py": "public sample agent code (attribution)",
        f"{REF_ROOT}/materialized/<agent_id>/deck.csv": "60-int deck list (public sample)",
        f"{REF_ROOT}/materialized/<agent_id>/ATTRIBUTION.md": "human-readable provenance",
        f"{REF_ROOT}/materialized/<agent_id>/source.json": "machine provenance",
        f"{REF_ROOT}/reference_source_manifest.json": "this intake plan",
        f"{REF_ROOT}/reference_agent_manifest.json": "post-fetch materialized manifest",
    },
    "gitignored": {
        f"{REF_ROOT}/_sdk/cg/": "shared cg SDK (Python modules + libcg.so) — runtime",
        f"{REF_ROOT}/raw_outputs/<agent_id>/": "raw `kaggle kernels output` artifacts",
        f"{REF_ROOT}/notebooks/<agent_id>/": "source .ipynb + kernel-metadata.json",
        f"{REF_ROOT}/tarballs/<agent_id>.tar.gz": "immutable benchmark tarball (incl. cg/)",
    },
}

GUARDRAILS = [
    "benchmark opponents ONLY — never our candidates",
    "NEVER uploaded or submitted to Kaggle (no_upload=true on every event)",
    "NEVER entered into the submission queue",
    "NEVER promoted, never family-champion, never portfolio-anchor",
    "NEVER mutated and never part of any mutation lineage",
    "NEVER counted toward the active-candidate cap",
    "NEVER ranked among 'our best' candidates",
    "excluded from the lifecycle manager (no protection/demotion/quarantine)",
    "internal benchmark win-rates are LOCAL diagnostics, NOT Kaggle scores",
    "cg SDK / libcg.so / official card CSV / PDFs / images stay gitignored",
]


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    agents = [
        {
            "agent_id": a.agent_id, "label": a.label, "kaggle_ref": a.kaggle_ref,
            "owner": a.owner, "slug": a.slug, "author": a.author,
            "author_display": a.author_display, "source_kind": a.source_kind,
            "deck_archetype": a.deck_archetype, "title": a.title,
            "optional": a.optional, "tags": list(a.tags),
            "pool_status": EXTERNAL_REFERENCE_STATUS,
            "materialize_via": f"kaggle kernels output {a.kaggle_ref}"
                               " -> extract submission.tar.gz",
        }
        for a in REFERENCE_AGENTS
    ]
    payload = {
        "pass": "40", "part": "B", "local_only": True, "no_upload": True,
        "upload_performed": False, "auto_submit": False, "github_push": False,
        "candidate_generation": False,
        "pool_status_lane": EXTERNAL_REFERENCE_STATUS,
        "competitions": COMPETITIONS,
        "required_count": len(REQUIRED_AGENTS),
        "optional_count": len(OPTIONAL_AGENTS),
        "agents": agents,
        "local_layout": LAYOUT,
        "guardrails": GUARDRAILS,
        "materialization_strategy": (
            "Each kiyotah kernel's `kaggle kernels output` ships submission.tar.gz "
            "= {main.py, deck.csv, cg/{__init__,api,game,sim,utils}.py, cg/libcg.so} "
            "— the canonical cg_typed layout. Materialize by extracting that tarball; "
            "no notebook-cell parsing required. The cg/ SDK is shared and stored once "
            "under _sdk/cg (gitignored runtime)."),
        "competition_bulk_download": (
            "SKIPPED unless a concrete need arises (e.g. local smoke requires "
            "EN_Card_Data.csv). cg/ + libcg.so come bundled in the kernel outputs; "
            "avoiding the bulk download keeps official PDFs/images out of the repo."),
    }
    (EXP / "pass40_reference_source_manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    md = [
        "# Pass 40 — Public reference-agent source / intake manifest (Part B)", "",
        "> Pre-fetch intake plan. These are **benchmark opponents only** — never our "
        "candidates. NO upload, NO submit, NO promote, NO mutate, NO queue, NO active-"
        "cap. Internal win-rates are LOCAL diagnostics, NOT Kaggle scores.", "",
        "## Competition context (read-only)",
        f"- primary: `{COMPETITIONS['primary']}` (entered)",
        f"- strategy challenge: `{COMPETITIONS['strategy_challenge']}`", "",
        f"## Reference agents ({len(REQUIRED_AGENTS)} required + "
        f"{len(OPTIONAL_AGENTS)} optional)", "",
        "| agent_id | label | source | archetype | kaggle_ref | optional |",
        "|---|---|---|---|---|---|",
    ]
    for a in REFERENCE_AGENTS:
        md.append(f"| `{a.agent_id}` | `{a.label}` | {a.source_kind} | "
                  f"{a.deck_archetype} | `{a.kaggle_ref}` | "
                  f"{'yes' if a.optional else 'no'} |")
    md += [
        "", f"All registered with pool status **`{EXTERNAL_REFERENCE_STATUS}`** "
        "(schedulable as opponent; excluded from cap/rankings/lifecycle/queue/"
        "promotion/mutation).", "",
        "## Local layout", "", "**Committed (provenance + code for inspection):**",
    ]
    for p, d in LAYOUT["committed"].items():
        md.append(f"- `{p}` — {d}")
    md += ["", "**Gitignored (reproducible runtime / SDK):**"]
    for p, d in LAYOUT["gitignored"].items():
        md.append(f"- `{p}` — {d}")
    md += ["", "## Guardrails"]
    md += [f"- {g}" for g in GUARDRAILS]
    md += ["", "## Materialization strategy", "", payload["materialization_strategy"],
           "", "## Competition bulk download", "", payload["competition_bulk_download"], ""]
    (EXP / "pass40_reference_source_manifest.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"source manifest: {len(REQUIRED_AGENTS)} required + "
          f"{len(OPTIONAL_AGENTS)} optional agents; status={EXTERNAL_REFERENCE_STATUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
