#!/usr/bin/env python3
"""Pass 18 (Part B) — build the strategy-family registry + emit lineage events.

Loads ``experiments/strategy_families.yaml`` (source of truth), validates that
every family carries the required fields, renders the registry to
``data/experiments/pass18_strategy_family_registry.{json,md}`` and emits one
``StrategyFamilyRegistered`` event (plus a ``StrategyHypothesisLogged`` event)
per family to the ActiveGraph lab log.

LOCAL ONLY. No upload. Idempotent rendering; re-running re-emits events (the log
is append-only by design).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml  # type: ignore

from ag_strategy_event import emit, register_family  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FAMILIES_YAML = REPO / "experiments" / "strategy_families.yaml"
OUT_JSON = REPO / "data" / "experiments" / "pass18_strategy_family_registry.json"
OUT_MD = REPO / "data" / "experiments" / "pass18_strategy_family_registry.md"

REQUIRED_FIELDS = (
    "family_id", "deck_ids", "candidate_ids", "playbook_paths", "fixture_paths",
    "current_best", "status", "hypothesis", "latest_results", "blockers",
    "next_experiment",
)
VALID_STATUS = {
    "active_reference", "promising_research", "rescue_candidate",
    "chaos_research_blocked", "backlog",
}


def load_families() -> dict:
    data = yaml.safe_load(FAMILIES_YAML.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("families"):
        raise SystemExit("strategy_families.yaml: missing 'families' list")
    return data


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    seen = set()
    for i, fam in enumerate(data.get("families") or []):
        fid = fam.get("family_id", f"<index {i}>")
        for field in REQUIRED_FIELDS:
            if field not in fam:
                errors.append(f"{fid}: missing required field '{field}'")
        if fam.get("status") not in VALID_STATUS:
            errors.append(f"{fid}: invalid status {fam.get('status')!r}")
        if not str(fam.get("hypothesis", "")).strip():
            errors.append(f"{fid}: empty hypothesis")
        if not str(fam.get("next_experiment", "")).strip():
            errors.append(f"{fid}: empty next_experiment")
        if fid in seen:
            errors.append(f"{fid}: duplicate family_id")
        seen.add(fid)
    return errors


def render_md(data: dict) -> str:
    lines = [
        "# ActiveGraph Pass 18 — Strategy Family Registry",
        "",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        f"- source: `experiments/strategy_families.yaml`",
        f"- families: {len(data.get('families') or [])}",
        "- **upload_performed: false** (local only — no Kaggle, no GitHub)",
        "",
        "| family_id | status | current_best | candidates | next experiment |",
        "|---|---|---|---|---|",
    ]
    for fam in data.get("families") or []:
        cands = ", ".join(fam.get("candidate_ids") or []) or "—"
        nxt = " ".join(str(fam.get("next_experiment", "")).split())
        lines.append(
            f"| {fam['family_id']} | {fam['status']} | "
            f"{fam.get('current_best') or '—'} | {cands} | {nxt} |")
    lines.append("")
    for fam in data.get("families") or []:
        lines.append(f"## {fam['family_id']} — {fam['status']}")
        lines.append("")
        lines.append(f"- **hypothesis:** {' '.join(str(fam['hypothesis']).split())}")
        lines.append(f"- **current_best:** {fam.get('current_best') or '—'}")
        lines.append(f"- **deck_ids:** {', '.join(fam.get('deck_ids') or []) or '—'}")
        lines.append(f"- **candidate_ids:** {', '.join(fam.get('candidate_ids') or []) or '—'}")
        lines.append(f"- **playbook_paths:** {', '.join(fam.get('playbook_paths') or []) or '—'}")
        lines.append(f"- **fixture_paths:** {', '.join(fam.get('fixture_paths') or []) or '—'}")
        lr = fam.get("latest_results") or {}
        if isinstance(lr, dict) and lr:
            lines.append("- **latest_results:**")
            for k, v in lr.items():
                lines.append(f"  - {k}: {v}")
        blockers = fam.get("blockers") or []
        if blockers:
            lines.append("- **blockers:**")
            for b in blockers:
                lines.append(f"  - {b}")
        lines.append(f"- **next_experiment:** {' '.join(str(fam['next_experiment']).split())}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-events", action="store_true",
                    help="render registry without emitting ActiveGraph events")
    args = ap.parse_args()

    data = load_families()
    errors = validate(data)
    if errors:
        for e in errors:
            print(f"INVALID: {e}")
        return 1

    families = data.get("families") or []
    emitted = []
    if not args.no_events:
        for fam in families:
            fev = register_family(fam)
            hev = emit("StrategyHypothesisLogged",
                       payload={"family_id": fam["family_id"],
                                "hypothesis": " ".join(str(fam["hypothesis"]).split()),
                                "status": fam["status"]},
                       tags=["family", fam["family_id"]],
                       parent_event_ids=[fev.event_id])
            emitted.append({"family_id": fam["family_id"],
                            "registered_event": fev.event_id,
                            "hypothesis_event": hev.event_id})

    registry = {
        "pass": "18",
        "part": "B",
        "schema": data.get("schema"),
        "upload_performed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "family_count": len(families),
        "families": families,
        "events_emitted": emitted,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(data), encoding="utf-8")

    print(f"validated {len(families)} families")
    print(f"emitted {len(emitted)} family event pair(s)"
          if not args.no_events else "events skipped (--no-events)")
    print(f"wrote {OUT_JSON.relative_to(REPO)}")
    print(f"wrote {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
