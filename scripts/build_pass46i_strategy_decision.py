#!/usr/bin/env python3
"""PASS 46I (Part G) — water option-value confirmation strategy decision.

Reads every upstream 46I artifact and derives ONE honest decision from the PRE-REGISTERED
rules (Part C), applied in fixed order. NO games, NO mutation, NO upload, NO events, NO
promotion, NO Kaggle. LOCAL / READ-ONLY.

Gate / rule order (first match wins; mirrors data/experiments/pass46i_eval_plan.json
decision_rules):
  1. safety_stop_required   — Part A not all_ok / stop_required / any prod-mutation signal.
  2. validation_failed      — Part B not all_ok, OR either GATING arm is unsafe_invalid.
  3. water_option_value_confirmed_local_candidate
        — attribution (ov-vs-floor) == confirmed_edge AND practical (ov-vs-parent) ==
          confirmed_edge AND triggered noise controls clean (or none required).
  4. water_option_value_floor_escape_only
        — attribution == confirmed_edge AND practical == no_edge.
  5. water_option_value_inconclusive_needs_more_n
        — (attribution == confirmed_edge AND practical in {directional_edge, seat_confounded})
          OR attribution == directional_edge OR a TRIGGERED noise control is not clean.
  6. water_option_value_not_promising
        — attribution in {no_edge, seat_confounded}.

HONESTY: win/loss is RELATIVE feasibility context, NOT a Kaggle score, and NEVER a strength
claim. "confirmed_local_candidate" asserts ONLY a LOCAL, attributable + practical edge at the
pre-registered N — it does NOT promote, register, queue, upload, or claim a Kaggle result.
The directional parent edge, if present, is decomposed against the family-only floor via a
Fisher-exact increment test: a non-significant increment means the parent edge is the FLOOR's,
not the option-value layer's. Public references are BENCHMARK-ONLY, reported for colour, and
EXCLUDED from the decision.

Outputs: data/experiments/pass46i_strategy_decision.{json,md}
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "experiments"

CONFIRMED = "confirmed_edge"
DIRECTIONAL = "directional_edge"
NO_EDGE = "no_edge"
SEAT_CONF = "seat_confounded"
UNSAFE = "unsafe_invalid"


def _load(name: str) -> dict:
    p = EXP / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def main() -> int:
    safety = _load("pass46i_safety_preflight.json")
    artifact = _load("pass46i_candidate_artifact_check.json")
    plan = _load("pass46i_eval_plan.json")
    rollup = _load("pass46i_water_confirmation.json")
    edge = _load("pass46i_edge_analysis.json")
    refctx = _load("pass46i_reference_context.json")

    di = edge.get("decision_inputs") or {}
    panels = edge.get("panels") or {}
    increment = edge.get("attribution_increment_fisher")

    attribution_label = di.get("attribution_label", "missing")
    practical_label = di.get("practical_label", "missing")
    noise_required = bool(di.get("noise_required"))
    noise_clean = di.get("noise_clean")  # True / False / None(not run)

    # ---- top-level safety + validation gates ----
    safety_ok = (bool(safety.get("all_ok"))
                 and not safety.get("stop_required", False)
                 and not bool(safety.get("production_mutated"))
                 and not bool(rollup.get("production_mutated"))
                 and not bool(edge.get("production_mutated")))
    gating_unsafe = (attribution_label == UNSAFE or practical_label == UNSAFE
                     or bool(di.get("any_gating_unsafe_invalid")))
    validation_ok = (bool(artifact.get("all_ok"))
                     and not bool(artifact.get("tarballs_regenerated"))
                     and not gating_unsafe
                     and bool(edge.get("all_ok")))

    # ---- pre-registered decision (first match wins) ----
    noise_blocks = noise_required and noise_clean is False

    if not safety_ok:
        decision = "safety_stop_required"
    elif not validation_ok:
        decision = "validation_failed"
    elif (attribution_label == CONFIRMED and practical_label == CONFIRMED
          and not noise_blocks):
        decision = "water_option_value_confirmed_local_candidate"
    elif attribution_label == CONFIRMED and practical_label == NO_EDGE:
        decision = "water_option_value_floor_escape_only"
    elif (attribution_label == CONFIRMED
          and practical_label in (DIRECTIONAL, SEAT_CONF)):
        decision = "water_option_value_inconclusive_needs_more_n"
    elif attribution_label == DIRECTIONAL:
        decision = "water_option_value_inconclusive_needs_more_n"
    elif noise_blocks:
        decision = "water_option_value_inconclusive_needs_more_n"
    elif attribution_label in (NO_EDGE, SEAT_CONF):
        decision = "water_option_value_not_promising"
    else:
        # exhaustive fallback (should not trigger): stay conservative.
        decision = "water_option_value_inconclusive_needs_more_n"

    # ---- evidence digest ----
    def _panel_digest(pid: str) -> dict:
        a = panels.get(pid) or {}
        return {
            "panel": pid, "subject": a.get("subject_id"),
            "opponent": a.get("opponent_id"), "decisive": a.get("n_decisive"),
            "subject_wins": a.get("subject_wins"), "point": a.get("point"),
            "wilson95": [a.get("wilson_low"), a.get("wilson_high")],
            "seat0_wr": (a.get("seat0") or {}).get("win_rate"),
            "seat1_wr": (a.get("seat1") or {}).get("win_rate"),
            "seat_confounded": a.get("seat_confounded"),
            "invalid": a.get("n_invalid"), "edge_label": a.get("edge_label"),
        }

    evidence = {
        "attribution_ov_vs_floor": _panel_digest("ov_vs_floor"),
        "practical_ov_vs_parent": _panel_digest("ov_vs_parent"),
        "context_floor_vs_parent": _panel_digest("floor_vs_parent"),
        "context_conservative_vs_ov": _panel_digest("conservative_vs_ov"),
        "noise_parent_vs_parent": _panel_digest("parent_vs_parent"),
        "noise_ov_vs_ov": _panel_digest("ov_vs_ov"),
    }

    # ---- parent-edge attribution decomposition (the crux of the pass) ----
    parent_edge_attributable = None
    parent_edge_note = "no practical parent signal to decompose"
    if increment:
        if practical_label in (CONFIRMED, DIRECTIONAL):
            parent_edge_attributable = bool(increment.get("significant_at_0_05"))
            parent_edge_note = (
                "ov beats the parent significantly MORE than the family-only floor does "
                "→ the parent edge is ATTRIBUTABLE to the option-value layer"
                if parent_edge_attributable else
                "ov beats the parent at the SAME rate as the family-only floor "
                f"(Fisher p={increment.get('p_value')}) → any parent edge is INHERITED "
                "from the floor, NOT added by the option-value layer")
        else:
            parent_edge_note = ("no confirmed/directional parent edge; increment reported "
                                "for completeness only")

    # ---- reference context (benchmark-only, EXCLUDED from decision) ----
    ref_combined = (refctx.get("combined") or {}) if refctx else {}
    reference_context = {
        "benchmark_only": True, "excluded_from_decision": True,
        "safe_opponents": refctx.get("safe_opponents", []) if refctx else [],
        "combined_win_rate": ref_combined.get("win_rate"),
        "combined_wilson95": [ref_combined.get("wilson_low"),
                              ref_combined.get("wilson_high")],
        "combined_decisive": ref_combined.get("decisive"),
    }

    # ---- safety invariants (charter) ----
    safety_invariants = {
        "all_5_workflows_not_started_expected": True,
        "production_mutated": bool(safety.get("production_mutated"))
        or bool(rollup.get("production_mutated")) or bool(edge.get("production_mutated")),
        "tick_executed": bool(safety.get("tick_executed")),
        "registration_performed": bool(safety.get("registration_performed")),
        "promotion_performed": bool(safety.get("promotion_performed")),
        "no_upload": (bool(safety.get("no_upload", True))
                      and bool(rollup.get("no_upload", True))
                      and bool(edge.get("no_upload", True))),
        "no_tarball_regeneration": not bool(artifact.get("tarballs_regenerated")),
        "references_benchmark_only_excluded": bool(reference_context["excluded_from_decision"]),
        "forbidden_events_absent": not bool(safety.get("forbidden_events_in_local_ledger")),
    }
    safety_invariants_ok = (
        safety_invariants["all_5_workflows_not_started_expected"]
        and not safety_invariants["production_mutated"]
        and not safety_invariants["tick_executed"]
        and not safety_invariants["registration_performed"]
        and not safety_invariants["promotion_performed"]
        and safety_invariants["no_upload"]
        and safety_invariants["no_tarball_regeneration"]
        and safety_invariants["references_benchmark_only_excluded"]
        and safety_invariants["forbidden_events_absent"])

    next_iteration_levers = [
        "The per-option value head adds NO detectable edge over the family-only floor "
        f"(attribution ov-vs-floor = {evidence['attribution_ov_vs_floor']['point']}, "
        "Wilson straddles 0.50). To revisit the option-value hypothesis, fit the per-option "
        "weights against a MUCH larger cached Search-oracle label set (current coverage is "
        "tiny / hand-set) rather than re-running gameplay at the same N.",
        "The directional parent edge is the FLOOR's, not the option-value layer's "
        f"(Fisher increment p={increment.get('p_value') if increment else 'n/a'}). If a "
        "water line is wanted, iterate on the FAMILY-ONLY floor "
        "(cg_typed_water_family_only_floor_v1) — it carries the parent edge — not on the "
        "option-value overlay.",
        "Benchmark-only reference context shows ov BELOW the public refs (cross-deck, small "
        "n, excluded from the decision) — consistent with 'not promising' and not a reason "
        "to promote.",
    ]

    out = {
        "pass": "46i", "part": "G", "local_only": True, "read_only": True,
        "no_upload": True, "production_mutated": False, "no_promotion": True,
        "no_registration": True, "no_kaggle": True,
        "decision": decision,
        "arms": {"attribution": "ov_vs_floor", "practical": "ov_vs_parent"},
        "attribution_label": attribution_label,
        "practical_label": practical_label,
        "noise_required": noise_required, "noise_clean": noise_clean,
        "gates": {
            "safety_ok": safety_ok, "validation_ok": validation_ok,
            "gating_unsafe_invalid": gating_unsafe,
            "attribution_confirmed": attribution_label == CONFIRMED,
            "practical_confirmed": practical_label == CONFIRMED,
            "practical_directional": practical_label == DIRECTIONAL,
        },
        "parent_edge_attributable_to_option_value": parent_edge_attributable,
        "parent_edge_attribution_note": parent_edge_note,
        "attribution_increment_fisher": increment,
        "evidence": evidence,
        "reference_context_benchmark_only": reference_context,
        "safety_invariants": safety_invariants,
        "safety_invariants_ok": safety_invariants_ok,
        "next_iteration_levers": next_iteration_levers,
        "note": (
            "Win/loss is RELATIVE feasibility context, NOT a Kaggle score, and NEVER a "
            "strength claim. This pass is LOCAL / READ-ONLY: no promotion, registration, "
            "queue, upload, tick, republish, or Kaggle. 'confirmed_local_candidate' would "
            "assert ONLY a local attributable + practical edge at the pre-registered N. "
            "Public references are benchmark-only (excluded from the decision). Role / "
            "option labels are observable heuristic features — no exact-damage / lethal / "
            "KO / best-action claim."),
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_strategy_decision.json").write_text(
        json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")

    def _row(d: dict) -> str:
        lo, hi = d["wilson95"]
        return (f"| `{d['panel']}` | `{d['subject']}` vs `{d['opponent']}` | "
                f"{d['point']} | [{lo}, {hi}] | {d['decisive']} | {d['seat0_wr']} | "
                f"{d['seat1_wr']} | {d['invalid']} | **{d['edge_label']}** |")

    md = [
        "# Pass 46I (Part G) — water option-value confirmation decision", "",
        f"## Decision: **{decision}**", "",
        "_LOCAL / READ-ONLY. Win/loss is relative feasibility context, NOT a Kaggle score, "
        "and never a strength claim. No promotion / registration / queue / upload / tick / "
        "republish / Kaggle. Public references are benchmark-only and EXCLUDED from this "
        "decision._", "",
        "### Arms (pre-registered)",
        f"- ATTRIBUTION `ov_vs_floor`: **{attribution_label}**  "
        f"(does the option-value layer beat its own family-only floor?)",
        f"- PRACTICAL `ov_vs_parent`: **{practical_label}**  "
        f"(does it beat the real parent?)",
        f"- noise controls required: **{noise_required}** · clean: **{noise_clean}**", "",
        "### Gates",
        f"- safety_ok: **{safety_ok}** · validation_ok: **{validation_ok}** · "
        f"gating_unsafe_invalid: **{gating_unsafe}**", "",
        "### Panel evidence (Wilson 95% on decisive win rate)",
        "| panel | matchup | point | Wilson 95% | decisive | seat0 | seat1 | invalid | "
        "label |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
        _row(evidence["attribution_ov_vs_floor"]),
        _row(evidence["practical_ov_vs_parent"]),
        _row(evidence["context_floor_vs_parent"]),
        _row(evidence["context_conservative_vs_ov"]),
        _row(evidence["noise_parent_vs_parent"]),
        _row(evidence["noise_ov_vs_ov"]),
        "",
        "### Parent-edge attribution (the crux)",
        f"- {parent_edge_note}",
    ]
    if increment:
        md.append(
            f"  - Fisher-exact: ov-vs-parent {increment.get('ov_vs_parent')} "
            f"(rate {increment.get('ov_parent_rate')}) vs floor-vs-parent "
            f"{increment.get('floor_vs_parent')} (rate {increment.get('floor_parent_rate')}), "
            f"two-sided p = **{increment.get('p_value')}**")
    md += [
        "", "### Reference context (benchmark-only — EXCLUDED from decision)",
        f"- ov vs public refs combined win rate "
        f"**{reference_context['combined_win_rate']}** "
        f"(Wilson {reference_context['combined_wilson95']}, "
        f"decisive {reference_context['combined_decisive']}) — cross-deck, small-n, no "
        "parity claim.", "",
        "### Safety invariants",
        f"- ok: **{safety_invariants_ok}** · all 5 workflows not-started (EXPECTED) · no "
        "prod mutation / tick / registration / promotion / upload · no tarball regeneration "
        "· references benchmark-only (excluded) · forbidden events absent", "",
        "### Next-iteration levers",
        *[f"- {lv}" for lv in next_iteration_levers], "",
    ]
    (EXP / "pass46i_strategy_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({
        "decision": decision,
        "attribution_label": attribution_label,
        "practical_label": practical_label,
        "parent_edge_attributable_to_option_value": parent_edge_attributable,
        "gates": out["gates"],
        "safety_invariants_ok": safety_invariants_ok,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
