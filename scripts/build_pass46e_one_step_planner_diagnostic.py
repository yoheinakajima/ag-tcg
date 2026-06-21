#!/usr/bin/env python3
"""PASS 46E — Part E: one-step action-ranking diagnostic.

On a bounded set of *rankable* decision frames (single-select, >=2 legal options)
drawn from the Pass-46C panel, enumerate legal one-step actions, score each with
the transparent ``generic_progress_v0`` function via the search oracle, and rank
them. Compares the rank the *actual* chosen action receives across role buckets
(public references vs internal candidates vs internal parents).

This is NOT a "best action" finder: every result is labelled
``one_step_score_rank under assumption`` and the oracle's unsupported claims stay
guarded. LOCAL / READ-ONLY / DIAGNOSTIC; no candidate generation, no upload.

Runnable standalone and importable (``run_planner() -> dict``).
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
import build_pass46e_search_oracle_calibration as CAL  # noqa: E402

EXP = REPO / "data" / "experiments"
TRACES = EXP / "pass46c_traces"


def _rankable_frames(steps, a_seat, role_a, role_b, per_bucket, seen):
    out = []
    for i, st in enumerate(steps[:-1]):
        if not isinstance(st, list):
            continue
        for seat, o in enumerate(st):
            if not isinstance(o, dict):
                continue
            # ACTIVE-only: INACTIVE rows carry stale action/observation data.
            if str(o.get("status", "")).upper() != "ACTIVE":
                continue
            obs = o.get("observation")
            if not isinstance(obs, dict) or not obs.get("search_begin_input"):
                continue
            sel = obs.get("select")
            if not isinstance(sel, dict) or not isinstance(obs.get("current"), dict):
                continue
            n_opt = len(sel.get("option") or [])
            if n_opt < 2 or (sel.get("maxCount") or 1) != 1:
                continue
            action = o.get("action")
            if not O._is_index_action(action, n_opt, sel.get("minCount"),
                                      sel.get("maxCount")):
                continue
            bucket = CAL.role_bucket(role_a if seat == a_seat else role_b)
            if seen.get(bucket, 0) >= per_bucket:
                continue
            seen[bucket] = seen.get(bucket, 0) + 1
            out.append({"step": i, "seat": seat, "role_bucket": bucket,
                        "family": CAL.classify_family(sel, action),
                        "frame": o, "n_options": n_opt})
    return out


def run_planner(per_bucket_per_trace: int = 4, total_cap: int = 60,
                max_actions: int = 8, timeout_s: float = 6.0) -> dict:
    trace_paths = sorted(glob.glob(str(TRACES / "*.json.gz")))
    frames = []
    for tp in trace_paths:
        try:
            d = json.loads(gzip.open(tp).read())
        except Exception:  # noqa: BLE001
            continue
        seen: dict = {}
        ff = _rankable_frames(d.get("steps") or [], int(d.get("a_seat", 0)),
                              d.get("role_a"), d.get("role_b"),
                              per_bucket_per_trace, seen)
        for f in ff:
            f["trace"] = Path(tp).name
        frames.extend(ff)
        if len(frames) >= total_cap:
            frames = frames[:total_cap]
            break

    results = []
    for f in frames:
        rk = O.rank_legal_actions_one_step(f["frame"], max_actions=max_actions,
                                           timeout_s=timeout_s)
        if not rk["ok"] or rk["actual_rank"] is None:
            continue
        n_supported = sum(1 for r in rk["ranking"]
                          if r["supported_level"] == "assumption_based_hidden_state")
        results.append({
            "trace": f["trace"], "step": f["step"], "seat": f["seat"],
            "role_bucket": f["role_bucket"], "family": f["family"],
            "n_options": f["n_options"], "n_candidates": rk["n_candidates"],
            "n_supported_candidates": n_supported,
            "actual_rank": rk["actual_rank"],
            "actual_score": next((r["score"] for r in rk["ranking"]
                                  if r.get("is_actual")), None),
            "top_score": rk["ranking"][0]["score"] if rk["ranking"] else None,
            "actual_is_top": rk["actual_rank"] == 0,
            "supported_level": rk["supported_level"],
            "label": rk["label"],
        })

    def _bucket_stats(bucket):
        rs = [r for r in results if r["role_bucket"] == bucket]
        ranks = [r["actual_rank"] for r in rs if isinstance(r["actual_rank"], int)]
        norm = [r["actual_rank"] / max(1, r["n_candidates"] - 1)
                for r in rs if r["n_candidates"] and r["n_candidates"] > 1]
        return {
            "n": len(rs),
            "actual_is_top_rate": round(sum(1 for r in rs if r["actual_is_top"]) / len(rs), 4)
            if rs else None,
            "median_actual_rank": round(statistics.median(ranks), 3) if ranks else None,
            "mean_actual_rank": round(statistics.mean(ranks), 3) if ranks else None,
            "median_normalized_rank": round(statistics.median(norm), 3) if norm else None,
        }

    buckets = ["public_reference", "internal_candidate", "internal_parent"]
    by_bucket = {b: _bucket_stats(b) for b in buckets}

    data = {
        "pass": "46e", "part": "E", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "tick_executed": False,
        "candidate_generated": False,
        "scoring_profile": "generic_progress_v0",
        "label": "one_step_score_rank_under_assumption_not_best_action",
        "max_actions": max_actions, "n_frames_ranked": len(results),
        "by_role_bucket": by_bucket,
        "rows": results,
        "unsupported_claims": O.unsupported_search_claims(),
        "caveat": "Rank distributions describe how the actually-chosen action scores "
                  "under generic_progress_v0 with fabricated hidden zones; they do NOT "
                  "prove which agent plays better, and assert no best/optimal action.",
    }
    body = (
        f"## One-step ranking diagnostic\n"
        f"- scoring_profile: `generic_progress_v0`\n"
        f"- label: `{data['label']}`\n"
        f"- frames ranked (supported, actual action found): **{len(results)}**\n\n"
        "## Actual-action rank by role bucket\n"
        + "".join(
            f"- `{b}`: n={by_bucket[b]['n']}, actual_is_top_rate="
            f"{by_bucket[b]['actual_is_top_rate']}, "
            f"median_actual_rank={by_bucket[b]['median_actual_rank']}, "
            f"median_normalized_rank={by_bucket[b]['median_normalized_rank']}\n"
            for b in buckets)
        + "\n> Small-n, diagnostic only. Not a strength claim; not a best-action claim.\n"
    )
    CAL.write_pair = CAL.write_pair  # reuse writer (same EXP dir + caveats convention)
    _write(data, body)
    return data


def _write(data: dict, body: str) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    stem = "pass46e_one_step_planner_diagnostic"
    (EXP / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str) + "\n",
                                      encoding="utf-8")
    head = ("# Pass 46E — Part E: one-step action-ranking diagnostic\n\n_READ-ONLY / "
            "LOCAL / DIAGNOSTIC. generic_progress_v0 one-step score rank under a "
            "fabricated hidden-state assumption; NOT a best-action or strength claim. "
            "No generation / promotion / upload / tick._\n\n")
    caveat = "## Caveats\n" + "".join(f"- {c}\n" for c in CAL.CAVEATS) + "\n"
    (EXP / f"{stem}.md").write_text(head + caveat + body + "\n", encoding="utf-8")


if __name__ == "__main__":
    out = run_planner()
    print(json.dumps({"n_frames_ranked": out["n_frames_ranked"],
                      "by_role_bucket": out["by_role_bucket"]}, indent=2))
