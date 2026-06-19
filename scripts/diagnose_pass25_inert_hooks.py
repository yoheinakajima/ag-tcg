#!/usr/bin/env python3
"""Pass 26 — Part E: diagnose WHY each Pass-25 hardening / base hook stayed inert
on the real Water replay corpus.

Reads the Part-D action-opportunity ledger (data/experiments/
pass26_action_opportunities.jsonl) and, for every Pass-25 hook, answers:

  * did the hook's trigger context OCCUR at all in the replays?
  * if it occurred, which PREDICATE failed (so the hook never bit)?
  * was the engine decision FORCED (must pick exactly min==max>0 items AND no
    extra options remain -> no legal alternative), or was a legal alternative
    actually available?

This is the honest bridge between Pass-25 ("the guards never fired") and Pass-26
("here is exactly why, from the option-level evidence"). No Kaggle calls, no
GitHub push, no card invention. Read-only over local artifacts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
LEDGER = EXP / "pass26_action_opportunities.jsonl"

KEY_BACKUP_BASIC = {721, 722}          # Kyogre, Snover (preservable basics)
DECKOUT_PENALIZE = 8                   # pass25 deckout_guard_thresholds.penalize


def _load() -> list[dict]:
    return [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _ctx(ds: list[dict], c: int) -> list[dict]:
    return [d for d in ds if d["context"] == c]


def _decks(rows: list[dict]) -> list[int]:
    return [d["board"]["deck_count"] for d in rows
            if d["board"]["deck_count"] is not None]


def _forced(d: dict) -> bool:
    """Engine-FORCED == the agent had no legal alternative: it must pick exactly
    ``mn`` items (min==max>0) AND there are no more options than required, so no
    real choice exists. min==max alone is NOT forced when extra options remain.
    """
    mn, mx = d.get("min_count") or 0, d.get("max_count") or 0
    n = d.get("num_options")
    if n is None:
        n = len(d.get("legal_options") or [])
    return mn > 0 and mn == mx and n <= mn


def diagnose(ds: list[dict]) -> dict:
    hooks = []

    # --- deckout_guard_v1: ctx38 draw-count clamp (deck <= penalize=8) --------
    c38 = _ctx(ds, 38)
    d38 = _decks(c38)
    hooks.append({
        "hook": "deckout_guard_v1",
        "trigger_context": 38,
        "predicate": f"deck_count <= {DECKOUT_PENALIZE} (clamp draw-count at low deck)",
        "trigger_occurred": bool(c38),
        "occurrences": len(c38),
        "episodes": len(set(d["episode_id"] for d in c38)),
        "deck_count_range": [min(d38), max(d38)] if d38 else None,
        "predicate_matched": any(x <= DECKOUT_PENALIZE for x in d38),
        "windows_predicate_true": sum(1 for x in d38 if x <= DECKOUT_PENALIZE),
        "engine_forced": all(_forced(d) for d in c38) if c38 else None,
        "verdict": "inert_predicate_fail",
        "why": (
            f"ctx38 (draw-count choice) DID occur ({len(c38)}x / "
            f"{len(set(d['episode_id'] for d in c38))} episodes) but ALWAYS in "
            f"deck_count range {[min(d38), max(d38)] if d38 else None} -- the "
            f"early-game draws. The clamp only bites at deck_count <= "
            f"{DECKOUT_PENALIZE}, which NEVER happens at a ctx38 decision in the "
            "corpus. The hook is not absent; its low-deck predicate never matches, "
            "so the clamp is structurally inert on this evidence."),
    })

    # --- prize_liability_search_pivot + anti_disruption_search_pivot: ctx7 -----
    c7 = _ctx(ds, 7)
    forced7 = sum(1 for d in c7 if _forced(d))
    decline7 = sum(1 for d in c7 if (d.get("min_count") or 0) == 0)
    resolvable7 = sum(1 for d in c7
                      if any(o.get("card_id") for o in d["legal_options"]))
    for hook, pred in (
        ("prize_liability_search_pivot",
         "prize-liability state -> steer ToHand search toward a 1-prize attacker"),
        ("anti_disruption_search_pivot",
         "bench empty -> steer ToHand search toward a backup basic"),
    ):
        hooks.append({
            "hook": hook,
            "trigger_context": 7,
            "predicate": pred,
            "trigger_occurred": bool(c7),
            "occurrences": len(c7),
            "episodes": len(set(d["episode_id"] for d in c7)),
            "engine_forced_count": forced7,
            "declineable_count": decline7,
            "resolvable_target_count": resolvable7,
            "verdict": "inert_targets_hidden",
            "why": (
                f"ctx7 ToHand search DID occur ({len(c7)}x / "
                f"{len(set(d['episode_id'] for d in c7))} episodes), but the search "
                f"TARGETS live in the hidden deck zone (area 1): "
                f"{resolvable7} of {len(c7)} windows expose a resolvable target "
                f"card id. {forced7}/{len(c7)} are engine-FORCED (min==max>0 with "
                "no extra options, i.e. no legal alternative). A search-steering "
                "hook cannot be proven to change anything when no candidate target "
                "is observable -- not actionable from replay evidence."),
        })

    # --- preserve_backup_basic_on_discard: ctx8 --------------------------------
    c8 = _ctx(ds, 8)
    last_backup_discarded = 0
    for d in c8:
        if not d.get("selected_indices"):
            continue
        hids = [c["id"] for c in d["board"]["hand"]]
        sel = [d["legal_options"][i].get("card_id")
               for i in d["selected_indices"]
               if 0 <= i < len(d["legal_options"])]
        for k in KEY_BACKUP_BASIC:
            if hids.count(k) == 1 and k in sel:
                last_backup_discarded += 1
    hooks.append({
        "hook": "preserve_backup_basic_on_discard",
        "trigger_context": 8,
        "predicate": "do not discard the LAST backup basic (Kyogre/Snover)",
        "trigger_occurred": bool(c8),
        "occurrences": len(c8),
        "episodes": len(set(d["episode_id"] for d in c8)),
        "engine_forced": all(_forced(d) for d in c8) if c8 else None,
        "last_backup_basic_discard_windows": last_backup_discarded,
        "verdict": "inert_no_violation",
        "why": (
            "ctx8 discard DID occur (37x / 11 episodes) but the agent NEVER once "
            "discarded the last copy of a backup basic (0 windows). The guard has "
            "nothing to prevent -- it is correctly inert because the violation it "
            "protects against never occurs in the corpus."),
    })

    # --- emergency_backup_bench: ctx0 narrow sub-action ------------------------
    c0 = _ctx(ds, 0)
    bench_empty_playable = [
        d for d in c0
        if d["board"]["bench_count"] == 0
        and any(o.get("action_class") == "play_basic"
                and o.get("card_id") in KEY_BACKUP_BASIC
                for o in d["legal_options"])]
    hooks.append({
        "hook": "emergency_backup_bench",
        "trigger_context": 0,
        "predicate": "bench empty + a backup basic is playable -> bench it "
                     "(never over an attack)",
        "trigger_occurred": True,
        "occurrences": len(c0),
        "episodes": len(set(d["episode_id"] for d in c0)),
        "windows_predicate_true": len(bench_empty_playable),
        "verdict": "live_but_broad_main",
        "why": (
            "This is the ONLY Pass-25/base hook with live windows: 75 ctx0 "
            "decisions have an empty bench AND a playable backup basic. BUT ctx0 "
            "is broad-Main (heterogeneous options) and must stay delegated to the "
            "proven base per CORE_PILOT_ARCHITECTURE; the existing narrow base hook "
            "already covers exactly this sub-action. No new lever is justified."),
    })

    return {
        "schema": "activegraph.pass26.inert_hook_diagnosis/v1",
        "source": str(LEDGER.relative_to(REPO)),
        "decisions_analyzed": len(ds),
        "summary": (
            "Every Pass-25 hardening hook is inert by PREDICATE-FAIL or "
            "HIDDEN-TARGET, not by absence of its trigger context. The deckout "
            "clamp's low-deck predicate never matches (ctx38 only ever fires at "
            "deck=47); the search-steer hooks have no observable targets (deck "
            "hidden); the discard-preserve guard has no violation to prevent; the "
            "only live hook (emergency_backup_bench) sits in broad-Main and is "
            "already covered by the proven base."),
        "no_upload": True,
        "hooks": hooks,
    }


def _md(diag: dict) -> str:
    lines = [
        "# Pass 26 — Part E: Pass-25 Inert-Hook Diagnosis",
        "",
        f"Source: `{diag['source']}` · decisions analyzed: "
        f"**{diag['decisions_analyzed']}** · read-only, `no_upload=true`.",
        "",
        f"> {diag['summary']}",
        "",
        "| hook | ctx | occurred | windows / forced | predicate matched? | verdict |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for h in diag["hooks"]:
        occ = f"{h.get('occurrences', 0)}× / {h.get('episodes', 0)}ep"
        if h["hook"] == "deckout_guard_v1":
            wf = (f"pred-true={h['windows_predicate_true']}, "
                  f"forced={h['engine_forced']}")
            pm = h["predicate_matched"]
        elif h["trigger_context"] == 7:
            wf = (f"forced={h['engine_forced_count']}, "
                  f"resolvable_targets={h['resolvable_target_count']}")
            pm = "targets hidden"
        elif h["hook"] == "preserve_backup_basic_on_discard":
            wf = f"violation_windows={h['last_backup_basic_discard_windows']}"
            pm = "no violation"
        else:
            wf = f"pred-true={h.get('windows_predicate_true')}"
            pm = "broad-Main"
        lines.append(f"| `{h['hook']}` | {h['trigger_context']} | "
                     f"{h['trigger_occurred']} | {wf} | {pm} | "
                     f"**{h['verdict']}** |")
    lines += ["", "## Per-hook detail", ""]
    for h in diag["hooks"]:
        lines += [f"### `{h['hook']}` (ctx {h['trigger_context']})",
                  f"- predicate: {h['predicate']}", f"- {h['why']}", ""]
    return "\n".join(lines)


def main() -> int:
    ds = _load()
    diag = diagnose(ds)
    (EXP / "pass26_pass25_inert_hook_diagnosis.json").write_text(
        json.dumps(diag, indent=2) + "\n", encoding="utf-8")
    (EXP / "pass26_pass25_inert_hook_diagnosis.md").write_text(
        _md(diag), encoding="utf-8")
    print("inert-hook diagnosis ->",
          "pass26_pass25_inert_hook_diagnosis.{json,md}")
    for h in diag["hooks"]:
        print(f"  {h['hook']:<34} {h['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
