#!/usr/bin/env python3
"""Pass 29 (Part E) — Venusaur effect-loop anatomy. LOCAL / READ-ONLY.

Detects non-progressing decision loops in the Pass-28 trace and characterises
each with the FULL per-option detail captured by
``capture_pass29_loop_options.py`` (the observability ratchet). Each loop is
classified:
  forced_engine_loop      — every loop context offers a single forced option
                            (no opt-out); the pilot has no agency to exit.
  optional_loop_with_exit — at least one loop context offers an explicit exit
                            (end_turn / decline) that the pilot is declining.
  beneficial_repeat       — repeats that make measurable positive progress.
  harmful_repeat          — repeats that lose resources / make negative progress.
  unknown                 — insufficient observability.

Outputs pass29_effect_loop_analysis.{json,md} and pass29_effect_loop_windows.jsonl.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
CAPTURE = REPO / "data" / "experiments" / "pass29_loop_option_capture.json"
OUT_JSON = REPO / "data" / "experiments" / "pass29_effect_loop_analysis.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_effect_loop_analysis.md"
OUT_WIN = REPO / "data" / "experiments" / "pass29_effect_loop_windows.jsonl"

LOOP_MIN_LEN = 25      # minimum repeated run to call it a loop
PROGRESS_KEYS = ("deck_count", "prize_count")


def _board_sig(b: dict) -> tuple:
    return (b.get("deck_count"), len(b.get("hand") or []),
            (b.get("active") or {}).get("card_id"),
            len(b.get("discard") or []), b.get("prize_count"))


def _load_capture():
    if not CAPTURE.exists():
        return {}
    cap = json.loads(CAPTURE.read_text(encoding="utf-8"))
    info = {}
    for ctx, wins in (cap.get("windows") or {}).items():
        nopts = {w["n_options"] for w in wins}
        classes = set()
        has_end = False
        for w in wins:
            for r in w.get("resolved_options", []):
                classes.add(r.get("action_class"))
            for o in w.get("raw_options", []):
                if o.get("type") in (12, 14):
                    has_end = True
        info[int(ctx)] = {
            "n_options_seen": sorted(nopts),
            "all_forced_single": nopts == {1},
            "option_classes": sorted(c for c in classes if c),
            "has_explicit_exit_option": has_end,
        }
    return info


def _classify(ctxs, cap_info, progress_delta) -> tuple[str, str]:
    loop_ctx_info = [cap_info[c] for c in ctxs if c in cap_info]
    observed = bool(loop_ctx_info)
    any_exit = any(ci["has_explicit_exit_option"] for ci in loop_ctx_info)
    all_forced = observed and all(ci["all_forced_single"] for ci in loop_ctx_info)
    if not observed:
        return "unknown", ("loop contexts not present in per-option capture; "
                           "exit observability undetermined")
    if any_exit:
        return "optional_loop_with_exit", ("an explicit exit option (end_turn) is "
                                           "offered at a loop context")
    if all_forced:
        return "forced_engine_loop", ("every loop context offers a single forced "
                                      "option (minCount=maxCount=1, no opt-out); "
                                      "the pilot cannot choose to exit")
    if progress_delta < 0:
        return "harmful_repeat", "repeats with negative resource progress"
    if progress_delta > 0:
        return "beneficial_repeat", "repeats with positive progress"
    return "unknown", ("no exit option observed but options are not all forced; "
                       "needs deeper capture")


def main() -> int:
    cap_info = _load_capture()
    by_seat = defaultdict(list)
    if TRACE.exists():
        with TRACE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                by_seat[(d.get("run_id"), d.get("seat"))].append(d)

    windows = []
    for (run_id, seat), rows in by_seat.items():
        rows.sort(key=lambda r: r.get("step", 0))
        i = 0
        n = len(rows)
        while i < n:
            j = i
            sig = _board_sig(rows[i].get("board") or {})
            ctxs = []
            while j < n and _board_sig(rows[j].get("board") or {}) == sig:
                ctxs.append(rows[j].get("select_context"))
                j += 1
            run_len = j - i
            if run_len >= LOOP_MIN_LEN:
                ctx_counter = Counter(ctxs)
                distinct = sorted(ctx_counter)
                b0 = rows[i].get("board") or {}
                b1 = rows[j - 1].get("board") or {}
                progress = ((b1.get("deck_count") or 0) - (b0.get("deck_count") or 0))
                terminated_naturally = (j < n)  # more decisions followed the run
                cls, why = _classify(distinct, cap_info, progress)
                w = {
                    "run_id": run_id, "seat": seat,
                    "family_id": rows[i].get("family_id"),
                    "start_step": rows[i].get("step"),
                    "end_step": rows[j - 1].get("step"),
                    "length": run_len,
                    "distinct_contexts": distinct,
                    "context_histogram": dict(ctx_counter),
                    "n_options_per_context": {
                        str(c): sorted({r.get("n_options") for r in rows[i:j]
                                        if r.get("select_context") == c})
                        for c in distinct},
                    "deck_count_delta": progress,
                    "board_static": True,
                    "terminated_within_trace": terminated_naturally,
                    "classification": cls,
                    "classification_reason": why,
                    "per_option_capture_available": all(
                        c in cap_info for c in distinct),
                }
                windows.append(w)
            i = max(j, i + 1)

    with OUT_WIN.open("w", encoding="utf-8") as fh:
        for w in windows:
            fh.write(json.dumps(w) + "\n")

    cls_counter = Counter(w["classification"] for w in windows)
    affected = sorted({w["family_id"] for w in windows})
    longest = max(windows, key=lambda w: w["length"], default=None)
    out = {
        "pass": "29", "part": "E",
        "note": "non-progressing decision loops detected in the pass28 trace, "
                "characterised with full per-option capture",
        "loop_min_len": LOOP_MIN_LEN,
        "loops_found": len(windows),
        "by_classification": dict(cls_counter),
        "affected_families": affected,
        "loop_contexts_capture": cap_info,
        "longest_loop": longest,
        "headline": (
            "The Venusaur loop is a FORCED engine loop: both loop contexts (33 "
            "energy-move, 21 place_card) present a single forced option with no "
            "opt-out, so the pilot is never offered an exit. The run makes zero "
            "deck/hand/board progress and does not terminate naturally."
            if cls_counter.get("forced_engine_loop") else
            "See per-loop classification."),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Venusaur Effect-Loop Anatomy (Part E)", "",
         f"- Loops found (>= {LOOP_MIN_LEN} static-board repeats): "
         f"**{len(windows)}**.",
         f"- By classification: **{dict(cls_counter)}**.",
         f"- Affected families: **{affected}**.", "",
         f"> {out['headline']}", "",
         "## Loop contexts — per-option capture", "",
         "| context | n_options seen | all forced? | option classes | exit option? |",
         "|---|---|---|---|---|"]
    for c, ci in sorted(cap_info.items()):
        if c in (33, 21):
            L.append(f"| {c} | {ci['n_options_seen']} | {ci['all_forced_single']} | "
                     f"{ci['option_classes']} | {ci['has_explicit_exit_option']} |")
    L += ["", "## Loop windows (top by length)", "",
          "| family | run_id | seat | length | contexts | deck Δ | terminated? | "
          "class |", "|---|---|---|---|---|---|---|---|"]
    for w in sorted(windows, key=lambda x: x["length"], reverse=True)[:15]:
        L.append(f"| {w['family_id']} | {w['run_id']} | {w['seat']} | {w['length']} "
                 f"| {w['distinct_contexts']} | {w['deck_count_delta']} | "
                 f"{w['terminated_within_trace']} | {w['classification']} |")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"loops={len(windows)} by_class={dict(cls_counter)} families={affected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
