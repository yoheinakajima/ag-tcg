#!/usr/bin/env python3
"""Pass 42 — emit the mutation-operator catalog artifact.

Describes the deterministic candidate-generation operators, the applicability
matrix over the CURRENT eligible internal source pool, and a preview of the
deterministic admission plan. LOCAL-only; writes nothing to Kaggle and mutates
no candidate. Read-only over the pool.

Outputs:
    data/experiments/pass42_mutation_operator_catalog.json
    data/experiments/pass42_mutation_operator_catalog.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.cards.card_db import load_card_db  # noqa: E402
from ptcg_activegraph.tournament import generation as G  # noqa: E402
from ptcg_activegraph.tournament.pool import CandidatePool  # noqa: E402

EXP = REPO / "data" / "experiments"


def _md(payload: dict) -> str:
    lines = ["# Pass 42 — Mutation Operator Catalog (candgen v0)", ""]
    lines.append(f"- catalog_version: `{payload['catalog_version']}`")
    lines.append(f"- deterministic seed: `{payload['seed']}`")
    lines.append(f"- operator rotation: `{payload['rotation']}` "
                 f"-> order {payload['operator_order']}")
    lines.append(f"- budgets: `{payload['budgets']}`")
    lines.append(f"- eligible families ({len(payload['eligible_families'])}): "
                 f"{', '.join(payload['eligible_families'])}")
    lines.append(f"- eligible source candidates "
                 f"({len(payload['eligible_source_ids'])}): "
                 f"{', '.join(payload['eligible_source_ids'])}")
    lines.append("")
    lines.append("> LOCAL-only, deterministic, probation-only factory. No Kaggle "
                 "upload/submit, no promotion, no root mutation, no public-ref "
                 "involvement. Admission means *eligible to be evaluated*, NOT "
                 "*good*.")
    lines.append("")
    lines.append("## Operators")
    lines.append("")
    lines.append("| operator | admits? | deck-changing? | summary |")
    lines.append("| --- | --- | --- | --- |")
    for op in payload["operators"]:
        lines.append(f"| `{op['name']}` | {'yes' if op['admits'] else 'no'} | "
                     f"{'yes' if op['deck_changing'] else 'no'} | {op['summary']} |")
    lines.append("")
    for op in payload["operators"]:
        lines.append(f"### `{op['name']}`")
        lines.append(f"- {op['summary']}")
        lines.append(f"- **Applicability:** {op['applicability']}")
        lines.append(f"- **Determinism:** {op['determinism']}")
        if op.get("non_admitted_reason"):
            lines.append(f"- **Not admitted in v0:** {op['non_admitted_reason']}")
        lines.append("")
    lines.append("## Applicability matrix (best source per eligible family)")
    lines.append("")
    lines.append("| family | applicable deck operators |")
    lines.append("| --- | --- |")
    for fam in payload["eligible_families"]:
        ops = payload["applicable_operators"].get(fam, [])
        lines.append(f"| {fam} | {', '.join(ops) if ops else '(none)'} |")
    lines.append("")
    lines.append("## Deterministic admission plan preview")
    lines.append("")
    if payload["planned_admissions"]:
        lines.append("| generated id | family | source | operator | deck delta |")
        lines.append("| --- | --- | --- | --- | --- |")
        for p in payload["planned_admissions"]:
            lines.append(f"| `{p['generated_candidate_id']}` | {p['family_id']} | "
                         f"`{p['source_candidate_id']}` | {p['operator']} | "
                         f"{p['deck_delta']} |")
    else:
        lines.append("_No admissions planned this run "
                     "(generation_infrastructure_ready_no_admissions)._")
    lines.append("")
    llm = payload["llm_proposals"]
    lines.append("## LLM proposal stub")
    lines.append(f"- enabled: {llm['enabled']} | materialized: {llm['materialized']}")
    lines.append(f"- {llm['note']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    card_db = load_card_db()
    pool = CandidatePool.load()
    payload = G.operator_catalog_payload(pool, card_db)

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass42_mutation_operator_catalog.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8")
    (EXP / "pass42_mutation_operator_catalog.md").write_text(
        _md(payload), encoding="utf-8")

    print("wrote pass42_mutation_operator_catalog.{json,md}")
    print(f"  seed={payload['seed'][:16]} families={len(payload['eligible_families'])} "
          f"planned={len(payload['planned_admissions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
