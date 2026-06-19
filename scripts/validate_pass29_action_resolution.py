#!/usr/bin/env python3
"""Pass 29 (Part D) — validate the resolver against state transitions / logs.

We do NOT trust the resolver blindly. For every resolved row we ask: is there
independent corroboration (a movement log, a board-state change, or an internal
schema-consistency check), does it contradict the evidence, or is it simply
unverifiable from the data we have? Reported honestly as corroborated /
contradicted / unverifiable — never inflated.

Outputs data/experiments/pass29_action_resolution_validation.{json,md}.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "data" / "experiments" / "pass29_action_resolution_dataset.jsonl"
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
OUT_JSON = REPO / "data" / "experiments" / "pass29_action_resolution_validation.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_action_resolution_validation.md"


def _trace_flag_index() -> dict:
    """Map (run_id, seat, step) -> option-presence flags for cross-checking."""
    idx = {}
    if not TRACE.exists():
        return idx
    with TRACE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            idx[(d.get("run_id"), d.get("seat"), d.get("step"))] = {
                "attack": d.get("attack_option_present"),
                "attach": d.get("attach_option_present"),
                "play": d.get("play_from_hand_present"),
                "classes": set(d.get("option_classes_present") or []),
            }
    return idx


def main() -> int:
    flags = _trace_flag_index()
    verdict = Counter()
    by_tier = {}
    contradictions: list[dict] = []

    with DATASET.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            res = r["resolution"]
            tier = res.get("confidence", "unresolved")
            bt = by_tier.setdefault(tier, Counter())
            aclass = res.get("action_class")

            if tier == "unresolved":
                verdict["unverifiable"] += 1
                bt["unverifiable"] += 1
                continue

            # verified_by_following_log is corroborated by construction (a log
            # transition matched during dataset build).
            if tier == "verified_by_following_log":
                verdict["corroborated"] += 1
                bt["corroborated"] += 1
                continue

            if r["source"] == "pass28_trace":
                key = (r.get("run_id"), r.get("seat"), r.get("step"))
                f = flags.get(key)
                if f is None:
                    verdict["unverifiable"] += 1
                    bt["unverifiable"] += 1
                    continue
                # Schema-consistency: resolved class must be among the classes the
                # trace recorded as present at that decision.
                if aclass in f["classes"]:
                    if tier == "inferred_from_state_delta" \
                            and not r.get("state_changed_after"):
                        verdict["contradicted"] += 1
                        bt["contradicted"] += 1
                        if len(contradictions) < 25:
                            contradictions.append({**key_to_dict(key),
                                                   "reason": "state-delta tier but "
                                                   "no board change",
                                                   "action_class": aclass})
                    else:
                        verdict["corroborated"] += 1
                        bt["corroborated"] += 1
                else:
                    verdict["contradicted"] += 1
                    bt["contradicted"] += 1
                    if len(contradictions) < 25:
                        contradictions.append({**key_to_dict(key),
                                               "reason": f"class {aclass} not in "
                                               f"recorded {sorted(f['classes'])}"})
            else:
                # raw_replay direct_option without a matching log: schema-only,
                # honestly unverifiable beyond the option's own fields.
                verdict["unverifiable"] += 1
                bt["unverifiable"] += 1

    total = sum(verdict.values())
    checkable = verdict["corroborated"] + verdict["contradicted"]
    out = {
        "pass": "29", "part": "D",
        "note": "resolver validated against logs, board-state deltas, and "
                "schema-consistency; reported honestly",
        "total_rows": total,
        "verdicts": dict(verdict),
        "checkable_rows": checkable,
        "agreement_among_checkable": round(
            verdict["corroborated"] / checkable, 4) if checkable else None,
        "by_tier": {k: dict(v) for k, v in by_tier.items()},
        "contradiction_examples": contradictions,
        "caveat": "raw-replay schema-only rows and unresolved rows are counted "
                  "as unverifiable, not as agreement, to avoid inflation.",
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Action Resolution Validation (Part D)", "",
         f"- Total rows checked: **{total}**.",
         f"- Corroborated: **{verdict['corroborated']}**; "
         f"contradicted: **{verdict['contradicted']}**; "
         f"unverifiable: **{verdict['unverifiable']}**.",
         f"- Agreement among checkable rows: "
         f"**{(out['agreement_among_checkable'] or 0)*100:.2f}%** "
         f"({checkable} checkable).", "",
         "## Verdict by confidence tier", "",
         "| tier | corroborated | contradicted | unverifiable |", "|---|---|---|---|"]
    for tier, c in by_tier.items():
        L.append(f"| {tier} | {c.get('corroborated',0)} | "
                 f"{c.get('contradicted',0)} | {c.get('unverifiable',0)} |")
    L += ["", f"> {out['caveat']}", ""]
    if contradictions:
        L += ["## Contradiction examples", ""]
        for c in contradictions[:15]:
            L.append(f"- {json.dumps(c)}")
        L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"verdicts={dict(verdict)} agreement_checkable="
          f"{out['agreement_among_checkable']}")
    return 0


def key_to_dict(key):
    return {"run_id": key[0], "seat": key[1], "step": key[2]}


if __name__ == "__main__":
    raise SystemExit(main())
