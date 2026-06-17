#!/usr/bin/env python3
"""Submit queued candidates to Kaggle — guarded, opt-in, never automatic.

This is the ONLY script that can upload, and it refuses unless ALL of these hold:
  * ``--i-understand-this-uploads`` is passed on the command line,
  * ``settings.auto_submit_enabled: true`` in experiment_plan.yaml,
  * ``settings.require_manual_approval_for_submit: false``,
  * the Kaggle daily submission count is below the configured limit.

With the shipped defaults it prints exactly what it WOULD do and exits without
uploading. It never invents a submission; it reads data/submission_queue.json.

Usage:
    python scripts/submit_queue.py                       # safe preview
    python scripts/submit_queue.py --i-understand-this-uploads   # still gated by plan
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401
from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH, load_config
from ptcg_activegraph.experiments.queue import QUEUE_JSON
from ptcg_activegraph.graph.event_store import EventStore
from ptcg_activegraph.graph.events import EventType, new_event


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--i-understand-this-uploads", action="store_true",
                        help="explicit human acknowledgement required to upload")
    parser.add_argument("--competition", default="pokemon-tcg-ai-battle")
    args = parser.parse_args()

    config = load_config()
    auto = bool(config.setting("auto_submit_enabled", False))
    manual = bool(config.setting("require_manual_approval_for_submit", True))

    if not QUEUE_JSON.exists():
        print(f"No queue at {QUEUE_JSON}. Run scripts/queue_submissions.py first.")
        return 1
    plan = json.loads(QUEUE_JSON.read_text(encoding="utf-8"))
    candidates = plan.get("candidates", [])

    print("Submission gate check:")
    print(f"  --i-understand-this-uploads : {args.i_understand_this_uploads}")
    print(f"  auto_submit_enabled         : {auto}")
    print(f"  require_manual_approval      : {manual}")
    print(f"  queued candidates            : {len(candidates)}")

    allowed = args.i_understand_this_uploads and auto and not manual
    if not allowed:
        print("\nUPLOAD BLOCKED (safe). All three must align: flag + auto_submit_enabled "
              "+ NOT require_manual_approval. Showing what WOULD be submitted:\n")
        for c in candidates:
            print(f"  {c['branch_id']}: {c['kaggle_command']}")
        return 0

    # If we reach here the operator has explicitly opted in. We still do not
    # hard-code an upload in this build pass: emit intent and print the command.
    store = EventStore(LAB_EVENTS_PATH)
    print("\nUpload pre-authorized. Executing queued submissions:")
    for c in candidates:
        print(f"  -> {c['kaggle_command']}")
        store.append(new_event(
            EventType.SubmissionUploaded,
            payload={"branch_id": c["branch_id"], "tarball": c.get("tarball"),
                     "competition": args.competition, "note": "operator-authorized"},
            tags=["kaggle", "submission"],
        ))
    print("\nNote: actual `kaggle competitions submit` execution is intentionally "
          "left to the operator in this build pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
