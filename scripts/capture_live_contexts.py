#!/usr/bin/env python3
"""Pass 16 -- live cabt context capture.

Runs N cabt self-play games with a maintained candidate piloting BOTH seats and
records, per ``select.context`` integer, the option-shape signature plus a few
trimmed example ``select`` dicts. This is the *live-trace* source for the
empirical context map (the other source is the raw replay corpus). A context is
only "confirmed" later if its raw integer + option shape are stable across BOTH
sources.

Importing kaggle_environments is slow (~115s: cabt/OpenSpiel registration), so
this is intended to be run as a background job; it writes:

  data/experiments/pass16_live_context_trace.json
  data/experiments/pass16_live_context_examples.jsonl

LOCAL ONLY. No upload, no submission, no GitHub push. Reads only local code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DEFAULT_CAND = (REPO / "data" / "submissions" / "candidates_pass14"
                / "core_pilot_water_v2_runtime.tar.gz")
OUT_JSON = REPO / "data" / "experiments" / "pass16_live_context_trace.json"
OUT_EXAMPLES = REPO / "data" / "experiments" / "pass16_live_context_examples.jsonl"

MAX_EXAMPLES_PER_CTX = 3


def _extract_main(cand: Path, dest: Path) -> Path:
    if cand.is_dir():
        m = cand / "main.py"
        if m.exists():
            return m
        for p in cand.rglob("main.py"):
            return p
        raise FileNotFoundError(f"no main.py under {cand}")
    if cand.suffix == ".gz" or cand.name.endswith(".tar.gz"):
        with tarfile.open(cand, "r:gz") as tf:
            tf.extractall(dest)
        m = dest / "main.py"
        if m.exists():
            return m
        for p in dest.rglob("main.py"):
            return p
        raise FileNotFoundError(f"no main.py inside {cand.name}")
    if cand.name == "main.py":
        return cand
    raise FileNotFoundError(f"unrecognized candidate {cand}")


def _trim_select(sel: dict) -> dict:
    """Keep a compact, structurally-faithful copy of a select dict for examples."""
    opts = sel.get("option") or sel.get("options") or []
    trimmed_opts = []
    for o in opts[:8]:
        if isinstance(o, dict):
            trimmed_opts.append({k: o.get(k) for k in sorted(o.keys())})
    return {
        "context": sel.get("context"),
        "type": sel.get("type"),
        "minCount": sel.get("minCount"),
        "maxCount": sel.get("maxCount"),
        "n_options": len(opts) if isinstance(opts, list) else None,
        "option_sample": trimmed_opts,
        "has_deck": isinstance(sel.get("deck"), list),
        "option_keys": sorted({k for o in opts if isinstance(o, dict) for k in o.keys()}),
    }


def capture(cand: Path, games: int) -> dict:
    try:
        from kaggle_environments import make  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"available": False,
                "reason": f"kaggle_environments unavailable: {exc!r}",
                "games": 0, "contexts": {}, "examples": []}

    records: dict = defaultdict(lambda: {"count": 0, "type_sets": set(),
                                         "min_counts": set(), "max_counts": set(),
                                         "sel_types": set(),
                                         "has_deck": 0, "has_inplay": 0,
                                         "opt_keys": set()})
    examples: dict = defaultdict(list)

    with tempfile.TemporaryDirectory() as tmp:
        main_path = _extract_main(cand, Path(tmp))
        src = main_path.read_text(encoding="utf-8")
        env_ns: dict = {"__file__": str(main_path), "__name__": "cand_live"}
        old_cwd = os.getcwd()
        os.chdir(main_path.parent)
        try:
            exec(compile(src, str(main_path), "exec"), env_ns)  # noqa: S102
            callables = [v for v in env_ns.values() if callable(v)]
            base_agent = callables[-1]

            def recording_agent(obs, *a, **k):
                try:
                    sel = obs.get("select") if isinstance(obs, dict) else None
                    if isinstance(sel, dict):
                        ctx = sel.get("context")
                        opts = sel.get("option") or sel.get("options") or []
                        if isinstance(opts, list) and opts:
                            rec = records[ctx]
                            rec["count"] += 1
                            tset = tuple(sorted({o.get("type") for o in opts
                                                 if isinstance(o, dict)
                                                 and isinstance(o.get("type"), int)}))
                            rec["type_sets"].add(tset)
                            if isinstance(sel.get("type"), int):
                                rec["sel_types"].add(sel.get("type"))
                            if isinstance(sel.get("minCount"), int):
                                rec["min_counts"].add(sel.get("minCount"))
                            if isinstance(sel.get("maxCount"), int):
                                rec["max_counts"].add(sel.get("maxCount"))
                            if isinstance(sel.get("deck"), list):
                                rec["has_deck"] += 1
                            if any(isinstance(o, dict) and "inPlayArea" in o
                                   for o in opts):
                                rec["has_inplay"] += 1
                            for o in opts:
                                if isinstance(o, dict):
                                    rec["opt_keys"].update(o.keys())
                            if len(examples[ctx]) < MAX_EXAMPLES_PER_CTX:
                                examples[ctx].append(_trim_select(sel))
                except Exception:  # noqa: BLE001
                    pass
                return base_agent(obs)

            game_env = None
            for cfg in ({}, {"actTimeout": 30}):
                try:
                    game_env = make("cabt", configuration=cfg)
                    break
                except Exception:
                    game_env = None
            if game_env is None:
                return {"available": False, "reason": "make('cabt') failed",
                        "games": 0, "contexts": {}, "examples": []}
            n = 0
            for _ in range(max(1, games)):
                game_env.run([recording_agent, recording_agent])
                n += 1
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": f"live run error: {exc!r}",
                    "games": 0,
                    "contexts": _serialize(records),
                    "examples": _flatten_examples(examples)}
        finally:
            os.chdir(old_cwd)

    return {"available": True, "reason": "", "games": n,
            "contexts": _serialize(records),
            "examples": _flatten_examples(examples)}


def _serialize(records) -> dict:
    out = {}
    for ctx, rec in records.items():
        out[str(ctx)] = {
            "context": ctx,
            "count": rec["count"],
            "select_types": sorted(rec["sel_types"]),
            "option_type_sets": sorted([list(t) for t in rec["type_sets"]]),
            "min_counts": sorted(rec["min_counts"]),
            "max_counts": sorted(rec["max_counts"]),
            "option_keys": sorted(rec["opt_keys"]),
            "saw_deck_in_select": rec["has_deck"],
            "saw_inplay_targets": rec["has_inplay"],
        }
    return out


def _flatten_examples(examples) -> list:
    out = []
    for ctx, exs in examples.items():
        for e in exs:
            out.append(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", default=str(DEFAULT_CAND))
    ap.add_argument("--games", type=int, default=12)
    ap.add_argument("--out", default=str(OUT_JSON))
    ap.add_argument("--examples-out", default=str(OUT_EXAMPLES))
    ap.add_argument("--sentinel", default=None,
                    help="path to touch on completion (for background jobs)")
    args = ap.parse_args()

    t0 = time.time()
    doc = capture(Path(args.candidate), args.games)
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    doc["candidate"] = Path(args.candidate).name
    doc["elapsed_sec"] = round(time.time() - t0, 1)
    doc["source"] = "live_cabt_self_play"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    examples = doc.pop("examples", [])
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    with open(args.examples_out, "w", encoding="utf-8") as fh:
        for e in examples:
            fh.write(json.dumps(e) + "\n")

    print(f"Wrote {out.relative_to(REPO)} "
          f"(available={doc['available']}, games={doc['games']}, "
          f"contexts={len(doc['contexts'])}, elapsed={doc['elapsed_sec']}s)")
    if not doc["available"]:
        print(f"  reason: {doc['reason']}")
    if args.sentinel:
        Path(args.sentinel).write_text("done\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
