#!/usr/bin/env python3
"""Pass-10 meta evaluation (SCOUT ONLY) + ranking.

This is deliberately honest about what could NOT be done:

  * Local self-play games are unrunnable: the competition runtime
    (``cabt`` / ``kaggle_environments``) is not importable in this environment,
    so no win rates can be measured.
  * Two of three opponent archetypes are BLOCKED (missing replays, unconfirmed
    card ids), so even a single-archetype surrogate covers only part of the meta.

Result: the weighted meta score has coverage < 1.0 and NO win-rate data, the
evaluation is INCOMPLETE, and NOTHING is promotable. The queue stays empty.

Outputs:
  data/meta_replays/pass10_eval_status.json
  data/meta_replays/pass10_eval_status.md
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.meta.scoring import (  # noqa: E402
    load_meta_pool, meta_pool_weights, weighted_meta_score)
from ptcg_activegraph.meta import archetypes as arch_mod  # noqa: E402

META_POOL = REPO / "experiments" / "meta_pool.yaml"
MANIFEST = REPO / "data" / "submissions" / "pass10_candidates_manifest.json"
OUT_JSON = REPO / "data" / "meta_replays" / "pass10_eval_status.json"
OUT_MD = REPO / "data" / "meta_replays" / "pass10_eval_status.md"

# The competition game engine is ``cabt``. ``kaggle_environments`` is the
# harness but cannot run the Pokemon-TCG games WITHOUT ``cabt`` — so the engine
# itself is what gates local self-play.
GAME_ENGINE = "cabt"
GAME_RUNTIME_MODULES = ("cabt", "kaggle_environments")


def _runtime_available() -> dict:
    found = {}
    for mod in GAME_RUNTIME_MODULES:
        try:
            found[mod] = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            found[mod] = False
    # Games are runnable ONLY when the engine itself (cabt) is importable.
    return {"modules": found, "any": bool(found.get(GAME_ENGINE, False))}


def _emit_events(status: dict) -> None:
    try:
        from ptcg_activegraph.graph.events import EventType, new_event
        from ptcg_activegraph.graph.event_store import EventStore
        from ptcg_activegraph.experiments.config import LAB_EVENTS_PATH
        store = EventStore(LAB_EVENTS_PATH)
        store.append(new_event(
            EventType.LocalEvaluationStarted,
            payload={"pass": "pass10", "mode": "scout_only"},
            tags=["pass10", "evaluation"]))
        store.append(new_event(
            EventType.MetricsComputed,
            payload={"pass": "pass10",
                     "weighted_meta_score": status["weighted_meta_score"],
                     "coverage": status["coverage"],
                     "complete": status["eval_complete"]},
            tags=["pass10", "evaluation"]))
        store.append(new_event(
            EventType.LocalEvaluationFinished,
            payload={"pass": "pass10", "status": "incomplete",
                     "reason": status["reason"],
                     "games_runnable": status["games_runnable_locally"]},
            tags=["pass10", "evaluation", "blocked"]))
        for cand in status["candidates"]:
            store.append(new_event(
                EventType.CandidateRanked,
                payload={"pass": "pass10", "candidate_id": cand["id"],
                         "promotable": False, "rank": None,
                         "reason": "meta eval incomplete; scout only"},
                tags=["pass10", "ranking"]))
    except Exception as exc:  # pragma: no cover - telemetry must not break
        print(f"  (event emission skipped: {type(exc).__name__}: {exc})")


def main() -> int:
    runtime = _runtime_available()
    pool = load_meta_pool(META_POOL)
    weights = meta_pool_weights(pool)
    available = {a.key for a in arch_mod.ARCHETYPES.values() if a.available}

    # No games were run -> no win rates. weighted_meta_score with empty winrates
    # is None and not complete; this is the honest result.
    winrates: dict[str, float] = {}
    score = weighted_meta_score(winrates, weights, available=available)

    built: list[dict] = []
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        built = manifest.get("built", [])

    candidates = [
        {"id": c["id"], "kind": c["kind"], "validated": c.get("validated", False),
         "winrate": None, "promotable": False,
         "reason": "no local games (cabt/kaggle_environments unavailable) + "
                   "external archetypes blocked"}
        for c in built
    ]

    status = {
        "schema": "activegraph.pass10.eval/v1",
        "mode": "scout_only",
        "games_runnable_locally": runtime["any"],
        "runtime_modules": runtime["modules"],
        "weighted_meta_score": score["weighted_meta_score"],
        "coverage": score["coverage"],
        "eval_complete": score["complete"],
        "available_archetypes": sorted(available),
        "blocked_archetypes": score["missing_archetypes"],
        "reason": "Local self-play runtime unavailable AND 2/3 archetypes blocked "
                  "(missing replays / unconfirmed ids).",
        "candidates": candidates,
        "promotable": [],   # nothing promotable
        "queue_action": "none (queue stays empty; no upload this pass)",
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")

    md = ["# Pass 10 meta evaluation — SCOUT ONLY (INCOMPLETE)", ""]
    md.append(f"- games runnable locally: **{status['games_runnable_locally']}** "
              f"({status['runtime_modules']})")
    md.append(f"- weighted_meta_score: **{status['weighted_meta_score']}** "
              f"(coverage {status['coverage']:.2f}, complete={status['eval_complete']})")
    md.append(f"- available archetypes: {status['available_archetypes']}")
    md.append(f"- blocked archetypes: {status['blocked_archetypes']}")
    md.append("")
    md.append("## Candidates (all scout-only, none promotable)")
    for c in candidates:
        md.append(f"- `{c['id']}` ({c['kind']}): validated={c['validated']}, "
                  f"winrate={c['winrate']}, promotable={c['promotable']}")
    md.append("")
    md.append("## Decision")
    md.append("- **Nothing is promotable.** Meta evaluation is incomplete: no "
              "win-rate data could be measured and most of the meta is blocked.")
    md.append("- **Queue stays empty. No upload this pass.**")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    _emit_events(status)

    print(f"games runnable locally: {status['games_runnable_locally']}")
    print(f"weighted_meta_score: {status['weighted_meta_score']} "
          f"(coverage {status['coverage']:.2f}, complete={status['eval_complete']})")
    print(f"promotable: {status['promotable']}")
    print(f"  -> {OUT_JSON.relative_to(REPO)}")
    print(f"  -> {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
