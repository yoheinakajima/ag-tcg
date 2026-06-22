#!/usr/bin/env python3
"""PASS 46L Part C — v1 planner blueprint + PRE-REGISTERED eval plan (LOCAL-ONLY).

This pre-registers the ``cg_typed_diamond_specialist_planner_v1`` design and its evaluation
BEFORE any v1 game is played. It supersedes the originally-frozen v1 thesis (attack-now/
end-turn gating + role-keyed search/bench/discard refinements): the Part-B reference-loss
trace audit and the option-resolution probe FALSIFIED that thesis with visible-only evidence
(see ``evidence_falsifying_frozen_thesis`` below, read live from those artifacts), and the
architect re-consult (responsibility=evaluate_task) directed a pivot to a NARROW set of
**namespace-independent structural** levers that actually fire in live reference play.

Honesty boundary is unchanged and hard: refs are benchmark-only and NEVER a gate for any
decision except the single pre-registered reference-improvement test; no exact damage / lethal
/ KO / missed-KO / Boss-gust / spread / best-action claims; numeric attackId alone is not a
claim; no invented card ids (the role-id table is FROZEN at v0 — extending it from observed
play is forbidden); deck byte-identical from the diamond parent; no prod mutation / Kaggle /
republish. Pure derivation; reads diagnostics; writes only data/experiments artifacts.

Outputs: pass46l_planner_v1_blueprint.{json,md}, pass46l_eval_plan.{json,md}.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
AUDIT = EXP / "pass46l_reference_loss_trace_audit.json"
PROBE = EXP / "pass46l_resolution_probe.json"


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _evidence() -> dict:
    audit = _load(AUDIT)
    probe = _load(PROBE)
    fat = audit.get("first_attack_turn", {})
    lf = audit.get("signals_loss_frames", {})
    wf = audit.get("signals_win_frames", {})
    return {
        "source_artifacts": ["pass46l_reference_loss_trace_audit.json",
                             "pass46l_resolution_probe.json"],
        "attack_gating_is_a_nonissue": {
            "first_attack_turn_min_mean_max": [fat.get("first_attack_turn_min"),
                                               fat.get("first_attack_turn_mean"),
                                               fat.get("first_attack_turn_max")],
            "never_attacked": fat.get("never_attacked"),
            "loss_attack_available_not_taken": lf.get("attack_available_not_taken"),
            "win_attack_available_not_taken": wf.get("attack_available_not_taken"),
            "loss_end_turn_with_alternatives": lf.get("end_turn_with_alternatives"),
            "win_end_turn_with_alternatives": wf.get("end_turn_with_alternatives"),
            "interpretation": "v0 already attacks early (mean ~turn 3), never fails to attack, "
                              "and never ends a turn with a productive option present; raising "
                              "attack priority or demoting pass/end-turn further is INERT.",
        },
        "role_keyed_refinements_inert_live": {
            "resolve_rate": probe.get("resolve_rate"),
            "in_map_rate": probe.get("in_map_rate"),
            "nonempty_role_rate": probe.get("nonempty_role_rate"),
            "by_context": probe.get("by_context"),
            "interpretation": "resolve_play_card maps ~80% of chosen action options to a live "
                              "card id, but only ~10% land in the owned role map: the live cabt "
                              "select id namespace differs from the offline role-map namespace, "
                              "so search/bench/discard/attach ROLE bonuses essentially never "
                              "fire live (planner collapses to the family-base table). This is a "
                              "card-id GROUNDING gap, not a policy-layer gap.",
        },
        "small_n_variance": {
            "fresh_panel_outcomes": audit.get("outcomes"),
            "frozen_baseline_46k_decisive": "W1/L59",
            "interpretation": "the same v0 went 5W/5L in this fresh 10-game ref panel vs ~1/60 "
                              "pooled in 46K; the frozen baseline is noisy but stays FROZEN for "
                              "pre-registration integrity (fresh panels are variance/context "
                              "only, never a re-baseline).",
        },
        "structural_levers_that_DO_fire_live": {
            "attach_target_fields_present": "attach options carry inPlayArea (active=4 / "
                                            "bench=5) + inPlayIndex, so _target_poke resolves "
                                            "and the attach target's VISIBLE energy count is "
                                            "readable -> a namespace-free reweight fires.",
            "choose_active_setup_bench_rare": "choose_active/setup_bench appeared 0x as chosen "
                                              "multi-option contexts in the probe (rare/forced); "
                                              "a tilt there is honest but expected near-inert.",
            "discard_targets_hand_not_inplay": "probe discard options targeted hand/deck zones "
                                               "(inPlayArea=None), so 'protect in-play poke from "
                                               "discard' rarely applies -> NOT adopted as a "
                                               "primary lever.",
        },
    }


def _v1_diff() -> list:
    """The CONCRETE, narrow, namespace-independent v1 diff vs v0. Each entry is machine-
    checkable so fixtures/tests can assert the implemented v1 matches this pre-registration.
    Every lever keys ONLY on board zone (active vs bench) and VISIBLE attached-energy COUNT —
    never roles, ids, damage, cost, lethal, KO, gust, or spread."""
    return [
        {
            "lever": "attach_active_preference",
            "context": "attach_energy", "namespace_independent": True,
            "v0": "+5.0 if target is active else 0.0",
            "v1": "+14.0 if target is active else 0.0",
            "why": "the only live-observable attach signal is target board zone; concentrate "
                   "energy on the visible active attacker. Role bonuses (energy_target/main/"
                   "backup) are KEPT byte-for-byte but are known ~inert live (grounding gap).",
            "expected_live_firing": "fires when >=2 attach options (active vs bench) co-occur",
        },
        {
            "lever": "attach_anti_overload",
            "context": "attach_energy", "namespace_independent": True,
            "v0": "-2.0 * attached_energy_count(target)",
            "v1": "-5.0 * attached_energy_count(target)",
            "why": "avoid piling energy onto an already-loaded target when a less-energized "
                   "eligible attacker is offered; energy COUNT is visible, never a cost/damage "
                   "threshold.",
            "expected_live_firing": "fires when attach targets differ in attached-energy count",
        },
        {
            "lever": "choose_active_energy_tilt",
            "context": "choose_active", "namespace_independent": True,
            "v0": "develop-phase promote: +5.0 * attached_energy_count(target)",
            "v1": "develop-phase promote: +8.0 * attached_energy_count(target)",
            "why": "when forced to promote a new active, lead with the most-ready (most-"
                   "energized) Pokemon you can SEE; namespace-free. Expected near-inert "
                   "(context is rare/forced) — included for honest coherence, not for impact.",
            "expected_live_firing": "rare (promotion windows are infrequent / often forced)",
        },
        {
            "lever": "attack_and_end_turn_UNCHANGED",
            "context": "attack,end_turn", "namespace_independent": True,
            "v0": "attack base 95/50/30; end_turn base 0; attackId tie-break 9/(1+id)",
            "v1": "IDENTICAL — no change",
            "why": "Part B proved attack gating is already correct live (attacks land early, "
                   "never_attacked=0, attack_available_not_taken=0, end_turn never chosen with "
                   "alternatives). Changing it would be a no-op dressed as progress.",
            "expected_live_firing": "n/a (intentionally unchanged)",
        },
        {
            "lever": "role_keyed_search_bench_discard_UNCHANGED",
            "context": "search_to_hand,setup_bench,discard,play_from_hand_engine",
            "namespace_independent": False,
            "v0": "role-keyed priority tables + discard role protection",
            "v1": "IDENTICAL — no change",
            "why": "these key on the role-id table, which matches only ~10% of live select ids. "
                   "Extending the table from observed play to make them fire = INVENTED IDS "
                   "(forbidden). They stay byte-identical (still correct in the ~10% aligned "
                   "cases + at fixture level). The honest fix is a separate grounding pass.",
            "expected_live_firing": "~10% (grounding-limited); not a v1 lever",
        },
        {
            "lever": "draw_count_deckout_guard_UNCHANGED",
            "context": "draw_count", "namespace_independent": True,
            "v0": "penalize drawing past deck_count-1 (deckout safety)",
            "v1": "IDENTICAL — no change",
            "why": "v0 already implements the conservative deckout guard the architect listed; "
                   "it is namespace-free and fires when a numeric draw-count option appears. No "
                   "honest improvement available without over-fitting.",
            "expected_live_firing": "fires when an effect_choice carries a numeric draw count",
        },
    ]


def _eval_plan() -> dict:
    """STAGED eval plan, pre-registered. The reference panel runs ONLY if v1 is demonstrably
    non-inert AND not internally worse than v0. Refs are benchmark-only and gate ONLY the
    single reference-improvement decision."""
    return {
        "baseline_frozen": {"v0_decisive": "W1/L59", "source": "pass46k",
                            "note": "FROZEN; fresh 5W/5L panel is variance/context only."},
        "stages": [
            {"stage": 0, "name": "safety_and_artifact",
             "gate": "safety_preflight all_ok AND candidate artifact verifies; else "
                     "decision=safety_stop_required / validation_failed (NO games)."},
            {"stage": 1, "name": "validation_lane_separation",
             "gate": "cg_typed accepts; stdlib rejects unchanged; import smoke resolves agent; "
                     "malformed obs never raises; fallback legal; deck==parent byte-identical; "
                     "root main.py/deck.csv unchanged; no reference code copied. Else "
                     "decision=validation_failed (NO games)."},
            {"stage": 2, "name": "fixtures_and_non_inertness", "blocking_gate": True,
             "metric": "v1-vs-v0 changed-decision rate on REAL trace frames (Part-B loss/win "
                       "frames + parent frames), per context, with illegal-decision=0.",
             "gate": "PROCEED to internal panels ONLY if changed-decision rate >= 5% AND the "
                     "changes land in relevant contexts (attach_energy primarily). If < 5% or "
                     "changes are only in forced/irrelevant contexts -> decision="
                     "diamond_v1_not_promising (clean negative); STOP, do NOT run any panel."},
            {"stage": 3, "name": "internal_panels",
             "panels": {"v1_vs_v0": ">=40 decisive", "v1_vs_parent": ">=60 decisive",
                        "v1_vs_generic_ov": ">=40 decisive", "v1_vs_v1_mirror": "20-30 games"},
             "gate": "v1 NOT internally worse than v0 (v1-vs-parent / v1-vs-generic_ov Wilson "
                     "lower bound not below v0's; v1-vs-v1 mirror CI straddles 0.5). If v1 is "
                     "internally worse -> decision=diamond_v1_not_promising."},
            {"stage": 4, "name": "reference_panel_benchmark_only",
             "panel": {"v1_vs_public_refs": "all runnable refs, >=4 games/ref, BOTH seats, "
                       "hard-timeout subprocess; benchmark-only"},
             "gate": "runs ONLY if stage 2 non-inert AND stage 3 not-worse. Refs NEVER gate "
                     "any decision except the reference-improvement test below."},
        ],
        "pre_registered_reference_improvement_test": {
            "name": "diamond_v1_reference_gap_improved_local_only",
            "decision_TRUE_iff_ALL": [
                "stage0 safety+artifact all_ok",
                "pooled v1 decisive (W+L) >= 50",
                "invalid rate <= 5%",
                "both seats represented",
                "v1-vs-v1 mirror Wilson CI straddles 0.5",
                "one-sided Fisher-exact (v1 pooled W/L vs frozen 1/59) p <= 0.05",
                "v1 pooled win-rate >= 0.10",
            ],
            "arithmetic_note": "at n=60 a >=0.10 win-rate AND Fisher p<=0.05 vs 1/59 needs "
                               "roughly >=7 wins; 2-3 wins is explicitly NO material gain.",
            "per_reference_rows": "explanatory ONLY, NEVER a gate.",
        },
        "decision_ladder_frozen": [
            "safety_stop_required",
            "validation_failed",
            "diamond_v1_not_promising",
            "diamond_v1_internal_only_no_reference_gain",
            "diamond_v1_reference_gap_improved_local_only",
        ],
        "most_likely_outcome": "diamond_v1_internal_only_no_reference_gain OR "
                               "diamond_v1_not_promising — a SUCCESSFUL pass if it yields clean "
                               "negative evidence + non-inertness/trace attribution + the "
                               "grounding-gap recommendation (a card-id grounding pass or a "
                               "different archetype, NOT another thin policy layer).",
    }


UNSUPPORTED_CLAIMS = [
    "exact_damage", "lethal", "ko", "missed_ko", "boss_gust_target", "spread",
    "best_action", "best_attack", "card_value", "tempo_value", "opponent_hand_contents",
    "opponent_deck_order", "own_deck_order", "prize_contents", "kaggle_score_or_strength",
    "reference_parity_or_superiority", "invented_card_ids", "attack_damage_ranking",
]


def main() -> int:
    EXP.mkdir(parents=True, exist_ok=True)
    blueprint = {
        "pass": "46L", "part": "C", "candidate": "cg_typed_diamond_specialist_planner_v1",
        "parent_candidate": "cg_typed_diamond_specialist_planner_v0",
        "local_only": True, "no_upload": True, "no_redeploy": True,
        "references_are": "benchmark_only_never_a_gate_except_the_one_reference_test",
        "deck": "byte_identical_from_diamond_parent",
        "role_id_table": "FROZEN_at_v0_no_new_ids",
        "design_pivot": "Frozen v1 thesis (attack-now/end-turn gating + role-keyed search/"
                        "bench/discard refinements) was FALSIFIED by Part-B trace + resolution "
                        "probe; architect re-consult (evaluate_task) directed a pivot to a "
                        "narrow set of namespace-independent STRUCTURAL levers.",
        "evidence_falsifying_frozen_thesis": _evidence(),
        "v1_diff": _v1_diff(),
        "guardrails": [
            "pure / never-raise; typed + raw-obs fallback; no online Search; no file I/O.",
            "self-contained INLINE region (V1 markers); no src import in the candidate.",
            "every lever keys only on board zone + visible attached-energy count.",
            "role-id table identical to v0 (no invented ids).",
            "all within-family magnitudes stay << DS_SCALE so the family base dominates.",
        ],
        "unsupported_claims": UNSUPPORTED_CLAIMS,
    }
    (EXP / "pass46l_planner_v1_blueprint.json").write_text(
        json.dumps(blueprint, indent=2, default=str) + "\n", encoding="utf-8")

    ev = blueprint["evidence_falsifying_frozen_thesis"]
    md = ["# Pass 46L Part C — v1 planner blueprint (PRE-REGISTERED, local-only)", "",
          "**Candidate:** `cg_typed_diamond_specialist_planner_v1` (from v0). "
          "**Deck:** byte-identical from the diamond parent. **References:** benchmark-only.",
          "", "## Design pivot (honest)", blueprint["design_pivot"], "",
          "### Evidence that falsified the originally-frozen v1 thesis",
          f"- **Attack gating is a non-issue:** first-attack-turn (min/mean/max) = "
          f"{ev['attack_gating_is_a_nonissue']['first_attack_turn_min_mean_max']}, "
          f"never_attacked={ev['attack_gating_is_a_nonissue']['never_attacked']}, "
          f"attack_available_not_taken (loss/win) = "
          f"{ev['attack_gating_is_a_nonissue']['loss_attack_available_not_taken']}/"
          f"{ev['attack_gating_is_a_nonissue']['win_attack_available_not_taken']}, "
          f"end_turn_with_alternatives (loss/win) = "
          f"{ev['attack_gating_is_a_nonissue']['loss_end_turn_with_alternatives']}/"
          f"{ev['attack_gating_is_a_nonissue']['win_end_turn_with_alternatives']}.",
          f"- **Role-keyed refinements ~inert live:** resolve_rate="
          f"{ev['role_keyed_refinements_inert_live']['resolve_rate']}, in_map_rate="
          f"{ev['role_keyed_refinements_inert_live']['in_map_rate']} "
          f"-> a card-id GROUNDING gap, not a policy gap.",
          f"- **Small-n variance:** fresh panel "
          f"{ev['small_n_variance']['fresh_panel_outcomes']} vs frozen "
          f"{ev['small_n_variance']['frozen_baseline_46k_decisive']} (baseline stays frozen).",
          "", "## v1 diff (narrow, namespace-independent)",
          "| lever | context | ns-free | v0 | v1 |",
          "|---|---|:---:|---|---|"]
    for d in blueprint["v1_diff"]:
        md.append(f"| {d['lever']} | {d['context']} | {d['namespace_independent']} | "
                  f"`{d['v0']}` | `{d['v1']}` |")
    md += ["", "_Primary live lever: the attach reweight. Attack/end-turn and the role-keyed "
           "search/bench/discard tables are intentionally UNCHANGED (see why-notes in the "
           "JSON)._", "", "## Unsupported claims (hard boundary)",
           ", ".join(UNSUPPORTED_CLAIMS), ""]
    (EXP / "pass46l_planner_v1_blueprint.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    eval_plan = {"pass": "46L", "part": "C", "local_only": True,
                 "pre_registered_before_any_v1_game": True, **_eval_plan()}
    (EXP / "pass46l_eval_plan.json").write_text(
        json.dumps(eval_plan, indent=2, default=str) + "\n", encoding="utf-8")

    em = ["# Pass 46L Part C — PRE-REGISTERED eval plan (staged, local-only)", "",
          f"Frozen baseline: **{eval_plan['baseline_frozen']['v0_decisive']}** "
          f"({eval_plan['baseline_frozen']['note']})", "", "## Staged gates"]
    for s in eval_plan["stages"]:
        em.append(f"- **Stage {s['stage']} — {s['name']}**"
                  + (" _(blocking)_" if s.get("blocking_gate") else "") + f": {s['gate']}")
    em += ["", "## Pre-registered reference-improvement test "
           f"(`{eval_plan['pre_registered_reference_improvement_test']['name']}`)",
           "TRUE iff ALL of:"]
    for c in eval_plan["pre_registered_reference_improvement_test"]["decision_TRUE_iff_ALL"]:
        em.append(f"- {c}")
    em += ["", eval_plan["pre_registered_reference_improvement_test"]["arithmetic_note"], "",
           "## Decision ladder (frozen)"]
    for d in eval_plan["decision_ladder_frozen"]:
        em.append(f"- `{d}`")
    em += ["", f"**Most likely outcome:** {eval_plan['most_likely_outcome']}", ""]
    (EXP / "pass46l_eval_plan.md").write_text("\n".join(em) + "\n", encoding="utf-8")

    print(json.dumps({
        "wrote": ["pass46l_planner_v1_blueprint.json", "pass46l_planner_v1_blueprint.md",
                  "pass46l_eval_plan.json", "pass46l_eval_plan.md"],
        "v1_levers": [d["lever"] for d in blueprint["v1_diff"]],
        "resolve_rate": ev["role_keyed_refinements_inert_live"]["resolve_rate"],
        "in_map_rate": ev["role_keyed_refinements_inert_live"]["in_map_rate"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
