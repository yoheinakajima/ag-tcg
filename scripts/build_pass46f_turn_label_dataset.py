#!/usr/bin/env python3
"""PASS 46F (Part C) — search-calibrated label dataset for the turn scorer.

For a bounded set of ACTIVE-seat decision frames drawn from the Pass-46C trace
panel, enumerate a bounded set of legal one-step candidate actions and evaluate
each with the Pass-46E Search oracle (ONE batched, subprocess-isolated pipeline).
Each candidate action is tagged with the SCORER's coarse action family
(``turn_scorer.family_for_option``) and the oracle's transparent
``generic_progress_v0`` one-step score, then aggregated PER FAMILY.

This produces the offline calibration signal for Part D: which coarse action
families tend to produce good immediate (one-step) outcomes under the recorded
hidden-state assumption. It is a property of the GAME's response to an action —
NOT an imitation of any agent's policy.

LOCAL / READ-ONLY / DIAGNOSTIC. No production mutation, no Object Storage write,
no candidate generation, no upload, no tick, no events.

Honesty (enforced):
* The oracle fabricates hidden zones (opponent deck/hand/prize, your prize), so
  every score is ``assumption_based_hidden_state`` — never exact. Unsupported /
  timed-out candidates are counted separately and excluded from family means.
* NO exact-damage / lethal / missed-KO / Boss-gust / spread / best-action claim.
* Public-reference frames are calibration INPUTS only (benchmark opponents), never
  a candidate source/parent; rows are tagged by role bucket so an internal-only
  view is available.

Runnable standalone and importable (``run_label_dataset() -> dict``).
"""
from __future__ import annotations

import glob
import gzip
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis import search_oracle as O  # noqa: E402
from ptcg_activegraph.analysis import turn_scorer as TS  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"

CAVEATS = [
    "READ-ONLY / LOCAL / DIAGNOSTIC: production Object Storage was not mutated.",
    "No production tick, candidate generation, promotion, queue, upload, or republish.",
    "Oracle scores are ASSUMPTION-BASED: hidden zones are fabricated placeholder "
    "basic-Pokemon IDs, not the real hidden state. Never exact.",
    "Per-family value is the GAME engine's one-step response to an action family, "
    "NOT an imitation of any agent's policy.",
    "No exact-damage / lethal / missed-KO / Boss-gust / spread / best-action claim.",
    "Public-reference frames are calibration INPUTS only (benchmark opponents); "
    "they are never a candidate source/parent. Rows are role-bucket tagged.",
]


def role_bucket(role) -> str:
    r = str(role or "").lower()
    if "public_ref" in r or "reference" in r:
        return "public_reference"
    if "parent" in r or "anchor" in r:
        return "internal_parent"
    return "internal_candidate"


def _select_active_choice_frames(steps, a_seat, role_a, role_b, per_family):
    """ACTIVE decision frames with a REAL choice (n_options>=2) + legal action."""
    picked = []
    counts: dict[str, int] = {}
    for i, st in enumerate(steps):
        if not isinstance(st, list):
            continue
        for seat, o in enumerate(st):
            if not isinstance(o, dict):
                continue
            if str(o.get("status", "")).upper() != "ACTIVE":
                continue
            obs = o.get("observation")
            if not isinstance(obs, dict) or not obs.get("search_begin_input"):
                continue
            sel, cur = obs.get("select"), obs.get("current")
            if not isinstance(sel, dict) or not isinstance(cur, dict):
                continue
            opts = sel.get("option") or []
            if len(opts) < 2:  # forced single-option steps are uninformative
                continue
            action = o.get("action")
            if not O._is_index_action(action, len(opts), sel.get("minCount"),
                                      sel.get("maxCount")):
                continue
            if cur.get("yourIndex") not in (0, 1):
                continue
            # balance sampling by the scorer-family of the ACTUAL chosen option
            chosen0 = action[0] if action else None
            fam = TS.family_for_option(opts[chosen0]) if isinstance(chosen0, int) \
                and 0 <= chosen0 < len(opts) else "unknown"
            if counts.get(fam, 0) >= per_family:
                continue
            counts[fam] = counts.get(fam, 0) + 1
            picked.append({
                "step": i, "seat": seat,
                "actual_family": fam,
                "role_bucket": role_bucket(role_a if seat == a_seat else role_b),
                "frame": o, "selected": list(action),
            })
    return picked


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return round(float(s[0]), 4)
    idx = min(len(s) - 1, int(round(p * (len(s) - 1))))
    return round(float(s[idx]), 4)


def _family_stats(scores):
    if not scores:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {"n": len(scores), "mean": round(statistics.fmean(scores), 4),
            "median": round(statistics.median(scores), 4),
            "p25": _pct(scores, 0.25), "p75": _pct(scores, 0.75)}


def run_label_dataset(per_family_per_trace: int = 2, total_frame_cap: int = 70,
                      max_actions: int = 5, timeout_s: float = 5.0,
                      chunk_size: int = 25) -> dict:
    trace_paths = sorted(glob.glob(str(TRACES / "*.json.gz")))
    frames: list[dict] = []
    per_trace_meta = []
    for tp in trace_paths:
        try:
            d = json.loads(gzip.open(tp).read())
        except Exception as exc:  # noqa: BLE001
            per_trace_meta.append({"trace": Path(tp).name, "error": type(exc).__name__})
            continue
        fr = _select_active_choice_frames(
            d.get("steps") or [], int(d.get("a_seat", 0)),
            d.get("role_a"), d.get("role_b"), per_family_per_trace)
        for f in fr:
            f["trace"] = Path(tp).name
            f["matchup"] = d.get("id")
        frames.extend(fr)
        per_trace_meta.append({"trace": Path(tp).name, "n_frames": len(fr)})
        if len(frames) >= total_frame_cap:
            frames = frames[:total_frame_cap]
            break

    # Build a bounded set of (frame, candidate_action) items across all frames.
    items = []          # (frame, selected_indices) for the oracle
    item_meta = []      # parallel metadata
    for f in frames:
        inputs = O.build_search_inputs_from_frame(f["frame"])
        if not inputs["ok"]:
            continue
        opts = (inputs["observation"].get("select") or {}).get("option") or []
        actual = f["selected"] if O._is_index_action(
            f["selected"], inputs["n_options"], inputs["min_count"],
            inputs["max_count"]) else None
        cands = O._candidate_select_lists(inputs, actual, max_actions)
        for c in cands:
            fam = TS.family_for_option(opts[c[0]]) if (c and 0 <= c[0] < len(opts)) \
                else "unknown"
            items.append((f["frame"], c))
            item_meta.append({
                "trace": f["trace"], "step": f["step"], "seat": f["seat"],
                "your_index": inputs["your_index"], "candidate_family": fam,
                "selected": c, "role_bucket": f["role_bucket"],
                "is_actual": (actual is not None and c == actual),
            })

    results = O.evaluate_actions_batch(items, timeout_s=timeout_s,
                                      chunk_size=chunk_size)

    rows = []
    for meta, res in zip(item_meta, results):
        sc = O.score_outcome_generic_progress_v0(
            res.outcome, meta["your_index"])
        supported = (res.ok and res.supported_level == "assumption_based_hidden_state"
                     and res.outcome is not None and not res.outcome.timed_out)
        rows.append({**meta, "oracle_score": sc["score"],
                     "score_breakdown": sc["breakdown"],
                     "supported_level": res.supported_level,
                     "supported": bool(supported)})

    # Aggregate per scorer-family over SUPPORTED candidates only.
    def _agg(filter_fn):
        by_fam: dict[str, list[float]] = {}
        for r in rows:
            if not r["supported"] or not filter_fn(r):
                continue
            by_fam.setdefault(r["candidate_family"], []).append(r["oracle_score"])
        return {fam: _family_stats(s) for fam, s in sorted(by_fam.items())}

    by_family_all = _agg(lambda r: True)
    by_family_internal = _agg(lambda r: r["role_bucket"] != "public_reference")

    n_items = len(rows)
    n_supported = sum(1 for r in rows if r["supported"])
    supported_levels: dict[str, int] = {}
    for r in rows:
        supported_levels[r["supported_level"]] = \
            supported_levels.get(r["supported_level"], 0) + 1

    data = {
        "pass": "46f", "part": "C", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "scoring_profile": "generic_progress_v0",
        "scorer_schema_version": TS.PROFILE_SCHEMA_VERSION,
        "n_traces": len(trace_paths), "per_trace": per_trace_meta,
        "n_frames_selected": len(frames),
        "n_candidate_items": n_items, "n_supported_items": n_supported,
        "supported_rate": round(n_supported / n_items, 4) if n_items else 0.0,
        "supported_level_breakdown": supported_levels,
        "by_family_all": by_family_all,
        "by_family_internal_only": by_family_internal,
        "feature_keys": list(TS.FEATURE_KEYS),
        "caveats": CAVEATS,
        "unsupported_claims": {**O.unsupported_search_claims(),
                               **TS.unsupported_scorer_claims()},
        "rows": rows,
    }

    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46f_turn_label_dataset.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46F — Part C: search-calibrated turn label dataset", "",
        "_Oracle one-step scores per SCORER action family. ASSUMPTION-BASED "
        "(fabricated hidden zones); never exact. No best-action / damage / lethal "
        "claim. LOCAL / READ-ONLY; no generation / upload / tick / events._", "",
        "## Caveats"] + [f"- {c}" for c in CAVEATS] + [
        "", "## Aggregate",
        f"- frames selected: **{len(frames)}**",
        f"- candidate items: **{n_items}** | supported: **{n_supported}** "
        f"({data['supported_rate']:.2%})",
        "", "## Per-family one-step score (ALL frames, supported only)",
        "| family | n | mean | median | p25 | p75 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for fam, s in by_family_all.items():
        md.append(f"| {fam} | {s['n']} | {s['mean']} | {s['median']} | "
                  f"{s['p25']} | {s['p75']} |")
    md += ["", "## Per-family one-step score (INTERNAL frames only, supported)",
           "| family | n | mean | median | p25 | p75 |",
           "|---|---:|---:|---:|---:|---:|"]
    for fam, s in by_family_internal.items():
        md.append(f"| {fam} | {s['n']} | {s['mean']} | {s['median']} | "
                  f"{s['p25']} | {s['p75']} |")
    (EXP / "pass46f_turn_label_dataset.md").write_text("\n".join(md) + "\n",
                                                       encoding="utf-8")
    return data


if __name__ == "__main__":
    out = run_label_dataset()
    print(json.dumps({k: out[k] for k in (
        "n_frames_selected", "n_candidate_items", "n_supported_items",
        "supported_rate", "by_family_all")}, indent=2, default=str))
