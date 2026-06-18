#!/usr/bin/env python3
"""CLI for the ActiveGraph run ledger (Pass 7A).

Thin wrapper over ``ptcg_activegraph.ag.ActiveGraphLedger``. Run from repo root so
the default store paths (``data/activegraph/...``) resolve correctly.

Examples::

    python scripts/ag_ledger.py create-run --run-id test --metadata '{"purpose":"smoke"}'
    python scripts/ag_ledger.py append --run-id test --type GamePlanned --payload '{"game_id":"g1"}'
    python scripts/ag_ledger.py heartbeat --run-id test --object-id g1
    python scripts/ag_ledger.py inspect --run-id test
    python scripts/ag_ledger.py export --run-id test --out data/activegraph/test_trace.jsonl
    python scripts/ag_ledger.py list-runs
"""

from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401  (adds src/ to sys.path)

from ptcg_activegraph.ag import ActiveGraphLedger


def _parse_json(label: str, raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--{label} is not valid JSON: {exc}")
    if not isinstance(val, dict):
        raise SystemExit(f"--{label} must be a JSON object")
    return val


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ActiveGraph run ledger CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-run", help="create a new run")
    p_create.add_argument("--run-id", required=True)
    p_create.add_argument("--metadata", default=None, help="JSON object")

    p_append = sub.add_parser("append", help="append an event")
    p_append.add_argument("--run-id", required=True)
    p_append.add_argument("--type", required=True, dest="event_type")
    p_append.add_argument("--payload", default=None, help="JSON object")
    p_append.add_argument("--tags", default=None, help="comma-separated tags")

    p_hb = sub.add_parser("heartbeat", help="append a heartbeat")
    p_hb.add_argument("--run-id", required=True)
    p_hb.add_argument("--object-id", default=None)
    p_hb.add_argument("--payload", default=None, help="JSON object")

    p_inspect = sub.add_parser("inspect", help="print run summary")
    p_inspect.add_argument("--run-id", required=True)

    p_export = sub.add_parser("export", help="export run trace as JSONL")
    p_export.add_argument("--run-id", required=True)
    p_export.add_argument("--out", required=True)

    sub.add_parser("list-runs", help="list all runs")

    args = parser.parse_args(argv)
    ledger = ActiveGraphLedger()

    if args.command == "create-run":
        ledger.create_run(args.run_id, _parse_json("metadata", args.metadata))
        print(json.dumps({"created": args.run_id, "backend": ledger.backend_name}))
    elif args.command == "append":
        tags = [t for t in (args.tags or "").split(",") if t]
        eid = ledger.append_event(
            args.run_id, args.event_type, _parse_json("payload", args.payload), tags=tags
        )
        print(json.dumps({"event_id": eid}))
    elif args.command == "heartbeat":
        ledger.heartbeat(
            args.run_id, object_id=args.object_id, payload=_parse_json("payload", args.payload)
        )
        print(json.dumps({"heartbeat": args.run_id, "object_id": args.object_id}))
    elif args.command == "inspect":
        print(json.dumps(ledger.inspect_run(args.run_id), indent=2, default=str))
    elif args.command == "export":
        out = ledger.export_trace(args.run_id, args.out)
        print(json.dumps({"exported": str(out)}))
    elif args.command == "list-runs":
        print(json.dumps(ledger.list_runs(), indent=2, default=str))
    else:  # pragma: no cover - argparse enforces
        parser.error("unknown command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
