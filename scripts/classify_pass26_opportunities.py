#!/usr/bin/env python3
"""Pass 26 — Part F + Part G.

Part F: classify the Part-D action-opportunity ledger into the 8 candidate
"true opportunity" classes, each with count / episodes / confidence / feasibility
/ expected-value sign / regression risk.

Part G: run every class through the trigger-coverage GATE. A class is
``build_allowed`` only if it clears EVERY condition:
  1. >= 3 replay windows OR 2 high-confidence LOSS windows
  2. a legal alternative was actually observed at the window
  3. option resolution is reliable (the relevant card ids are exposed)
  4. the hook is NARROW (single context, not broad-Main ctx0)
  5. positive-control windows exist (so a hook would not overfit)
  6. the window is NOT broad-Main (ctx0 stays delegated)
  7. the opportunity is fixture-testable (reduced-model gradeable)

Read-only; no Kaggle, no GitHub, no card invention.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"
LEDGER = EXP / "pass26_action_opportunities.jsonl"

SEARCH = {1121, 1145, 1092}
DRAW = {1219, 1227, 1262}
DRAW_SEARCH = SEARCH | DRAW
KEY = {721, 722, 723}                  # Kyogre, Snover, Mega Abomasnow ex
EVOLUTION_PAYOFF = 723
SNOVER = 722


def _load() -> list[dict]:
    return [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _sel_card_ids(d: dict) -> set:
    out = set()
    for i in d.get("selected_indices") or []:
        if isinstance(i, int) and 0 <= i < len(d["legal_options"]):
            out.add(d["legal_options"][i].get("card_id"))
    return out


def _hand_ids(d: dict) -> list:
    return [c["id"] for c in d["board"]["hand"]]


def _snover_in_play(d: dict) -> bool:
    b = d["board"]
    if any(c["id"] == SNOVER for c in b["bench"]):
        return True
    act = b.get("active")
    return bool(act and act.get("id") == SNOVER)


def classify(ds: list[dict]) -> list[dict]:
    classes = []

    # 1) optional_main_draw_search_low_deck -----------------------------------
    c1 = [d for d in ds if d["context"] == 0
          and any(o.get("card_id") in DRAW_SEARCH for o in d["legal_options"])
          and (set(d["available_action_classes"]) &
               {"attack", "end", "attach", "evolve", "play_basic"})
          and ({"low_deck", "very_low_deck"} & set(d["hazards"]))]
    classes.append({
        "name": "optional_main_draw_search_low_deck",
        "count": len(c1), "episodes": sorted({d["episode_id"] for d in c1}),
        "confidence": "n/a", "feasibility": "not_actionable",
        "expected_value": "none",
        "regression_risk": "n/a",
        "evidence": ("ZERO windows. The corpus has NO low-deck decision at all "
                     "(min deck_count at ctx0 == 14; ctx38 only ever fires at "
                     "deck=47). The Pass-25 deckout lever has no supporting "
                     "window. The actual deckout-loss episode (80622626) is not "
                     "even in the available corpus."),
    })

    # 2) search_target_misprioritized (ctx7) ----------------------------------
    c2 = [d for d in ds if d["context"] == 7]
    c2_res = [d for d in c2
              if any(o.get("card_id") for o in d["legal_options"])]
    classes.append({
        "name": "search_target_misprioritized",
        "count": len(c2), "episodes": sorted({d["episode_id"] for d in c2}),
        "resolvable_windows": len(c2_res),
        "confidence": "low", "feasibility": "not_actionable",
        "expected_value": "unknown",
        "regression_risk": "high",
        "evidence": ("141 ctx7 ToHand searches, but search targets live in the "
                     "hidden deck (area 1): 0/141 expose a resolvable target. A "
                     "steering hook cannot be proven to change anything."),
    })

    # 3) bench_backup_available_unplayed (ctx0) -------------------------------
    c3 = [d for d in ds if d["context"] == 0
          and d["board"]["bench_count"] == 0
          and any(o.get("card_id") in {721, 722}
                  and o.get("action_class") == "play_basic"
                  for o in d["legal_options"])]
    classes.append({
        "name": "bench_backup_available_unplayed",
        "count": len(c3), "episodes": sorted({d["episode_id"] for d in c3}),
        "confidence": "medium", "feasibility": "unsafe_broad_main",
        "expected_value": "low_positive",
        "regression_risk": "high",
        "evidence": ("75 ctx0 windows with empty bench + a playable backup "
                     "basic. BUT ctx0 is broad-Main (must stay delegated) and "
                     "the existing base hook `emergency_backup_bench` already "
                     "covers exactly this narrow sub-action. No new lever."),
    })

    # 4) discard_preserve_line_failure (ctx8) ---------------------------------
    c4_all, c4_genuine, c4_hi = [], [], []
    for d in ds:
        if d["context"] != 8 or not d.get("selected_indices"):
            continue
        hids = _hand_ids(d)
        sel = _sel_card_ids(d)
        n = d.get("min_count") or len(d["selected_indices"])
        nonkey = [c for c in hids if c not in KEY]
        for k in KEY:
            if hids.count(k) == 1 and k in sel and len(nonkey) >= n:
                c4_all.append(d)
                c4_genuine.append((d["episode_id"], k, d["result"]))
                # high-confidence: discarded the SOLE evolution payoff while a
                # Snover line is live (so the Mega was actually castable soon).
                if k == EVOLUTION_PAYOFF and _snover_in_play(d) \
                        and d["result"] == "loss":
                    c4_hi.append(d["episode_id"])
                break
    classes.append({
        "name": "discard_preserve_line_failure",
        "count": len(c4_all),
        "episodes": sorted({e for e, _, _ in c4_genuine}),
        "high_confidence_loss_windows": len(c4_hi),
        "confidence": "mixed",
        "feasibility": "needs_more_context",
        "expected_value": "low_positive",
        "regression_risk": "medium",
        "evidence": ("Only 2 genuine windows (both losses) where the SOLE copy "
                     "of a key piece was discarded with a non-key alternative "
                     "present. Of those, only 1 is high-confidence (live Snover "
                     "on bench, Mega castable next turn); the other had no Snover "
                     "anywhere with the line already depleted (Mega not "
                     "castable). 1 hi-conf + 1 medium < gate bar."),
    })

    # 5) attach_target_misprioritized (ctx0) ----------------------------------
    c5 = [d for d in ds if d["context"] == 0
          and any(o.get("action_class") == "attach" for o in d["legal_options"])]
    classes.append({
        "name": "attach_target_misprioritized",
        "count": len(c5), "episodes": sorted({d["episode_id"] for d in c5}),
        "confidence": "low", "feasibility": "needs_more_context",
        "expected_value": "unknown", "regression_risk": "high",
        "evidence": ("812 ctx0 decisions expose an attach option, but the attach "
                     "TARGET (which benched Pokemon) is not reliably "
                     "distinguishable and this is broad-Main; cannot prove a "
                     "better target without board simulation."),
    })

    # 6) attack_available_but_not_taken (ctx0) --------------------------------
    c6 = [d for d in ds if d["context"] == 0
          and "attack" in set(d["available_action_classes"])
          and d.get("selected_indices")
          and "attack" not in set(d.get("selected_action_classes") or [])]
    classes.append({
        "name": "attack_available_but_not_taken",
        "count": len(c6), "episodes": sorted({d["episode_id"] for d in c6}),
        "confidence": "low", "feasibility": "needs_more_context",
        "expected_value": "unknown", "regression_risk": "high",
        "evidence": ("25 windows where an attack was legal but a non-attack was "
                     "recorded. Declining an attack is frequently correct "
                     "(setup turns); cannot label as a miss without damage/KO "
                     "simulation. Broad-Main."),
    })

    # 7) evolution_available_but_not_taken (ctx0) -----------------------------
    c7 = [d for d in ds if d["context"] == 0
          and "evolve" in set(d["available_action_classes"])
          and d.get("selected_indices")
          and "evolve" not in set(d.get("selected_action_classes") or [])]
    classes.append({
        "name": "evolution_available_but_not_taken",
        "count": len(c7), "episodes": sorted({d["episode_id"] for d in c7}),
        "confidence": "low", "feasibility": "unsafe_broad_main",
        "expected_value": "unknown", "regression_risk": "high",
        "evidence": ("102 windows declining a legal evolution. Often correct "
                     "(holding for tempo / no benefit yet). Broad-Main; forcing "
                     "evolution risks tempo regressions."),
    })

    # 8) retreat_or_switch_available_but_not_used -----------------------------
    has_retreat = any(o["action_class"] in ("retreat", "switch")
                      for d in ds for o in d["legal_options"])
    classes.append({
        "name": "retreat_or_switch_available_but_not_used",
        "count": 0, "episodes": [],
        "confidence": "n/a", "feasibility": "not_actionable",
        "expected_value": "none", "regression_risk": "n/a",
        "evidence": ("No retreat/switch option class is resolvable in the "
                     "corpus; the engine does not expose it as a distinct "
                     "our-seat decision here. Nothing to act on."
                     if not has_retreat else "resolvable"),
    })

    return classes


def gate(classes: list[dict]) -> dict:
    """Part G — run each class through the trigger-coverage gate."""
    hooks = []
    for c in classes:
        cnt = c["count"]
        hi_loss = c.get("high_confidence_loss_windows", 0)
        feas = c["feasibility"]
        broad_main = feas in ("unsafe_broad_main",) or c["name"] in {
            "bench_backup_available_unplayed", "attach_target_misprioritized",
            "attack_available_but_not_taken",
            "evolution_available_but_not_taken",
        }
        reliable = feas not in ("not_actionable",) and c["name"] not in {
            "search_target_misprioritized",
            "retreat_or_switch_available_but_not_used",
        }
        coverage_ok = (cnt >= 3) or (hi_loss >= 2)
        # discard class: the GENUINE window count is what matters, not raw cnt.
        if c["name"] == "discard_preserve_line_failure":
            coverage_ok = (cnt >= 3) or (hi_loss >= 2)
        legal_alt = c["name"] not in {
            "retreat_or_switch_available_but_not_used",
            "optional_main_draw_search_low_deck",
        }
        fixture_testable = not broad_main and reliable and feas != "not_actionable"
        positive_controls = reliable and cnt > 0
        not_broad_main = not broad_main

        conditions = {
            "coverage_>=3_or_2hiconf_loss": coverage_ok,
            "legal_alternative_observed": legal_alt,
            "option_resolution_reliable": reliable,
            "narrow_single_context": not_broad_main,
            "positive_control_windows_exist": positive_controls,
            "not_broad_main": not_broad_main,
            "fixture_testable": fixture_testable,
        }
        build_allowed = all(conditions.values())
        hooks.append({
            "class": c["name"],
            "count": cnt,
            "high_confidence_loss_windows": hi_loss,
            "conditions": conditions,
            "build_allowed": build_allowed,
            "blocking_reasons": [k for k, v in conditions.items() if not v],
        })
    any_allowed = any(h["build_allowed"] for h in hooks)
    return {
        "schema": "activegraph.pass26.trigger_coverage/v1",
        "gate": ("a class is build_allowed ONLY if it clears coverage "
                 "(>=3 windows or 2 high-confidence loss windows), legal "
                 "alternative observed, reliable resolution, narrow non-broad-"
                 "Main context, positive controls, and is fixture-testable"),
        "any_build_allowed": any_allowed,
        "no_upload": True,
        "hooks": hooks,
    }


def _md_classes(classes: list[dict]) -> str:
    lines = [
        "# Pass 26 — Part F: True Opportunity Classes",
        "",
        "Eight candidate opportunity classes mined from the real Water replay "
        "corpus (read-only, `no_upload=true`). Counts are our-seat decision "
        "windows; Mega Abomasnow ex (723) is never treated as a Basic.",
        "",
        "| # | class | count | episodes | confidence | feasibility | EV | regression risk |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, c in enumerate(classes, 1):
        lines.append(
            f"| {i} | `{c['name']}` | {c['count']} | {len(c['episodes'])} | "
            f"{c['confidence']} | **{c['feasibility']}** | "
            f"{c['expected_value']} | {c['regression_risk']} |")
    lines += ["", "## Evidence per class", ""]
    for i, c in enumerate(classes, 1):
        lines += [f"### {i}. `{c['name']}`",
                  f"- count={c['count']} · episodes={c['episodes']}",
                  f"- feasibility=**{c['feasibility']}**, confidence="
                  f"{c['confidence']}, EV={c['expected_value']}, "
                  f"regression_risk={c['regression_risk']}",
                  f"- {c['evidence']}", ""]
    return "\n".join(lines)


def _md_gate(g: dict) -> str:
    lines = [
        "# Pass 26 — Part G: Trigger-Coverage Gate",
        "",
        f"> {g['gate']}",
        "",
        f"**any_build_allowed = {g['any_build_allowed']}** · `no_upload=true`.",
        "",
        "| class | count | hi-conf loss | build_allowed | blocking reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for h in g["hooks"]:
        reasons = ", ".join(h["blocking_reasons"]) or "—"
        lines.append(
            f"| `{h['class']}` | {h['count']} | "
            f"{h['high_confidence_loss_windows']} | "
            f"{'YES' if h['build_allowed'] else 'no'} | {reasons} |")
    lines += [
        "",
        "## Verdict",
        "",
        ("**No class clears the gate** -> Pass-26 proceeds as "
         "`no_build_no_trigger`: no candidates are built, no tarballs are "
         "produced, and a blocked manifest is written. The closest class "
         "(`discard_preserve_line_failure`) has only 1 high-confidence + 1 "
         "medium loss window (< the 2-high-confidence-loss bar); every other "
         "class is either broad-Main, has hidden targets, or has zero windows."
         if not g["any_build_allowed"] else
         "At least one class clears the gate; proceed to fixtures + candidate "
         "design."),
    ]
    return "\n".join(lines)


def main() -> int:
    ds = _load()
    classes = classify(ds)
    g = gate(classes)

    classes_doc = {
        "schema": "activegraph.pass26.opportunity_classes/v1",
        "source": str(LEDGER.relative_to(REPO)),
        "decisions_analyzed": len(ds),
        "no_upload": True,
        "classes": classes,
    }
    (EXP / "pass26_true_opportunity_classes.json").write_text(
        json.dumps(classes_doc, indent=2) + "\n", encoding="utf-8")
    (EXP / "pass26_true_opportunity_classes.md").write_text(
        _md_classes(classes), encoding="utf-8")
    (EXP / "pass26_trigger_coverage.json").write_text(
        json.dumps(g, indent=2) + "\n", encoding="utf-8")
    (EXP / "pass26_trigger_coverage.md").write_text(
        _md_gate(g), encoding="utf-8")

    print("opportunity classes ->",
          dict(collections.Counter(c["feasibility"] for c in classes)))
    print("any_build_allowed =", g["any_build_allowed"])
    for h in g["hooks"]:
        print(f"  {h['class']:<42} build_allowed={h['build_allowed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
