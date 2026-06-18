#!/usr/bin/env python3
"""Ingest + analyze a Kaggle cabt episode replay.

Usage:
    python scripts/analyze_replay.py data/kaggle_replays/80374966.json

Behavior:
- If the replay file exists, parse it, write
  ``data/replays/<id>_analysis.json`` + ``.md`` and emit
  ReplayImported / ReplayAnalyzed / FailureRegimeTagged / IdeaGenerated.
- If the file is absent, emit ReplayImported with ``status=missing`` and report
  that the replay must be uploaded to the workspace. No analysis is fabricated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event
from ptcg_activegraph.replays import (
    ReplayNotFound,
    analyze,
    load_replay,
    to_markdown,
)

DEFAULT_REPLAY = "data/replays/80374966.json"
OUT_DIR = Path("data/replays")

# Replay-derived seam ideas emitted as IdeaGenerated when a replay is analyzed.
SEAM_IDEAS = [
    "policy.effect_resolution_targeting",
    "policy.ultra_ball_discard_and_search",
    "policy.secret_box_mode_selection",
    "policy.mega_signal_evolution_search",
    "policy.deckout_awareness",
    "policy.attach_targeting",
    "policy.setup_active_choice",
]


def _store() -> EventStore:
    return EventStore(LAB_EVENTS_PATH)


def _episode_label(path: Path) -> str:
    return path.stem or "unknown"


def run(replay_path: str) -> int:
    store = _store()
    path = Path(replay_path)

    try:
        replay = load_replay(path)
    except ReplayNotFound:
        store.append(new_event(
            EventType.ReplayImported,
            payload={
                "requested_path": str(path),
                "status": "missing",
                "note": ("replay file not present in workspace; upload it to "
                         f"{path} and re-run analyze_replay.py"),
            },
            tags=["pass5", "replay", "missing"],
        ))
        print(f"[replay] NOT FOUND: {path}")
        print("[replay] emitted ReplayImported(status=missing).")
        print("[replay] ACTION NEEDED: upload the Kaggle episode JSON to "
              f"{path} then re-run this script for full analysis.")
        # Scaffold-only: still write a placeholder analysis marker so the report
        # can state "needs upload" deterministically.
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        label = _episode_label(path)
        marker = OUT_DIR / f"{label}_analysis.json"
        marker.write_text(json.dumps({
            "status": "missing",
            "requested_path": str(path),
            "note": "replay not uploaded; analysis pending",
        }, indent=2), encoding="utf-8")
        print(f"[replay] wrote placeholder marker -> {marker}")
        return 0

    # Replay present: emit import, analyze, write outputs, emit downstream events.
    store.append(new_event(
        EventType.ReplayImported,
        payload={
            "path": str(path),
            "status": "present",
            "episode_id": replay.episode_id,
            "num_steps": replay.num_steps,
        },
        tags=["pass5", "replay"],
    ))

    analysis = analyze(replay)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    label = str(replay.episode_id or _episode_label(path))
    json_out = OUT_DIR / f"{label}_analysis.json"
    md_out = OUT_DIR / f"{label}_analysis.md"
    json_out.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    md_out.write_text(to_markdown(analysis), encoding="utf-8")

    store.append(new_event(
        EventType.ReplayAnalyzed,
        payload={
            "episode_id": replay.episode_id,
            "analysis_json": str(json_out),
            "analysis_md": str(md_out),
            "decisions": analysis.get("telemetry", {}).get("decisions"),
            "effect_traces": analysis.get("effect_traces", {}).get("trace_count"),
            "strongest_failure_tag": analysis.get("strongest_failure_tag"),
        },
        tags=["pass5", "replay"],
    ))

    for tag in analysis.get("failure_tags", []):
        if tag.get("present"):
            store.append(new_event(
                EventType.FailureRegimeTagged,
                payload={"episode_id": replay.episode_id, **tag},
                tags=["pass5", "replay", "failure"],
            ))

    for idea in SEAM_IDEAS:
        store.append(new_event(
            EventType.IdeaGenerated,
            payload={"seam": idea, "source": "replay",
                     "episode_id": replay.episode_id},
            tags=["pass5", "replay", "seam"],
        ))

    print(f"[replay] analyzed episode {replay.episode_id}")
    print(f"[replay] wrote {json_out}")
    print(f"[replay] wrote {md_out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("replay", nargs="?", default=DEFAULT_REPLAY,
                   help=f"path to the Kaggle episode JSON (default: {DEFAULT_REPLAY})")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return run(args.replay)


if __name__ == "__main__":
    raise SystemExit(main())
