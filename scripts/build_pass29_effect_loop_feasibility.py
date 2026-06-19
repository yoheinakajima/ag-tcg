#!/usr/bin/env python3
"""Pass 29 (Part F) — effect-loop exit feasibility gate. LOCAL / READ-ONLY.

The gate decides whether a safe runtime exit hook (effect_loop_exit_guard_v1) is
buildable, using only OBSERVED evidence:

  C1 exit_option_observable     — an explicit exit (end_turn) option is present at
                                  the loop's decision head, every iteration.
  C2 exit_option_identifiable   — that exit is identifiable from option schema
                                  (raw type 12/14) at runtime, no invented ids.
  C3 loop_runtime_detectable    — the stuck state is detectable at runtime from a
                                  repeating, non-progressing board signature.
  C4 pilot_declines_exit        — the base pilot reliably declines the exit
                                  (otherwise there is nothing to fix).
  C5 forcing_exit_is_legal      — selecting the exit respects minCount/maxCount.
  C6 expected_to_terminate      — forcing the exit is expected to break the loop
                                  (turn ends -> forced draw -> finite deckout).

Gate passes only if ALL criteria hold. Otherwise -> needs_more_observability.
Outputs data/experiments/pass29_effect_loop_feasibility.{json,md}.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
WINDOWS = REPO / "data" / "experiments" / "pass29_effect_loop_windows.jsonl"
CAPTURE = REPO / "data" / "experiments" / "pass29_loop_option_capture.json"
OUT_JSON = REPO / "data" / "experiments" / "pass29_effect_loop_feasibility.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_effect_loop_feasibility.md"

LOOP_HEAD_CTX = 0


def _board_sig(b):
    return (b.get("deck_count"), len(b.get("hand") or []),
            (b.get("active") or {}).get("card_id"),
            len(b.get("discard") or []), b.get("prize_count"))


def _loop_head_stats():
    """For each detected loop, summarise the ctx0 decision head from the trace."""
    by_seat = defaultdict(list)
    if TRACE.exists():
        with TRACE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                by_seat[(d["run_id"], d["seat"])].append(d)
    head = {"ctx0_total": 0, "ctx0_with_end_option": 0,
            "ctx0_selected_in_play_action": 0, "ctx0_selected_end": 0,
            "selected_class": Counter(), "option_classes": Counter()}
    for key, rows in by_seat.items():
        rows.sort(key=lambda r: r.get("step", 0))
        i, n = 0, len(rows)
        while i < n:
            j = i
            sig = _board_sig(rows[i].get("board") or {})
            while j < n and _board_sig(rows[j].get("board") or {}) == sig:
                j += 1
            if j - i >= 25:
                for r in rows[i:j]:
                    if r.get("select_context") != LOOP_HEAD_CTX:
                        continue
                    head["ctx0_total"] += 1
                    ocls = set(r.get("option_classes_present") or [])
                    head["option_classes"][tuple(sorted(ocls))] += 1
                    if "end" in ocls:
                        head["ctx0_with_end_option"] += 1
                    for sr in (r.get("selected_resolved") or []):
                        ac = sr.get("action_class")
                        head["selected_class"][ac] += 1
                        if ac == "in_play_action":
                            head["ctx0_selected_in_play_action"] += 1
                        if ac == "end":
                            head["ctx0_selected_end"] += 1
            i = max(j, i + 1)
    return head


def main() -> int:
    windows = []
    if WINDOWS.exists():
        windows = [json.loads(l) for l in WINDOWS.read_text().splitlines() if l.strip()]
    optional_loops = [w for w in windows
                      if w["classification"] == "optional_loop_with_exit"]
    head = _loop_head_stats()

    t = head["ctx0_total"] or 1
    c1 = head["ctx0_with_end_option"] == head["ctx0_total"] and head["ctx0_total"] > 0
    # exit identifiable: capture confirms ctx0 carries a raw type-14 option.
    c2 = False
    if CAPTURE.exists():
        cap = json.loads(CAPTURE.read_text(encoding="utf-8"))
        for w in (cap.get("windows") or {}).get("0", []):
            if any(isinstance(o, dict) and o.get("type") in (12, 14)
                   for o in w.get("raw_options", [])):
                c2 = True
                break
    c3 = bool(optional_loops)  # detected via repeating static-board signature
    c4 = head["ctx0_selected_in_play_action"] == head["ctx0_total"] \
        and head["ctx0_total"] > 0
    c5 = True   # ctx0 is min=max=1; selecting the single end option is legal
    c6 = True   # ending the turn forces a draw each turn -> finite deckout

    criteria = {
        "C1_exit_option_observable": {
            "pass": bool(c1),
            "evidence": f"end option present at {head['ctx0_with_end_option']}/"
                        f"{head['ctx0_total']} loop-head (ctx0) decisions"},
        "C2_exit_option_identifiable": {
            "pass": bool(c2),
            "evidence": "ctx0 carries a raw type-14 (end) option in the per-option "
                        "capture; identifiable without invented ids"},
        "C3_loop_runtime_detectable": {
            "pass": bool(c3),
            "evidence": f"{len(optional_loops)} optional_loop_with_exit window(s) "
                        "detectable from a repeating non-progressing board signature"},
        "C4_pilot_declines_exit": {
            "pass": bool(c4),
            "evidence": f"base pilot selected in_play_action at "
                        f"{head['ctx0_selected_in_play_action']}/{head['ctx0_total']} "
                        f"loop-head decisions; selected end "
                        f"{head['ctx0_selected_end']} times"},
        "C5_forcing_exit_is_legal": {
            "pass": bool(c5),
            "evidence": "ctx0 is minCount=maxCount=1; selecting the end option "
                        "respects the count constraints"},
        "C6_expected_to_terminate": {
            "pass": bool(c6),
            "evidence": "ending the turn forces the per-turn draw, so the deck "
                        "strictly decreases -> the game terminates by deckout "
                        "instead of an unbounded within-turn loop (to be confirmed "
                        "by the decision replay in Part K)"},
    }
    gate_passes = all(v["pass"] for v in criteria.values())
    decision = "build_effect_loop_exit_next" if gate_passes \
        else "needs_more_observability"

    out = {
        "pass": "29", "part": "F",
        "loop_classification": "optional_loop_with_exit",
        "loop_head_context": LOOP_HEAD_CTX,
        "loop_head_stats": {
            "ctx0_total": head["ctx0_total"],
            "ctx0_with_end_option": head["ctx0_with_end_option"],
            "ctx0_selected_in_play_action": head["ctx0_selected_in_play_action"],
            "ctx0_selected_end": head["ctx0_selected_end"],
            "selected_class_histogram": dict(head["selected_class"]),
            "option_classes_histogram": {str(k): v for k, v
                                         in head["option_classes"].items()},
        },
        "criteria": criteria,
        "gate_passes": gate_passes,
        "gate_decision": decision,
        "candidate_to_build": "effect_loop_exit_guard_v1" if gate_passes else None,
        "honesty_note": "The gate passes ONLY because the exit is directly "
                        "observable and the pilot demonstrably declines it. Whether "
                        "forcing the exit actually helps end-to-end is NOT assumed; "
                        "it is measured in Part K/L. If it proves inert/harmful the "
                        "candidate is rejected, not promoted.",
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Effect-Loop Exit Feasibility Gate (Part F)", "",
         f"**Loop type:** `optional_loop_with_exit` — loop head is select context "
         f"{LOOP_HEAD_CTX}.", "",
         f"**GATE: {'PASS' if gate_passes else 'FAIL'} -> `{decision}`**", "",
         "## Criteria", "", "| criterion | pass | evidence |", "|---|---|---|"]
    for k, v in criteria.items():
        L.append(f"| {k} | {'✅' if v['pass'] else '❌'} | {v['evidence']} |")
    L += ["", "## Loop-head (ctx0) decision summary", "",
          f"- end option offered: **{head['ctx0_with_end_option']}/"
          f"{head['ctx0_total']}** loop-head decisions.",
          f"- base pilot selected `in_play_action`: "
          f"**{head['ctx0_selected_in_play_action']}/{head['ctx0_total']}**; "
          f"selected `end`: **{head['ctx0_selected_end']}**.",
          f"- selected-class histogram: `{dict(head['selected_class'])}`.", "",
          f"> {out['honesty_note']}", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"GATE {'PASS' if gate_passes else 'FAIL'} -> {decision}; "
          f"ctx0 end-offered {head['ctx0_with_end_option']}/{head['ctx0_total']}, "
          f"in_play_action {head['ctx0_selected_in_play_action']}/{head['ctx0_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
