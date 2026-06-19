#!/usr/bin/env python3
"""ActiveGraph Pass 18 — strategy-family + iteration lineage events.

Extends the generic ``scripts/ag_event.py`` helper with the strategy-lab event
vocabulary introduced in Pass 18. Every strategy family, every candidate
iteration, every fixture addition, every league run and every decision is
recorded as an immutable JSONL event in ``data/activegraph/lab_events.jsonl`` so
the lineage can be replayed later.

Two ways to use it:

  * Importable helpers (used by the Pass 18 experiment scripts)::

        from ag_strategy_event import emit, register_family, record_iteration
        emit("StrategyReportGenerated", payload={...}, tags=["pass18"])

  * CLI (manual entries / inspection)::

        python scripts/ag_strategy_event.py emit --type StrategyBlocked \
            --payload '{"family_id": "durant_deckout_carousel"}'
        python scripts/ag_strategy_event.py lineage --family raging_bolt_ogerpon

The helper never uploads anything and records ``upload_performed: false`` on the
report/decision events so downstream tooling can assert the no-upload invariant.
"""
from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event

# The strategy-lab event vocabulary recognized by this helper. Each maps to an
# EventType member added to the enum in Pass 18.
STRATEGY_EVENT_TYPES = (
    "StrategyFamilyRegistered",
    "StrategyIterationCreated",
    "StrategyIterationEvaluated",
    "StrategyHypothesisLogged",
    "StrategyFixtureAdded",
    "StrategyBlocked",
    "StrategyDecisionRecorded",
    "StrategyPromotionDecision",
    "InternalLeagueStarted",
    "InternalLeagueFinished",
    "StrategyReportGenerated",
    "ParentChildComparisonStarted",
    "ParentChildComparisonFinished",
)


def _store() -> EventStore:
    return EventStore(LAB_EVENTS_PATH)


def emit(event_type: str, *, payload: dict | None = None,
         tags: list[str] | None = None, match_id: str | None = None,
         parent_event_ids: list[str] | None = None, store: EventStore | None = None):
    """Append a strategy event and return the stored ``Event``.

    ``event_type`` must be a recognized strategy event type (raises otherwise so
    typos cannot silently create an unknown-type event).
    """
    if event_type not in STRATEGY_EVENT_TYPES:
        raise ValueError(
            f"unknown strategy event type {event_type!r}; "
            f"expected one of {STRATEGY_EVENT_TYPES}")
    et = getattr(EventType, event_type)
    base_tags = ["pass18", "strategy"]
    all_tags = base_tags + [t for t in (tags or []) if t not in base_tags]
    ev = new_event(
        et,
        payload=dict(payload or {}),
        tags=all_tags,
        match_id=match_id,
        parent_event_ids=list(parent_event_ids or []),
    )
    (store or _store()).append(ev)
    return ev


def register_family(family: dict, *, store: EventStore | None = None):
    """Emit ``StrategyFamilyRegistered`` for one family registry entry."""
    payload = {
        "family_id": family.get("family_id"),
        "status": family.get("status"),
        "deck_ids": family.get("deck_ids", []),
        "candidate_ids": family.get("candidate_ids", []),
        "current_best": family.get("current_best"),
        "hypothesis": family.get("hypothesis"),
        "next_experiment": family.get("next_experiment"),
        "upload_performed": False,
    }
    return emit("StrategyFamilyRegistered", payload=payload,
                tags=["family", str(family.get("family_id"))], store=store)


def record_iteration(*, family_id: str, candidate_id: str,
                     parent_candidate: str | None = None,
                     hypothesis: str = "", deck_diff=None, playbook_diff=None,
                     runtime_context_diff=None, validation_status: str = "pending",
                     league_result=None, decision: str = "pending",
                     parent_event_ids: list[str] | None = None,
                     store: EventStore | None = None):
    """Emit ``StrategyIterationCreated`` with the full lineage payload."""
    payload = {
        "family_id": family_id,
        "candidate_id": candidate_id,
        "parent_candidate": parent_candidate,
        "hypothesis": hypothesis,
        "deck_diff": deck_diff or {},
        "playbook_diff": playbook_diff or {},
        "runtime_context_diff": runtime_context_diff or {},
        "validation_status": validation_status,
        "league_result": league_result,
        "decision": decision,
        "upload_performed": False,
    }
    return emit("StrategyIterationCreated", payload=payload,
                tags=["iteration", family_id, candidate_id],
                parent_event_ids=parent_event_ids, store=store)


def lineage(family_id: str | None = None, store: EventStore | None = None) -> list:
    """Return strategy events (optionally filtered by ``family_id``)."""
    st = store or _store()
    events = st.load()
    out = []
    for e in events:
        if e.event_type not in STRATEGY_EVENT_TYPES:
            continue
        if family_id and (e.payload or {}).get("family_id") != family_id \
                and family_id not in (e.tags or []):
            continue
        out.append(e)
    return out


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--payload is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("--payload must be a JSON object")
    return data


def cmd_emit(args) -> int:
    ev = emit(args.type, payload=_parse_payload(args.payload),
              tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
              match_id=args.match_id)
    print(f"emitted {ev.event_type} ({ev.event_id}) -> {LAB_EVENTS_PATH}")
    return 0


def cmd_lineage(args) -> int:
    events = lineage(args.family)
    if args.limit:
        events = events[-args.limit:]
    for e in events:
        fam = (e.payload or {}).get("family_id", "-")
        cand = (e.payload or {}).get("candidate_id", "")
        extra = f" {cand}" if cand else ""
        print(f"{e.timestamp:>15.2f}  {e.event_type:<27} {fam}{extra}")
    print(f"\n{len(events)} strategy event(s) from {LAB_EVENTS_PATH}")
    return 0


def cmd_types(args) -> int:
    for t in STRATEGY_EVENT_TYPES:
        print(t)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("emit", help="append a strategy event")
    e.add_argument("--type", required=True, choices=STRATEGY_EVENT_TYPES)
    e.add_argument("--payload", help="JSON object payload")
    e.add_argument("--tags", help="comma-separated tags")
    e.add_argument("--match-id", help="optional match id")
    e.set_defaults(func=cmd_emit)

    ln = sub.add_parser("lineage", help="list strategy events")
    ln.add_argument("--family", help="filter by family_id")
    ln.add_argument("--limit", type=int, default=0)
    ln.set_defaults(func=cmd_lineage)

    ty = sub.add_parser("types", help="print supported strategy event types")
    ty.set_defaults(func=cmd_types)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
