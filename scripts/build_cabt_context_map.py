#!/usr/bin/env python3
"""Pass 16 -- empirical cabt context map.

Builds an evidence-grounded map of cabt ``select.context`` integers by merging
TWO independent sources:

  1. The raw replay corpus (``data/meta_replays/raw/*.json``) -- real games,
     module_version 1.30.1 -- which exposes per-decision ``select`` dicts.
  2. A live cabt self-play trace captured by ``capture_live_contexts.py``
     (``data/experiments/pass16_live_context_trace.json``).

For every context it records the option-shape signature (select type, option
type-set, min/max counts, option keys), the temporal position in the replay
(0=game start, 1=game end), the per-source decision counts, and a few trimmed
example ``select`` dicts.

A context is **confirmed** only when its raw integer + option shape are stable
across BOTH sources (or, for the two docs-named contexts 7/8, by docs + replay).
The map then assigns a conservative *recommended action* (wire / defer) used by
the Pass 16 runtime-expansion plan -- the broad Main context (0) is ALWAYS
deferred (delegated), and only unambiguous, cross-source-confirmed, safely
deterministic contexts are eligible to wire.

Outputs:
  data/experiments/pass16_context_map.json
  data/experiments/pass16_context_map.md
  data/experiments/pass16_context_examples.jsonl

LOCAL ONLY. No upload, no submission, no GitHub push. No invented card IDs.
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW_REPLAYS = REPO / "data" / "meta_replays" / "raw"
LIVE_TRACE = REPO / "data" / "experiments" / "pass16_live_context_trace.json"
OUT_JSON = REPO / "data" / "experiments" / "pass16_context_map.json"
OUT_MD = REPO / "data" / "experiments" / "pass16_context_map.md"
OUT_EXAMPLES = REPO / "data" / "experiments" / "pass16_context_examples.jsonl"

# Docs-named contexts (src/ptcg_activegraph/pilot/state.py + docs/CABT_SCHEMA_NOTES.md).
# These are grounded by documentation AND the replay corpus, so they are treated
# as confirmed even if a particular short live run does not happen to hit them.
NAMED_CONTEXTS = {7: "search_to_hand", 8: "discard"}

# Curated, shape+temporal-grounded interpretation of each observed context.
# `hypothesis` is the inferred meaning; `policy` is the deterministic action a
# runtime hook *could* take; `eligible` says whether it is a candidate for
# wiring at all (broad Main and ambiguous mid-game places are NOT). These are
# interpretations of observed structure -- NOT invented card IDs or rules.
CONTEXT_INTERP = {
    0:  {"label": "main_action_broad",
         "hypothesis": "Broad main-phase action menu (play/attack/retreat/ability); "
                       "options carry inPlayArea/inPlayIndex/attackId.",
         "policy": "DELEGATE to deck-safe base agent (too broad to wire safely).",
         "eligible": False},
    1:  {"label": "setup_place_active",
         "hypothesis": "Setup: place exactly one basic as the active Pokemon "
                       "(min=max=1, basic-from-hand options, occurs at game start).",
         "policy": "Place best available basic active (Kyogre > Snover).",
         "eligible": True},
    2:  {"label": "setup_place_bench",
         "hypothesis": "Setup: optionally place 0..N basics on the bench "
                       "(min=0, basic-from-hand options, occurs at game start).",
         "policy": "Bench available basics as backups (cap by maxCount).",
         "eligible": True},
    3:  {"label": "place_basic_single_midgame",
         "hypothesis": "Mid-game single basic placement / promote (min=max=1, "
                       "occurs ~mid-game) -- semantics ambiguous vs promote-after-KO.",
         "policy": "DEFER -- cannot disambiguate setup vs promote vs play.",
         "eligible": False},
    4:  {"label": "place_basic_single_midgame_b",
         "hypothesis": "Mid-game single basic placement (min=max=1, ~mid-game); "
                       "ambiguous sibling of context 3.",
         "policy": "DEFER -- ambiguous.",
         "eligible": False},
    5:  {"label": "place_basic_optional",
         "hypothesis": "Optional basic placement (min=0,max=2); sparse, early-ish.",
         "policy": "DEFER -- sparse, ambiguous vs bench/mulligan.",
         "eligible": False},
    7:  {"label": "search_to_hand",
         "hypothesis": "Search/draw a card to hand (docs-named).",
         "policy": "core_pilot_decide('search_to_hand') -- ALREADY WIRED.",
         "eligible": True},
    8:  {"label": "discard",
         "hypothesis": "Discard selection (docs-named).",
         "policy": "core_pilot_decide('discard') with base-count floor -- ALREADY WIRED.",
         "eligible": True},
    19: {"label": "select_basic_sparse",
         "hypothesis": "Sparse basic/target selection.",
         "policy": "DEFER -- too few samples.",
         "eligible": False},
    21: {"label": "select_target_midlate",
         "hypothesis": "Mid/late target selection (opt_type 3).",
         "policy": "DEFER -- ambiguous target semantics.",
         "eligible": False},
    22: {"label": "select_target_midlate_b",
         "hypothesis": "Mid/late selection (opt_type 3, variable min).",
         "policy": "DEFER -- ambiguous.",
         "eligible": False},
    26: {"label": "energy_select_narrow",
         "hypothesis": "Energy-index selection (select type 2, opt_type 5, "
                       "energyIndex key) -- narrow attach/move-energy.",
         "policy": "Conservative: only wire if cross-source confirmed AND the "
                   "energy choice is unambiguous; else DEFER.",
         "eligible": True},
    30: {"label": "energy_count",
         "hypothesis": "Energy count selection (select type 4, opt_type 6, "
                       "count+energyIndex keys).",
         "policy": "DEFER -- count semantics ambiguous.",
         "eligible": False},
    37: {"label": "inplay_action_sparse",
         "hypothesis": "In-play action (select type 7, opt_type 9, inPlay*).",
         "policy": "DEFER -- single sample, near game end.",
         "eligible": False},
    38: {"label": "number_drawcount",
         "hypothesis": "Numeric choice (select type 8, opt_type 0 with `number` "
                       "field) -- a draw/count quantity; occurs early.",
         "policy": "Choose count that avoids self-deckout (low-deck draw avoid).",
         "eligible": True},
    41: {"label": "yesno_isfirst",
         "hypothesis": "Binary choice (select type 9, opt_type {1,2}, only `type` "
                       "key) -- who-goes-first / yes-no; FIRST decision of game.",
         "policy": "Conservative deterministic pick; DEFER unless confirmed safe.",
         "eligible": False},
    43: {"label": "select_sparse_43",
         "hypothesis": "Sparse selection (opt_type 3).",
         "policy": "DEFER -- too few samples.",
         "eligible": False},
}


def _shape_sig(sel: dict) -> dict:
    opts = sel.get("option") or sel.get("options") or []
    if not isinstance(opts, list):
        opts = []
    opt_types = tuple(sorted({o.get("type") for o in opts
                              if isinstance(o, dict) and isinstance(o.get("type"), int)}))
    opt_keys = sorted({k for o in opts if isinstance(o, dict) for k in o.keys()})
    return {
        "select_type": sel.get("type"),
        "opt_types": opt_types,
        "minCount": sel.get("minCount"),
        "maxCount": sel.get("maxCount"),
        "opt_keys": opt_keys,
        "n_options": len(opts),
        "has_deck": isinstance(sel.get("deck"), list),
        "has_inplay": any(isinstance(o, dict) and "inPlayArea" in o for o in opts),
    }


def aggregate_replays() -> tuple[dict, list]:
    agg = defaultdict(lambda: {
        "count": 0, "select_types": set(), "opt_type_sets": set(),
        "min_counts": set(), "max_counts": set(), "opt_keys": set(),
        "positions": [], "first_select": 0, "saw_deck": 0, "saw_inplay": 0,
    })
    examples = defaultdict(list)
    files = sorted(glob.glob(str(RAW_REPLAYS / "*.json")))
    for f in files:
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        steps = d.get("steps", [])
        nsteps = len(steps) or 1
        seen_first = False
        for si, st in enumerate(steps):
            if not isinstance(st, list):
                continue
            for a in st:
                if not isinstance(a, dict):
                    continue
                sel = (a.get("observation") or {}).get("select")
                if not isinstance(sel, dict) or sel.get("context") is None:
                    continue
                c = sel["context"]
                sig = _shape_sig(sel)
                rec = agg[c]
                rec["count"] += 1
                if isinstance(sig["select_type"], int):
                    rec["select_types"].add(sig["select_type"])
                rec["opt_type_sets"].add(sig["opt_types"])
                if isinstance(sig["minCount"], int):
                    rec["min_counts"].add(sig["minCount"])
                if isinstance(sig["maxCount"], int):
                    rec["max_counts"].add(sig["maxCount"])
                rec["opt_keys"].update(sig["opt_keys"])
                rec["positions"].append(si / nsteps)
                rec["saw_deck"] += int(sig["has_deck"])
                rec["saw_inplay"] += int(sig["has_inplay"])
                if not seen_first:
                    rec["first_select"] += 1
                    seen_first = True
                if len(examples[c]) < 3:
                    examples[c].append({
                        "source": "replay", "context": c,
                        "select_type": sig["select_type"],
                        "minCount": sig["minCount"], "maxCount": sig["maxCount"],
                        "opt_types": list(sig["opt_types"]),
                        "opt_keys": sig["opt_keys"],
                        "position": round(si / nsteps, 3),
                    })
    out = {}
    for c, rec in agg.items():
        pos = rec["positions"]
        out[c] = {
            "count": rec["count"],
            "select_types": sorted(rec["select_types"]),
            "opt_type_sets": sorted([list(t) for t in rec["opt_type_sets"]]),
            "min_counts": sorted(rec["min_counts"]),
            "max_counts": sorted(rec["max_counts"]),
            "opt_keys": sorted(rec["opt_keys"]),
            "mean_position": round(sum(pos) / len(pos), 3) if pos else None,
            "min_position": round(min(pos), 3) if pos else None,
            "first_select_count": rec["first_select"],
            "saw_deck_in_select": rec["saw_deck"],
            "saw_inplay_targets": rec["saw_inplay"],
            "n_replay_files": len(files),
        }
    flat_ex = [e for c in examples for e in examples[c]]
    return out, flat_ex


def load_live() -> dict:
    if not LIVE_TRACE.exists():
        return {"available": False, "reason": "live trace not captured yet",
                "games": 0, "contexts": {}}
    try:
        return json.loads(LIVE_TRACE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"unreadable: {exc!r}",
                "games": 0, "contexts": {}}


def _opt_sets_compatible(a: list, b: list) -> bool:
    """Two option-type-set collections are compatible if they share at least one
    option type (replays show many subsets of the same broad menu)."""
    flat_a = {t for s in a for t in s}
    flat_b = {t for s in b for t in s}
    if not flat_a or not flat_b:
        return False
    return bool(flat_a & flat_b)


def confirm(replay: dict, live: dict) -> dict:
    live_ctx = {int(k): v for k, v in (live.get("contexts") or {}).items()}
    all_ctx = sorted(set(replay) | set(live_ctx))
    rows = []
    for c in all_ctx:
        r = replay.get(c)
        lv = live_ctx.get(c)
        in_replay = r is not None
        in_live = lv is not None
        interp = CONTEXT_INTERP.get(c, {
            "label": f"unknown_ctx_{c}",
            "hypothesis": "Unrecognized context shape.",
            "policy": "DEFER -- unrecognized.",
            "eligible": False,
        })
        # select-type agreement
        st_replay = set(r["select_types"]) if in_replay else set()
        st_live = set(lv["select_types"]) if in_live else set()
        select_type_match = bool(st_replay & st_live) if (in_replay and in_live) else False
        # option shape agreement
        shape_match = False
        if in_replay and in_live:
            shape_match = _opt_sets_compatible(r["opt_type_sets"], lv["option_type_sets"])
        cross_source = in_replay and in_live and select_type_match and shape_match
        docs_named = c in NAMED_CONTEXTS
        if cross_source:
            confidence = "confirmed_cross_source"
        elif docs_named and in_replay:
            confidence = "confirmed_docs_replay"
        elif in_replay and in_live:
            confidence = "both_sources_shape_mismatch"
        elif in_replay:
            confidence = "replay_only"
        elif in_live:
            confidence = "live_only"
        else:
            confidence = "none"
        confirmed = confidence in ("confirmed_cross_source", "confirmed_docs_replay")
        already_wired = c in NAMED_CONTEXTS
        # Safe-to-wire gate: eligible interp AND confirmed AND not broad Main.
        safe_to_wire = bool(interp["eligible"] and confirmed and c != 0)
        recommended = "wire" if safe_to_wire else "defer"
        if already_wired:
            recommended = "keep_wired"
        rows.append({
            "context": c,
            "label": interp["label"],
            "hypothesis": interp["hypothesis"],
            "policy": interp["policy"],
            "eligible_shape": interp["eligible"],
            "in_replay": in_replay,
            "in_live": in_live,
            "replay_count": r["count"] if in_replay else 0,
            "live_count": lv["count"] if in_live else 0,
            "select_type_match": select_type_match,
            "option_shape_match": shape_match,
            "confidence": confidence,
            "confirmed": confirmed,
            "already_wired": already_wired,
            "safe_to_wire": safe_to_wire,
            "recommended_action": recommended,
            "replay_shape": r if in_replay else None,
            "live_shape": lv if in_live else None,
        })
    return {"rows": rows}


def build() -> dict:
    replay, replay_examples = aggregate_replays()
    live = load_live()
    conf = confirm(replay, live)
    confirmed = [r for r in conf["rows"] if r["confirmed"]]
    wire = [r for r in conf["rows"] if r["recommended_action"] == "wire"]
    keep = [r for r in conf["rows"] if r["recommended_action"] == "keep_wired"]
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "replays": {"dir": str(RAW_REPLAYS.relative_to(REPO)),
                        "n_files": replay[next(iter(replay))]["n_replay_files"]
                        if replay else 0,
                        "n_contexts": len(replay)},
            "live": {"available": live.get("available"),
                     "reason": live.get("reason", ""),
                     "games": live.get("games", 0),
                     "n_contexts": len(live.get("contexts") or {}),
                     "candidate": live.get("candidate")},
        },
        "named_contexts": {str(k): v for k, v in NAMED_CONTEXTS.items()},
        "summary": {
            "total_contexts": len(conf["rows"]),
            "confirmed": [r["context"] for r in confirmed],
            "recommend_wire_new": [r["context"] for r in wire],
            "keep_wired": [r["context"] for r in keep],
            "broad_main_deferred": any(r["context"] == 0 and
                                       r["recommended_action"] == "defer"
                                       for r in conf["rows"]),
        },
        "rows": conf["rows"],
    }
    return doc, replay_examples, live


def render_md(doc: dict) -> str:
    s = doc["summary"]
    src = doc["sources"]
    L = ["# Pass 16 -- Empirical cabt Context Map", ""]
    L.append(f"- Generated: {doc['generated_at']}")
    L.append(f"- Replay source: `{src['replays']['dir']}` "
             f"({src['replays']['n_files']} files, {src['replays']['n_contexts']} contexts)")
    L.append(f"- Live source: available={src['live']['available']} "
             f"games={src['live']['games']} contexts={src['live']['n_contexts']} "
             f"candidate={src['live']['candidate']}")
    if not src['live']['available']:
        L.append(f"  - live reason: {src['live']['reason']}")
    L.append(f"- **Confirmed contexts:** {s['confirmed']}")
    L.append(f"- **Recommend wire (new):** {s['recommend_wire_new']}")
    L.append(f"- **Keep wired:** {s['keep_wired']}")
    L.append(f"- Broad Main (ctx 0) deferred: {s['broad_main_deferred']}")
    L.append("")
    L.append("| ctx | label | conf. | replay n (pos) | live n | shape match | action |")
    L.append("|---|---|---|---|---|---|---|")
    for r in doc["rows"]:
        rs = r["replay_shape"]
        pos = f"@{rs['mean_position']}" if rs and rs.get("mean_position") is not None else ""
        sm = "type+opt" if (r["select_type_match"] and r["option_shape_match"]) else (
            "partial" if (r["in_replay"] and r["in_live"]) else "-")
        L.append(f"| {r['context']} | {r['label']} | {r['confidence']} | "
                 f"{r['replay_count']} {pos} | {r['live_count']} | {sm} | "
                 f"{r['recommended_action']} |")
    L.append("")
    L.append("## Per-context interpretation")
    for r in doc["rows"]:
        L.append(f"### ctx {r['context']} -- {r['label']} "
                 f"({r['confidence']}; action={r['recommended_action']})")
        L.append(f"- Hypothesis: {r['hypothesis']}")
        L.append(f"- Candidate policy: {r['policy']}")
        if r["replay_shape"]:
            rs = r["replay_shape"]
            L.append(f"- Replay: n={rs['count']}, select_types={rs['select_types']}, "
                     f"opt_type_sets={rs['opt_type_sets']}, "
                     f"min={rs['min_counts']}, max={rs['max_counts']}, "
                     f"mean_pos={rs['mean_position']}, first_select={rs['first_select_count']}")
        if r["live_shape"]:
            ls = r["live_shape"]
            L.append(f"- Live: n={ls['count']}, select_types={ls.get('select_types')}, "
                     f"opt_type_sets={ls['option_type_sets']}, "
                     f"min={ls['min_counts']}, max={ls['max_counts']}")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--out-examples", default=str(OUT_EXAMPLES))
    args = ap.parse_args()

    doc, replay_examples, live = build()
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    Path(args.out_md).write_text(render_md(doc), encoding="utf-8")

    # examples: replay examples + any live examples file appended
    live_ex_path = REPO / "data" / "experiments" / "pass16_live_context_examples.jsonl"
    live_examples = []
    if live_ex_path.exists():
        for ln in live_ex_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    e = json.loads(ln)
                    e["source"] = "live"
                    live_examples.append(e)
                except Exception:
                    pass
    with open(args.out_examples, "w", encoding="utf-8") as fh:
        for e in replay_examples + live_examples:
            fh.write(json.dumps(e) + "\n")

    print(f"Wrote {Path(args.out_json).relative_to(REPO)}")
    print(f"Confirmed: {doc['summary']['confirmed']}")
    print(f"Recommend wire (new): {doc['summary']['recommend_wire_new']}")
    print(f"Keep wired: {doc['summary']['keep_wired']}")
    print(f"Broad Main deferred: {doc['summary']['broad_main_deferred']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
