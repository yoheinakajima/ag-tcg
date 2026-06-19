#!/usr/bin/env python3
"""Pass 29 (Part H) — search / supporter / engine-card observability. LOCAL/RO.

Asks: when the pilot searches a deck, plays a supporter, or runs a draw/engine
card, can we observe WHICH card it is? This bounds whether engine-card fixtures
(search targeting, supporter sequencing) are buildable. Reports honestly.

Outputs data/experiments/pass29_engine_card_observability.{json,md}.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
DATASET = REPO / "data" / "experiments" / "pass29_action_resolution_dataset.jsonl"
OUT_JSON = REPO / "data" / "experiments" / "pass29_engine_card_observability.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_engine_card_observability.md"

ENGINE_CLASSES = ("select_card", "play_from_hand", "use_ability", "in_play_action")


def main() -> int:
    # From the trace: selected engine-class actions and whether card identity known.
    per_class = {c: {"decisions": 0, "card_id_known": 0} for c in ENGINE_CLASSES}
    search_contexts = Counter()
    if TRACE.exists():
        with TRACE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                for sr in (d.get("selected_resolved") or []):
                    ac = sr.get("action_class")
                    if ac in per_class:
                        per_class[ac]["decisions"] += 1
                        if sr.get("card_id") is not None:
                            per_class[ac]["card_id_known"] += 1
                        if ac == "select_card":
                            search_contexts[d.get("select_context")] += 1

    # From the dataset: select_card identity resolvability by confidence.
    select_card_conf = Counter()
    if DATASET.exists():
        with DATASET.open(encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                res = r["resolution"]
                if res.get("action_class") == "select_card":
                    select_card_conf[res.get("confidence")] += 1

    def frac(a, b):
        return round(a / b, 4) if b else None

    obs = {c: {
        "decisions": v["decisions"],
        "card_identity_observable_fraction": frac(v["card_id_known"], v["decisions"]),
    } for c, v in per_class.items()}

    out = {
        "pass": "29", "part": "H",
        "by_engine_class": obs,
        "search_contexts_seen": {str(k): v for k, v in search_contexts.most_common()},
        "select_card_confidence_in_dataset": dict(select_card_conf),
        "observable": [
            "search-to-hand (ctx7) target identity — resolvable from the candidate "
            "resolver / select.deck (high card-identity coverage)",
            "play-from-hand card identity when board reconstruction succeeds",
        ],
        "NOT_observable_yet": [
            "supporter/Trainer EFFECT outcomes (what a supporter actually did) are "
            "not linked to the play event in the trace",
            "in_play_action / use_ability card identity is frequently null (the "
            "ability's source Pokemon is not always resolvable from the option) -> "
            "this is exactly the Venusaur loop's in_play_action head",
        ],
        "fixture_feasibility": (
            "A search-target fixture (ctx7) is buildable now. A supporter-sequencing "
            "or ability-effect fixture is NOT yet buildable: effect outcomes and many "
            "in_play_action sources are unobserved -> needs_more_observability (link "
            "play/ability events to their resulting state delta)."),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Search / Supporter / Engine-Card Observability (Part H)", "",
         "## Card-identity observability by engine class", "",
         "| class | decisions | card identity observable |", "|---|---|---|"]
    for c, v in obs.items():
        f = v["card_identity_observable_fraction"]
        L.append(f"| {c} | {v['decisions']} | "
                 f"{(f*100):.1f}% |" if f is not None else f"| {c} | "
                 f"{v['decisions']} | n/a |")
    L += ["", f"- Search contexts seen: {out['search_contexts_seen']}.",
          f"- select_card confidence (dataset): {dict(select_card_conf)}.",
          "", "## Observable", ""]
    L += [f"- {x}" for x in out["observable"]]
    L += ["", "## NOT observable yet", ""]
    L += [f"- {x}" for x in out["NOT_observable_yet"]]
    L += ["", "## Fixture feasibility", "", out["fixture_feasibility"], ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"engine-card obs: " + ", ".join(
        f"{c}={obs[c]['card_identity_observable_fraction']}" for c in ENGINE_CLASSES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
