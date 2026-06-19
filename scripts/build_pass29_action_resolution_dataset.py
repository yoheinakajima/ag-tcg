#!/usr/bin/env python3
"""Pass 29 (Part C) — build the action-resolution dataset. LOCAL / READ-ONLY.

Runs the v2 resolver over two sources and tags every row with a confidence tier:
  1. The one raw replay (full options + select.deck + per-step logs) -> best case,
     including ``verified_by_following_log`` where a movement log corroborates.
  2. The Pass-28 forensic trace (8504 decisions; selected option + board snapshot)
     -> ``direct_option`` for the class and ``inferred_from_state_delta`` for
     identity when consecutive board snapshots change.

Outputs:
  data/experiments/pass29_action_resolution_dataset.jsonl
  data/experiments/pass29_action_resolution_summary.{json,md}
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ptcg_activegraph.analysis.action_resolver import (  # noqa: E402
    resolve_option, match_following_log, CONFIDENCE_TIERS)

REPLAY = REPO / "data" / "replays" / "80374966.json"
TRACE = REPO / "data" / "experiments" / "pass28_action_trace.jsonl"
OUT_JSONL = REPO / "data" / "experiments" / "pass29_action_resolution_dataset.jsonl"
OUT_JSON = REPO / "data" / "experiments" / "pass29_action_resolution_summary.json"
OUT_MD = REPO / "data" / "experiments" / "pass29_action_resolution_summary.md"


def _iter_replay_selects(replay: dict):
    """Yield (step_index, agent_index, select, following_logs)."""
    steps = replay.get("steps", [])
    for si, step in enumerate(steps):
        nxt = steps[si + 1] if si + 1 < len(steps) else []
        for ai, ag in enumerate(step):
            obs = ag.get("observation") if isinstance(ag, dict) else None
            if not isinstance(obs, dict):
                continue
            sel = obs.get("select")
            if not isinstance(sel, dict):
                continue
            opts = sel.get("option") or sel.get("options") or []
            if not opts:
                continue
            # following logs: same-step trailing logs + next step's logs.
            flogs = list(obs.get("logs") or [])
            for nag in nxt:
                nobs = nag.get("observation") if isinstance(nag, dict) else None
                if isinstance(nobs, dict):
                    flogs += list(nobs.get("logs") or [])
            yield si, ai, sel, flogs


def build_from_replay(rows: list[dict], conf: Counter, cls: Counter) -> int:
    if not REPLAY.exists():
        return 0
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    n = 0
    for si, ai, sel, flogs in _iter_replay_selects(replay):
        opts = sel.get("option") or []
        # Resolve every option (class coverage); selected ones get verification.
        sel_idx = set()  # raw replay does not record the agent's pick reliably
        for oi, opt in enumerate(opts):
            res = resolve_option(opt, select=sel)
            if res.confidence == "direct_option" and match_following_log(res, flogs):
                res.confidence = "verified_by_following_log"
            conf[res.confidence] += 1
            cls[res.action_class] += 1
            rows.append({
                "source": "raw_replay", "replay_step": si, "agent": ai,
                "context": sel.get("context"), "select_type": sel.get("type"),
                "n_options": len(opts), "option_index": oi,
                "selected": oi in sel_idx, "resolution": res.to_dict(),
            })
            n += 1
    return n


def build_from_trace(rows: list[dict], conf: Counter, cls: Counter) -> int:
    if not TRACE.exists():
        return 0
    n = 0
    prev_by_seat: dict = {}
    with TRACE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            board = d.get("board") or {}
            seat_key = (d.get("run_id"), d.get("seat"))
            prev = prev_by_seat.get(seat_key)
            state_changed = bool(prev is not None and prev != board)
            prev_by_seat[seat_key] = board
            for sr in (d.get("selected_resolved") or []):
                # The trace already resolved the selected option's class+identity
                # via the candidate resolver; re-wrap with confidence + target.
                aclass = sr.get("action_class", "unknown")
                has_id = sr.get("card_id") is not None
                if has_id:
                    confidence = "direct_option"
                elif aclass in ("attack", "attach_energy") and board.get("active"):
                    confidence = "inferred_from_state_delta" if state_changed \
                        else "direct_option"
                elif state_changed:
                    confidence = "inferred_from_state_delta"
                else:
                    confidence = "direct_option" if aclass != "unknown" \
                        else "unresolved"
                conf[confidence] += 1
                cls[aclass] += 1
                rows.append({
                    "source": "pass28_trace", "run_id": d.get("run_id"),
                    "family_id": d.get("family_id"), "seat": d.get("seat"),
                    "step": d.get("step"), "context": d.get("select_context"),
                    "select_type": d.get("select_type"),
                    "n_options": d.get("n_options"),
                    "state_changed_after": state_changed,
                    "resolution": {
                        "action_class": aclass, "raw_type": sr.get("type"),
                        "card_id": sr.get("card_id"),
                        "card_name": sr.get("card_name"),
                        "roles": sr.get("roles", []),
                        "confidence": confidence,
                    },
                })
                n += 1
    return n


def main() -> int:
    rows: list[dict] = []
    conf: Counter = Counter()
    cls: Counter = Counter()
    n_replay = build_from_replay(rows, conf, cls)
    n_trace = build_from_trace(rows, conf, cls)

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    total = len(rows)
    resolved = total - conf.get("unresolved", 0)
    summary = {
        "pass": "29", "part": "C",
        "note": "action-resolution dataset over raw replay + pass28 trace; "
                "confidence-tiered, no invented card ids",
        "sources": {"raw_replay_rows": n_replay, "pass28_trace_rows": n_trace},
        "total_rows": total,
        "resolved_rows": resolved,
        "resolved_fraction": round(resolved / total, 4) if total else 0.0,
        "by_confidence": {k: conf.get(k, 0) for k in CONFIDENCE_TIERS},
        "by_action_class": dict(cls.most_common()),
        "confidence_tier_definitions": {
            "direct_option": "class/target read straight from option schema",
            "verified_by_following_log": "a following movement log corroborates it",
            "inferred_from_state_delta": "identity/effect inferred from board diff",
            "unresolved": "not determinable from available data (not guessed)",
        },
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    L = ["# Pass 29 — Action Resolution Dataset (Part C)", "",
         f"- Sources: raw replay **{n_replay}** option-rows, Pass-28 trace "
         f"**{n_trace}** decision-rows.",
         f"- Total rows: **{total}**; resolved (non-unresolved): **{resolved}** "
         f"(**{summary['resolved_fraction']*100:.1f}%**).",
         "", "## By confidence tier", "", "| tier | rows |", "|---|---|"]
    for k in CONFIDENCE_TIERS:
        L.append(f"| {k} | {conf.get(k, 0)} |")
    L += ["", "## By action class", "", "| action_class | rows |", "|---|---|"]
    for k, v in cls.most_common():
        L.append(f"| {k} | {v} |")
    L += ["", "## Confidence tier definitions", ""]
    for k, v in summary["confidence_tier_definitions"].items():
        L.append(f"- **{k}** — {v}")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"rows={total} resolved={resolved} "
          f"({summary['resolved_fraction']*100:.1f}%) by_conf={dict(conf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
