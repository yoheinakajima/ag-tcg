#!/usr/bin/env python3
"""PASS 46I (Part C) — PRE-REGISTERED evaluation design (no games run here).

Declares, BEFORE a single confirmation game is played, the exact panels, seat-balancing
rule, target decisive sample sizes, the per-panel edge labels, the noise-control trigger,
the reference policy, and the decision rule that maps measurements -> the Pass-46I
decision. Writing the plan first makes the analysis (Part E) and the decision (Part G)
falsifiable rather than post-hoc.

Two confirmation arms decide the pass:
  * ATTRIBUTION arm  = ov_vs_floor  — does the option-value treatment beat the
    family-only floor control (i.e. do the per-option value features add anything
    on top of the 46G family scorer)?
  * PRACTICAL arm    = ov_vs_parent — does the treatment beat the REAL internal
    parent it was forked from (a practical, not merely within-family, edge)?

Supporting panels (context, not gating): floor_vs_parent (is the floor itself already
at/above parent?) and conservative_vs_ov (does the conservative sibling differ?).
Self-mirror noise controls (parent_vs_parent, ov_vs_ov) run ONLY if the treatment
appears to clear the parent, to prove a measured edge is not engine seat/first-move
bias. Public references are BENCHMARK-ONLY context, excluded from every decision.

LOCAL / READ-ONLY: no games, no mutation, no upload, no events. Writes
data/experiments/pass46i_eval_plan.{json,md}. Exit 0 iff the plan resolves cleanly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiments"
BUILD_JSON = EXP / "pass46h_candidate_build.json"
PARENT_TARBALL = (ROOT / "data" / "submissions" / "candidates_pass33"
                  / "league_water_anti_disruption_pivot_v1.tar.gz")
REF_RAW = ROOT / "data" / "reference_agents" / "raw_outputs"

TREATMENT = "cg_typed_water_option_value_v1"
FLOOR = "cg_typed_water_family_only_floor_v1"
CONSERVATIVE = "cg_typed_water_conservative_option_value_v1"
PARENT = "league_water_anti_disruption_pivot_v1"

# Wilson 95% two-sided.
WILSON_Z = 1.96
# A panel arm: decisive win rate the subject must clear (lower Wilson bound) to "confirm".
CONFIRM_WILSON_LOW = 0.50
# Directional (suggestive) point-estimate threshold when Wilson bound can't confirm.
DIRECTIONAL_POINT = 0.60
# Seat confound: edge present in one seat but reversed in the other.
SEAT_CONFOUND_HI = 0.60
SEAT_CONFOUND_LO = 0.40
# Invalid tolerance: a panel is unsafe if invalid games exceed BOTH an absolute and a
# rate floor (so a single fluke in a big panel doesn't nuke it, but systemic breakage does).
INVALID_ABS_TOL = 2
INVALID_RATE_TOL = 0.05
# Self-mirror noise control is "clean" iff its decisive win-rate Wilson CI contains 0.50.
NOISE_CI_MUST_CONTAIN = 0.50


def _resolve_tarballs() -> dict:
    build = json.loads(BUILD_JSON.read_text(encoding="utf-8"))
    by_id = {c["candidate_id"]: c for c in build["candidates"]}
    out = {}
    for cid in (TREATMENT, FLOOR, CONSERVATIVE):
        c = by_id.get(cid)
        out[cid] = {"candidate_id": cid,
                    "tarball": c["tarball"] if c else None,
                    "kind": "cg_typed_candidate",
                    "present": bool(c and (ROOT / c["tarball"]).exists())}
    out[PARENT] = {"candidate_id": PARENT,
                   "tarball": str(PARENT_TARBALL.relative_to(ROOT)),
                   "kind": "stdlib_parent",
                   "present": PARENT_TARBALL.exists()}
    return out


def _reference_dirs() -> list[dict]:
    refs = []
    for sub in sorted(REF_RAW.glob("public_ref_*/submission.tar.gz")):
        refs.append({"ref_id": sub.parent.name,
                     "tarball": str(sub.relative_to(ROOT)),
                     "kind": "public_reference_benchmark_only", "present": True})
    return refs


def main() -> int:
    if not BUILD_JSON.exists():
        raise SystemExit(f"missing 46H build record: {BUILD_JSON}")
    participants = _resolve_tarballs()
    refs = _reference_dirs()

    def hard_cap(target: int) -> int:
        return round(target * 1.5) + 10

    panels = [
        {"panel_id": "ov_vs_floor", "arm": "attribution", "gating": True,
         "subject": TREATMENT, "opponent": FLOOR, "target_decisive": 40,
         "hard_cap_games": hard_cap(40), "seat_balanced": True,
         "purpose": "Do per-option value features beat the family-only floor control?"},
        {"panel_id": "ov_vs_parent", "arm": "practical", "gating": True,
         "subject": TREATMENT, "opponent": PARENT, "target_decisive": 40,
         "hard_cap_games": hard_cap(40), "seat_balanced": True,
         "purpose": "Does the treatment beat the REAL internal parent (practical edge)?"},
        {"panel_id": "floor_vs_parent", "arm": "context", "gating": False,
         "subject": FLOOR, "opponent": PARENT, "target_decisive": 40,
         "hard_cap_games": hard_cap(40), "seat_balanced": True,
         "purpose": "Is the family-only floor itself already at/above the parent?"},
        {"panel_id": "conservative_vs_ov", "arm": "context", "gating": False,
         "subject": CONSERVATIVE, "opponent": TREATMENT, "target_decisive": 20,
         "hard_cap_games": hard_cap(20), "seat_balanced": True,
         "purpose": "Does the conservative option-value sibling differ from treatment?"},
    ]
    conditional_noise_controls = [
        {"panel_id": "parent_vs_parent", "arm": "noise_control", "gating": False,
         "subject": PARENT, "opponent": PARENT, "target_decisive": 20,
         "hard_cap_games": hard_cap(20), "seat_balanced": True,
         "trigger": "only if ov appears to clear parent (practical confirmed/directional)",
         "purpose": "Self-mirror noise floor: decisive win rate must straddle 0.50."},
        {"panel_id": "ov_vs_ov", "arm": "noise_control", "gating": False,
         "subject": TREATMENT, "opponent": TREATMENT, "target_decisive": 20,
         "hard_cap_games": hard_cap(20), "seat_balanced": True,
         "trigger": "only if ov appears to clear parent (practical confirmed/directional)",
         "purpose": "Self-mirror noise floor: decisive win rate must straddle 0.50."},
    ]
    optional_reference_context = [
        {"panel_id": "ov_vs_refs", "arm": "reference_benchmark", "gating": False,
         "subject": TREATMENT, "opponents": [r["ref_id"] for r in refs][:2],
         "target_decisive": 12, "hard_cap_games": hard_cap(12), "seat_balanced": True,
         "trigger": "optional context only",
         "purpose": "Benchmark-only context vs public refs; NO parity claim; excluded "
                    "from every decision."}
    ]

    edge_label_rules = {
        "metric": "decisive win rate (winner != None) of subject over opponent",
        "wilson_z": WILSON_Z,
        "unsafe_invalid": (f"invalid games > {INVALID_ABS_TOL} AND invalid_rate > "
                           f"{INVALID_RATE_TOL}"),
        "seat_confounded": (f"one seat decisive win rate >= {SEAT_CONFOUND_HI} while the "
                            f"other <= {SEAT_CONFOUND_LO} (edge reverses with seat)"),
        "confirmed_edge": (f"Wilson_low > {CONFIRM_WILSON_LOW} AND NOT seat_confounded "
                           f"AND NOT unsafe_invalid"),
        "directional_edge": (f"point estimate >= {DIRECTIONAL_POINT} AND Wilson_low <= "
                             f"{CONFIRM_WILSON_LOW} AND NOT seat_confounded AND NOT "
                             f"unsafe_invalid"),
        "no_edge": ("residual (exhaustive): NOT confirmed_edge AND NOT directional_edge "
                    "AND NOT seat_confounded AND NOT unsafe_invalid — i.e. no meaningful "
                    "or even suggestive edge, INCLUDING a point estimate marginally above "
                    f"{CONFIRM_WILSON_LOW} whose Wilson lower bound does not clear "
                    f"{CONFIRM_WILSON_LOW}"),
        "noise_clean": (f"self-mirror Wilson CI for decisive win rate CONTAINS "
                        f"{NOISE_CI_MUST_CONTAIN}"),
    }

    # Decision rule: ATTRIBUTION (ov_vs_floor) x PRACTICAL (ov_vs_parent), gated by
    # invalid-safety and (conditionally) noise cleanliness. Forward-compatible map so
    # tests can assert decision->gate-state without re-deriving the logic.
    decision_rules = {
        "arms": {"attribution": "ov_vs_floor", "practical": "ov_vs_parent"},
        "order": [
            {"decision": "validation_failed",
             "when": "either gating arm is unsafe_invalid, OR Part A/B not all_ok"},
            {"decision": "water_option_value_confirmed_local_candidate",
             "when": "attribution == confirmed_edge AND practical == confirmed_edge AND "
                     "noise controls clean (or not required)"},
            {"decision": "water_option_value_floor_escape_only",
             "when": "attribution == confirmed_edge AND practical == no_edge"},
            {"decision": "water_option_value_inconclusive_needs_more_n",
             "when": "attribution == confirmed_edge AND practical in "
                     "{directional_edge, seat_confounded}; OR attribution == "
                     "directional_edge; OR a triggered noise control is not clean"},
            {"decision": "water_option_value_not_promising",
             "when": "attribution in {no_edge, seat_confounded}"},
            {"decision": "safety_stop_required",
             "when": "Part A preflight stop_required (handled upstream)"},
        ],
        "reference_policy": "public references are benchmark-only and NEVER gate or "
                            "change the decision",
        "noise_control_trigger": "run parent_vs_parent and ov_vs_ov ONLY if practical "
                                 "arm is confirmed_edge or directional_edge",
    }

    all_present = all(p["present"] for p in participants.values())
    data = {
        "pass": "46i", "part": "C", "read_only": True, "production_mutated": False,
        "local_only": True, "no_upload": True, "games_played": 0,
        "pre_registered": True,
        "participants": participants,
        "references_available": refs,
        "panels": panels,
        "conditional_noise_controls": conditional_noise_controls,
        "optional_reference_context": optional_reference_context,
        "seat_balancing": "each panel splits decisive games ~50/50 across subject-seat-0 "
                          "and subject-seat-1; play continues (alternating seats) until "
                          "target_decisive reached or hard_cap_games hit",
        "thresholds": {
            "wilson_z": WILSON_Z, "confirm_wilson_low": CONFIRM_WILSON_LOW,
            "directional_point": DIRECTIONAL_POINT,
            "seat_confound_hi": SEAT_CONFOUND_HI, "seat_confound_lo": SEAT_CONFOUND_LO,
            "invalid_abs_tol": INVALID_ABS_TOL, "invalid_rate_tol": INVALID_RATE_TOL,
            "noise_ci_must_contain": NOISE_CI_MUST_CONTAIN,
        },
        "edge_label_rules": edge_label_rules,
        "decision_rules": decision_rules,
        "all_participants_present": all_present,
        "all_ok": all_present,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    (EXP / "pass46i_eval_plan.json").write_text(
        json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    md = [
        "# Pass 46I (Part C) — pre-registered evaluation design", "",
        "_LOCAL / READ-ONLY. No games here. Declares the panels, seat-balancing, target "
        "decisive Ns, edge labels, the noise-control trigger, and the decision rule "
        "BEFORE any confirmation game is played, so the analysis and decision are "
        "falsifiable rather than post-hoc. Public references are benchmark-only and never "
        "gate the decision._", "",
        "## Confirmation arms",
        "- **ATTRIBUTION** = `ov_vs_floor` — option-value treatment vs family-only floor.",
        "- **PRACTICAL** = `ov_vs_parent` — treatment vs the REAL internal parent.", "",
        "## Panels (gating + context)",
        "| panel | arm | gating | subject | opponent | target decisive | hard cap |",
        "|---|---|:---:|---|---|:---:|:---:|",
    ]
    for p in panels:
        md.append(f"| `{p['panel_id']}` | {p['arm']} | {p['gating']} | "
                  f"`{p['subject']}` | `{p['opponent']}` | {p['target_decisive']} | "
                  f"{p['hard_cap_games']} |")
    md += ["", "## Conditional noise controls (only if ov appears to clear parent)"]
    for p in conditional_noise_controls:
        md.append(f"- `{p['panel_id']}` (self-mirror, target {p['target_decisive']}): "
                  f"{p['purpose']}")
    md += ["", "## Edge labels"]
    for k, v in edge_label_rules.items():
        md.append(f"- **{k}**: {v}")
    md += ["", "## Decision rule (in order)"]
    for step in decision_rules["order"]:
        md.append(f"- `{step['decision']}` ⟵ {step['when']}")
    md += ["", f"**all participants present = {all_present}** — **all_ok = {all_present}**"]
    (EXP / "pass46i_eval_plan.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"all_ok": all_present, "n_panels": len(panels),
                      "n_conditional_noise": len(conditional_noise_controls),
                      "n_refs_available": len(refs),
                      "participants_present": {k: v["present"]
                                               for k, v in participants.items()}},
                     indent=2))
    return 0 if all_present else 1


if __name__ == "__main__":
    raise SystemExit(main())
