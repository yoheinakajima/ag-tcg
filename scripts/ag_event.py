#!/usr/bin/env python3
"""Append, list, and summarize ActiveGraph lab events.

The lab records every step as an immutable JSONL event in
``data/activegraph/lab_events.jsonl``. This CLI is the manual entry point for
that log (the experiment scripts emit events directly).

Usage:
    python scripts/ag_event.py summary
    python scripts/ag_event.py list --type CandidateRanked --limit 20
    python scripts/ag_event.py append --type IdeaGenerated \
        --payload '{"idea": "trim energy"}' --tags experiment,manual
    python scripts/ag_event.py register-baseline --name v1_kaggle_349_8 --score 349.8
    python scripts/ag_event.py kaggle-score --name policy_attack_heavy --score 351.2
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def _store() -> EventStore:
    return EventStore(LAB_EVENTS_PATH)


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


def _tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def cmd_append(args) -> int:
    store = _store()
    ev = new_event(
        args.type,
        payload=_parse_payload(args.payload),
        tags=_tags(args.tags),
        match_id=args.match_id,
    )
    store.append(ev)
    print(f"appended {ev.event_type} ({ev.event_id}) -> {store.path}")
    return 0


def cmd_register_baseline(args) -> int:
    store = _store()
    ev = new_event(
        EventType.BaselineRegistered,
        payload={"name": args.name, "kaggle_score": args.score, "note": args.note},
        tags=["baseline", "control"],
    )
    store.append(ev)
    print(f"registered baseline {args.name} (score={args.score})")
    return 0


def cmd_kaggle_score(args) -> int:
    store = _store()
    ev = new_event(
        EventType.KaggleScoreUpdated,
        payload={"name": args.name, "kaggle_score": args.score,
                 "submission_id": args.submission_id},
        tags=["kaggle", "score"],
    )
    store.append(ev)
    print(f"recorded Kaggle score {args.score} for {args.name}")
    return 0


def cmd_list(args) -> int:
    store = _store()
    events = store.query(event_type=args.type) if args.type else store.load()
    if args.match_id:
        events = [e for e in events if e.match_id == args.match_id]
    if args.limit:
        events = events[-args.limit:]
    for e in events:
        ts = e.timestamp
        print(f"{ts:>15.2f}  {e.event_type:<26}  {json.dumps(e.payload, default=str)[:120]}")
    print(f"\n{len(events)} event(s) from {store.path}")
    return 0


def cmd_summary(args) -> int:
    store = _store()
    events = store.load()
    counts = Counter(e.event_type for e in events)
    print(f"ActiveGraph lab event summary ({store.path})")
    print(f"  total events: {len(events)}")
    if not events:
        print("  (no events yet)")
        return 0
    print("  by type:")
    for et, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"    {et:<28} {n}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("append", help="append a generic event")
    a.add_argument("--type", required=True, help="event type name")
    a.add_argument("--payload", help="JSON object payload")
    a.add_argument("--tags", help="comma-separated tags")
    a.add_argument("--match-id", help="optional match id")
    a.set_defaults(func=cmd_append)

    rb = sub.add_parser("register-baseline", help="emit BaselineRegistered")
    rb.add_argument("--name", default="v1_kaggle_349_8")
    rb.add_argument("--score", type=float, default=349.8)
    rb.add_argument("--note", default="")
    rb.set_defaults(func=cmd_register_baseline)

    ks = sub.add_parser("kaggle-score", help="emit KaggleScoreUpdated")
    ks.add_argument("--name", required=True)
    ks.add_argument("--score", type=float, required=True)
    ks.add_argument("--submission-id", default="")
    ks.set_defaults(func=cmd_kaggle_score)

    ls = sub.add_parser("list", help="list events")
    ls.add_argument("--type", help="filter by event type")
    ls.add_argument("--match-id", help="filter by match id")
    ls.add_argument("--limit", type=int, default=50)
    ls.set_defaults(func=cmd_list)

    sm = sub.add_parser("summary", help="counts by event type")
    sm.set_defaults(func=cmd_summary)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
